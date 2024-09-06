# 生产环境搭建 kubernetes(11.3)


直接进入正题，这篇文章讲述生产环境如何搭建 kubernets cluster。
我们使用 kubespray 使用搭建 k8s cluster。 至于其他搭建工具 kops, kubeadm 感兴趣的大家可以自己研究一下，各有优势。
## 环境:
* aws(cn-north-1)
* ubuntu 16.04
* kubernetes v1.11.3
* kubespray v2.7.0

## 搭建 ->
### 环境准备
* 准备实例 
我们先准备5个实例，其中3个作为 master, 2个作为 node  
* 分发公钥
选定其中一个作为我们的操作实例，因为后续操作都是通过 ssh 与各个节点交互, 先在操作节点上 `ssh-keygen` 生成公私钥并且把公钥`id_rsa.pub`分发到其他的节点上
* kubespray环境
  * 下载 kubespray  
     ` wget https://github.com/kubernetes-incubator/kubespray/releases/tag/v2.7.0`  
  * 解压并且按照依赖  
    `tar xzvf v2.7.0.tar.gz && cd kubespray-2.7.0 pip install -r requirements.txt`
   * 生成清单    
     * 清单目录      
     `cp -r inventory/sample inventory/my_cluster`  
     * 声明实例地址   
      `declare -a IPS=(172.31.xx.1 172.31.xx.2 172.31.xx.3 172.31.xx.4 172.31.xx.5)`  
     * 生成目标机器的地址配置     
       `CONFIG_FILE=inventory/my_cluster/hosts.ini python3 contrib/inventory_builder/inventory.py ${IPS[@]}`  

### 镜像地址修改  
直接安装是无法成功的，因为我们在 cn 很多k8s需要的镜像无法直接 pull 下来。这一步我们就必须把镜像地址改成我们能拉倒的地址  
主要是两类镜像 `gco.io` 和 `quay.io`，这两类镜像地址必须修改。   
```
find . -name '*.yml' | xargs -n1 -I{} sed -i 's/quay\.io/quay\.mirrors\.ustc\.edu\.cn/' {}`
find . -name '*.yml' | xargs -n1 -I{} sed -i 's/gcr\.io\/google-containers\//anjia0532\/google-containers\./' {}`
find . -name '*.yml' | xargs -n1 -I{} sed -i 's/gcr\.io\/google_containers\//anjia0532\/google-containers\./' {}`
```
### 修改 docker 本身的仓库    
修改roles/docker/defaults/main.yml文件  
```
docker_ubuntu_repo_base_url: "http://mirrors.aliyun.com/docker-ce/linux/ubuntu"
docker_ubuntu_repo_gpgkey: "http://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg"
dockerproject_apt_repo_base_url: "https://mirrors.tuna.tsinghua.edu.cn/docker/apt/repo"
dockerproject_apt_repo_gpgkey: "https://mirrors.tuna.tsinghua.edu.cn/docker/apt/gpg"
```
### 安装启动    
在 kubesray 目录下  
`ansible-playbook -i inventory/zaihui_cluster/hosts.ini cluster.yml -b -v`    
由此安装开始...    
如果此过程没有任何报错，最后能看到所有节点的状态是**success**。 那么应该就安装成功了！   
但是这个过程很可能还是会失败，最大的可能性就是上面我们修改的镜像地址有的可能还是拉不到镜像, 这个时候就要根据具体的镜像做修改。    
比如 `quay.mirrors.ustc.edu.cn/calico/cni:v3.1.3` 拉取失败，我们可以去 docker hub 上看是否有相应版本的镜像。修改成 `calico/cni:v3.1.3`。  

### kubernetes dashboard  
kubespray 安装的时候默认已经安装了 k8s dashboard。我们可以创建 service account 并赋予相应的权限来使用 token 访问dashboard。     
比如我们给默认 namespace default 下的 serviceaccount **default** 分配权限。  
* RABC 配置文件 
```
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  namespace: default
  name: default
rules:
- apiGroups: ["", "extensions", "apps", "batch"]
  resources: ["*"]
  verbs: ["update", "get", "watch", "list", "create", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: default-role-binding
  namespace: default
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: default
subjects:
- kind: ServiceAccount
  name: default
  namespace: default 
```
* 获取token   
`kubectl -n default describe secret $(kubectl -n default get secret | grep default | awk '{print $1}')` 

* 使用 nginx 反向代理 api-server
示例配置  
```
 server {
    server_name

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Server $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_pass https://172.31.xx.xxx:6443;
        client_max_body_size 200m;
    }
}
```

