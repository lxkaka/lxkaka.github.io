# k8s 中部署 Harbor


随着我们服务的全面容器化，代码和配置都以 docker image 的形式存储在 docker registry 中。搭建高可用，安全的企业r私有 docker registy 就变得十分必要。 
Harbor 作为 CNCF 托管的开药 docker registry 项目是我们的首先。它除了提供存储、签名、扫描镜像的功能，还有常用的功能如鉴权、授权、权限管理等来增强 docker registry 的安全性。
除此之外，Harbor 还有从其他 registry 复制镜像的功能，新版本集成了 chartmuseum 从而可以作为 Helm Charts 的 repository。Harbor 一个重要的特点是它是通过可插拔的方式来
集合第三方组件来提供不同的功能，比如用于镜像签名的 notary；镜像扫描的 clair; 镜像存储，推送和拉取的 docker registry；helm charts 存储，管理的 chartmuseum。

在之前我们其实已经通过 docker-compose 搭建了 Harbor。这里主要介绍的是 Harbor 的工作原理和在 k8s 中部署 Harbor。
首先，我们结合 Harbor 的架构来介绍一下各个组件的功能。

### Harbor 架构  
下面这张图是来自 Harbor github 的官方架构图，结合这张图我们介绍一下关键的组件    

![harbor-arch](https://pics.lxkaka.wang/harbor-architecture-1.10.png)  

#### 数据层  
* redis
  用于数据缓存和定时，异步任务的临时存储  

* 镜像存储  
  支持的方式非常多，比如本地磁盘，网络文件系统(NAS), 对象存储(S3, OSS)等等  
  
* 数据库  
  新版本使用 PostgreSQL, 用来存储 Harbor 里创建的 projects, users, roles , replication policies, tag retention policies, clair 从各大开源社区获取的CVE漏洞缺陷数据以及镜像层的扫描结构数据
  
### 核心组件
* proxy
  用 nginx 作为反向代理，转发来自浏览器和 docker 客户端的请求到不同的后端服务，比如 core, registry, token service, 网页客户端入口服务等

* core
  核心模块，包括鉴权和授权；配置管理；项目管理；项目容量管理；代理 chartmuseum; 镜像复制管理; 镜像扫描管理；webhook 提供的回调等等
  
* job service
  处理定时任务和异步任务，主要包括镜像同步，镜像扫描任务

* chart museum
  第三方开源 chart repository, 提供 helm chart 的管理和 api 访问

* docker registry
  第三方 registry 服务, 镜像处理的核心组件，处理镜像的上传、下拉等，直接操作镜像存储服务，如 S3、nas 等
  
* notary
  第三方内容信任服务，用来保证镜像在 pull，push 和传输过程中的一致性和完整性

### 鉴权过程  
这里我们重点描述一下 docker 客户端登录 Harbor 的过程  
在客户端登录我们自然首先会输入以下命令  
`docker login harbor.abc.com`  
然后输入我们的用户名和密码  
1.客户端首先发送一个 GET 请求 *harbor.abc.com/v2* 到 registry 服务  

2.registry 服务配置的是通过 JWT token 鉴权，所以返回的是一个 401 错误码，并且同时会在 response 的 header  
里通知客户端去获取 token 的真正地址。Harbor 里这个地址指向的是 core service    

3.客户度收到 401 和 response, 接着发送获取 token 的请求到指定的 url, 这个 url 会是 *harbor.abc.com/service.token*，在 request 的
header 中包含用户民和密码    

4.token service（被包含在 core 的容器中）接收到请求后，解析请求拿到用户民和密码，然后去数据库中验证用户的有效性。token service 可以
配置对接外部的 LDAP/AD 来进行认证。认证成功后，返回 200 并且 response body 中包含由私钥产生的 JWT token   
 
5.docker 客户端收到 200 请求，则登录成功。打印出 `Login Succeeded`    

 ```
|---------------|           |----------|           |---------------|
| docker client |           | registry |           | token service |
|---------------|           |----------|           |---------------|
      |   1. harbor.abc.com/v2   |                         |            
      |------------------------->|                         |                         
      |        2. return 401     |                         |                         
      |<-------------------------|                         |                         
      |        3. harbor.abc.com/service/token             |                        
      |--------------------------------------------------->|                                                   
      |        4. return 200                               |           
      |<---------------------------------------------------|
      |                          |                         |
      |   5. login success       |                         |
  
 ```
 
push 镜像的过程和登录类似，主要区别在  
鉴权那一步，会具体检查用户是否有往对应项目推送 image 的权限。   

### k8s 部署  
推荐使用 Helm 安装
* 下载 harbor helm chart
`wget https://github.com/goharbor/harbor-helm/archive/v1.2.2.tar.gz` 

* 解压，复制一份 values.yaml 进行定制
推荐使用 ingress 对外暴露服务    
主要需要修改的配置是数据持久化和镜像存储，这里我们使用 NAS 通过区分 subpath, 把同一个 PVC 挂载到不同的容器   

```yaml

# The persistence is enabled by default and a default StorageClass
# is needed in the k8s cluster to provision volumes dynamicly.
# Specify another StorageClass in the "storageClass" or set "existingClaim"
# if you have already existing persistent volumes to use
#
# For storing images and charts, you can also use "azure", "gcs", "s3",
# "swift" or "oss". Set it in the "imageChartStorage" section
persistence:
  enabled: true
  # Setting it to "keep" to avoid removing PVCs during a helm delete
  # operation. Leaving it empty will delete PVCs after the chart deleted
  resourcePolicy: "keep"
  persistentVolumeClaim:
    registry:
      # Use the existing PVC which must be created manually before bound,
      # and specify the "subPath" if the PVC is shared with other components
      existingClaim: "harbor-nas"
      # Specify the "storageClass" used to provision the volume. Or the default
      # StorageClass will be used(the default).
      # Set it to "-" to disable dynamic provisioning
      storageClass: ""
      subPath: "registry"
      accessMode: ReadWriteOnce
      size: 5Gi
    chartmuseum:
      existingClaim: "harbor-nas"
      storageClass: ""
      subPath: "chartmuseum"
      accessMode: ReadWriteOnce
      size: 5Gi
    jobservice:
      existingClaim: "harbor-nas"
      storageClass: ""
      subPath: "jobservice"
      accessMode: ReadWriteOnce
      size: 1Gi
    # If external database is used, the following settings for database will
    # be ignored
    database:
      existingClaim: "harbor-nas"
      storageClass: ""
      subPath: "database"
      accessMode: ReadWriteOnce
      size: 10Gi
    # If external Redis is used, the following settings for Redis will
    # be ignored
    redis:
      existingClaim: "harbor-nas"
      storageClass: ""
      subPath: "redis"
      accessMode: ReadWriteOnce
      size: 1Gi
```  
NAS PVC, 前提是在阿里云中开通了 NAS 并且集群中要创建 alicloud-nas-controller(具体可参照阿里云 NAS 文档)

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: alicloud-nas
mountOptions:
- nolock,tcp,noresvport
- vers=3
parameters:
  volumeAs: subpath
  server: "xxxxx"
provisioner: alicloud/nas
reclaimPolicy: Delete
---
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
 name: harbor-nas
spec:
 accessModes:
    - ReadWriteMany
 resources:
   requests:
     storage: 50Gi
 storageClassName: alicloud-nas
```

* 部署  
在解压后的目录里执行    
`helm install --name harbor -f edited_values.yaml . --namespace harbor` 

* 检查部署  
部署完成后我们可以看到部署了以下服务   

```
NAME                                 READY   UP-TO-DATE   AVAILABLE   AGE
harbor-chartmuseum     1/1     1            1           2d1h
harbor-clair           1/1     1            1           2d1h
harbor-core            1/1     1            1           2d1h
harbor-jobservice      1/1     1            1           2d1h
harbor-notary-server   1/1     1            1           2d1h
harbor-notary-signer   1/1     1            1           2d1h
harbor-portal          1/1     1            1           2d1h
harbor-registry        1/1     1            1           2d1h
```
 

