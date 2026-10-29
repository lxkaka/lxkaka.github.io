# Nginx Ingress 进阶——灰度发布


[Nginx Ingress Controller](https://kubernetes.github.io/ingress-nginx/) 作为 Kubernetes 官方推荐的 ingress controller 实现，可以说是非常好用，尤其是在你之前如果使用 Nginx 作为反向代理或者负载均衡，那么对于 nginx ingress controller 的应用也会得心应手。Nginx ingress controller 对外暴露 kubernetes 中的服务，作为外部流量的入口，是集群中非常关键的组件。我们这篇文章关注 nginx ingress 通过 annotation 提供的流量管理功能，利用 annotation 的配置可以轻松帮助我们实现金丝雀发布和A/B test。

### Nginx ingress annotations  
假设我们现在部署了两个版本的服务，老版本和 canary 版本
* nginx.ingress.kubernetes.io/canary-by-header
  请求头中如果包含了这个 annotation 设置的值，则流量被转发到 canary 版本的服务  
* nginx.ingress.kubernetes.io/canary-by-header-value
  这个 annotation 是配合 `nginx.ingress.kubernetes.io/canary-by-header` 来使用的，当请求头对应上面配置的 header 的值与这个 annotation 匹配， 则流量转发到 canary 版本
* nginx.ingress.kubernetes.io/canary-weight 
  根据权重来转发流量，配置的权重值为 0-100。如配置 30 ，则把 30% 的流量转发到 canary 版本
* nginx.ingress.kubernetes.io/canary-by-cookie
  根据请求头中的 cookie 转发流量，如果 cookie 与配置的 annotation 的值匹配，且 cookie 的 value 是 `always`, 则该请求会被转发到 canary 版本

### 部署服务
这里我们服务的 deployment 就不展示了，service 配置如下
```yml
# 测试版本
apiVersion: v1
kind: Service
metadata:
    name: hello-service
    labels:
    app: hello-service
spec:
ports:
- port: 80
    protocol: TCP
selector:
    app: hello-service
# canary 版本
apiVersion: v1
kind: Service
metadata:
    name: canary-hello-service
    labels:
    app: canary-hello-service
spec:
ports:
- port: 80
    protocol: TCP
selector:
    app: canary-hello-service
```

### 根据权重转发
ingress 配置如下
```yaml
apiVersion: extensions/v1beta1
kind: Ingress
metadata:
  name: canary
  annotations:
    kubernetes.io/ingress.class: nginx
    nginx.ingress.kubernetes.io/canary: "true"
    nginx.ingress.kubernetes.io/canary-weight: "30"
spec:
  rules:
  - host: canary-service.abc.com
    http:
      paths:
      - backend:
          serviceName: canary-hello-service 
          servicePort: 80
```
测试结果如下  
```shell
$ for i in $(seq 1 10); do curl http://canary-service.abc.com; echo '\n'; done

hello world-version1
hello world-version1
hello world-version2
hello world-version2
hello world-version1
hello world-version1
hello world-version1
hello world-version1
hello world-version1
hello world-version1
```
### 根据请求头转发
`annotation` 配置如下（ingress 其余部分省略）
```yaml
annotations:
  kubernetes.io/ingress.class: nginx
  nginx.ingress.kubernetes.io/canary: "true"
  nginx.ingress.kubernetes.io/canary-by-header: "test"
```
测试结果如下
```shell
$ for i in $(seq 1 5); do curl http://canary-service.abc.com; echo '\n'; done
hello world-version1
hello world-version1
hello world-version1
hello world-version1
hello world-version1

$ for i in $(seq 1 5); do curl -H 'test:always' http://canary-service.abc.com; echo '\n'; done
hello world-version2
hello world-version2
hello world-version2
hello world-version2
hello world-version2
```

### 根据特定的请求头和值转发
annotation 配置如下
```yaml
  kubernetes.io/ingress.class: nginx
  nginx.ingress.kubernetes.io/canary: "true"
  nginx.ingress.kubernetes.io/canary-by-header: "test"
  nginx.ingress.kubernetes.io/canary-by-header-value: "abc"
```
测试结果如下：  
```shell
$ for i in $(seq 1 5); do curl -H 'test:always' http://canary-service.abc.com; echo '\n'; done
hello world-version1
hello world-version1
hello world-version1
hello world-version1
hello world-version1

$ for i in $(seq 1 5); do curl -H 'test:abc' http://canary-service.abc.com; echo '\n'; done
hello world-version2
hello world-version2
hello world-version2
hello world-version2
hello world-version2
```
### 根据 cookie 转发
使用 cookie 来进行流量管理的场景比较适合用于 A/B test，比如用户的请求 cookie 中含有特殊的标签，那么我们可以把这部分用户的请求转发到特定的服务进行处理。  
annotation 配置如下  
```yaml
  kubernetes.io/ingress.class: nginx
  nginx.ingress.kubernetes.io/canary: "true"
  nginx.ingress.kubernetes.io/canary-by-cookie: "like_music"
```  
测试结果如下  
```shell
$ for i in $(seq 1 5); do curl -b 'like_music=1' http://canary-service.abc.com; echo '\n'; done
hello world-version1
hello world-version1
hello world-version1
hello world-version1
hello world-version1

$ for i in $(seq 1 5); do curl -b 'like_music=always' http://canary-service.abc.com; echo '\n'; done
hello world-version2
hello world-version2
hello world-version2
hello world-version2
hello world-version2
```
三种 `annotation` 按如下顺序匹配  
`canary-by-header > canary-by-cookie > canary-weight`

### 总结  
我们从以上的测试结果来看，可以把流量的转发分成以下两类  
1. 根据权重  
```
    nginx.ingress.kubernetes.io/canary: "true"
    nginx.ingress.kubernetes.io/canary-weight: "30"

                                         70%
                                      |------> 生产版本
users --- 100% ---> Nginx Ingress ----|  30%
                                      |------> canary 版本
```
2. 根据用户
```
    nginx.ingress.kubernetes.io/canary: "true"
    nginx.ingress.kubernetes.io/canary-by-header: "test"
    nginx.ingress.kubernetes.io/canary-by-header-value: "abc"

                                      others
                                  |-----------> 生产版本
users ------> Nginx Ingress ------| "test:abc"
                                  |-----------> canary 版本
```

