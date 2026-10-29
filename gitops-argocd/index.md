# Kustomize + Argo CD 优化发布流程


GitOps 相信不少人听说过，这种新的交付模式越来越受到大家的关注，包括我自己在内。今天在这篇文章里我结合我们的实际生产上遇到的痛点，讲讲我们在 GitOps 上的实践，希望能给大家带来一些参考作用。
首先关于 GitOps 的介绍资源还是非常多的，在这里我引用一下大佬们总结的 GitOps 概念。

## GitOps 概念
GitOps 的概念最初来源于 Weaveworks 的联合创始人 Alexis 在 2017 年 8 月发表的一篇博客 GitOps - Operations by Pull Request。文章介绍了 Weaveworks 的工程师如何以 Git 作为事实的唯一真实来源，部署、管理和监控基于 Kubernetes 的 SaaS 应用。
> GitOps 是一种持续交付的方式。它的核心思想是将应用系统的声明性基础架构和应用程序存放在 Git 版本库中。将 Git 作为交付流水线的核心，每个开发人员都可以提交拉取请求（Pull Request）并使用Gi​​t来加速和简化 Kubernetes的应用程序部署和运维任务。通过使用像Git这样的简单工具，开发人员可以更高效地将注意力集中在创建新功能而不是运维相关任务上（例如，应用系统安装、配置、迁移等）。

### GitOps 基本原则
* 以 Git 作为事实的唯一真实来源
  描述系统相关的所有内容：策略，代码，配置和版本控制等，并且将这些内容全部存储在 Git 仓库中，在通过版本库中的内容构建系统的基础架构或者应用程序的时候，如果没有成功，则可以迅速的回滚，并且重新来过。

* 用 pull 的模式构建 Pipeline
  不断地检查 Git 仓库，将任何状态变化都反映到 Kubernetes 集群中，具体说来就是 GitOps 检测到集群状态和 Git 仓库不一致，会从配置仓库中拉取更新后的清单，并将包含新功能的镜像部署到集群里。

关于 GitOps 就简要介绍一下，更多的信息大家可以去关注一下。

## 工具链
因为我们讲的是 GitOps 的实践，所以依赖的工具或者说组件必须先介绍一下

* Git 仓库 
  我们使用 GitLab 来管理和存储我们的代码和各种配置

* Kubernetes 集群
  用于部署我们应用程序的底层集群

* Kustomize
  kubernetes 配置管理

* ArgoCD
  ArgoCD 是一个声明式、GitOps 持续交付的 Kubernetes 工具，它的配置和使用分非常简单，并且自带一个简单易用的 Dashboard，更重要的是 ArgoCD 支持 kustomzie、helm、ksonnet 等多种工具

## 流程
下图展示了我们实践的 GitOps 工作流程     
![gitops](https://pics.lxkaka.wang/gitops.png)

1. 提交代码到对应的 feature branch
2. 代码和并到 dev branch or master branch
3. 触发 GitLab CI
4. 在 CI 中更新应用配置文件
5. 提交新的配置到 GitLab 仓库
6. ArgoCD 监控到 GitLab 仓库变化，触发同步，拉取镜像发布新的应用版本

### 安装 ArgoCD
ArgoCD 的安装比较简单，我们可以选择用 helm 安装，或者直接 Kubectl apply 配置文件。   
```
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```
这里强调一下 `ingress` 的配置, 转发到 443 端口（80 会被 redirect 到443，造成浏览器多次 redirect）
```
apiVersion: extensions/v1beta1
kind: Ingress
metadata:
  name: argocd-server-http-ingress
  namespace: argocd
  annotations:
    kubernetes.io/ingress.class: "nginx"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"
spec:
  rules:
  - http:
      paths:
      - backend:
          serviceName: argocd-server
          servicePort: https
    host: argocd.example.com
  tls:
  - hosts:
    - argocd.example.com
    secretName: argocd-secret # do not change, this is provided by Argo CD
```
安装完成后，就可以浏览器访问 ArgoCD dashbaord。默认的用户名为 admin，密码为 server Pod 的名称

### 创建应用

### 使用 Kustomize 管理配置  
相信大家在使用 Kubernetes 的时候光为了部署应用就要写一大堆的配置文件，尤其是有多个环境，每个环境都要维护这么一套相似度极高的配置文件，既繁琐又容易出错。所以，Kubernetes 社区就开发了 Kustomize 来帮助我们简化和管理这样的配置。  
Kustomize 的能力   
* kustomize 通过 Base & Overlays 维护不同环境的应用配置
* kustomize 使用 patch 方式复用 Base 配置，并在 Overlay 描述与 Base 应用配置的差异部分来实现资源复用
* kustomize 管理的都是 Kubernetes 原生 YAML 文件，学习成本低  

下面是我们的实践  
以一个应用为例首先我们有这样一份 base 位于 Git 仓库 `deploy/k8s/base` 文件夹下  
```
-rw-r--r--  1 lxkaka  staff  2150  7 16 18:39 deployment.yml
-rw-r--r--  1 lxkaka  staff   276  7 16 18:49 ingress.yml
-rw-r--r--  1 lxkaka  staff   131  7 16 17:30 kustomization.yml
```
其中 deployment 里我们其实可以写多个应用，因为 service.yml 不应修改我们这里也合并到了 deployment.ym 里。 
在 deploy/k8s/overlays 下分别包括了测试环境，生产环境的配置  
以测试环境 `kustomization.yml` 为例，这里我们有两个应用 web, scheuler 根据环境的不同把需要改动的部分声明成配置文件即可，而不需要再重复的写一遍配置。Ingress 的改动通过编写一个 patch 文件也可以实现。
```
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

bases:
- ../../base
patchesStrategicMerge:
- web.yml
- scheduler.yml
patches:
- path: ingress_patch.yml
  target:
    group: extensions
    version: v1beta1
    kind: Ingress
    name: airflow
    namespace: airflow
```
最后的目录结构是下面的这样
```
k8s
├── base
│   ├── deployment.yaml
│   ├── kustomization.yaml
│   └── ingress.yaml
└── overlays
    ├── prod
    │   ├── web.yaml
    │   ├── scheuler.yaml
    │   ├── ingess_patch.yaml
    │   └── kustomization.yaml
    └── test
        ├── web.yaml
        ├── scheuler.yaml
        ├── ingess_patch.yaml
        └── kustomization.yaml
```
### CI Pipeline
首先为了突出重点，我们这里简化一下 Pipeline, 只定义了两个 stage, 其中 build 和 deploy 都分别包含了测试和生产环境
```
stages:
  - build
  - deploy
```
* build stage 
这一步 build 新的 image 并推送到镜像仓库 
```
.build:
  image: ${IMAGE_REGISYRY}/inf/common/docker:compose
  stage: build
  script:
    - >
      echo "$PROJECT start build $ENV:$VERSION =============>";
      IMAGE_BASE=${BASE_DOCKER}/${PROJECT}/${ENV}/code;
      IMAGE_URL=${BASE_DOCKER}/${PROJECT}/${ENV}/code:${VERSION};

      docker build --pull -t ${IMAGE_URL} --build-arg ENV=${ENV} -f deploy/docker/code.Dockerfile .;
      docker push ${IMAGE_URL};

      echo "build process done =========="
```
* deploy stage   
这里我们重点介绍一下这个 stage, 根据不同的环境，我们会更新应用的 image tag, 并把 image 最新的配置更新到`kustomization.yml`，然后推送到 Git 仓库。

```
.deploy:
  stage: deploy
  image: ${IMAGE_REGISYRY}/inf/common/:kustomize:v1.1
  before_script:
    - mkdir ~/.ssh
    - chmod 700 ~/.ssh
    - echo "${DEPLOY_KEY}" > ~/.ssh/id_rsa
    - chmod 600 ~/.ssh/id_rsa
    - echo -e "Host *\n\tStrictHostKeyChecking no\n\n" > ~/.ssh/config
    - git remote set-url origin ${REPOSITORY}
    - git config user.email ${GITLAB_USER_EMAIL}
    - git config user.name ${GITLAB_USER_NAME}
  script:
    - cd deploy/k8s/overlays/${ENV}
    - kustomize edit set image ${BASE_DOCKER}/${PROJECT}/${ENV}/code:${VERSION}
    - git add .
    - git commit -m '[skip ci]update image tag'
    - git push origin HEAD:${CI_COMMIT_REF_NAME} -f
```

### ArgoCD 创建应用  
在 ArgoCD 创建应用，其实就是告诉 ArgoCD 我们要发布什么应用，这个应用的配置去哪读取。既可以通过 Argo CRD 定义 编写 yaml 也可以通过 Web UI 创建应用  
示例如下  
```
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: app-test
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'git@example.com:sync.git'
    path: deploy/k8s/overlays/test
    targetRevision: dev
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: airflow
  syncPolicy:
    automated: {}
```
上面定义的 Application 这个资源，就是 Argo CD 用于描述应用的 CRD 对象：

name：Argo CD 应用程序的名称
project：应用程序将被配置的项目名称，这是在 Argo CD 中应用程序的一种组织方式
repoURL：源代码的仓库地址
targetRevision：想要使用的 git 分支
path：Kubernetes 配置文件在仓库中的路径
destination：Kubernetes 集群中的目标

### 流程 demo
在这里我们展示一下一个完整的 GitOps 流程   
1. 修改代码，push 到 feature 分支，并把分支合并到 dev 触发 Pipeline    
![pipeline](https://pics.lxkaka.wang/pipeline.png)

2. 在 ArgoCD 中查看应用同步状态       
Pipeline 成功执行后，我们可以看到应用马上开始同步，图中我们可以看到新版本的 pod 已经 running, 老的 pod 正在被删除。我们这里 image tag 使用的是 Pipeline id，可以看到同步后的 image tag 是 *177839* 和 Pipeline id 一致，证明同步的就是这个版本。
![argocd](https://pics.lxkaka.wang/argocd.png)  
![image](https://pics.lxkaka.wang/image.png)

我们的 GitOps 的实践就介绍到这里。希望大家试用，一定能体会到 GitOps 带来的
* 开发效率的提升
* 安全性的提升
* 可靠性的提升

#### 附件
在这里贴一下 `kustomize` 的 `dockerfile` 供大家参考
```
FROM alpine:latest
ENV KUSTOMIZE_VERSION v3.8.0

RUN sed -i "s/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g" /etc/apk/repositories && apk add git curl bash openssh
RUN  curl -L --output /tmp/kustomize_v3.8.0_linux_amd64.tar.gz https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv3.8.0/kustomize_v3.8.0_linux_amd64.tar.gz \
  && echo "89cbe307506b25aca031ff6dfc9b4da022284ede65452a49e4e5988346f6354e  /tmp/kustomize_v3.8.0_linux_amd64.tar.gz" | sha256sum -c \
  && tar xzf /tmp/kustomize_v3.8.0_linux_amd64.tar.gz -C /usr/local/bin \
  && chmod +x /usr/local/bin/kustomize
```

