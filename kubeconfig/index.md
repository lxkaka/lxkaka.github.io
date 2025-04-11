# kubectl 操作 Kubernetes 的权限控制


Kubernetes 集群的安全性的重要程度不用强调，当我们与集群交互时，不管是通过 **kubernetes-dashborad** 还是通过命令行工具 **kubectl** 都需要进行身份验证和鉴权。那么我们是怎么利用 k8s 本身提供的能力来做身份验证和鉴权的呢？
Kubernetes 集群的访问权限控制由 kube-apiserver 负责，kube-apiserver 的访问权限控制由身份验证(authentication)、授权(authorization)和准入控制（admission control）三步骤组成，这三步骤是按序进行的。
* authentication
k8s 支持 tls client certificate、basic auth、token 等方式对客户端发起的请求进行身份校验。APIServer 启动时，可以指定一种 Authentication 方法，也可以指定多种方法。如果指定了多种方法，那么 APIServer 将会逐个使用这些方法对客户端请求进行验证，只要请求数据通过其中一种方法的验证，APIServer 就会认为 Authentication 成功。 

* authorization  
APIServer 支持多种 authorization mode，包括 Node、RBAC、Webhook 等。APIServer 启动时，可以指定一种 authorization mode，也可以指定多种 authorization mode，如果是后者，只要 Request 通过了其中一种 mode 的授权，那么该环节的最终结果就是授权成功。authorization-mode 的默认配置是 ”Node,RBAC”。Node 授权器主要用于各个 node 上的 kubelet 访问 apiserver 时使用的，其他一般均由 RBAC 授权器来授权。   
这里我们着重介绍一下 **RBAC**   

![rbac](https://pics.lxkaka.wang/rbac.png)  

**RBAC**(Role-Based Access Control)，它使用 "rbac.authorization.k8s.io" 实现授权决策，允许管理员通过 Kubernetes API 动态配置策略。在 RBAC API 中，一个角色(Role)包含了一组权限规则。
**Role** 有两种：**Role** 和 **ClusterRole**。一个Role对象只能用于授予对某一单一命名空间（namespace）中资源的访问权限。ClusterRole对象可以授予与Role对象相同的权限，但由于它们属于集群范围对象。 
**RoleBinding**: 角色绑定则是定义了将一个角色的各种权限授予一个或者一组用户。 角色绑定包含了一组相关主体（即 subject, 包括用户——User、用户组——Group、或者服务账户——Service Account）以及对被授予角色的引用。 在命名空间中可以通过 **RoleBinding** 对象进行用户授权，而集群范围的用户授权则可以通过 **ClusterRoleBinding**对象完成。

在上面的基础上我们来创建具有特定权限的用户  
我们创建一个用户 **release** 从名字可以看出他是干什么的，我们赋予这个用户可以在集群中发布服务的权限。  

### 创建具有对应权限的用户  
* 创建 cluster role
示例如下  
```yaml
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRole
    metadata:
    name: cluster-release
    rules:
    - apiGroups: ["", "extensions", "apps", "batch"]
    resources: ["*"]
    verbs: ["update", "get", "watch", "list", "create", "patch"]
```
* 绑定用户，创建 ClusterRoleBinding
```yaml
    apiVersion: rbac.authorization.k8s.io/v1beta1
    kind: ClusterRoleBinding
    metadata:
    name: cluster-release
    roleRef:
    apiGroup: rbac.authorization.k8s.io
    kind: ClusterRole
    name: cluster-release
    subjects:
    - apiGroup: rbac.authorization.k8s.io
    kind: User
    name: release
```

### 创建 kubeconfig  
**kubeconfig** 其实就是集群的身份认证和鉴权的配置文件，它包含了集群信息，客户信息，上下文(context)等。并且根据不同的 context 可以实现多集群的访问。
这里我们用  tls client certificate 来作为身份验证的安全凭证，之前也说过也可以用 token 的方式。 

#### 1. 创建用户安全凭证(CA 证书)
* 给用户创建 private key(比如给用户release)
`openssl genrsa -out release.key 2048`
说明  

```
在申请数字证书之前，您必须先生成证书私钥和证书请求文件(CSR,Cerificate Signing Request),CSR是您的公钥证书原始文件，包含了您的服务器信息和您的单位信息，需要提交给CA认证中心。在生成CSR文件时会同时生成私钥文件，请妥善保管和备份您的私钥。

生成CSR文件时，一般需要输入以下信息(中文需要UTF8编码)：

Organization Name(O)：申请单位名称法定名称，可以是中文或英文
Organization Unit(OU)：申请单位的所在部门，可以是中文或英文
Country Code(C)：申请单位所属国家，只能是两个字母的国家码，如中国只能是：CN
State or Province(S)：申请单位所在省名或州名，可以是中文或英文
Locality(L)：申请单位所在城市名，可以是中文或英文
Common Name(CN)：申请SSL证书的具体网站域名
```

* 创建证书签名请求(csr) CN(这里是用户名) O(这里是组)要显示指明
`openssl req -new -key release.key -out release.csr -subj "/CN=release/O=k8s"`
* 给用户release签发证书
`openssl x509 -req -in release.csr -CA /etc/kubernetes/ssl/ca.pem -CAkey /etc/kubernetes/ssl/ca-key.pem -CAcreateserial -out release.crt -days 365`

   至此我们应该生成了证书 release.crt 和 release.key。    

#### 2. 生成 kubeconfig 文件   
* 先要指明 api-server 的地址      
 `export KUBE_APISERVER=https://172.31.xx.xx:6443`  
* 设置k8s 集群信息     
 `sudo kubectl config set-cluster cluster.local --certificate-authority=/etc/kubernetes/ssl/ca.pem --embed-certs=true --server=${KUBE_APISERVER} --kubeconfig=release.kubeconfig`
* 设置用户安全凭证     
 `sudo kubectl config set-credentials release --client-certificate=release.crt --client-key=release.key --embed-certs=true --kubeconfig=release.kubeconfig`
* 设置 context  参数
 `sudo kubectl config set-context release-context --cluster=cluster.local --user=release --kubeconfig=release.kubeconfig`
* 设置默认 context
 `sudo kubectl config use-context release-context --kubeconfig=release.kubeconfig`

  至此生成好了 kubeconfig 文件。    
`kubectl config view` 可以查看生成好的内容。   

### 使用 kubeconfig  
我们可以用生成好的 kubeconfig 文件来赋予 **kubectl** 操作集群的能力 
示例如下    
```dockerfile
FROM ubuntu:16.04

COPY kubectl /usr/local/bin/
RUN chmod +x /usr/local/bin/kubectl
RUN mkdir /root/.kube
COPY config /root/.kube/
```
下面这张图总结了我们的工作  
![kubectl-auth](https://pics.lxkaka.wang/kubectl-auth.png)  

