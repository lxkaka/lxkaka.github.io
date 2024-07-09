# 系统自适应限流算法-BBR

在 Golang 服务中我们经常会选择用官方库自带的令牌桶算法来实现服务实例级别的限流。
使用示例如下
```golang
package main

import (
    "context"
    "log"
    "time"

    "golang.org/x/time/rate"
)


func main() {
    l := rate.NewLimiter(1, 2)
    // 构造方法接受两个参数 limit表示每秒产生 token 数，burst 最多存令牌数
    for i := 0; i < 50; i++ {
        //这里是阻塞等待的，一直等到取到一个令牌为止
        log.Println("... ... Wait")
        c, _ := context.WithTimeout(context.Background(), time.Second*2)
        //Wait 阻塞等待
        if err := l.Wait(c); err != nil {
            log.Println("limiter wait error : " + err.Error())
        }
        log.Println("Wait  ... ... ")

        // Reserve 返回等待时间，再去取令牌
        // 返回需要等待多久才有新的令牌, 这样就可以等待指定时间执行任务
        r := l.Reserve()
        log.Println("reserve time :", r.Delay())

        //判断当前是否可以取到令牌
        //Allow 判断当前是否可以取到令牌
        a := l.Allow()
        log.Println("Allow == ", a)
    }
}
```
上述令牌桶限流器确实能够保护系统不被拖垮, 但这样的保护方法都是设定一个 quota, 当超过该 quota 后就阻止或减少流量的继续进入，当系统负载降低到某一水平后则恢复流量的进入。但其通常都是被动的，其实际效果取决于限流阈值设置是否合理，但往往设置合理不是一件容易的事情。  
阿里开源的 [Sentinel](https://github.com/alibaba/Sentinel)基于 TCP BBR 算法的思想开发了系统自适应限流。
>Sentinel 系统自适应限流从整体维度对应用入口流量进行控制，结合应用的 Load、CPU 使用率、总体平均 RT、入口 QPS 和并发线程数等几个维度的监控指标，通过自适应的流控策略，让系统的入口流量和系统的负载达到一个平衡，让系统尽可能跑在最大吞吐量的同时保证系统整体的稳定性。
在我们的 Golang 服务中同样采用了系统自适应限流算法来提高系统稳定性。这里面用到算法就是 [Kratos](https://github.com/go-kratos/kratos)中借鉴 Sentinel 设计而实现的 Golang 版本 BBR。在这篇文章我们介绍一下 BBR 的实现原理。

### 限流指标
Kratos BBR 通过综合分析服务的 cpu 使用率、请求成功的 qps 和请求成功的 rt 来做自适应限流保护。  
* cpu: 最近 1s 的 CPU 使用率均值，使用滑动平均计算，采样周期是 250ms
* inflight: 当前处理中正在处理的请求数量
* pass: 请求处理成功的量
* rt: 请求成功的响应耗时

### 滑动窗口
在自适应限流保护中，采集到的指标的时效性非常强，系统只需要采集最近一小段时间内的 qps、rt 即可，对于较老的数据，会自动丢弃。为了实现这个效果，kratos 使用了滑动窗口来保存采样数据。

![bbr-window](https://pics.lxkaka.wang/bbr-window.png)  

如上图，展示了一个具有两个桶（bucket）的滑动窗口（rolling window）。整个滑动窗口用来保存最近 1s 的采样数据，每个小的桶用来保存 500ms 的采样数据。 当时间流动之后，过期的桶会自动被新桶的数据覆盖掉，在图中，在 1000-1500ms 时，bucket 1 的数据因为过期而被丢弃，之后 bucket 3 的数据填到了窗口的头部。

### 限流公式  
`(cpu > 800 OR (Now - PrevDrop)) < 1s AND (MaxPass * MinRt * windows / 1000) < InFlight`

* MaxPass 表示最近 10s 内，单个 bucket 中最大的请求数
* MinRt 表示最近 10s 内，单个 bucket 中最小的响应时间
* windows 表示一秒内 bucket 的数量，默认配置中是 10s 100 个bucket，那么 windows 的值为 10

### 源码实现

#### Allow
```golang
func (l *BBR) Allow(ctx context.Context, opts ...limit.AllowOption) (func(info limit.DoneInfo), error) {
	allowOpts := limit.DefaultAllowOpts()
	for _, opt := range opts {
		opt.Apply(&allowOpts)
	}
	if l.shouldDrop() { // 判断是否触发限流
		return nil, ecode.LimitExceed
	}
	atomic.AddInt64(&l.inFlight, 1) // 增加正在处理请求数
	stime := time.Since(initTime) // 记录请求到来的时间
	return func(do limit.DoneInfo) {
		rt := int64((time.Since(initTime) - stime) / time.Millisecond) // 请求处理成功的响应时长
		l.rtStat.Add(rt) // 增加 rtStat 响应耗时的统计
		atomic.AddInt64(&l.inFlight, -1) // 请求处理成功后, 减少正在处理的请求数
		switch do.Op {
		case limit.Success:
			l.passStat.Add(1) // 处理成功后增加成功处理请求数的统计
			return
		default:
			return
		}
	}, nil
}
```
#### shouldDrop
```golang
func (l *BBR) shouldDrop() bool {
	// 判断目前cpu的使用率是否达到设置的CPU的限制, 默认值800
	if l.cpu() < l.conf.CPUThreshold { 
		// 如果上一次舍弃请求的时间是0, 那么说明没有限流的需求, 直接返回
		prevDrop, _ := l.prevDrop.Load().(time.Duration)
		if prevDrop == 0 {
			return false
		}
		// 如果上一次请求的时间与当前的请求时间小于1s, 那么说明有限流的需求
		if time.Since(initTime)-prevDrop <= time.Second {
			if atomic.LoadInt32(&l.prevDropHit) == 0 {
				atomic.StoreInt32(&l.prevDropHit, 1)
			}
			// 增加正在处理的请求的数量
			inFlight := atomic.LoadInt64(&l.inFlight)
			// 判断正在处理的请求数是否达到系统的最大的请求数量
			return inFlight > 1 && inFlight > l.maxFlight()
		}
		// 清空当前的prevDrop
		l.prevDrop.Store(time.Duration(0))
		return false
	}
	// 增加正在处理的请求的数量
	inFlight := atomic.LoadInt64(&l.inFlight)
	// 判断正在处理的请求数是否达到系统的最大的请求数量
	drop := inFlight > 1 && inFlight > l.maxFlight()
	if drop {
		prevDrop, _ := l.prevDrop.Load().(time.Duration)
		// 如果判断达到了最大请求数量, 并且当前有限流需求
		if prevDrop != 0 {
			return drop
		}
		l.prevDrop.Store(time.Since(initTime))
	}
	return drop
}
```
#### maxFlight
该函数是核心函数. 其计算公式: `MaxPass * MinRt * windows / 1000. maxPASS/minRT` 都是基于 metric.RollingCounter 来实现的
```golang
// winBucketPerSec: 每秒内的采样数量,其计算方式:int64(time.Second)/(int64(conf.Window)/int64(conf.WinBucket)), conf.Window 默认值 10s, conf.WinBucket 默认值100. 
// 简化下公式: 1/(10/100) = 10, 所以每秒内的采样数就是10
func (l *BBR) maxFlight() int64 {
	return int64(math.Floor(float64(l.maxPASS()*l.minRT()*l.winBucketPerSec)/1000.0 + 0.5))
}

// 单个采样窗口在一个采样周期中的最大的请求数, 默认的采样窗口是10s, 采样bucket数量100
func (l *BBR) maxPASS() int64 {
	rawMaxPass := atomic.LoadInt64(&l.rawMaxPASS)
	if rawMaxPass > 0 && l.passStat.Timespan() < 1 {
		return rawMaxPass
	}
	// 遍历100个采样 bucket, 找到采样 bucket 中最大的请求数
	rawMaxPass = int64(l.passStat.Reduce(func(iterator metric.Iterator) float64 {
		var result = 1.0
		for i := 1; iterator.Next() && i < l.conf.WinBucket; i++ {
			bucket := iterator.Bucket()
			count := 0.0
			for _, p := range bucket.Points {
				count += p
			}
			result = math.Max(result, count)
		}
		return result
	}))
	if rawMaxPass == 0 {
		rawMaxPass = 1
	}
	atomic.StoreInt64(&l.rawMaxPASS, rawMaxPass)
	return rawMaxPass
}

// 单个采样窗口中最小的响应时间
func (l *BBR) minRT() int64 {
	rawMinRT := atomic.LoadInt64(&l.rawMinRt)
	if rawMinRT > 0 && l.rtStat.Timespan() < 1 {
		return rawMinRT
	}
	// 遍历100个采样 bucket, 找到采样 bucket 中最小的响应时间
	rawMinRT = int64(math.Ceil(l.rtStat.Reduce(func(iterator metric.Iterator) float64 {
		var result = math.MaxFloat64
		for i := 1; iterator.Next() && i < l.conf.WinBucket; i++ {
			bucket := iterator.Bucket()
			if len(bucket.Points) == 0 {
				continue
			}
			total := 0.0
			for _, p := range bucket.Points {
				total += p
			}
			avg := total / float64(bucket.Count)
			result = math.Min(result, avg)
		}
		return result
	})))
	if rawMinRT <= 0 {
		rawMinRT = 1
	}
	atomic.StoreInt64(&l.rawMinRt, rawMinRT)
	return rawMinRT
}
```

### 使用方式
BBR 限流器可以作为 grpc server 的 `UnaryServerInterceptor` 实现
```golang
// Limit is a server interceptor that detects and rejects overloaded traffic.
func (b *RateLimiter) Limit() grpc.UnaryServerInterceptor {
	return func(ctx context.Context, req interface{}, args *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (resp interface{}, err error) {
		uri := args.FullMethod
		limiter := b.group.Get(uri)
		done, err := limiter.Allow(ctx)
		b.printStats(uri, limiter, err == nil)
		if err != nil {
			_metricServerBBR.Inc(uri)
			return
		}
		defer func() {
			done(limit.DoneInfo{Op: limit.Success})
		}()
		resp, err = handler(ctx, req)
		return
	}
}
```
启动 grpc server 的时候可以把这个 `UnaryServerInterceptor` 添加到 server 的 Interceptor 链中来保护 grpc server。
```golang
s.server = grpc.NewServer(opt...)
s.health = health.NewServer()
s.Use(bbr.New(nil).Limit())
```
