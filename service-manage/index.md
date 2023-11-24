# 用 StatefulSet 实现同步服务和异步服务的管理

一个服务里既有同步逻辑又有异步逻辑是非常常见的事，比如可以通过 Http 接口调用服务或者通过消息队列传递消息来实现同样的服务逻辑，同一套代码逻辑区别只是入口不一样。  
在 Golang 服务里我们用 `goroutine` 非常容易的起两个入口；在 Python 服务里我们可以用多进程也容易实现。    
现在我们看另外一种场景，服务同样需要对外提供同步和异步入口，但是服务本身是计算密集型的且非常占用资源，典型的例子比如使用 GPU 的推理服务。首先推理服务启动时需要加载模型，而这一般需要很大的显存可能达到数个 G 甚至超过十个 G。但是我们的单张显卡显存当然是有上限的，就拿 T4 来说显存只有 15个G 可用，所以一个推理服务同时启动同步和异步可能显存就不够；影响更严重的一个问题是即使显存足够同时启动同步和异步服务，但是当同步和异步同时进行计算是，对显卡的计算资源会存在争夺的情况，那么这样计算速度可能会大大降低，严重降低了推理服务的性能。   
为了解决上述问题一个很自然的办法就是同步和异步分别部署一套服务。对于一个这样的服务说是没问题的我们多加一个服务节点、一套 CI/CD 配置、一套服务配置、一套应用配置等就完成了。但是有这样需求的服务有多个，并且数目会持续增加，那么分别部署同步和异步的成本和服务维护的成本就急剧增加。      
在这篇文章里我就分享下我们的解决办法，如何在一个服务里(一个节点，一套配置)独立运行同步和异步实例。（这里的实例指的是在 K8s 中一个 deployment 里的一个 Pod）  

### 精确实例数量
一个服务的总实例数目是通过配置定义的。假如我们配置的服务实例数是 10，然后在这10个实例当中一部分是同步实例，一部分是异步实例。如何保证这些实例数量是按照我们要求分布的呢？    
#### 按比例随机  
  假如同步和异步的实例数比例是 **4:6**, 在服务启动脚本里我们可以生成一个 1-10 的随机整数然后跟同步实例数比例比较，如果小于等于 4 则以同步的方式启动实例，否则以异步的方式启动。    
  示例脚本如下  

  ```shell
	#!/bin/bash

	# 同步实例数比例(通过环境变量注入)
	SYNCS=$SYNC_RATE

	# 默认启动同步实例
	if [ -z "$SYNCS" ]; then
	  SYNCS=10
	fi
	Rand=$(( ( RANDOM % 10 )  + 1 ))

	if [ "$Rand" -le "$SYNCS" ]; then
	  # 启动grpc server(同步）
	  python /data/app/grpc_server/server.py

	else
	  # 启动任务进程(异步）
	  python /data/app/start/__init__.py
	fi
  ```

  很明显随机启动无法准确的控制实例数量，尤其是总实例数目较少的时候实例分布偏差较大。

#### StatefulSet   
我们知道在 K8s 中除了常用的服务形式 `Deployment` 还有一种比较常用的服务形式是 `StatefulSet`, 后者相比前者来说最显著的一个区别是 `StatefulSet` 下的 `Pod` 名字是也有序号的。例如一个 StatefulSet 形式服务名是 web-service 且有 3个实例，那么 3个实例的名字分别是 web-service-0、web-service-1、web-service-2。   
我们可以正好利用 StatefulSet 这种 Pod 按编号顺序启动的方式来控制同步和异步实例启动的数量。思路就是比如我们设置好了同步实例的数量，那么在每次实例启动的时候我们可以根据实例的编号和同步实例数做比较，如果编号比同步数小那么就以同步的方式启动实例，反之则以异步的方式启动。    
示例脚本如下    

  ```shell
	#!/bin/bash

	# pod 编号
	POD_NUM=`echo ${POD_NAME} | awk -F'-' '{print $NF}'`
	# 同步实例数(通过环境变量注入)
	SYNCS=$SYNC_INSTANCE

	# 默认同步方式(INSTANCE是期望的总实例数)
	if [ -z "$SYNCS" ]; then
	  SYNCS=$INSTANCE
	fi

	if [ "$POD_NUM" -lt "$SYNCS" ]; then
	  # 启动grpc server(同步）
	  python /data/app/grpc_server/server.py

	else
	  # 启动任务进程(异步）
	  python /data/app/start/__init__.py
	fi
  ```
所以通过上面的描述我们看到可以利用 `StatefulSet` 来精确控制同步和异步实例数量。

### 容器多进程管理  
在我们上面的例子中因为服务同时包含了同步实例和异步实例，同步实例有暴露端口的需求而异步实例是没有对外暴露端口的，这样带来的矛盾就是如果服务配置了端口，则我们的基础平台会对异步服务配置的端口健康检查和服务注册，结果就是异步服务必然健康检查失败而启动失败。为了绕过基础平台的功能我们决定对服务不配置暴露端口，同步服务自己实现服务注册的功能。即我们在同步服务中除了启动服务进程之外，再启动一个服务注册管理进程，实现服务注册、服务心跳和服务注销功能。    
上面这个情况比较特殊，可能其他同学并不会遇到，我们拿这个例子是为了说明在 K8s 容器中有多个进程该怎么管理。上面说到除了服务进程之外，容器中还存在一个服务注册进程，这个进程必须实现在容器销毁的时候必须向注册中心注销服务实例。    
在 K8s 中，Pod 停止时 kubelet 会先给容器中的主进程发 SIGTERM 信号来通知进程进行 shutdown 以实现优雅停止，如果超时进程还未完全停止则会使用 SIGKILL 来强行终止。但是在我们的场景中我们的业务进程是在脚本中启动的，容器的启动入口使用了脚本，所以容器中的主进程并不是我们所希望的业务进程而是 shell 进程，导致业务进程收不到 SIGTERM 信号，自然就无法实现主动注销服务。    
我们利用 `trap` 来实现    
#### trap 捕捉信号  
通常trap都在脚本中使用，主要有2种功能：  
1. 忽略信号。当运行中的脚本进程接收到某信号时(例如误按了CTRL+C)，可以将其忽略，免得脚本执行到一半就被终止  
2. 捕捉到信号后做相应处理，比如清理创建的临时文件  

#### 常用信号
```shell
Signal     Value   Comment

─────────────────────────────

SIGHUP      1      终止进程，特别是终端退出时，此终端内的进程都将被终止
SIGINT      2      中断进程，几乎等同于sigterm，会尽可能的释放执行clean-up，
                   释放资源，保存状态等(CTRL+C)
SIGQUIT     3      从键盘发出杀死(终止)进程的信号
SIGKILL     9      强制杀死进程，该信号不可被捕捉和忽略，进程收到该信号后不会
                   执行任何clean-up行为，所以资源不会释放，状态不会保存
SIGTERM    15      杀死(终止)进程，几乎等同于sigint信号，会尽可能的释放执行
                   clean-up，释放资源，保存状态等
SIGSTOP    19      该信号是不可被捕捉和忽略的进程停止信息，收到信号后会进入stopped状态
SIGTSTP    20      该信号是可被忽略的进程停止信号(CTRL+Z)
```
#### trap 使用
```
trap [-lp] [[arg] signal_spec ...]
-l    打印信号名称以及信号名称对应的数字。
-p    显示与每个信号关联的trap命令。

参数
arg：接收到信号时执行的命令或函数 
signal_spec：信号名称或信号名称对应的数字  
```
通过上述介绍之后我们知道给容器多进程传递信号方式为：可以在 shell 中使用 trap 来捕获信号，当收到信号后触发回调函数来将信号通过 kill 传递给业务进程。  
示例脚本如下    
```shell
#!/bin/bash

# pod 编号
POD_NUM=`echo ${POD_NAME} | awk -F'-' '{print $NF}'`
# 同步实例数
SYNCS=$SYNC_INSTANCE

if [ -z "$SYNCS" ]; then
  SYNCS=$INSTANCE
fi

if [ "$POD_NUM" -lt "$SYNCS" ]; then
  # 启动grpc server
  python /data/app/grpc_server/server.py & pid1="$!"
  python /data/app/grpc_server/register.py & pid2="$!"
  handle_sigterm() {
    echo "[INFO] Received SIGTERM"
    kill -SIGTERM $pid1 $pid2 # 传递 SIGTERM 给业务进程
    wait $pid1 $pid2 # 等待所有业务进程完全终止
  }
  trap handle_sigterm TERM # 捕获 SIGTERM 信号并回调 handle_sigterm 函数
  wait # 等待回调执行完，主进程再退出

else
  # 启动任务进程
  python /data/app/start/__init__.py
fi
```

下图是实现的效果    

![sync-aysnc](https://pics.lxkaka.wang/sync-async-instance.png)
