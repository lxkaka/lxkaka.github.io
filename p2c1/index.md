# 算法服务稳定性优化之负载控制

在我们的算法服务中，我们通过 gRPC server 对外提供服务。这里算法和一般的服务有一个很大的区别, 算法服务依赖于 GPU, 往往一次请求就能把单卡的性能吃到 80%。为了并发请求进来不互相影响我们往往会把 server 的处理线程池设为 1，这就意味着单个实例的并发数只有 1， 如果同一时刻实例接收到 2 个请求，则有一个请求会在 gRPC server 中排队。这样随之出现的问题就是如果先处理的请求耗时过长，那么排队的请求还来不及处理客户端就因为超时返回了。这种情况对于客户端来说得一直等到超时并且失败，非常不友好；再者客户端已经超时返回了，服务器还在处理已经返回的请求白白浪费资源。
在这篇文章里我分享一下我们的优化思路，希望能帮到有类似场景的同学。

### 快速失败
在上面我们提到在限制并发能力的情况下由于 gRPC server 的排队机制可能导致请求已经超时返回而服务器还在处理这个请求。很自然的想法就是我们把队列设置成 1, 同一时刻进来的多个请求只有一个会被处理，其他请求则返回失败。 
这样降低了服务器的负载，但客户端的请求还是失败了，并没有从根本上提升用户的体验。
在服务器处理速率和请求速率相当的情况下，如果我们在快速失败的基础上能立即重试并且不让打到之前失败的实例上，这样能大大降低客户端的调用失败率。
所以，关键就是如果让重试的请求不打到失败的实例。这里我们用的负载均衡算法是 `P2C`。

#### P2C
> P2C 算法全称 Pick of 2 choices，相比 WRR，P2C 有着更科学的 LB 策略，它通过随机选择两个节点后在这俩节点里选择优胜者来避免羊群效应，并通过指数加权移动平均算法统计服务端的实时状态，从而做出最优选择。
我们这里不详细介绍 `P2C`，只是把该算法节点选择的过程说清楚，让大家便于明白重试请求不容易打到失败的实例。

##### 核心逻辑  
1. 在多个节点中随机选择两个节点:会随机的选择3次，如果其中一次选择的节点的健康条件满足要求，就中断选择，采用这两个节点  
2. 比较 nodeA、nodeB 两个节点，选出负载最低（综合请求响应时间、服务器 cpu 负载、正在处理的请求数据、请求成功率）的节点作为被选中的节点 
下图说明了这个选择过程  

    ![p2c](https://pics.lxkaka.wang/p2c.png)

##### 关键实现
在[这里](https://www.lxkaka.wang/gprc-balancer/)我们介绍过实现自定义 gRPC 负载均衡器的关键就是   
1. 实现 google.golang.org/grpc/balancer/base/base.go/PickerBuilder 接口, 这个接口是有服务节点更新的时候会调用接口里的 Build 方法
```golang
type PickerBuilder interface {
    // Build returns a picker that will be used by gRPC to pick a SubConn.
    Build(info PickerBuildInfo) balancer.Picker
}
``` 

2. 还要实现 google.golang.org/grpc/balancer/balancer.go/Picker 接口。这个接口主要实现负载均衡，挑选一个节点供请求使用
```golang
type Picker interface {
  Pick(info PickInfo) (PickResult, error)
}
```
3. 注册自己实现的负载均衡器  


重点看一下节点筛选逻辑     

* 选择两个节点    
```golang
// choose two distinct nodes
// 总循环 3 次，随机从 subConns []*subConn 中选择两个节点 nodeB 和 nodeA，
// 如果满足 node.valid() 的要求，直接返回，不满足的话，返回最后一次的选择的两个节点
func (p *p2cPicker) prePick() (nodeA *subConn, nodeB *subConn) {
	for i := 0; i < 3; i++ {
		p.lk.Lock()
		a := p.r.Intn(len(p.subConns))
		b := p.r.Intn(len(p.subConns) - 1)
		p.lk.Unlock()
		if b >= a {
			b = b + 1
		}
		nodeA, nodeB = p.subConns[a], p.subConns[b]
		if nodeA.valid() || nodeB.valid() {
			break
		}
	}
	return
}
```

* 二选一  
```golang
func (p *p2cPicker) pick(ctx context.Context, opts balancer.PickInfo) (balancer.PickResult, error) {
	var pc, upc *subConn
	start := time.Now().UnixNano()

	if len(p.subConns) <= 0 {
		return balancer.PickResult{}, balancer.ErrNoSubConnAvailable
	} else if len(p.subConns) == 1 {
		pc = p.subConns[0]
	} else {
		nodeA, nodeB := p.prePick()
		// meta.Weight为服务发布者在disocvery中设置的权重
		if nodeA.load()*nodeB.health()*nodeB.meta.Weight > nodeB.load()*nodeA.health()*nodeA.meta.Weight {
			pc, upc = nodeB, nodeA
		} else {
			pc, upc = nodeA, nodeB
		}
		// 如果选中的节点，在forceGap期间内没有被选中一次，那么强制一次
		// 利用强制的机会，来触发成功率、延迟的衰减
		// 原子锁conn.pick保证并发安全，放行一次
		pick := atomic.LoadInt64(&upc.pick)
		if start-pick > forceGap && atomic.CompareAndSwapInt64(&upc.pick, pick, start) {
			pc = upc
		}
	}
	log.Warn("node inflight: %s, %d \n", pc.addr.Addr, atomic.LoadInt64(&pc.inflight))

	// 节点未发生切换才更新pick时间
	if pc != upc {
		atomic.StoreInt64(&pc.pick, start)
	}
	atomic.AddInt64(&pc.inflight, 1)
	atomic.AddInt64(&pc.reqs, 1)
```

#### 错误实例被选择概率大大降低  
在下面的这段代码我们可以看到当请求调用发生错误时，节点健康值 `success` 会变的很小几乎为0 (采用指数加权移动平均算法更新)，这样当请求失败立即重试有极大的概率被路由到空闲的实例上。  
```golang
if di.Err != nil {
	if st, ok := status.FromError(di.Err); ok {
		// only counter the local grpc error, ignore any business error
		if st.Code() != codes.Unknown && st.Code() != codes.OK {
			success = 0
		}
	}
	}
	oldSuc := atomic.LoadUint64(&pc.success)
	success = uint64(float64(oldSuc)*w + float64(success)*(1.0-w))
	atomic.StoreUint64(&pc.success, success)
...
```
下图是快速失败 + 立即重试策略的测试结果, 图中右半部分可以看到在使用了优化策略的情况下错误率大大降低，并且响应时间没有明显增加。  

![fast-fail](https://pics.lxkaka.wang/fast-fail.png)

### 优选空闲节点
在 `P2C` 算法中我们看到在比较节点的负载的时候是下面的方法, 其中 `inflight` 表示节点正在处理的请求数   
```golang
func (sc *subConn) load() uint64 {
	lag := uint64(math.Sqrt(float64(atomic.LoadUint64(&sc.lag))) + 1)
	load := atomic.LoadUint64(&sc.svrCPU) * lag * uint64(atomic.LoadInt64(&sc.inflight))
	if load == 0 {
		// penalty是初始化没有数据时的惩罚值，默认为1e9 * 250
		load = penalty
	}
	return load
}
```
既然我们有 `inflight` 这个指标，那我们选择节点的时候只选择 `inflight=1`的节点是不是就能完美解决上面的问题。理论上是的，但是实际上服务器就是成本，在满足业务需求的时候我们尽可能降低服务器成本，那么在这种情况下在生产环境很难一直有*空闲*的节点。所以在成本和性能的 trade off 下，我们使用的策略是在挑选两节点的阶段在 3次循环中优先挑选 `inflight=1`的节点。如果三次都没有符合条件的节点就退化成普通的 `P2C`。    
如代码所示      

```golang
func (p *p2cPicker) prePick() (nodeA *subConn, nodeB *subConn) {
	for i := 0; i < 3; i++ {
		p.lk.Lock()
		a := p.r.Intn(len(p.subConns))
		b := p.r.Intn(len(p.subConns) - 1)
		p.lk.Unlock()
		if b >= a {
			b = b + 1
		}
		nodeA, nodeB = p.subConns[a], p.subConns[b]
		if nodeA.valid() || nodeB.valid() {
			break
		}
	}
	return
}

func (sc *subConn) valid() bool {
	return sc.health() > 500 && atomic.LoadUint64(&sc.svrCPU) < 900 && atomic.LoadInt64(&sc.inflight) <=1
}
```
这种优化策略，我们把他起名为 `P2C1`。  

下图是我们在快速失败的基础上使用了进一步的优化策略 `P2C1`, 可以看到图中第三部分错误请求基本没有了。我们的优化起到了良好的效果。  

![p2c1](https://pics.lxkaka.wang/p2c1.png)

希望这篇文章里的优化思路和方法能给其他有类似限制场景的同学提供参考。 
