# Docker 核心原理

对 Docker 的使用大部分都比较熟悉，但是说到 docker 的实现原理很多人还是一知半解。我把在团队内部做的一次 Docker 核心原理分享总结到文章里，以供参考。

## Docker 的优势
> Build once, Run anywhere
上面这句话很精辟的总结了 docker 的优点。我从下面几点具体描述 docker 带给开发者的能力
* 应用标准化
无论什么语言开发的应用，我们都能用 dockerfile 和构建脚本方便的进行应用构建打包，代码库 + 构建 + registry 统一了 CI/CD 流程，也提升了效率。
* 环境一致
由于应用和依赖全部构建成镜像，做到了一次构建多次交付，无论是开发，测试还是上线环境都是一致的。大大提高了开发效率
* 应用隔离
由于通过 docker 部署的应用，容器之间相互隔离，并且能按需分配资源。大大提高了运维效率和资源利用率

## 架构
 Docker使用了 C/S 体系架构，Docker 客户端与 Docker 守护进程通信，Docker 守护进程负责构建，运行和分发 Docker 容器。Docker 客户端和守护进程可以在同一个系统上运行，也可以将Docker客户端连接到远程Docker守护进程。
 我们日常在命令行的操作 `docker build, docker push, docker pull, docke build` 等等操作都是客户端通过 rest api 请求与 Docker 守护进程交互。
 ![docker-cs](https://pics.lxkaka.wang/docker-cs.png)

 ## 实现原理
 下面我们就介绍一下 Docker 在实现隔离，资源控制，文件系统等关键部分所采用的的技术

 ### Namespace
 [Linux manaul page](https://man7.org/linux/man-pages/man7/namespaces.7.html) 很好的介绍了 namespace 的作用。
 namespace提供了一种内核级别隔离系统资源的方法，通过将系统的全局资源放在不同的 namespace 中，来实现资源隔离的目的。不同 namespace 的进程拥有相互隔离的系统资源。
 这里指的资源隔离包含以下这些：
 * Mount: 隔离文件系统挂载点
 * UTS: 隔离主机名和域名信息
 * IPC: 隔离进程间通信
 * PID: 隔离进程的 ID
 * Network: 隔离网络资源
 * User: 隔离用户和用户组  
通过下面的 `clone` 系统调用可以创建新的进程，参数 `flags` 控制创建的进程所属的 namespace, 多个 `flags` 可以同时创建多个 namespace。
```
int clone(int (*child_func)(void *), void *child_stack, int flags, void *arg);
```
我们知道容器本质上就是隔离的进程，Docker 在创建容器的时候就是使用 namespace 来实现了容器与容器，容器与宿主机的隔离。
每个进程都有一个 /proc/[pid]/ns 的目录，里面保存了该进程所在对应 namespace 的链接, 我们来查看某个容器也就是某一个进程对应的 namespace 文件描述  
```
root@lxkaka-server:~# ls -l /proc/23204/ns
total 0
lrwxrwxrwx 1 root root 0 Jan  9 13:51 cgroup -> 'cgroup:[4026531835]'
lrwxrwxrwx 1 root root 0 Jan 20 12:11 ipc -> 'ipc:[4026532341]'
lrwxrwxrwx 1 root root 0 Jan 20 12:11 mnt -> 'mnt:[4026532339]'
lrwxrwxrwx 1 root root 0 Jul  9  2020 net -> 'net:[4026532344]'
lrwxrwxrwx 1 root root 0 Jan 20 12:11 pid -> 'pid:[4026532342]'
lrwxrwxrwx 1 root root 0 Jan  9 13:51 pid_for_children -> 'pid:[4026532342]'
lrwxrwxrwx 1 root root 0 Jan  9 13:51 user -> 'user:[4026531837]'
lrwxrwxrwx 1 root root 0 Jan 20 12:11 uts -> 'uts:[4026532340]'
```
每个文件都是对应 namespace 的文件描述符，方括号里面的值是 namespace 的 inode，如果两个进程所在的 namespace 一样，那么它们列出来的 inode 是一样的。
我们对比一下另外一个宿主机上的进程  
```
root@lxkaka-server:~# ls -l /proc/20/ns
total 0
lrwxrwxrwx 1 root root 0 Jan 20 12:19 cgroup -> 'cgroup:[4026531835]'
lrwxrwxrwx 1 root root 0 Jan 20 12:19 ipc -> 'ipc:[4026531839]'
lrwxrwxrwx 1 root root 0 Jan 20 12:19 mnt -> 'mnt:[4026531840]'
lrwxrwxrwx 1 root root 0 Jan 20 12:19 net -> 'net:[4026531993]'
lrwxrwxrwx 1 root root 0 Jan 20 12:19 pid -> 'pid:[4026531836]'
lrwxrwxrwx 1 root root 0 Jan 20 12:19 pid_for_children -> 'pid:[4026531836]'
lrwxrwxrwx 1 root root 0 Jan 20 12:19 user -> 'user:[4026531837]'
lrwxrwxrwx 1 root root 0 Jan 20 12:19 uts -> 'uts:[4026531838]'
```
可以看到进程，文件系统，网络，进程通信，主机名都是不同的 namespace。

#### 网络模式
Docker 虽然可以通过命名空间创建一个隔离的网络环境，但是如果我们的应用需要对外提供服务，不能与外界进行通信是没有意义的。Docker 提供了多种网络模式来实现容器和外部的通信。
我们重点介绍一下 docker 默认的网络模式 `bridge` 
![docker-bridge](https://pics.lxkaka.wang/docker-bridge.png)

守护进程会创建一对对等虚拟设备接口 veth pair，将其中一个接口设置为容器的 eth0 接口（容器的网卡），另一个接口放置在宿主机的命名空间中，以类似 vethxxx 这样的名字命名，从而将宿主机上的所有容器都连接到这个内部网络上。虚拟网桥的工作方式和物理交换机类似，这样主机上的所有容器就通过交换机连在了一个二层网络中。
* 容器访问外部网络  
请求通过 veth pair 到达 docker0 处，docker0 网桥开启了IP forwarding功能，将请求发送至宿主机eth0；
宿主机处理请求时，使用 SNAT 规则，将源地址替换成了宿主机 ip，然后把报文转发出去
* 外部访问容器 
docker run -p 时，docker 实际是在 iptables 做了DNAT规则，实现端口转发功能。
```
# iptables -t nat -L
Chain DOCKER (2 references)
target     prot opt source               destination
RETURN     all  --  anywhere             anywhere
DNAT       tcp  --  anywhere             anywhere             tcp dpt:8888 to:172.17.0.4:8888
```
外部请求访问访问地址为 宿主机ip:8888，网络包到达 eth0;
命中 iptables dnat 规则，把宿主机ip:8888 替换成 容器ip:8888;
宿主机把报文通过 veth pair 传递到容器 eth0

##### 其他网络模式
 * Host 模式
 和宿主机共用一个 Network Namespace。容器将不会虚拟出自己的网卡，配置自己的 IP 等，而是使用宿主机的 IP 和端口。但是，容器的其他方面，如文件系统、进程列表等还是和宿主机隔离的
 * Contanier 模式
 这个模式指定新创建的容器和已经存在的一个容器共享一个 Network Namespace，而不是和宿主机共享。新创建的容器不会创建自己的网卡，配置自己的 IP，而是和一个指定的容器共享 IP、端口范围等
 * None 模式
 使用none模式，Docker 容器拥有自己的 Network Namespace，但是，并不为Docker 容器进行任何网络配置。也就是说，这个 Docker 容器没有网卡、IP、路由等信息。需要我们自己为 Docker 容器添加网卡、配置 IP 等

 ### Cgroups
 通过 Linux Namespace 为新创建的进程隔离了文件系统、网络并与宿主机器之间的进程相互隔离，但是 Namespace 并不能够为我们提供物理资源上的隔离，比如 CPU 或者内存。所以 Docker 还借助了 Linux Cgroups 来达到上述目的。
 CGroup 全称 Linux Control Group， 是 Linux 内核的一个功能，用来限制，控制与分离一个进程组群的资源（如CPU、内存、磁盘输入输出等)
 一组按照某种标准划分的进程，其表示了某进程组，Cgroups 中的资源控制都是以控制组为单位实现，一个进程可以加入到某个控制组。而资源的限制是定义在这个组上，简单点说，cgroup 的呈现就是一个目录带一系列的可配置文件。
 理解 cgroups 的几个关键字
 * cgroup 进程组
 进程按照某种标准组织成一个控制组，资源的控制定义在这个组上，新加入的进程就继承该组的配置。比如 docker 启动的容器都加入 docker 这个进程组
 * subsystem 子系统
 cgroups 为每种可以控制的资源定义了一个子系统(即资源控制器)
 ```
 root@lxkaka-server:~# lssubsys
 cpuset # 分配单独的 cpu 节点或者内存节点
 cpu,cpuacct # 限制进程的 cpu 使用率;cpu 使用统计
 blkio # 限制进程的块设备 io
 memory # 限制进程的 memory 使用量
 devices # 控制进程能够访问某些设备
 freezer # 挂起或者恢复 cgroups 中的进程。
 net_cls,net_prio # 可以标记 cgroups 中进程的网络数据包，对数据包进行控制
 ```
 * hierarch 层级关系
 由一系列控制组以一个树状结构排列而成，hierarch 通过绑定对应的子系统进行资源调度。hierarch 中的 cgroup 节点可以包含零或多个子节点，子节点继承父节点的属性。整个系统可以有多个hierarchy。

配置示例   
`docker run -d --cpus=0.1 --memory=100MB busybox`  
```
root@lxkaka-server:/sys/fs/cgroup/cpu/docker/ee43bb16af9947ed9e8498ad42c859318e001365043e4cda410f68b4a0d79378# cat cpu.cfs_quota_us
10000

root@lxkaka-server:/sys/fs/cgroup/memory/docker/ee43bb16af9947ed9e8498ad42c859318e001365043e4cda410f68b4a0d79378# cat memory.limit_in_bytes
104857600
```

### 文件驱动
 Docker 中的每一个镜像都是由一系列只读的层组成的，Dockerfile 中的每一个命令都会在已有的只读层上创建一个新的层。当镜像被 docker run 命令创建时就会在镜像的最上层添加一个可写的层，也就是容器层，所有对于运行时容器的修改其实都是对这个容器读写层的修改。容器和镜像的区别就在于，所有的镜像都是只读的，而每一个容器其实等于镜像加上一个可读写的层，也就是同一个镜像可以对应多个容器。  

![docker-image](https://pics.lxkaka.wang/docker-image.png)  

这种分层的逻辑是什么呢？
这就是docker 里文件驱动的职责，负责镜像和容器的文件系统组织。  
目前 docker 默认的文件驱动是 `overlay2`, 它是基于 Linux OverlayFS 的，下面这张图映射了 docker 容器的文件层级结构和 OverlayFS 的对应关系。

![overlay2](https://pics.lxkaka.wang/docker-overlay.png)

OverlayFS 是一种堆叠文件系统，它依赖并建立在其它的文件系统之上，不直接参与磁盘空间结构的划分，仅将原来文件系统中不同目录和文件进行 merge。用户看到就是这个 merged 目录。这些被处理的每个目录都被称为层，视图统一的过程则称为联合挂载。多个目录进行层叠，肯定具有上下层关系，OverlayFS 将下层的目录称为lowerdir，上层的目录称为upperdir，被暴露的统一视图目录称为 merged。

#### 容器文件系统层级示例  
```
root@lxkaka-server:~# docker inspect a2b1e73dda7f
...
"GraphDriver": {
    "Data": {
        "LowerDir": "/var/lib/docker/overlay2/77a2b28678d5406b8184e213a725bac51e4bb0132cb2c2c7928c9805bbeb57e3-init/diff:/var/lib/docker/overlay2/2c24c0bcddaf45a0442e2aa1f061e5a10ac0bb327519c4c7ddc11ecb85878bb1/diff:/var/lib/docker/overlay2/4c689dd9bd8baaff479edf0549e7888b754bf9a635d354e4a7f1531bf946f936/diff:/var/lib/docker/overlay2/84b84a32ceb721075356a9f9d4e8f8c3272a3a440f732a639993293a221236cd/diff:/var/lib/docker/overlay2/fd803c843f13047fd21fda7270a8bec065a4ba62310f95aa5524ec3156755e25/diff:/var/lib/docker/overlay2/fe43a13d9aa35f8b6038d26db6fa83bbd9a108fa59e9599e520505e9b028105d/diff:/var/lib/docker/overlay2/ec929233dc85f54a5b13e906dc1ebd20328fefdebfe2a411a06b6551c501928c/diff",
        "MergedDir": "/var/lib/docker/overlay2/77a2b28678d5406b8184e213a725bac51e4bb0132cb2c2c7928c9805bbeb57e3/merged",
        "UpperDir": "/var/lib/docker/overlay2/77a2b28678d5406b8184e213a725bac51e4bb0132cb2c2c7928c9805bbeb57e3/diff",
        "WorkDir": "/var/lib/docker/overlay2/77a2b28678d5406b8184e213a725bac51e4bb0132cb2c2c7928c9805bbeb57e3/work"
    },
    "Name": "overlay2"
},
...
```
我们可以看到 lowerdir 包含了多层，每个镜像层目录中包含了一个文件 link，文件内容则是当前层对应的短标识符；lower 文件指向了其所有的父层，其文件内容则是父层id的短标识符；镜像层的内容则存放在 diff 目录
lowerdir 某层示例  
```
root@lxkaka-server:/var/lib/docker/overlay2/2c24c0bcddaf45a0442e2aa1f061e5a10ac0bb327519c4c7ddc11ecb85878bb1# ls
diff  link  lower  work
root@lxkaka-server:/var/lib/docker/overlay2/2c24c0bcddaf45a0442e2aa1f061e5a10ac0bb327519c4c7ddc11ecb85878bb1# ls
diff  link  lower  work
root@lxkaka-server:/var/lib/docker/overlay2/2c24c0bcddaf45a0442e2aa1f061e5a10ac0bb327519c4c7ddc11ecb85878bb1# cat link
5NC3EXCFR4DKUVKSTJQNDVB3SWroot@lxkaka-server:/var/lib/docker/overlay2/2c24c0bcddaf45a0442e2aa1f061e5a10ac0bb327519c4c7ddc11ecb85878bb1# cat lower
l/XJFQUCXRFOKWIS2NCRBGZOQ573:l/AOHICFFE7WZQDQIZIGXPZSUVPN:l/4DLC3KZMRJUW4GUIU3PIACENJB:l/55TW2N2I52PI5IQD7U5PCZ5H4O:l/5R5RBP6MZNORLVMAOJHVTWMWRN
```
查看容器层  
```
root@lxkaka-server:/var/lib/docker/overlay2/77a2b28678d5406b8184e213a725bac51e4bb0132cb2c2c7928c9805bbeb57e3# ls diff
root
root@lxkaka-server:/var/lib/docker/overlay2/77a2b28678d5406b8184e213a725bac51e4bb0132cb2c2c7928c9805bbeb57e3# ls merged/
bin  boot  data  dev  etc  home  lib  lib64  media  mnt  opt  proc  root  run  sbin  srv  sys  tmp  usr  var

# 进入到对应的容器
root@a2b1e73dda7f:/# ls
bin  boot  data  dev  etc  home  lib  lib64  media  mnt  opt  proc  root  run  sbin  srv  sys  tmp  usr  var
```
我们可以看到容器的目录结构和 `merged` 是一致的。


## 多阶段构建
在文章的最后我们介绍比较实用的优化构建的方法，多阶段构建 
下面的 dockerfile 是一个简单的 golang 应用构建过程 
```
FROM golang:1.15.6-alpine3.12

RUN mkdir -p /src
WORKDIR /src
COPY src/ .
RUN go build -o app .
EXPOSE 8000
ENTRYPOINT ["./app"]
```
对于这个例子来说我们其实只需要构建后的二进制包，其他文件包括 golang 我们都是不需要的。
我们可以把上述构建成两个阶段，可以大大减小构建后的镜像大小

```
FROM golang:1.15.6-alpine3.12 as builder

RUN mkdir -p /src
WORKDIR /src
COPY src/ .
RUN go build -o app .

FROM alpine:3.12

COPY --from=builder /src/ .
EXPOSE 8000
ENTRYPOINT ["./app"]
```
```
$ docker image ls
REPOSITORY                                        TAG                 IMAGE ID            CREATED             SIZE
app-test                                          v2                  0fde852a1af1        4 seconds ago       13MB
app-test                                          v1                  9d528c34a9f9        15 seconds ago      306MB
```
v2 是多阶段构建出来的可以看到相比 v1 体积减小了20多倍。
