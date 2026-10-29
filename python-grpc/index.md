# Python 和 Go 之间的 gRPC 交互

因为不同的业务场景，异构的业务系统十分常见。异构服务之间的同步通信方式的选择不外乎 HTTP 和 RPC 两种。RPC 方式可以像调用本地方法一样调用远程服务提供的方法，对客户端来说具体实现完全是透明的，服务之间的通信会变得更容易。
对于 RPC 框架的选择，gRPC 当前已经是首先:
>gRPC是一个高性能、通用的开源RPC框架，其由Google主要面向移动应用开发并基于HTTP/2协议标准而设计，基于ProtoBuf(Protocol Buffers)序列化协议开发，且支持众多开发语言。

* gRPC具有以下重要特征：

    * 强大的IDL特性  
    RPC使用ProtoBuf来定义服务，ProtoBuf是由Google开发的一种数据序列化协议，性能出众，得到了广泛的应用。
    * 支持多种语言  
    支持 C++、Java、Go、Python、Ruby、C#、Node.js、Android Java、Objective-C、PHP等编程语言。
    * 基于 HTTP/2 标准设计  

    下面这张图来自于官方网站清晰的给我们展示了使用 gRPC 服务之间的交互流程  
    ![grpc](https://pics.lxkaka.wang/gRPC.png)

* gRPC使用流程
    * 定义标准的proto文件
    * 生成标准代码
    * 服务端使用生成的代码提供服务
    * 客户端使用生成的代码调用服务

在这里我们以我们实际业务场景 Python 服务和 Go 服务之间的交互来介绍一下 gRPC 的使用。

## Python gRPC
1. python 环境
这里可以使用 `virtualenv` 来初始化一个干净的 Python 环境
```
pip3 install virtualenv
# 使用 python3.7 创建虚拟环境
virtualenv --python=python3.7 venv
source venv/bin/activate
``` 
2. gRPC 依赖
```
# grpcio 是启动 gRPC 服务的项目依赖
pip install grpcio
# gPRC tools 包含 protocol buffer 编译器和用于从 .proto 文件生成服务端和客户端代码的插件
pip install grpcio-tools
```
3. 定义 proto 文件
```proto
syntax = "proto3";

import "google/protobuf/empty.proto";


// service 关键字定义提供的服务
service MyService {
  // 定义一个探活方法
  rpc Health (.google.protobuf.Empty) returns (.google.protobuf.Empty){
  }
  // 定义一个批量查询 user 的方法
  rpc User (UserReq) returns (UserReply){
  }

}

// message 关键字定义交互的数据结构
message UserReq {
  repeated int32 userIDs= 1;
}

message UserReply {
  string message = 1;
  // repeated 定义一个数组
  repeated User data = 2;
}

message User {
  string name = 1;
  int32 age = 2;
  string email = 3;
}
```
4. 生成代码
```
# 使用 protoc 和相应的插件可以编译生成对应语言的代码
# -I 指定 import 路径，可以指定多个 -I 参数，编译时按顺序查找，不指定默认当前目录
python -m grpc_tools.protoc -I ./ --python_out=. --grpc_python_out=. ./api.proto
```
经过上述步骤，我们生成了这样两个文件   
`api_pb2.py` 此文件包含每个 `message` 生成一个含有静态描述符的模块，，该模块与一个元类（metaclass）在运行时（runtime）被用来创建所需的Python数据访问类  
`api_pb2_grpc.py` 此文件包含生成的 客户端(MyServiceStub)和服务端  (MyServiceServicer)的类。

5. 实现服务端
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging
from concurrent import futures

import grpc
from api import api_pb2_grpc, api_pb2
from api.api_pb2_grpc import MyServiceServicer
from service import get_users


class Service(MyServiceServicer):
    def Health(self, request, context):
        return

    def User(self, request, context):
        print('start to process request...')
        res = get_users(request.userIDs)
        users = []
        for u in res:
            users.append(api_pb2.User(name=u['name'], age=u['age'], email=u['email']))
        return api_pb2.UserReply(message='success', data=users)


def serve():
    print('start grpc server====>')
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    api_pb2_grpc.add_MyServiceServicer_to_server(Service(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    logging.basicConfig()
    serve()
```
到此，如果我们用 Python 客户端当然也能请求到服务端。因为我们这里介绍的是 Go 和 Python 的交互，这里就不 demo 了。

## Go gRPC 
我们这里 Go 服务作为客户端调用 Python 服务，同样需要根据 proto 文件生成代码，进而创建客户端发起 RPC。
1. go gRPC 依赖
```
# 安装 ptotobuf, 推荐使用 brew
brew install protobuf
# protoc go 插件安装
go get -u github.com/golang/protobuf/protoc-gen-go
# 这里安装在 GOPATH 下的 bin 目录，所以保证这个目录在 $PATH 中
export PATH="$PATH:$(go env GOPATH)/bin"
# 代码 gprc 依赖安装
go get -u google.golang.org/grpc
```

2. 生成 Go pb 代码
`protoc -I ./ --go_out=plugins=grpc:./ api.proto` 

3. 客户端调用
```go
package main

import (
	"context"
	"fmt"
	"log"
	"time"

	"ginDemo/api"
	"google.golang.org/grpc"
)

const (
	address     = "localhost:50051"
	defaultName = "world"
)

func main() {
	conn, err := grpc.Dial(address, grpc.WithInsecure(), grpc.WithBlock())
	if err != nil {
		log.Fatalf("did not connect: %v", err)
	}
	defer conn.Close()
	c := api.NewMyServiceClient(conn)

	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	r, err := c.User(ctx, &api.UserReq{UserIDs: []int32{1, 2}})
	if err != nil {
		log.Fatalf("could not greet: %v", err)
	}
	fmt.Printf("gprc result: %+v", r.Data)
}
```
Python 服务端输出示例    
![pyhton-grpc](https://pics.lxkaka.wang/python-grpc.png)

Go 客户端输出示例  
![go-grpc](https://pics.lxkaka.wang/go-grpc.png)

以 Python 服务和 Go 服务之间的 gRPC 通信就说到这里，希望对想使用 gRPC 的同学带来参考和启示。

