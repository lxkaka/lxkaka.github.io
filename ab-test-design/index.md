# AB Test 框架方案设计

>作者注：文章的结构是我让 LLM 参考我的设计简稿生成的

## 引言

AB Test 是现代软件开发和产品管理中的一项关键技术。它允许团队通过比较网页或应用功能的两个或多个版本，来确定哪个表现更好，从而做出数据驱动的决策。在这篇文章中，介绍一下我们如何快速设计一个低成本和扩展性高的 AB Test 基础设施。

## 框架概述

我们的AB测试框架设计注重简洁性和可扩展性。它由四个主要组件组成：

1. 创建实验规则
2. 基于规则的流量路由
3. 用户分段和请求头注入
4. 用于流量分发的API网关

让我们详细探讨每个组件。

## 1. 创建实验规则

我们AB测试框架的基础在于创建清晰灵活的实验规则。这些规则定义了每个测试的参数，包括：

- Project（项目名称，即实验标识符）
- Router（路由器，即分段或分桶名称）
- Weight（权重，即流量分配）
- Service（目标服务名称）
- URI（目标端点）
- Rewrite URI（可选的修改后端点）

为了创建这些规则，我们实现了一个简单的API端点，接受JSON格式的数据。以下是创建规则的示例：

```bash
curl --location '127.0.0.1:8081/internal/ab/config' \
--header 'Content-Type: application/json' \
--data '{
  "project": "exp_discover_for_you_tab",
  "router": "ad_line",
  "weight": 50,
  "uri": "/recmd/homepage",
  "rewrite_uri": "/deal/homepage_recommendation_v2",
  "service": "kaka-recmd-service.kaka.svc.clusterset.local"
}'
```

这种灵活性使产品经理和开发人员能够轻松设置和修改实验，而无需更改底层代码。

## 2. 基于规则的流量路由

一旦规则设置完成，我们的框架就会创建流量路由配置。这些配置决定了如何在不同版本或正在测试的功能之间分配用户流量。

路由机制考虑以下因素：
- 用户参与的实验（project）
- 用户所属的分段（router）
- 分配给每个变体的权重（weight）

这确保了流量按照预定义的比例进行分割，从而可以准确比较不同版本之间的表现。

## 3. 用户分段和请求头注入

AB测试的一个关键方面是一致的用户分段。我们的框架通过以下方式处理这一问题：

1. 识别用户（通过cookies、用户ID或其他方式）
2. 确定用户有资格参与哪些实验
3. 为每个相关实验将用户分配到特定的分段
4. 将这些信息注入到请求头中

具体而言，我们向每个Web请求添加一个自定义头部 `Kaka-Ex`，其中包含该用户的路由信息。这个头部可能看起来像这样：

```
kaka-Ex: exp_discover_for_you_tab=ad_line
```

这种方法确保用户在多次访问中始终看到相同的变体，这对于测试结果的有效性至关重要。

## 4. 用于流量分发的API网关

我们AB测试框架的最后一个部分是API网关，它充当流量警察的角色，根据实验规则和用户分段将请求定向到适当的服务或端点。

API网关的工作流程：
1. 读取来自传入请求的 `Kaka-Ex` 头部
2. 将头部信息与路由规则匹配
3. 将请求转发到适当的服务和URI
4. 如果规则中指定了，则可选地重写URI

这种设置允许在测试中具有极大的灵活性，因为您可以将流量路由到完全不同的服务，或同一服务中的不同端点，而无需更改前端代码。


![abtest-architech](https://pics.lxkaka.wang/20240906-184947.png)

## 实现细节

### 用于获取头部的中间件

为了简化获取分段信息的过程，我们计划实现一个中间件，自动检索和处理 `kaka-Ex` 头部。这将使开发人员更容易在其应用程序代码中访问AB测试信息。

### 日志记录

我们的框架会自动记录每个请求的AB测试信息。这包括：
- 用户参与的实验
- 分配给他们的分段
- 他们看到的变体

这些数据对于分析AB测试结果和基于用户行为做出明智决策至关重要。

## 结论

这个AB测试框架为在应用程序中实现分割测试提供了一个强大、灵活且可扩展的解决方案。通过分离实验定义、用户分段和流量路由的关注点，我们创建了一个可以适应各种测试场景的系统。

该框架的主要优势包括：
- 通过简单的API轻松设置实验
- 跨会话的一致用户体验
- 灵活的流量路由，包括服务级别的分割

在实施这个框架时，请记住AB测试的真正价值不仅在于技术实现，还在于提出正确的问题、形成清晰的假设，以及仔细分析结果以推动产品的有意义改进。

## 下一步

虽然这个框架为AB测试提供了坚实的基础，但总有改进的空间。未来可能的增强领域包括：
- 自动日志记录，便于分析
- 用于创建和管理实验的用户界面
- 实时监控和可视化测试结果



## API Gateway
这里我使用的 [APISIX](https://apisix.apache.org/)
#### 部署方式 

```shell
helm repo add apisix https://charts.apiseven.com
helm repo update
helm install apisix apisix/apisix -n apisix --create-namespace -f values.yaml
```
推荐必须修改的配置如下 
```yaml
# replicaCount: 1
# production 环境
replicaCount: 2


# 自定义 storage class 名称
etcd:
  persistence:
    storageClass: standard-rwo
    size: 25Gi

apisix:
# 自定义 admin API key  
  admin:
    credentials:
      admin: xxxx
      viewer: view

# 自定义 dashboard 账号密码
dashboard:
  enabled: true
  config:
    authentication:
      users:
      - username: xxx
        password: xxx
  
  image:
    tag: 3.0.1-alpine


global:
  storageClass: standard-rwo
```
