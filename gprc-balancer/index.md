# gRPC 一致性 Hash balancer 实现

在开发过程中我们遇到了需要 session 保持的场景，即同一个用户的请求需要我们路由到后端服务的同一个实例。如果是 http 请求我们可用利用 nginx 的 ip hash 负载均衡策略来实现此目的；如果服务之间的调用我们用的是 gprc， 该怎么实现呢？在这篇文章里我就介绍一下我们如何实现 grpc 中的 session 保持。
在介绍实现 自定义 gprc balancer 之前，我们必须了解一下 grpc 中服务发现和负载均衡的原理。

## grpc 负载均衡
下面这张图展示了在 grpc 中实现负载均衡的的两个核心模块 `resovler` 和 `balancer`。

![gprc-balancing](https://pics.lxkaka.wang/grpc-conn.png)
### Resolver
gprc client 通过 server name 和 grpc server 交互式，resolver 负责解析 server name, 通过 server name 从注册中心实时获取当前 server 的地址列表，同步发送给 Balancer

### Balancer
接收从 Resolver 发送的server 地址列表，建立并维护连接状态；每次当 Client 发起 RPC 调用时，按照一定算法从连接池中选择一个连接进行发起调用

## 核心模块原理
### Resolver 流程
代码 `resolver/resolver.go`重点定义如下  
```go
// scheme://authority/endpoint
type Target struct {
	Scheme    string
	Authority string
	Endpoint  string
}

// 向grpc注册服务发现实现时，实际上注册的是Builder
type Builder interface {
    // 创建Resolver，当resolver发现服务列表更新，需要通过ClientConn接口通知上层
	Build(target Target, cc ClientConn, opts BuildOption) (Resolver, error)
	Scheme() string
}

type Resolver interface {
    // 当有连接被出现异常时，会触发该方法，因为这时候可能是有服务实例挂了，需要立即实现一次服务发现
	ResolveNow(ResolveNowOption)
	Close()
}

//
type ClientConn interface {
	// 服务列表和服务配置更新回调接口
	UpdateState(State)
	// 服务列表更新通知接口
	NewAddress(addresses []Address)
 	// 服务配置更新通知接口
	NewServiceConfig(serviceConfig string)
}
```
其中 Builder 接口用来创建 Resolver，我们可以提供自己的服务发现实现，然后将其注册到 grpc 中，其中通过 scheme 来标识，而 Resolver 接口则是提供服务发现功能。当 resover 发现服务列表发生变更时，会通过 ClientConn 回调接口通知上层。
那么注册进来的 resolver 在哪里用到的呢？当创建客户端的时候调用 DialContext 方法创建 ClientConn 的时候回进行如下操作  
* 拦截器处理
* 各种配置项处理
* 解析 target
* 获取 resolver
* 创建 ccResolverWrapper
* 创建 clientConn 的时候回根据 target 解析出 scheme，然后根据 scheme 去找已注册对应的 resolver，如果没有找到则使用默认的 resolver。
相关代码可以在 `grpc/clientconn.go` 中看到。

### Balancer 流程
代码 `balancer/balancer.go` 重点定义如下 
```go
// 声明了balancer需要用到的回调接口
type ClientConn interface {
  	// 根据地址创建网络连接
	NewSubConn([]resolver.Address, NewSubConnOptions) (SubConn, error)
    // 移除无效网络连接
	RemoveSubConn(SubConn)
    // 更新Picker，Picker用于在执行rpc调用时执行负载均衡策略，选举一条连接发送请求
	UpdateBalancerState(s connectivity.State, p Picker)
    // 立即触发服务发现
	ResolveNow(resolver.ResolveNowOption)
	Target() string
}

// 根据当前的连接列表，执行负载均衡策略选举一条连接发送rpc请求
type Picker interface {
	Pick(ctx context.Context, opts PickOptions) (conn SubConn, done func(DoneInfo), err error)
}

// Builder用于创建Balancer，注册的时候也是注册builder
type Builder interface {
	Build(cc ClientConn, opts BuildOptions) Balancer
	Name() string
}

type Balancer interface {
    // 当有连接状态变更时，回调
	HandleSubConnStateChange(sc SubConn, state connectivity.State)
    // 当resolver发现新的服务地址列表时调用（有可能地址列表并没有真的更新）
	HandleResolvedAddrs([]resolver.Address, error)
	Close()
}
``` 
当 Resolver 发现新的服务列表时，最终会调用 Balancer 的 HandleResolvedAddrs 方法进行通知；Balancer 通过 ClientConn 的接口创建网络连接，然后根据当前的网络连接连接构造新的 Picker，然后回调 ClientConn.UpdateBalancerState 更新 Picker。当发送 grpc 请求时，会先执行 Picker 的接口，根据具体的负载均衡策略选举一条网络连接，然后发送rpc请求。

## 一致性 Hash balancer 实现

### 一致性 Hash 
在实现 balancer 之前，先简单介绍一下一致性 Hash
基本原理是 hash ring(hash 环)，即将节点 node 本身也 hash 到环上，通过数据和节点的 hash 相对位置来决定数据归属，因此当有新 node 加入时只有一部分的数据迁移。但事实上，这样的一致性hash导致数据分布不均匀，因为 node 在 hash ring 上的分布不均匀。分布不均匀的问题通过引入虚拟节点来解决，虚拟节点是均匀分布在环上的，数据做两次 match，最终到实际节点上。这样来保证数据分布的均匀性。

![consistent-hash](https://pics.lxkaka.wang/hash-ring.png)
我们这里用一致性 Hash 就是为了同一个用户的请求能路由到同一个 server 实例。

```go
type Ketama struct {
	sync.Mutex
	hash     HashFunc
	replicas int // 虚拟节点数
	keys     []int // 构造的 hash ring
	hashMap  map[int]string
}
```
#### 添加节点
在添加节点时，为每个节点创建 replica 个虚拟节点，并计算虚拟节点的 hash 值存入 hash ring，也就是 keys 这个 slice 中，同时把这些虚拟节点的 hash 值与 node 的对应关系保存在 hashMap。最后给 keys 排个序，就像在环上分布，顺时针递增一样。
```go
func (h *Ketama) Add(nodes ...string) {
	h.Lock()
	defer h.Unlock()

	for _, node := range nodes {
		for i := 0; i < h.replicas; i++ {
			key := int(h.hash([]byte(Salt + strconv.Itoa(i) + node)))

			if _, ok := h.hashMap[key]; !ok {
				h.keys = append(h.keys, key)
			}
			h.hashMap[key] = node
		}
	}
	sort.Ints(h.keys)
}
```
#### 查询节点
Get 方法是获取数据对应的节点，相当于负载均衡中源 ip 对应到哪个节点。计算数据的 hash，并在 hash Ring 上二分查找第一个大于 hash 的虚拟节点，也就通过hashMap 找到了对应的真实节点。
```go
func (h *Ketama) Get(key string) (string, bool) {
	if h.IsEmpty() {
		return "", false
	}

	hash := int(h.hash([]byte(key)))

	h.Lock()
	defer h.Unlock()

	idx := sort.Search(len(h.keys), func(i int) bool {
		return h.keys[i] >= hash
	})

	if idx == len(h.keys) {
		idx = 0
	}
	str, ok := h.hashMap[h.keys[idx]]
	return str, ok
}
```
### balancer 实现
在了解了 grpc 负载均衡的工作原理之后，实现自定义 balancer 需要完成的工作：
* 实现 PickerBuilder，Build 方法返回 balancer.Picker

* 实现 balancer.Picker，Pick 方法实现负载均衡算法逻辑

* 调用 balancer.Registet 注册自定义 Balancer
#### 实现 Build 方法 
```go
func (b *consistentHashPickerBuilder) Build(buildInfo base.PickerBuildInfo) balancer.V2Picker {
	grpclog.Infof("consistentHashPicker: newPicker called with buildInfo: %v", buildInfo)
	if len(buildInfo.ReadySCs) == 0 {
		return base.NewErrPickerV2(balancer.ErrNoSubConnAvailable)
	}

    // 构造 consistentHashPicker
	picker := &consistentHashPicker{
		subConns:          make(map[string]balancer.SubConn),
		hash:              NewKetama(3, nil), // 构造一致性hash 
		consistentHashKey: b.consistentHashKey, // 用于计算hash的key
	}

	for sc, conInfo := range buildInfo.ReadySCs {
		node := conInfo.Address.Addr
		picker.hash.Add(node)
		picker.subConns[node] = sc
	}
	return picker
}
```

#### 实现 Pick 方法
```go
func (p *consistentHashPicker) Pick(info balancer.PickInfo) (balancer.PickResult, error) {
	var ret balancer.PickResult
	key, ok := info.Ctx.Value(p.consistentHashKey).(string)
	if ok {
		targetAddr, ok := p.hash.Get(key) // 根据key的hash值挑选出对应的节点
		if ok {
			ret.SubConn = p.subConns[targetAddr]
		}
	}
	return ret, nil
}
```
## 一致性 Hash balancer 使用
```go
func NewClient(cfg *warden.ClientConfig) (rb.ResourceTaskClient, error) {
    // 初始化balancer
	balancer.InitConsistentHashBuilder("test")
	if cfg == nil {
		cfg = &warden.ClientConfig{}
	}
	client := warden.NewClient(cfg)
	client.UseOpt(grpc.WithBalancerName(balancer.Name))
	cc, err := client.Dial(context.Background(), fmt.Sprintf("discovery://default/%s", AppID))
	if err!=nil{
		panic(err)
	}
	return rb.NewResourceTaskClient(cc), err
}

func (s *Service) GrpcTest(ctx context.Context) (reply *rb.GetTaskResReply, err error){
    // 在context中塞入hash key
	ctx = context.WithValue(ctx, "test", strconv.Itoa(rand.Intn(1000)))
	reply, err = s.gClient.GetTaskRes(ctx, &rb.GetTaskResReq{TaskId: "ct340984037629763021"})
	return
}
```
我们把选中的节点信息打印出来展示如下, 不同的 key 选取了不同的节点，如果同一个 key 那么请求还是路由到同一个节点。由此实现我们的 session 保持的目的。
```shell
INFO 02/20-14:46:32.958 /Users/lxkaka/bili/cv-service/interface/balancer/conhash.go:61 hash map: map[543647748:10.217.28.143:9000 946644225:10.217.27.218:9000 2448604328:10.217.27.218:9000 2521173259:10.217.27.218:9000 3082607229:10.217.28.143:9000 3098647747:10.217.28.143:9000]
INFO 02/20-14:46:32.958 /Users/lxkaka/bili/cv-service/interface/balancer/conhash.go:62 hash key:71
INFO 02/20-14:46:32.958 /Users/lxkaka/bili/cv-service/interface/balancer/conhash.go:66 ip addr:10.217.28.143:9000

INFO 02/20-14:48:05.270 /Users/lxkaka/bili/cv-service/interface/balancer/conhash.go:61 hash map: map[543647748:10.217.28.143:9000 946644225:10.217.27.218:9000 2448604328:10.217.27.218:9000 2521173259:10.217.27.218:9000 3082607229:10.217.28.143:9000 3098647747:10.217.28.143:9000]
INFO 02/20-14:48:05.270 /Users/lxkaka/bili/cv-service/interface/balancer/conhash.go:62 hash key:705
INFO 02/20-14:48:05.270 /Users/lxkaka/bili/cv-service/interface/balancer/conhash.go:66 ip addr:10.217.27.218:9000
```

