# 利用 Casbin 高效实现基于 RBAC 的权限系统

在大部分的业务系统中权限控制是少不了的模块，它对这个系统的数据安全起着关键作用。既然权限系统或者模块这么重要且又很普适，当我们搭建一个权限系统是就没必要从头开始写起重复造轮子。在这篇文章里我们介绍一下如果利用开源的框架快速搭建一个权限系统，希望起到抛砖引玉的作用。
在此之前我们得了解目前常用的权限模型。

### 权限模型
#### ACL(Access Control List)
权限直接赋予用户, 即每一个用户和某一项特定的权限绑定，如果是 n 个用户和 m 项权限，我们就需要创建 n*m 条权限记录。这种模式的缺点在于，但用户量达到一定量级的时候，那么就需要对每个用户都进行一次授权操作，那么这个工作量就会相当大。总体来说 ACL 对稍微复杂一点的场景就不太友好。

#### RBAC(Role-Based Access Control)
相比于 ACL 模型，RBAC 模型在用户与权限之间多了一个元素**角色**，通过权限关联角色、角色关联用户的方法来间接地赋予用户权限，从而实现用户与权限的解耦。RBAC 是目前权限系统中最为常用的模型。根据场景和需求复杂度不同，RBAC 又有几种变体。
基本的RBAC模型中定义了三个对象和两个关系，三个对象分别是：user，role，permission。一个用户可以属于多个角色，而一个角色下面也可以有多个用户。同样，角色和权限之间也是这种多对多的关系。关系如下图。

![rbac](https://pics.lxkaka.wang/rbac_model.png) 

* User（用户）：每个用户都有唯一的UID识别，并被授予不同的角色
* Role（角色）：不同角色具有不同的权限
* Permission（权限）：访问权限
* 用户-角色映射：用户和角色之间的映射关系
* 角色-权限映射：角色和权限之间的映射   

RBAC 的进阶变体这里就不做详细介绍, 我们简要介绍一下区别
* RBAC1：在角色中引入了继承的概念。简单理解就是，给角色可以分成几个等级，每个等级权限不同，从而实现更细粒度的权限管理。  
* RBAC2：建立在RBAC0基础之上，仅是对用户、角色和权限三者之间增加了一些限制。这些限制可以分成两类，即静态职责分离SSD(Static Separation of Duty)和动态职责分离DSD(Dynamic Separation of Duty)    
* RBAC3：RBAC1和RBAC2的合集，所以RBAC3既有角色分层，也包括可以增加各种限制     

总之根据 RBAC 模型去做设计基本上能满足我们对权限系统的要求。    

### Casbin
[Casbin](https://casbin.org/docs/zh-CN/overview) 是一个强大的、高效的开源访问控制框架，其权限管理机制支持多种访问控制模型。这里的访问控制模型就包括 **RBAC**。  
casbin的核心是一套基于PERM metamodel(Policy,Effect,Request,Matchers)的 DSL。Casbin 从用这种 DSL 定义的配置文件中读取访问控制模型，作为后续权限验证的基础。更多原理方面的文档大家可以参看上述的文档链接。

### 实现
#### 功能
我们的权限控制目标是可以在中间件中，统一对用户进行鉴权，如果没有权限，中止继续访问，返回无权限的状态码，而如果有权限，则放行。

#### 模型
定义 RBAC 模型
```
# Request definition 即为请求定义，代表了可以传入什么样的参数来确定权限
[request_definition]
r = sub, obj, act

# Policy definition 代表了规则的组成
[policy_definition]
p = sub, obj, act

# g 是一个 RBAC系统, _, _表示角色继承关系的前项和后项，即前项继承后项角色的权限
[role_definition]
g = _, _

# Policy effect 则表示什么样的规则可以被允许, e = some(where (p.eft == allow)) 这句就表示当前请求中包含的任何一个规则被允许的话，这个权限就会被允许
[policy_effect]
e = some(where (p.eft == allow))

# 是策略匹配程序的定义。表示请求与规则是如何起作用的
[matchers]
m = g(r.sub, p.sub) && r.obj == p.obj && r.act == p.act
```

#### 初始化 Casbin
```golang
import (
	"strconv"

	"github.com/casbin/casbin/v2"
	"github.com/casbin/casbin/v2/model"
	gormadapter "github.com/casbin/gorm-adapter/v3"
	"gorm.io/gorm"
)

type Permit struct {
	*casbin.Enforcer
}

func NewPermit(db *gorm.DB) *Permit {
    // 使用 mysql 作为 policy 的存储；使用 gormadapter 作为 policy 的管理 api
    adapter, _ := gormadapter.NewAdapterByDB(db)
    // 加载 model 配置
	m, _ := model.NewModelFromString(CasbinConf)
	enforcer, _ := casbin.NewEnforcer(m, adapter)
	enforcer.EnableAutoSave(true)
	enforcer.EnableAutoNotifyWatcher(true)
	return &Permit{
		Enforcer: enforcer,
	}
}
```

#### 中间件
```golang
func (p *Permit) Permit(action string) bm.HandlerFunc {
	return func(ctx *bm.Context) {
		var (
			mid      int64
			err      error
			obj      string
			midStr   string
			isPermit bool
		)
		midI, ok := ctx.Get("mid")
		if !ok {
			ctx.JSON(nil, ecode.NoLogin)
			ctx.Abort()
			return
        }
        // 用户
        mid = midI.(int64)
        // 资源
		obj = ctx.Request.Header.Get("OBJ-ID")
		if obj == "" {
			ctx.JSON(nil, ecode.AppDenied)
			ctx.Abort()
			return
		}
        midStr = strconv.FormatInt(mid, 10)
        // 检查用户权限
		isPermit, err = p.Enforce(midStr, obj, action)
		if err != nil {
			ctx.JSON(nil, err)
			ctx.Abort()
			return
		}
		if !isPermit {
			ctx.JSON(nil, ecode.AccessDenied)
			ctx.Abort()
			return
		}
	}
}
```

#### 常用操作
```golang
// 添加角色
_, err = s.permit.AddPolicy(roleName, roleId, action)
// 赋予用户角色
_, err := s.permit.AddRoleForUser(user, roleName)
// 查看具有某角色的所有用户
res, err := s.permit.GetUsersForRole(roleName)
// 移除用户具有的角色
_, err := s.permit.DeleteRoleForUser(user, roleName)
// 移除角色，跟角色相关联的用户都被移除
_, err = s.permit.DeleteRole(roleName)
```
下图是接口权限访问控制的示例，可以看到在请求头带上了资源我们就实现了资源权限访问控制

![rbac_res](https://pics.lxkaka.wang/rbac_res.png)

以上就是我们利用 Casbin 实现了基于 RBAC 的权限控制，可以看到成本非常低。在一个规模不是很大的系统中去做权限设计我相信这是一个高效的选择。
