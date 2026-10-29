# Istio 实践


在之前的文章中我们提到过, 服务拆分后，不同的服务之间必须进行交互才能实现特定的功能。在这里引入 **service mesh** 这个概念，service mesh 通常用于描述构成这些应用程序的微服务网络以及应用之间的交互。随着服务的规模和复杂性的增长，service mesh 变的越来越不容易理解和管理。这个时候必须引入相应的解决方案，于是有了 Istio, Linkerd 等 service mesh 框架。以 Istio 为例，它旨在解决大量微服务的发现、连接、管理、监控以及安全等问题。Istio 对应用是透明的，不需要改动任何服务代码就可以实现透明的服务治理。

## Istio 特性
Istio 只需要在我们的应用部署的环境中部署一个 sidecar 代理并使用 Istio 控制平面功能配置和管理代理，这个代理会拦截服务之间的通信。从而带来了以下特性
* HTTP、gRPC、WebSocket 和 TCP 流量的自动负载均衡。
* 通过丰富的路由规则、重试、故障转移和故障注入，可以对流量行为进行细粒度控制。
* 可插入的策略层和配置 API，支持访问控制、速率限制和配额。
* 对出入集群入口和出口中所有流量的自动度量指标、日志记录和跟踪。
* 通过强大的基于身份的验证和授权，在集群中实现安全的服务间通信。

## Istio 基本原理
Istio 服务网格逻辑上分为数据平面和控制平面。

* 数据平面由一组以 sidecar 方式部署的智能代理（Envoy）组成。这些代理可以调节和控制微服务及 Mixer 之间所有的网络通信。
* 控制平面负责管理和配置代理来路由流量。此外控制平面配置 Mixer 以实施策略和收集遥测数据。

下图显示了构成数据平面和控制平面的不同组件：
![istio](https://pics.lxkaka.wang/istio.png)

核心组件
* [Envoy](https://www.envoyproxy.io/docs/envoy/latest/start/start)  
Lyft 开源的高性能代理，用于调解服务网格中所有服务的入站和出站流量。它支持动态服务发现、负载均衡、TLS 终止、HTTP/2 和 gPRC 代理、熔断、健康检查、故障注入和性能测量等丰富的功能。Envoy 以 sidecar 的方式部署在相关的服务的 Pod 中，从而无需重新构建或重写代码。
* [Mixer](https://Istio.io/docs/concepts/policies-and-telemetry/)
负责访问控制、执行策略并从 Envoy 代理中收集遥测数据。Mixer 支持灵活的插件模型，方便扩展（支持 GCP、AWS、Prometheus、Heapster 等多种后端）。
* [Pilot](https://Istio.io/docs/concepts/traffic-management/#pilot-and-envoy)
动态管理 Envoy 实例的生命周期，提供服务发现、智能路由和弹性流量管理（如超时、重试）等功能。它将流量管理策略转化为 Envoy 数据平面配置，并传播到 sidecar 中。
Pilot 为 Envoy sidecar 提供服务发现功能，为智能路由（例如 A/B 测试、金丝雀部署等）和弹性（超时、重试、熔断器等）提供流量管理功能。它将控制流量行为的高级路由规则转换为特定于 Envoy 的配置，并在运行时将它们传播到 sidecar。Pilot 将服务发现机制抽象为符合 Envoy 数据平面 API 的标准格式，以便支持在多种环境下运行并保持流量管理的相同操作接口。
* Citadel  
Citadel 通过内置身份和凭证管理提供服务间和最终用户的身份认证。支持基于角色的访问控制、基于服务标识的策略执行等。
* Galle
是 Istio 1.0 中新引入的组件，在 Istio 中，承担配置的导入、处理和分发任务，为 Istio 提供了配置管理服务,提供在 k8s 服务端验证 Istio 的 CRD 资源的合法性的方法。

## 在 k8s 中搭建 Istio     
使用 helm 方式    
#### 1. 下载 istio 安装包  
   * `wget https://github.com/istio/istio/releases/download/1.0.4/istio-1.0.4-linux.tar.gz`  
   * `cd istio-1.0.4`
   * `export PATH=$PWD/bin:$PATH`  

#### 2. 下载 helm  
   * `wget https://storage.googleapis.com/kubernetes-helm/helm-v2.11.0-linux-amd64.tar.gz`  
   * `解压 and mv linux-amd64/helm /usr/local/bin/helm`  

#### 3. 安装      
   * 给 tiller 生成 cluste-admin的 serviceaccount
    `kubectl apply -f install/kubernetes/helm/helm-service-account.yaml`  
   * 部署 tiller    
    `helm init -i anjia0532/kubernetes-helm.tiller:v2.11.0 --service-account tiller`
   * 安装 istio（默认方式）  
     `helm install install/kubernetes/helm/istio --name istio --namespace istio-system`
   * 自定义方式    
     获取 cluster service 的 ip range, 使用这个 iprange pass cluster所有出口的请求   
     `kubectl cluster-info dump | grep service-cluster-ip-range`   

      ```
      helm install install/kubernetes/helm/istio --name istio --namespace istio-system \  
        --set global.proxy.includeIPRanges="10.233.0.0/18" \  
        --set gateways.istio-ingressgateway.type=NodePort \  
        --set tracing.enabled=true \  
        --set kiali.enabled=true \  
        --set grafana.enabled=true  
      ```

   * 是否成功安装  
     `helm ls --all`  
     `kubeclt get pod -n istio-system`  
     `kubectl get service -n istio-system`      

## 使用 Istio
#### 1. 部署服务
首先要把服务所在的 namespace 开启 Istio sidecar 自动注入  
` kubectl label namespace <namespace> istio-injection=enabled`  
 
然后我们部署一个 hello-service 的服务, 这个服务我们部署两个不同的版本 v1 和 v2         
示例的 service 和 deploymnent 配置如下  

```yaml
apiVersion: v1
kind: Service
metadata:
  name: hello-service
  labels:
    app: hello-service
spec:
  #type: NodePort
  ports:
  - port: 8888
    name: http
  selector:
    app: hello-service
---
apiVersion: extensions/v1beta1
kind: Deployment
metadata:
  name: hello-service-v1
spec:
  revisionHistoryLimit: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 3
      maxUnavailable: 1
  replicas: 1
  template:
    metadata:
      labels:
        app: hello-service
        version: v1
    spec:
      containers:
      - name: hello-service
        resources:
          requests:
            memory: "64Mi"
            cpu: "125m"
          limits:
            memory: "128Mi"
            cpu: "250m"
        image: kaka_server:v1
        imagePullPolicy: Always
        ports:
        - containerPort: 8888
        livenessProbe:
          httpGet:
            path: /
            port: 8888
          initialDelaySeconds: 1
          periodSeconds: 10
          timeoutSeconds: 2
          successThreshold: 1
          failureThreshold: 3
        volumeMounts:
        - mountPath: /home/kaka/logs
          name: hello
      volumes:
      - name: hello
        hostPath:
          path: /var/log/k8s
          type: DirectoryOrCreate
---
apiVersion: extensions/v1beta1
kind: Deployment
metadata:
  name: hello-service-v2
spec:
  revisionHistoryLimit: 3
  replicas: 1
  template:
    metadata:
      labels:
        app: hello-service
        version: v2
    spec:
      containers:
      - name: hello-service
        image: kaka_server:v2
        imagePullPolicy: Always
        ports:
        - containerPort: 8888
```

#### 2. 创建 Istio CRD  
首先了解下面的几个重要的 CRD，对我们服务的部署才能有更好的理解    

* Gateway：为网格配置网关，以允许一个服务可以被网格外部访问。
* Virtualservice：用于定义路由规则，如根据来源或 Header 制定规则，或在不同服务版本之间分拆流量。
* DestinationRule：定义目的服务的配置策略以及可路由子集。策略包括断路器、负载均衡以及 TLS 等。
* ServiceEntry：用 ServiceEntry 可以向Istio中加入附加的服务条目，以使网格内可以向istio 服务网格之外的服务发出请求。

#### 1. 创建 Istio Ingress Gateway
示例配置文件如下  

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: Gateway
metadata:
  name: hello-gateway
spec:
  selector:
    istio: ingressgateway # use Istio default gateway implementation
  servers:
  - port:
      number: 80
      name: http
      protocol: HTTP
    hosts:
    - "*"
```
这个 gateway 的作用作为我们整个 service mesh 的流量入口

#### 2. 创建 Virtualservice
这里我们定义两个路由规则, 把 80% 的流量路由到服务版本 v1, 20% 的流量路由到服务版本 v2  

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: hello-service
spec:
  hosts:
  - "hello-service.example.com"
  gateways:
    - hello-gateway
  http:
  - match:
    - uri:
        prefix: /
    route:
    - destination:
        #port:
        #number: 8888
        host: hello-service
        subset: v1
      weight: 80
    - destination:
        # port:
        #  number: 8888
        host: hello-service
        subset: v2
      weight: 20
```

##### 3. 创建 DestinationRule
定义服务的配置策略，示例把 不同的服务版本定义成了不同的 subset  

```yaml
apiVersion: networking.istio.io/v1alpha3  
kind: DestinationRule
metadata:
  name: hello-service
spec:
  host: hello-service
  subsets:
  - name: v1
    labels:
      version: v1
  - name: v2
    labels:
      version: v2
```

以上完成以后，我们访问 http://hello-service.example.com 就能看到大部分请求访问到了 hello-service v1, 小部分请求访问到了 hello-service v2.

下面这张图显示了 hello-service 在 Istio service mesh 下的流量管理  
![hello-service](https://pics.lxkaka.wang/hello-service.png)  

