# Flannel 在 k8s 中的使用


在处理过的 k8s 集群的众多问题中数据链路的问题往往是最复杂，最难排查的。这需要我们对 k8s 集群的网络通信的过程有着清晰的认识。Docker 通过 veth 虚拟网络设备以及 Linux bridge 实现了同一台主机上的容器网络通信，再通过 iptables 进行 NAT 实现了容器和外部网络的通信。而 k8s 作为容器编排平台，集群中有众多节点，并且每个节点上也部署了众多 pod, 要实现 pod 跨节点通信，就没有这么简单了。

### k8s 网络模型
为了解决 k8s 当中网络通信的问题，K8s 作为一个容器编排平台提出了 k8s 网络模型，但是并没有自己去实现，具体网络通信方案通过网络插件来实现。

其实 K8s 网络模型当中总共只作了三点要求：

* 运行在一个节点当中的 Pod 能在不经过NAT的情况下跟集群中所有的 Pod 进行通信
* 节点当中的客户端（system daemon、kubelet）能跟该节点当中的所有 Pod 进行通信
* 以 host network 模式运行在一个节点上的Pod能跟集群中所有的 Pod 进行通信
从 k8s 的网络模型我们可以看出来，在 k8s 当中希望做到的是每一个 Pod 都有一个在集群当中独一无二的IP，并且可以通过这个 IP 直接跟集群当中的其他 Pod 以及节点自身的网络进行通信，一句话概括就是 k8s 当中希望网络是扁平化的。
所以只要再符合 k8s 网络模型的要求，就可以以插件的方式在 k8s 集群中作为跨节点网络通信实现。目前比较流行的实现有 flannel, calico, weave, canal等。
这里结合我们自己在阿里云中的 k8s 集群的 CNI **flannel** 来解释 pod 之间的通信过程。

### Flannel 介绍
Flannel 是由 CoreOS 团队针对 k8s 设计的一个  Overlay Network(也就是将TCP数据包装在另一种网络包里面进行路由转发和通信) 实现，目前已经支持UDP、VxLAN、AWS VPC和GCE路由等数据转发方式，实现集群间网络通讯。  
在 k8s 各个节点上通过DaemonSet的方式运行了一个 flannel 的Pod
`kubectl get ds -n kube-system app=flannel`    
```
NAME              DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR                                               AGE
kube-flannel-ds   4         4         4       4            4           beta.kubernetes.io/arch=amd64,beta.kubernetes.io/os=linux   63d
```
每一个 flannel 的 Pod 当中都运行了一个 flanneld 进程，且 flanneld 的配置文件以 ConfigMap 的形式挂载到容器内的 /etc/kube-flannel/目录供 flanneld 使用。 
flannel 通过在每一个节点上启动一个叫 flanneld 的进程，负责每一个节点上的子网划分，并将相关的配置信息如各个节点的子网网段、外部IP等保存到 etcd 当中，而具体的网络包转发交给具体的 Backend 来实现。
flanneld 可以在启动的时候通过配置文件来指定不同的 Backend 来进行网络通信，目前比较成熟的 Backend 有 VXLAN、host-gw以及UDP三种方式，也已经有诸如AWS，GCE and AliVPC这些还在实验阶段的 Backend。VXLAN 是目前官方最推崇的一种 Backend 实现方式，host-gw 一般用于对网络性能要求比较高的场景，但需要基础架构本身的支持，UDP 则一般用于 Debu g和一些比较老的不支持 VXLAN 的 Linux 内核。  
![flannel-arch](https://pics.lxkaka.wang/flannel-arch.png)
flannel 默认使用 UDP 作为集群间通讯实现，如上图所示，flannel 通过 etcd 管理整个集群中所有节点与子网的映射关系，如上图所示，flannel分别为节点A和B划分了两个子网：10.1.15.0/16和10.1.20.0/16。同时通过修改docker启动参数，确保Docker启动的容器能够特定的网段中如10.1.15.1/24。
* 同一 Pod 实例容器间通信：对于 Pod 而言，其可以包含1~n个容器实例，这些容器实例共享 Pod 的存储以及网络资源，Pod 直接可以直接通过127.0.0.1进行通讯。其通过 Linux 的 Network Namespace 为这组容器实现了一个隔离网络。
* 相同主机上 Pod 间通信：对于 Pod 而言，每一个 Pod 实例都有一个独立的 Pod IP，该 IP 是挂载到虚拟网卡（VETH）上，并且 bridge 到docker0 的网卡上。以节点A为例，其节点上运行的 Pod 均在10.1.15.1/24的网段中，其属于相同网络，因此直接通过 docker0 进行通信。
* 对于跨节点间的 Pod 通信：以节点A和节点B通讯而言，由于不同节点 docker0 网卡的网段并不相同，因此 flannel 通过主机路由表的方式，将对节点B POD IP网段地址的访问路由到 flannel0 的网卡上。 而 flannel0 网卡的背后运行的则是 flannel 在每个节点上运行的进程 flanneld。由于 flannel通过 ETCD 维护了节点间所有网络的路由关系，原本容器将的数据报文，被 flanneld 封装成 UDP 协议，发送到了目标节点的 flanneld 进程，再对 udp 报文进行解包，后将数据发送到 docker0，从而实现跨主机的 Pod 通讯。

### 公有云中的 flannel
上面我们解释了 flannel backend 为 UDP的通信过程。由于 UDP 作为backend存在明显的性能问题，一般生产环境不会使用这种方式，而在像 AWS 阿里云这样的公有云厂商提供的 k8s 集群服务中的 flannel 优先选择 vpc 作为backend, 这种方式其实类似 host-gw(Host Gateway)。
就像上面我们所说，flannel 通过 etcd 会统一为每个节点分配相应的网段， 下面为一个特定节点的网段
```
$ cat /run/flannel/subnet.env
FLANNEL_NETWORK=172.20.0.0/16
FLANNEL_SUBNET=172.20.1.1/25
FLANNEL_MTU=1500
FLANNEL_IPMASQ=true
```
如上所示，flannel 建立了一个 172.20.0.0/16 的大网段，而这个节点则分配了 一个172.20.1.1/25的小网段。所以该节点上所有Pod的IP地址一定是在该网段中（172.20.1.1 ~ 172.20.1.126).
节点的网卡信息如下  
```
cni0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 172.20.1.1  netmask 255.255.255.128  broadcast 0.0.0.0
        ether 0a:58:ac:14:01:01  txqueuelen 1000  (Ethernet)
        RX packets 78766736  bytes 6621717501 (6.1 GiB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 106139605  bytes 12076081112 (11.2 GiB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

docker0: flags=4099<UP,BROADCAST,MULTICAST>  mtu 1500
        inet 169.254.123.1  netmask 255.255.255.0  broadcast 169.254.123.255
        ether 02:42:ed:90:79:ea  txqueuelen 0  (Ethernet)
        RX packets 0  bytes 0 (0.0 B)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 0  bytes 0 (0.0 B)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 172.19.220.255  netmask 255.255.240.0  broadcast 172.19.223.255
        ether 00:16:3e:1a:6b:dc  txqueuelen 1000  (Ethernet)
        RX packets 119587253  bytes 30187869460 (28.1 GiB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 84789814  bytes 20787336532 (19.3 GiB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536
        inet 127.0.0.1  netmask 255.0.0.0
        loop  txqueuelen 1000  (Local Loopback)
        RX packets 1191  bytes 172882 (168.8 KiB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 1191  bytes 172882 (168.8 KiB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

veth005c911b: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        ether d2:de:24:f6:e2:13  txqueuelen 0  (Ethernet)
        RX packets 66417441  bytes 6329850773 (5.8 GiB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 95129695  bytes 8452269811 (7.8 GiB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

veth027b91b9: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        ether b6:e3:ee:c6:86:2f  txqueuelen 0  (Ethernet)
        RX packets 1746691  bytes 150672105 (143.6 MiB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 1790627  bytes 164054145 (156.4 MiB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0
# 其他veth省略
```
其中 veth177b8616 是每个 Pod 的虚拟网卡，并且连接到网桥 cni0：
```
$ brctl show cni0
bridge name	bridge id		      STP enabled	interfaces
cni0        8000.0a58ac140101	  no	        veth005c911b
                                                veth027b91b9
                                                veth4963357e
                                                veth6b1d3200
                                                veth6c793e18
                                                veth8e551bfa
```
* 数据包出
该点上的 pod 内的数据包通过网桥方式发送到 cni0.  
cni0怎么转发数据包呢？这里是使用的就是在 vpc 中建立的路由规则
![vpc-route](https://pics.lxkaka.wang/vpc-route.png)
例如数据包的目标 pod ip 是 172.20.1.43 则会匹配到图中的路由规则，然后转发到 pod 所在的节点。

* 数据包入
此时，数据包已经到达节点，那么怎么发送到目标 pod 呢？
查看接收流量主机的路由规则：
```
$ route -n
Kernel IP routing table
Destination     Gateway         Genmask         Flags Metric Ref    Use Iface
0.0.0.0         172.19.223.253  0.0.0.0         UG    0      0        0 eth0
169.254.0.0     0.0.0.0         255.255.0.0     U     1002   0        0 eth0
169.254.123.0   0.0.0.0         255.255.255.0   U     0      0        0 docker0
172.19.208.0    0.0.0.0         255.255.240.0   U     0      0        0 eth0
172.20.1.0      0.0.0.0         255.255.255.128 U     0      0        0 cni0
```
根据主机路由表规则，发送到 pod 172.16.1.43 的请求会落到路由表
`172.20.1.0      0.0.0.0         255.255.255.128 U     0      0        0 cni0`
然后数据包被发给网桥 cni0 然后经 veth 虚拟网卡 发送到 pod.
上述过程我们用下面这张示意图来总结    
![flannel-vpc](https://pics.lxkaka.wang/flannel%20in%20vpc.png)

像开始我们说的那样一个主机中的容器通过 bridge 模式就能实现容器与容器，容器与主机的通信。flannel 更像是这种模式的扩展，集群的主机如果都在一个子网内，就配置路由转发过去；若是不在一个子网内，就通过隧道转发过去。

