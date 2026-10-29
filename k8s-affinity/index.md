# 利用 K8s NodeAffinity 隔离服务


我们知道在默认情况下，pod 的调度会由 scheduler-crontroller 根据节点资源和优先级来自动完成。但是有一些场景，我们希望把特定的 pod 调度到特定的节点，就不能让 scheduler 自动完成。这个时候我们可以利用 k8s 的 **NodeSelector** 或者 **NodeAffinity**来实现。  
有这样一个场景，在我们的集群里部署了 Prometheus, 但是随着集群规模的扩大 Prometheus 需要抓取的指标数量十分巨大。这样部署 Prometheus 的实例 I/O 压力会很大，这样会导致实例本身变得不够稳定。这样一来跟 Prometheus 部署在同一个实例上的服务就容易受到影响，导致不可用。所以，我们应该把 Prometheus 这样占用资源很多的服务与其他服务隔离开来。解决办法也是很自然的想法，就是把 Promethues 这样的服务固定到某些实例上，且其他服务不会漂移到这样的实例上。

### NodeSelector  
使用 NodeSelector 是最简单的方式。原理就是我们给 node 打上标签，NodeSelector 是 pod spec 的一个字段，只要给它赋值 node 对应的标签。scheduler 就只会把 pod 调度到具有该标签的 node 上。
* 节点打标签
```
# 列出节点
kubectl get no
# 打标签
kubectl label no node3 test_label=yes
# 查看标签
kubectl get no node3 --show-labels
# 删除标签
kubectl label no node3 test_label-
```

* 配置添加 NodeSelector   
```
apiVersion: v1
kind: Pod
metadata:
  name: hello-service
  labels:
    env: test
spec:
  containers:
  - name: hello-sevice
    image: xxxx/hello-service:latest
    imagePullPolicy: IfNotPresent
  nodeSelector:  #Add this field
    test_label: yes
```
## NodeAffinity
NodeAffinity 应用上和 NodeSelector 相似。与后者相比优点是:
* 语法支持的操作符丰富 （in, NotIn, Exists, DoesNotExit, Gt, Lt）  
* 规则可以更灵活，可以不是硬性要求，简单说就是即使不满足条件也能调度成功  
具体 NodeAffinity 支持的策略包括：  
* **requiredDuringSchedulingIgnoredDuringExecution**：必须满足指定的规则才可以调度Pod到Node上（功能与nodeSelector很像，语法不同），相当于硬限制。
* **preferredDuringSchedulingIgnoredDuringExecution**：强调优先级，可以设置权重，但不是强制的，相当于软限制。  
示例配置  
```yml
apiVersion: v1
kind: Deployment
metadata:
  name: dep-affinity
spec:
  replicas: 1
  template:
    metadata:
      labels:
        app: test-app
    spec: 
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:  # 硬限制
            nodeSelectorTerms:
            - matchExpressions:
              - key: beta.kubernetes.io/arch
                operator: In
                values:
                - amd64
          preferredDuringSchedulingIgnoredDuringExecution:  # 软限制
          - weight: 1
            preference:
              matchExpressions:
              - key: test_label
                operator: In
                values:
                - yes
      containers:
      - name: dep-affinity
        image: xxxx/hello-service:latest
```
需要注意的地方  
* 如果同时定义了 nodeSelector 和 nodeAffinity，那么必须两个条件都得到满足，pod 才能最终运行在指定的 node 上。
* 如果 nodeAffinity 指定了多个 nodeSelectorTerms，那么只需要其中一个能够匹配成功即可。
* 如果 nodeSelectorTerms 中有多个 matchExpressions,则一个节点必须满足所有 matchExpressions 才能运行该 pod。
* 如果一个 pod 所在的节点在Pod运行期间标签发生了变化，不再符合该 pod 的亲和性需求，pod 不会进行重新调度，继续在该节点上运行。

## podAffinity and podAntiAffinity  
根据正在节点上运行的 pod 的标签来对 pod 进行调度而不是使用 node 的标签。简单说就是根据已存在 pod 来决定要不要和它部署在同一 node 上。 生效策略与 NodeAffinity 一样有硬限制（requiredDuringSchedulingIgnoredDuringExecution）和软限制（preferredDuringSchedulingIgnoredDuringExecution）  
示例配置如下  
```yml
apiVersion: v1
kind: Pod
metadata:
  name: pod-affinity
spec:
  affinity:
    podAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
          - key: test_pod
            operator: In
            values:
            - pod1
        topologyKey: failure-domain.beta.kubernetes.io/zone
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchExpressions:
            - key: app
              operator: In
              values:
              - nginx
          topologyKey: kubernetes.io/hostname
  containers:
  - name: pod-affinity
    image: xxxxx/hello-service:latest
```
上面的 podAffinity 表示被调度 pod 只能运行在集群中的特定节点上，这些节点已经至少运行一个具有"test_pod=pod1"标签的 pod，并且和这些节点在同一个 zone;
podAntiAffinity 表示如果 node 上已经有 "app=nignx"标签的 pod, 则优先不调度到该节点。  
需要注意的地方   
为了性能考虑只允许一些有限的topologyKey，默认情况下，有以下几个：  
* kubernetes.io/hostname
* failure-domain.beta.kubernetes.io/zone
* failure-domain.beta.kubernetes.io/region
除了设置 LabelSelector 和 topologyKey,还可以指定 namespace 列表来进行限制，同样，使用 LabelSelector 对 namespace 进行选择。namespace 的定义和LabelSelector及 topologyKey 同级。 省略namespace的设置，表示使用定义了 affinity/anti-affinity 的 pod 所在的 namespace。 如果namespace设置为空值（""），则表示所有namespace。    
在所有关联requiredDuringSchedulingIgnoredDuringExecution的matchExpressions 全部满足之后，系统才能将Pod调度到某个Node上。  



