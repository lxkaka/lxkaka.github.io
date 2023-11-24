# Kubernetes 基础概念


## Kubernetes 概述
Kubernetes 是一个跨主机集群的 开源的容器调度平台，它可以自动化应用容器的部署、扩展和操作 , 提供以容器为中心的基础架构。
使用 Kubernetes, 可以快速高效地响应客户需求:

* 快速、可预测地部署应用程序
* 拥有即时扩展应用程序的能力
* 不影响现有业务的情况下，无缝地发布新功能
* 优化硬件资源，降低成本

## Kubernetes 组件
我们先从下面这张图来总体把握 k8s 的架构  
![k8s](https://pics.lxkaka.wang/k8s.png)

### Master 组件 
Master 组件提供的集群控制。Master 组件对集群做出全局性决策(例如：调度)，以及检测和响应集群事件(副本控制器的replicas字段不满足时, 启动新的副本)。
下面这张图展示了 master 的构成  
![master](https://pics.lxkaka.wang/k8s-master.png)

master 又由下面重要的组件来实现它的功能：
* kube-apiserver  
  k8s API Server提供了k8s各类资源对象（pod,RC,Service等）的增删改查及watch等HTTP Rest接口，是整个系统的数据总线和数据中心。  
  kubernetes API Server的功能：  
    * 提供了集群管理的REST API接口(包括认证授权、数据校验以及集群状态变更)；
    * 提供其他模块之间的数据交互和通信的枢纽（其他模块通过API Server查询或修改数据，只有API Server才直接操作etcd）;
    * 是资源配额控制的入口；
    * 拥有完备的集群安全机制.

* kube-controller-manager
  Controller Manager作为集群内部的管理控制中心，负责集群内的Node、Pod副本、服务端点（Endpoint）、命名空间（Namespace）、服务账号（ServiceAccount）、资源定额（ResourceQuota）的管理，当某个Node意外宕机时，Controller Manager会及时发现并执行自动化修复流程，确保集群始终处于预期的工作状态。  
  每个Controller通过API Server提供的接口实时监控整个集群的每个资源对象的当前状态，当发生各种故障导致系统状态发生变化时，会尝试将系统状态修复到“期望状态”。  

* kube-scheduler  
  Scheduler负责Pod调度。在整个系统中起"承上启下"作用，承上：负责接收Controller Manager创建的新的Pod，为其选择一个合适的Node；启下：Node上的kubelet接管Pod的生命周期。  
  Scheduler：
    * 通过调度算法为待调度Pod列表的每个Pod从Node列表中选择一个最适合的Node，并将信息写入etcd中

    * kubelet通过API Server监听到kubernetes Scheduler产生的Pod绑定信息，然后获取对应的Pod清单，下载Image，并启动容器。

* etcd
  etcd 是 kubernetes 存放集群状态和配置的地方，这是集群状态同步的关键，所有节点都是从 etcd 中获取集群中其他机器状态的；集群中所有容器的状态也是放在这里的。

### Node 组件
Node是集群的工作负载节点，默认情况kubelet会向Master注册自己，一旦Node被纳入集群管理范围，kubelet会定时向Master汇报自身的情报，包括操作系统，Docker版本，机器资源情况等。  
如果Node超过指定时间不上报信息，会被Master判断为“失联”，标记为Not Ready，随后Master会触发Pod转移。
下面这张图展示了 node 主要构成
![node](https://pics.lxkaka.wang/k8s-node.png)

node 主要组成：
* kubelet
  kubelet是主要的节点代理,它监测已分配给其节点的 Pod(通过 apiserver 或通过本地配置文件)，提供如下功能:

    * 挂载 Pod 所需要的数据卷(Volume)。
    * 下载 Pod 的 secrets。
    * 通过 Docker 运行(或通过 rkt)运行 Pod 的容器。
    * 周期性的对容器生命周期进行探测。
    * 如果需要，通过创建镜像Pod（Mirror Pod)将 Pod 的状态报告回系统的其余部分。
    * 将节点的状态报告回系统的其余部分。

* kube-proxy
  kube-proxy 为 pod 提供代理服务。service是一组pod的服务抽象，相当于一组pod的LB，负责将请求分发给对应的pod。service会为这个LB提供一个IP，一般称为cluster IP。 kube-proxy的作用主要是负责service的实现，具体来说，就是实现了内部从pod到service和外部的从node port向service的访问。
  用下面这张图来展示 kube-proxy在 k8s 中的作用  
  ![kube-proxy](https://pics.lxkaka.wang/kube-proxy.png)

* docker
  容器的创建, 运行和管理

## Kubernetes 基本的服务部署
我们先用下面这张图来展示一个部署在 k8s 中的服务的逻辑组成
![deployment](https://pics.lxkaka.wang/deployment.jpeg)

* Pod  
  Pod 是Kubernetes的基本操作单元，也是应用运行的载体。整个Kubernetes系统都是围绕着Pod展开的，比如如何部署运行Pod、如何保证Pod的数量、如何访问Pod等。另外，Pod是一个或多个机关容器的集合，这可以说是一大创新点，提供了一种容器的组合的模型。    
  在Docker中，容器是最小的处理单元，增删改查的对象是容器，容器是一种虚拟化技术，容器之间是隔离的，隔离是基于Linux Namespace实现的。而在Kubernetes中，Pod包含一个或者多个相关的容器，Pod可以认为是容器的一种延伸扩展，一个Pod也是一个隔离体，而Pod内部包含的一组容器又是共享的（包括PID、Network、IPC、UTS）。除此之外，Pod中的容器可以访问共同的数据卷来实现文件系统的共享。

* RelicaSet
  在说 ReplicaSet 之前我们先要介绍一下 Replication Controller(RC). RC 是Kubernetes中的另一个核心概念，应用托管在Kubernetes之后，Kubernetes需要保证应用能够持续运行，这是RC的工作内容，它会确保任何时间Kubernetes中都有指定数量的Pod在运行。在此基础上，RC还提供了一些更高级的特性，比如滚动升级、升级回滚等。  
  RC与Pod的关联是通过Label来实现的。Label机制是Kubernetes中的一个重要设计，通过Label进行对象的弱关联，可以灵活地进行分类和选择。对于Pod，需要设置其自身的Label来进行标识，Label是一系列的Key/value对，在Pod-->metadata-->labeks中进行设置。  
  RelicaSet 是 RC的升级，它与当前RC的唯一区别在于Replica Set支持基于集合的Label Selector(Set-based selector)，而旧版本RC只支持基于等式的Label Selector(equality-based selector)。 Kubernetes1.2以上版本通过Deployment来维护Replica Set而不是单独使用Replica Set。即控制流为：Delpoyment→Replica Set→Pod。即新版本的Deployment+Replica Set替代了RC的作用。 

* Deployment    
  Kubernetes提供了一种更加简单的更新RC和Pod的机制，叫做Deployment。通过在Deployment中描述你所期望的集群状态，Deployment Controller会将现在的集群状态在一个可控的速度下逐步更新成你所期望的集群状态。Deployment主要职责同样是为了保证pod的数量和健康，90%的功能与Replication Controller完全一样，可以看做新一代的Replication Controller。但是，它又具备了Replication Controller之外的新特性：  

    * Replication Controller全部功能  
      Deployment继承了上面描述的Replication Controller全部功能。  

    * 事件和状态查看  
       可以查看Deployment的升级详细进度和状态。

    * 回滚  
      当升级pod镜像或者相关参数的时候发现问题，可以使用回滚操作回滚到上一个稳定的版本或者指定的版本。

    * 版本记录  
      每一次对Deployment的操作，都能保存下来，给予后续可能的回滚使用。

    * 暂停和启动  
      对于每一次升级，都能够随时暂停和启动。

    * 多种升级方案    
       Recreate----删除所有已存在的pod,重新创建新的; RollingUpdate----滚动升级，逐步替换的策略，同时滚动升级时，支持更多的附加参数，例如设置最大不可用pod数量，最小升级间隔时间等等。

* Service  
  在Kubernetes中，在受到RC调控的时候，Pod副本是变化的，对于的虚拟IP也是变化的，比如发生迁移或者伸缩的时候。这对于Pod的访问者来说是不可接受的。Kubernetes中的Service是一种抽象概念，它定义了一个Pod逻辑集合以及访问它们的策略，Service同Pod的关联同样是居于Label来完成的。Service的目标是提供一种桥梁， 它会为访问者提供一个固定访问地址，用于在访问时重定向到相应的后端，这使得非 Kubernetes原生应用程序，在无须为Kubemces编写特定代码的前提下，轻松访问后端。    
  Service同RC一样，都是通过Label来关联Pod的。当你在Service的yaml文件中定义了该Service的selector中的label为app:my-web，那么这个Service会将Pod-->metadata-->labeks中label为app:my-web的Pod作为分发请求的后端。当Pod发生变化时（增加、减少、重建等），Service会及时更新。这样一来，Service就可以作为Pod的访问入口，起到代理服务器的作用，而对于访问者来说，通过Service进行访问，无需直接感知Pod。  
  需要注意的是，Kubernetes分配给Service的固定IP是一个虚拟IP，并不是一个真实的IP，在外部是无法寻址的。真实的系统实现上，Kubernetes是通过Kube-proxy组件来实现的虚拟IP路由及转发。所以在之前集群部署的环节上，我们在每个Node上均部署了Proxy这个组件，从而实现了Kubernetes层级的虚拟转发网络。    
  我们用下面这张图来说明 service 的作用  
  ![service](https://pics.lxkaka.wang/service.png)





