# Elastic APM 补齐服务监控

在之前的[文章](https://www.lxkaka.wang/app-metrics/)介绍过服务可观测性。其中 **tracing** 扩展一下我们可以称之为 **APM**(Application Performance Monitoring)。在这篇文章里，我会具体介绍我们在 Golang 服务中的 APM 实践。

### APM(应用性能监控)
>对于大部分应用程序来说性能都是很重要的一个因素，尤其对于比如网站、手机app等直接由用户访问的应用来说更是如此，因为性能较差的应用将会直接影响其用户体验。因此，能对应用进行性能监控变得非常重要，这将帮助我们找到性能瓶颈并优化。
APM 是对应用程序性能和可用性的监视和管理。APM 努力检测和诊断复杂的应用程序性能问题，以维持预期的服务等级。  

目前主流的开源链路追踪实现 `Jaeger`, `SkyWalking`其实都实现了 APM 的部分目的。但这些方案各有优劣，使用成本也不太相同。今天在这里我们就介绍一下我们的实践 `Elastic APM`，相比其他方案 Elastic APM 具有支持框架和语音全面；监控数据全面; 查询方便；界面美观等等优点。

### Elastic APM
Elastic APM是一个 Elastic Stack 的应用性能监控（APM）系统，它能够：  
1. 实时的监控软件服务和应用：为传入的请求，数据库查询，对缓存的调用，外部 HTTP 请求等收集有关响应时间的详细性能信息，使得可以轻松快速地找出并解决性能问题。
2. 自动收集未处理的错和异常以及它们的调用栈，让你能快速定位新错误并且跟踪错误出现的频率。
3. 收集机器级别以及特定 agent 的指标（比如 Java JVM 和 Go Runtime 的指标）。
4. 支持分布式追踪：使你能够在一个视图中分析整个服务架构的性能。
5. 支持真实用户监控（Real User Monitoring，RUM）：可捕获用户与客户端（例如Web浏览器）的交互。

#### ES APM 架构
Elastic APM 由四个组件组成：

* APM agents：以应用程序库的形式提供，收集程序中的性能监控数据并上报给APM server。
* APM Server：从 APM agents 接收数据、进行校验和处理后写入 Elasticsearch 特定的 APM 索引中。虽然 agent 也可以实现为：将数据收集处理后直接上报到ES，不这么做官方给出的理由：使 agent 保持轻量，防止某些安全风险以及提升 Elastic 组件的兼容性。
* Elasticsearch：用于存储性能指标数据并提供聚合功能。
* Kibana：可视化性能数据并帮助找到性能瓶颈。

![es-apm-arch](https://pics.lxkaka.wang/es-apm-arch.png)

#### 数据模型
Elastic APM agent从其检测（instrument）的应用程序中收集不同类型的数据，这些被称为事件，类型包括 span，transaction，错误和指标四种。 
* Span 包含有关已执行的特定代码路径的信息。它们从活动的开始到结束进行度量，并且可以与其他span具有父/子关系。
* 事务（Transaction） 是一种特殊的Span（没有父span，只能从中派生出子span，可以理解为“树”这种数据结构的根节点），具有与之关联的其他属性。可以将事务视为服务中最高级别的工作，比如服务中的请求等。
* 错误(Error)：错误事件包含有关发生的原始异常或有关发生异常时创建的日志的信息。  
* 指标(Metric)：APM agent 自动获取基本的主机级别指标，包括系统和进程级别的 CPU 和内存指标。除此之外还可获取特定于代理的指标，例如 Java agent 中的JVM 指标和 Go agent 中的 Go Runtime 指标。 

### ES APM 实践
我们的 Golang web 服务使用了自研的微服务框架，为了使用 ES APM。我们做了如下的改造，下面列举出重点部分和部分代码示例   
#### middleware 
middleware 是在处理 Http Request 之前框架层面对 request 做的统一处理，比如实现 access log 记录；统一鉴权；trace 打点等。为了把 Http Request 纳入 apm，我们按照自己服务框架的中间件规范实现了 es apm middleware。
```golang
package middleware

import (
	"fmt"
	"net/http"
	"strings"

	"go.elastic.co/apm"
	"go.elastic.co/apm/module/apmhttp"
)

func APM(o ...Option) bm.HandlerFunc {
	m := &middleware{
		tracer: apm.DefaultTracer,
	}
	if env.AppID != "" {
		m.tracer.Service.Name = strings.ReplaceAll(env.AppID, ".", "_")
	}
	m.tracer.Service.Environment = env.DeployEnv
	for _, o := range o {
		o(m)
	}
	if m.requestIgnorer == nil {
		m.requestIgnorer = apmhttp.NewDynamicServerRequestIgnorer(m.tracer)
	}
	return m.handle
}

type middleware struct {

	tracer         *apm.Tracer
	requestIgnorer apmhttp.RequestIgnorerFunc
	//setRouteMapOnce sync.Once
	//routeMap        map[string]map[string]routeInfo
}

func (m *middleware) handle(c *bm.Context) {
	if !m.tracer.Recording() || m.requestIgnorer(c.Request) {
		c.Next()
		return
	}
	requestName := c.Request.Method + " " + c.Request.URL.Path
	tx, req := apmhttp.StartTransaction(m.tracer, requestName, c.Request)
	c.Request = req
	defer tx.End()

	body := m.tracer.CaptureHTTPRequestBody(c.Request)
	c.Context = apm.ContextWithTransaction(c.Context, tx)
	defer func() {
		if v := recover(); v != nil {
			c.AbortWithStatus(http.StatusInternalServerError)
			e := m.tracer.Recovered(v)
			e.SetTransaction(tx)
			setContext(&e.Context, c, body)
			e.Send()
		}

		err := c.Error
		cerr := ecode.Cause(err)
		message := cerr.Message()
		if cerr.Code() == 0 {
			message = "ok"
		}
		c.Writer.WriteHeader(http.StatusOK)
		tx.Result = fmt.Sprintf("HTTP %d %s", cerr.Code(), message)

		if tx.Sampled() {
			setContext(&tx.Context, c, body)
		}

		if c.Error != nil {
			e := m.tracer.NewError(c.Error)
			e.SetTransaction(tx)
			setContext(&e.Context, c, body)
			e.Handled = true
			e.Send()
		}
		body.Discard()
	}()
	c.Next()
}

func setContext(ctx *apm.Context, c *bm.Context, body *apm.BodyCapturer) {
	ctx.SetTag("region", env.Region)
	ctx.SetTag("zone", env.Zone)
	ctx.SetTag("hostname", env.Hostname)
	ctx.SetTag("env", env.DeployEnv)
	ctx.SetHTTPRequest(c.Request)
	ctx.SetHTTPRequestBody(body)
	ctx.SetHTTPStatusCode(ecode.Cause(c.Error).Code())
	ctx.SetHTTPResponseHeaders(c.Writer.Header())
}
```

#### gorm 
我们使用 `gorm` 操作 db, 对 gorm client 改造如下
```golang
func NewMySQL(c *Config) (db *gorm.DB) {
	db, err := apmgorm.Open("mysql", c.DSN)
	if err != nil {
		log.Error("orm: open error(%v)", err)
		panic(err)
	}
	db.DB().SetMaxIdleConns(c.Idle)
	db.DB().SetMaxOpenConns(c.Active)
	db.DB().SetConnMaxLifetime(time.Duration(c.IdleTimeout))
	db.SetLogger(ormLog{})
    .... // 省略其他部分
    return
```
#### redis
操作 redis, 我们对客户端改造如下  
```golang
type Redis struct {
	Redis *redis.Redis
}

func (r Redis) Do(ctx context.Context, commandName string, args ...interface{}) (reply interface{}, err error) {
	conn := r.Redis.Conn(ctx)
	defer conn.Close()
	return Do(ctx, conn, commandName, args...)
}
// Do calls conn.Do(commandName, args...), and also reports the operation as a span to Elastic APM.
func Do(ctx context.Context, conn redis.Conn, commandName string, args ...interface{}) (interface{}, error) {
	spanName := strings.ToUpper(commandName)
	if spanName == "" {
		spanName = "(flush pipeline)"
	}
	span, _ := apm.StartSpan(ctx, spanName, "db.redis")
	defer span.End()
	return conn.Do(commandName, args...)
}
...
```
像 `grpc server`, `grpc client`, `http client` 等的改造可参照[官方例子](https://www.elastic.co/guide/en/apm/agent/go/current/builtin-modules.html#builtin-modules-apmgrpc)。

### ES APM 部署
在上面我们介绍过 ES APM 的组件，要部署一个生产基本可用的 ES APM 至少部署清单应该如下  
* APM Server 至少两个实例
* ElasticSearch 至少3实例组成的集群
* Kibana 一个实例
ES APM 整体的部署成本的大头就是 Elasticsearch cluster。 建议以容器的方式部署，降低部署和运维成本。如果在 k8s 中部署，建议 es 实例配置好 `pod antiaffinity` 并且提前规划好存储容量。如果以 docker-compose 方式部署，每个 es 实例建议部署到单独的宿主机。
下面是各个组件的 docker-compose yaml 配置文件，供大家参考   
> Elasticsearch 对各种文件混合使用了 NioFs（ 注：非阻塞文件系统）和 MMapFs （ 注：内存映射文件系统）。配置的最大映射数量，以便有足够的虚拟内存可用于 mmapped 文件。可以在宿主机上设置：
`sysctl -w vm.max_map_count=262144`  
#### Elasticsearch cluster
```yml
version: '3.7'
services:
  es01:
    image: docker.elastic.co/elasticsearch/elasticsearch:7.11.2
    container_name: es01
    deploy:
      resources:
        limits:
          cpus: '8'
          memory: 24000M
        reservations:
          cpus: '8'
          memory: 24000M
    environment:
      - node.name=es01
      - network.host=0.0.0.0
      - network.publish_host=10.1.1.16
      - http.port=9205  
      - cluster.name=bdjs-es-docker-cluster
      - discovery.seed_hosts=10.1.1.17, 10.1.1.18
      - cluster.initial_master_nodes=es01,es02,es03
      - bootstrap.memory_lock=true
    ulimits:
      memlock:
        soft: -1
        hard: -1
    volumes:
      - /data/apm/es/data:/usr/share/elasticsearch/data
    ports:
      - 9205:9205
      - 9300:9300


version: '3.7'
services:
  es02:
    image: docker.elastic.co/elasticsearch/elasticsearch:7.11.2
    container_name: es02
    deploy:
      resources:
        limits:
          cpus: '8'
          memory: 24000M
        reservations:
          cpus: '8'
          memory: 24000M
    environment:
      - node.name=es02
      - network.host=0.0.0.0
      - network.publish_host=10.1.1.17
      - http.port=9205      
      - cluster.name=bdjs-es-docker-cluster
      - discovery.seed_hosts=10.1.1.16, 10.1.1.18
      - cluster.initial_master_nodes=es01,es02,es03
      - bootstrap.memory_lock=true
    ports:
      - 9205:9205
      - 9300:9300
    ulimits:
      memlock:
        soft: -1
        hard: -1
    volumes:
      - /data/apm/es/data:/usr/share/elasticsearch/data


version: '3.7'
services:
  es03:
    image: docker.elastic.co/elasticsearch/elasticsearch:7.11.2
    container_name: es03
    deploy:
      resources:
        limits:
          cpus: '8'
          memory: 24000M
        reservations:
          cpus: '8'
          memory: 24000M 
    environment:
      - node.name=es03
      - network.host=0.0.0.0
      - network.publish_host=10.1.1.18
      - http.port=9205
      - cluster.name=bdjs-es-docker-cluster
      - discovery.seed_hosts=10.1.1.16,10.1.1.17
      - cluster.initial_master_nodes=es01,es02,es03
      - bootstrap.memory_lock=true
     ports:
      - 9205:9205
      - 9300:9300
    ulimits:
      memlock:
        soft: -1
        hard: -1
    volumes:
      - /data/apm/es/data:/usr/share/elasticsearch/data
```
#### APM server 和 Kibana
```yml
version: '3.7'
services:
  kibana:
    image: docker.elastic.co/kibana/kibana:7.11.2
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 8000M
        reservations:
          cpus: '2'
          memory: 8000M
    environment:
      ELASTICSEARCH_HOSTS: '["http://10.1.1.16:9205","http://10.1.1.17:9205","http://10.1.1.18:9205"]'
    ports:
    - 5601:5601
    networks:
    - elastic
    healthcheck:
      interval: 10s
      retries: 20
      test: curl --write-out 'HTTP %{http_code}' --fail --silent --output /dev/null http://localhost:5601/api/status

  apm-server:
    image: docker.elastic.co/apm/apm-server:7.11.2
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 8000M
        reservations:
          cpus: '2'
          memory: 8000M 
    cap_add: ["CHOWN", "DAC_OVERRIDE", "SETGID", "SETUID"]
    cap_drop: ["ALL"]
    ports:
    - 8200:8200
    networks:
    - elastic
    command: >
       apm-server -e
         -E apm-server.rum.enabled=true
         -E setup.kibana.host=kibana:5601
         -E setup.template.settings.index.number_of_replicas=0
         -E apm-server.kibana.enabled=true
         -E apm-server.kibana.host=kibana:5601
         -E output.elasticsearch.hosts=["10.1.1.16:9205","10.1.1.17:9205","10.1.1.18:9205"]
    healthcheck:
      interval: 10s
      retries: 12
      test: curl --write-out 'HTTP %{http_code}' --fail --silent --output /dev/null http://localhost:8200/ 
networks:
  elastic:
    driver: bridge
```
### APM 结果
下图是示例服务的 transactions 汇总的概览  

![apm-trans](https://pics.lxkaka.wang/apm-trans.png)

下图是某 gprc 请求的链路 timeline 

![apm-timeline](https://pics.lxkaka.wang/apm-timelines.png)
