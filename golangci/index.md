# golangci-lint 提效代码 review


在 Golang 项目中为了写出健壮和优雅的代码我们会采用 linter 帮助我们检查有问题或者不规范的代码。Golang 的 linter 非常多，各自检查的范围或者内容不尽相同，如果一个个 linter 去配置和使用非常的低效和麻烦。所以我们一般会使用 golangci-lint 高效的进行代码检查。
[golangci-lint](https://golangci-lint.run/) 是 linter 的集合器，本身集成了众多的 golang linter(48种)；并行执行检查，速度很快。
项目一般都是多人共同开发，大家应该遵守相同的代码规范,所以 golangci-lint 的检查应该要放到 CI 流程中。随之而来的一个问题是如果检查出了 bad case 不强制修改也是没有意义的。如果我们能把 bad case 通过 `comment`的形式展现出来不仅能提到强提醒的作用，而且如果不 resolve comment 无法合并代码。这样的方式我认为能帮助团队形成良好的编码和习惯和风格。在这里我就介绍一下我们如何用 **golangci-lint** + **reviewdog** 高效的进行代码检查。

在介绍具体的操作步骤之前有必要简要介绍一下一个重要的工具 `reviewdog`
### reviewdog
[reviewdog](https://github.com/reviewdog/reviewdog) 能够自动化的检测 PR（Pull Requests）里面的一些语法和格式的错误，同时提交评论，目前支持各个平台 GitHub、GitLab。总的来说 reviewdog 的工作原理是通过解析 Lint 的输出结果得 然后与代码提交的 Diff 进行比较，从中找出此次变更的问题。与直接通过静态代码扫描进行拦截相比，reviewdog 通过交互式的代码评审方式，能够减小错误检测（false positive）带来的影响。

实践步骤如下    
### Image 构建
我们先构建 CI 中需要使用的 image， image 里有 golangci-lint 和 reviewdog  
```dockerfile
FROM golangci/golangci-lint:latest-alpine

RUN go get -u github.com/reviewdog/reviewdog/cmd/reviewdog
```
如果项目里使用了 `cgo`, golangci-lint 镜像就不能使用 alpine 版本，因缺乏相关的依赖库。

### gitlab CI 配置文件
在 CI 中添加 `lint` stage，这一步即实现代码检查和自动 comment.
```yml
stages:
    - lint

before_script:
  - echo "before_script"
  - go env -w GO111MODULE=on
  - go env -w GOPROXY="http://goproxy.example.co"

golangci-lint:
    tags:
        - cv-service
    image: hub.exapmle.co/compile/bdjs/reviewdog
    stage: lint
    script:
      - git fetch
      - export GITLAB_API="https://git.example.co/api/v4"
      - export REVIEWDOG_INSECURE_SKIP_VERIFY=true
      - reviewdog -reporter=gitlab-mr-discussion
#      - golangci-lint run | reviewdog -f=golangci-lint -reporter=gitlab-mr-discussion
    only:
      - merge_requests
    allow_failure: true
```
### 配置 access token
reviewdog 实现自动 comment 需要配置环境变量 `REVIEWDOG_GITLAB_API_TOKEN`  
* 创建 access token
![access-token](https://pics.lxkaka.wang/access-token.png)

* 配置 CI 环境变量(项目级)
![ci-variable](https://pics.lxkaka.wang/ci-variable.png)

### lint 配置
我们之前说过 golangci-lint 支持多种 linter, 可以通过配置文件灵活配置各种检查规则。
示例配置文件 `.golangci.yml`   
```yml
linters:
  disable-all: true  
  enable:            
    - deadcode      
    - errcheck     
    - gosimple      
    - govet         
    - ineffassign   
    - staticcheck   
    - structcheck   
    - typecheck     
    - unused        
    - varcheck      
    - bodyclose
    - misspell
    - structcheck
    - typecheck
    - varcheck
    - gofmt
    - goimports
    - unconvert
    - exportloopref

linters-settings:
  govet:            
    check-shadowing: true
    check-unreachable: true
    check-rangeloops: true
    check-copylocks: true

```

### reviewdog 配置
reviewdog 命令和 comment 格式配置 
```yml
runner:
  golint:
    cmd: golangci-lint run
    errorformat:
      - "%f:%l:%c: %m"
    level: warning
```
经过上述的工作，如果提交 MR 即能触发 lint 和 自动 comment，一切正常的话你会看到下面的效果   
![reviewdog](https://pics.lxkaka.wang/reviewdog.png)

### 可能遇到的问题  
如果遇到以下问题  
* `could not import C (cgo preprocessing failed)]]`
golangci-lint:alpine 镜像缺乏依赖库, 请使用 golangci-lint:latest 或特定版本

* `reviewdog: failed to get merge-base commit: exit status 128`
需要先 git fetch 获得远端分支的更新
