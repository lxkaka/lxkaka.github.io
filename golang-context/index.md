# Golang Context 探究

在用 Golang 开发过程中，我们一定能在代码里很多函数或方法都会传递 `context`, 也会经常遇到这样的报错 `context deadline exceeded`。你有想过或去探究过 context 到底是什么吗，为什么会遇到上述的报错。在这里我们就分析一下 context 是什么及用途。
首选 Golang 中的 context 值得是 `context.Context` 接口,Golang 在 1.7 版本中引入标准库的接口。context 主要用来在 goroutine 之间传递上下文信息，包括：取消信号、截止时间、key-value 等。

### Context 定义  
Context 接口定义如下  
```go
type Context interface {
    // 返回 context.Context的截止时间（也就是取消时间）
    Deadline() (deadline time.Time, ok bool)
    // 返回一个 Channel，这个 Channel 会在当前操作完成或者上下文被取消之后关闭，多次调用 Done 方法会返回同一个 Channel
    Done() <-chan struct{}
    // 返回 context.Context 结束的原因
    Err() error
    // 从 context.Context 中获取键对应的值, 该方法可以用来传递请求特定的数据
	Value(key interface{}) interface{}
}
```
### Context 实现
首先我们思考为什么Golang 中需要 Context。用我们最熟悉的例子 http server 来解释, Go 服务每次都是启动一个新的 goroutine 来处理每一个请求，在这个请求的操作往往会启动新 goroutine 访问数据库或其他服务，如果此时客户端断开了连接，后续的消耗资源的操作就完全没必要了。所以我们需要一个在 goroutine 之间同步取消信号，截止时间的机制或者特定请求数据。而 `Context` 被设计出来就是帮我们实现这个目标。
```
|-----------|         |-----------|         |-----------|
| goroutine |-------> | goroutine |-------> | goroutine |
|-----------|         |-----------|         |-----------|
```
##### 默认 Context
context 包中最常用的方法还是 `context.Background`、`context.TODO`，这两个方法都会返回预先初始化好的私有变量 background 和 todo。这两个私有变量都是通过 `new(emptyCtx)` 语句初始化的，它们是指向私有结构体 context.emptyCtx 的指针。
```go
func Background() Context {
	return background
}

func TODO() Context {
	return todo
}
```
通过下面代码可以看出 `emptyCtx` 就是 `Context` 的实现，只不过没有实际功能。
我们一般用 context.Background 作为根 context; 在不确定使用哪种 context 时用 context.Todo 一般起到占位的作用
```go
type emptyCtx int

func (*emptyCtx) Deadline() (deadline time.Time, ok bool) {
	return
}

func (*emptyCtx) Done() <-chan struct{} {
	return nil
}

func (*emptyCtx) Err() error {
	return nil
}

func (*emptyCtx) Value(key interface{}) interface{} {
	return nil
}
```

##### 取消的实现
如果 context 实现了下面的这个接口，则是能取消的 context。源码中有两个类型实现了 canceler 接口：`*cancelCtx` 和 `*timerCtx`
```go
type canceler interface {
	cancel(removeFromParent bool, err error)
	Done() <-chan struct{}
}
```
###### context.cancelCtx
首先函数 `WithCancel` 就是我们用来创建可以取消的 context(`context.cancelCtx`) 的入口。
```go
func WithCancel(parent Context) (ctx Context, cancel CancelFunc) {
    // 将传入的上下文包装成私有结构体 context.cancelCtx
    c := newCancelCtx(parent)
    // 构建父子上下文之间的关联，当父上下文被取消时，子上下文也会被取消
	propagateCancel(parent, &c)
	return &c, func() { c.cancel(true, Canceled) }
}
```
我们重点看 `propagateCancel` 的实现   
```go
func propagateCancel(parent Context, child canceler) {
    done := parent.Done()
    // 父 context 是 emptyCtx
	if done == nil {
		return // parent is never canceled
	}

	select {
	case <-done:
		// parent is already canceled
		child.cancel(false, parent.Err())
		return
	default:
	}

    // 找到可以取消的父 context
	if p, ok := parentCancelCtx(parent); ok {
		p.mu.Lock()
		if p.err != nil {
			// 父节点已经被取消了，子节点也要取消
			child.cancel(false, p.err)
		} else {
            // 父节点未取消
			if p.children == nil {
				p.children = make(map[canceler]struct{})
            }
            // 与父 context 关联
			p.children[child] = struct{}{}
		}
		p.mu.Unlock()
	} else {
        // 如果没有找到可取消的父 context，新启动一个协程监控父节点或子节点取消信号
		atomic.AddInt32(&goroutines, +1)
		go func() {
			select {
			case <-parent.Done():
				child.cancel(false, parent.Err())
			case <-child.Done():
			}
		}()
	}

```
`context.propagateCancel` 的作用是把子 context 和父 context 关联起来，保证在 parent 被取消时，child 也会收到对应的信号，达到父 context 取消，子 context 也能同时取消的目的。  
下面重点看一下 `context.cancelCtx` 的 `cancel` 方法  
```go
func (c *cancelCtx) cancel(removeFromParent bool, err error) {

	if err == nil {
		panic("context: internal error: missing cancel error")
	}
	c.mu.Lock()
	if c.err != nil {
		c.mu.Unlock()
		return // 已经被其他协程取消
	}
	c.err = err
	// 关闭 channel，通知其他协程
	if c.done == nil {
		c.done = closedchan
	} else {
		close(c.done)
	}
	
	// 遍历它的所有子节点
	for child := range c.children {
	    // 递归地取消所有子节点
		child.cancel(false, err)
	}
	// 将子节点置空
	c.children = nil
	c.mu.Unlock()

	if removeFromParent {
	    // 从父节点中移除自己 
		removeChild(c.Context, c)
	}
}
```
###### context.timerCtx
timerCtx 基于 cancelCtx，只是多了一个 time.Timer 和一个 deadline。Timer 会在 deadline 到来时，自动取消 context。  
```go
type timerCtx struct {
	cancelCtx
	timer *time.Timer // Under cancelCtx.mu.

	deadline time.Time
}
```
创建 `timerCtx` 的函数  
```go
func WithTimeout(parent Context, timeout time.Duration) (Context, CancelFunc) {
	return WithDeadline(parent, time.Now().Add(timeout))
}

func WithDeadline(parent Context, d time.Time) (Context, CancelFunc) {
    // 如果父节点 context 的 deadline 早于指定时间。直接构建一个可取消的 context。
	// 原因是一旦父节点超时，自动调用 cancel 函数，子节点也会随之取消。
	// 所以不用单独处理子节点的计时器时间到了之后，自动调用 cancel 函数
	if cur, ok := parent.Deadline(); ok && cur.Before(d) {
		// The current deadline is already sooner than the new one.
		return WithCancel(parent)
    }
    // 创建 timerCtx
	c := &timerCtx{
		cancelCtx: newCancelCtx(parent),
		deadline:  d,
    }
    // 与父节点关联
    propagateCancel(parent, c)
    // 计算当前距离 deadline 的时间
    dur := time.Until(d)
    // 直接取消
	if dur <= 0 {
		c.cancel(true, DeadlineExceeded) // deadline has already passed
		return c, func() { c.cancel(false, Canceled) }
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.err == nil {
        //dur 后 timer 会自动调用 cancel 函数。自动取消
		c.timer = time.AfterFunc(dur, func() {
			c.cancel(true, DeadlineExceeded)
		})
	}
	return c, func() { c.cancel(true, Canceled) }
}
```
timerCtx 首先是一个 cancelCtx，所以它能取消。看下 cancel() 方法：
```go
func (c *timerCtx) cancel(removeFromParent bool, err error) {
	// 直接调用 cancelCtx 的取消方法
	c.cancelCtx.cancel(false, err)
	if removeFromParent {
		// 从父节点中删除子节点
		removeChild(c.cancelCtx.Context, c)
	}
	c.mu.Lock()
	if c.timer != nil {
		// 关掉定时器，这样，在deadline 到来时，不会再次取消
		c.timer.Stop()
		c.timer = nil
	}
	c.mu.Unlock()
}
```
总结：context 实现取消和定时取消的核心是 `context.cancelCtx` 和 `context.timerCtx`。

##### context 传递数据   
###### context.valueCtx 
在 Golang 中使用 context.valueCtx 来传递上下文的数据，定义如下   
```go
type valueCtx struct {
	Context
	key, val interface{}
}

// 创建 valueCtx 
func WithValue(parent Context, key, val interface{}) Context {
	if key == nil {
		panic("nil key")
	}
	if !reflectlite.TypeOf(key).Comparable() {
		panic("key is not comparable")
	}
	return &valueCtx{parent, key, val}
}

// context.valueCtx 中存储的键值对与 context.valueCtx.Value 方法中传入的参数不匹配
// 就会从父上下文中查找该键对应的值直到在某个父上下文中返回 nil 或者查找到对应的值
func (c *valueCtx) Value(key interface{}) interface{} {
	if c.key == key {
		return c.val
	}
	return c.Context.Value(key)
}
```
在 context 传递数据的场景一般很有限，比较常见的使用场景是传递请求对应用户 token 以及用于进行分布式追踪的 trace id。不建议用来传递请求参数。
我用下面这种图来展示 Context 的关键实现  

![context](https://pics.lxkaka.wang/context.png)

### Context 使用  

#### context 超时取消
这里我们以一个 Http 服务接口中包含访问其他服务的操作来举例  
```go
func main() {
	http.HandleFunc("/test", testHandler)
	err := http.ListenAndServe("0.0.0.0:8000", nil)
	if err != nil {
		log.Println(err)
	}
}

func testHandler(w http.ResponseWriter, r *http.Request) {
    // 初始化一个超时 context
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	getMessage(ctx)
}

func getMessage(ctx context.Context) {
    // 新建带 context 超时取消的 http 请求实例
    req, _ := http.NewRequestWithContext(ctx, http.MethodGet, "http://127.0.0.1:8008/test", nil)
	client := &http.Client{}
    res, err := client.Do(req)
    if res != nil {
		fmt.Printf("res: %v", res.StatusCode)
		defer res.Body.Close()
	}
	if err != nil {
		fmt.Printf("%v", err)
	}
}
```
请求服务不超时则 console 输出 `res: 200`  
请求服务超时则 console 输出 `Get "http://127.0.0.1:8008/test": context deadline exceeded`

#### context 传递 trace
```go
// 初始化传递 trace 的 context
func NewContext(ctx context.Context, t Trace) context.Context {
	return context.WithValue(ctx, _ctxkey, t)
}

// 初始化一个 trace 实例
func ServerTrace(ctx context.Context, operationName string) context.Context {
	t := New(operationName)
	defer t.Finish(nil)
	t.SetTitle(operationName)
	t.SetTag(String(TagSpanKind, "server"))
	return NewContext(ctx, t)
}
// 从 context 获取 trace 
func FromContext(ctx context.Context) (t Trace, ok bool) {
	t, ok = ctx.Value(_ctxkey).(Trace)
	return
}
```
