# Dapr 初探-Pub/Sub 实践

### Dapr 介绍
Dapr 是一个开源项目，由微软发起，下面是来自 Dapr 官方网站的介绍
>Dapr 是一个可移植的、事件驱动的运行时，它使任何开发人员能够轻松构建出弹性的、无状态和有状态的应用程序，并可运行在云平台或边缘计算中，它同时也支持多种编程语言和开发框架。

通过阅读官方文档和实践，我理解的 dapr 的定位包含这些：
* 不依赖于特定的库，包和框架，可以使用任意的编程语言开发业务功能
* 不依赖于特定的中间件，存储等，并且可以按需替换
* 不依赖于特定平台，可以在本地、Kubernetes 集群或者其它集成 Dapr 的托管环境中运行应用程序  
* 业务通过标准的 API 提供服务，无需关心底层具体实

如下图所示，概括了 Dapr 的能力和层次架构  

![dapr-poi](https://docs.dapr.io/images/overview.png)

#### 服务构建块（building block)  
构建块是 dapr 提供的可以通过标准 Http 或者 gRPC API访问的模块化最佳实践。构建块可以使用任何组件组合，例如 actors 构建块和 状态管理 构建块都使用 状态组件。 另一个示例是 Pub/Sub 构建块使用 Pub/Sub 组件。

以下是 Dapr 提供的构建块类型:   
![building-block](https://docs.dapr.io/images/building_blocks.png)

#### 组件 （component）
组件是 dapr 中最佳实践的功能实现，每个组件都有接口定义，所有组件都是可插拔的，因此可以将组件换为另一个具有相同接口的组件。   
目前 dapr 提供的组件例子如下图，具体可以查看[官方文档](https://docs.dapr.io/reference/components-reference/)  

![components](https://docs.dapr.io/images/concepts-components.png)

### 发布订阅实践

#### 运行过程
发布和订阅 (pub/sub) 使微服务能够使用事件驱动架构的消息相互通信。这种服务模式的好处在这里就不赘述了。我们主要是介绍一下 dapr 如何帮助我们来实现这张服务模式。
Dapr 中的发布/订阅 API 功能
* 提供与平台无关的 API 来发送和接收消息 
* 提供至少一次消息传递保证 
* 与各种消息代理集成例如 redis,kafka, rabbitmq 等等
服务所使用的消息代理是可插拔的，并被配置为运行时的 Dapr Pub/Sub 组件。 这种方法消除了服务的依赖性，从而使服务可以更加可移植和更灵活变更。
Dapr 中使用 pub/sub 的过程：
1. 服务对 Dapr 发布/订阅构建块 API 进行调用
2. pub/sub 构建块调用封装特定消息代理的 Dapr pub/sub 组件
3. 为了接收消息，Dapr 订阅 pub/sub 组件，并在消息到达时将消息传递到服务提供的接口   

下图是一个 dapr 中 pub/sub 的例子     
![pub-sub](https://docs.dapr.io/images/pubsub-overview-publish-API.png)

#### 示例
作为消息接收者的服务实现    
```golang
package main

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"

	"github.com/gorilla/mux"
)

type JSONObj struct {
	PubsubName string `json:"pubsubName"`
	Topic      string `json:"topic"`
	Route      string `json:"route"`
}

type Result struct {
	Data *Data `json:"data"`
}

type Data struct {
	Name string `json:"name"`
	Id   int    `json:"id"`
}


// Register Dapr pub/sub subscriptions
func getSub(w http.ResponseWriter, r *http.Request) {
	jsonData := []JSONObj{
		{
			PubsubName: "pubsub",
			Topic:      "test",
			Route:      "test",
		},
	}
	jsonBytes, err := json.Marshal(jsonData)
	if err != nil {
		log.Fatal("Error in reading the result obj")
	}
	_, err = w.Write(jsonBytes)
	if err != nil {
		log.Fatal("Error in writing the result obj")
	}
}

// Dapr subscription in /dapr/subscribe sets up this route
func postMessage(w http.ResponseWriter, r *http.Request) {
	data, err := ioutil.ReadAll(r.Body)
	if err != nil {
		log.Fatal(err)
	}
	var result Result
	fmt.Println("raw data: ", string(data))
	err = json.Unmarshal(data, &result)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("Subscriber received: ", result.Data)
	obj, err := json.Marshal(data)
	if err != nil {
		log.Fatal("Error in reading the result obj")
	}
	_, err = w.Write(obj)
	if err != nil {
		log.Fatal("Error in writing the result obj")
	}
}

func main() {
	appPort := "6001"
	if value, ok := os.LookupEnv("APP_PORT"); ok {
		appPort = value
	}

	r := mux.NewRouter()

	r.HandleFunc("/dapr/subscribe", getSub).Methods("GET")

	// Dapr subscription routes orders topic to this route
	r.HandleFunc("/test", postMessage).Methods("POST")

	if err := http.ListenAndServe(":"+appPort, r); err != nil {
		log.Panic(err)
	}
}
``` 
##### 启动消费者服务
```shell
dapr run --app-port 6001 --app-id message-processor --app-protocol http --dapr-http-port 3501 --components-path ~/.dapr/components -- go run .
```

##### 发送消息
首先启动一个 dapr sidecar 用于接收消息  
```shell  
dapr run --app-id myapp --dapr-http-port 3500
```  
`
POST http://localhost:<daprPort>/v1.0/publish/<pubsubname>/<topic>[?<metadata>]
`
可以用来把消息发给指定的 topic     
示例中的消息如下所示  
```shell
curl --location --request POST 'http://localhost:3500/v1.0/publish/pubsub/test' \
--header 'Content-Type: application/json' \
--data-raw '{
    "name": "lxkaka",
    "id": 123
}'
```
当然我们可以在服务中去调用 API 作为生产者。  

消费者输出如下：
```
== APP == raw data:  {"data":{"id":123,"name":"lxkaka"},"datacontenttype":"application/json","id":"5b895456-2d57-42bd-855f-d8a6882e406b","pubsubname":"pubsub","source":"mydapr","specversion":"1.0","topic":"test","traceid":"00-c731a591f41c36b09f966b213fa6b7be-4e6eb22474fc2c21-01","traceparent":"00-c731a591f41c36b09f966b213fa6b7be-4e6eb22474fc2c21-01","tracestate":"","type":"com.dapr.event.sent"}
== APP == Subscriber received:  &{lxkaka 123}
```
##### 消费组
Dapr 会根据 *app_id* 把 app_id 相同的服务实例作为消费组，同一个消费组里只有一个实例能消费到消息。
示例如下，我们再启动一个消费实例   
```shell
dapr run --app-port 6002 --app-id message-processor --app-protocol http --dapr-http-port 3502 --components-path ~/.dapr/components -- go run .
```
发了 5 条消息，其中一个实例收到 2 条，另外一个实例收到 3条输出如下：
```shell
== APP == Subscriber received:  &{lxkaka 1}
== APP == raw data:  {"data":{"id":3,"name":"lxkaka"},"datacontenttype":"application/json","id":"9e929d03-6c7e-4440-a4a9-f58dc93e2192","pubsubname":"pubsub","source":"mydapr","specversion":"1.0","topic":"test","traceid":"00-f03697dcc9fe5e0b0e543402bbdad8ef-db83433662f25934-01","traceparent":"00-f03697dcc9fe5e0b0e543402bbdad8ef-db83433662f25934-01","tracestate":"","type":"com.dapr.event.sent"}
== APP == Subscriber received:  &{lxkaka 3}
== APP == raw data:  {"data":{"id":5,"name":"lxkaka"},"datacontenttype":"application/json","id":"93922ff8-7ef4-4721-ab55-97fcd5f425d5","pubsubname":"pubsub","source":"mydapr","specversion":"1.0","topic":"test","traceid":"00-2a5716b4f43826481b9e841dccaece8a-6e74bc49ca407097-01","traceparent":"00-2a5716b4f43826481b9e841dccaece8a-6e74bc49ca407097-01","tracestate":"","type":"com.dapr.event.sent"}
== APP == Subscriber received:  &{lxkaka 5}
```
关于 Pub/Sub 中 Dapr 还支持其他功能比如
* 消息有效
* topic 绑定应用
* 根据内容路由
* dead letter topics  

希望这篇文章对大家认识和理解 Dapr 有帮助。至于 Dapr 更多的应用场景和实践还需要更多的探索。
