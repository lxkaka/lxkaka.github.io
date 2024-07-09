# Golang 实现的 Redis 分布式锁

最近在做一个功能的时候需要用到分布式锁，发现我们的公共库里好像没有可以直接拿来用的分布式锁，那就自己实现一个。首先想到方案就是 Redis 分布式锁。一个相对完备的分布式锁应该满足以下几点：
* 互斥性。互斥是锁的基本特征，同一时刻锁只能被一个协程持有，执行操作。

* 超时释放。通过超时释放，可以避免死锁，防止不必要的协程等待和资源浪费。

* 可重入性。一个协程在持有锁的情况可以对其再次请求加锁，防止锁在协程执行完操作之前释放。

* 高性能和高可用。加锁和释放锁的过程性能开销要尽可能的低，同时也要保证高可用，防止分布式锁意外失效。

由于我们有现成的 redis 集群，所以选择 Redis 分布式锁实现成本是最低的，并且基本能满足以上特点。

这里我们就总结一下 redis 实现分布式锁的几种方式和分别存在的问题

### 实现方式

#### SETNX + EXPIRE
最基本的做法就是利用 Redis 的 SETNX 指令，该指令只在 key 不存在的情况下，将 key 的值设置为 value，若 key 已经存在，则 SETNX 命令不做任何动作。key 是锁的唯一标识，可以按照业务需要锁定的资源来命名。
在使用 SETNX 拿到锁以后，必须给 key 设置一个过期时间，以保证即使没有被显式释放，在获取锁达到一定时间后也要自动释放，防止资源被长时间独占。由于 SETNX 不支持设置过期时间，所以需要额外的 EXPIRE 指令。
```golang
func (d *dao) RedisLock(ctx context.Context, lockKey, lockValue string, ttl int64) (err error) {
	result, err := redis.String(d.redis.Do(ctx, "SET", lockKey, lockValue))
	if err != nil || result != "OK" {
		if err == redis.ErrNil {
			err = nil
			return
		}
		log.Error("Error on acquiring lock for %s, %v", lockKey, err)
	}
	// 设置过期时间	
	if ok, err = redis.Bool(d.redis.Do(ctx, "EXPIRE", lockKey, ttl)); err != nil {
		log.Error("Erron on expiring lock for %s, %v", key, err)
		return
		}
	return
	}	
```
这样实现的分布式锁仍然存在一个严重的问题，由于 SETNX 和 EXPIRE 这两个操作是非原子性的，如果程序在执行 SETNX 和 EXPIRE 之间发生异常，SETNX 执行成功，但 EXPIRE 没有执行，导致锁不会过期，其他协程无法正常获取锁。

#### SET 扩展命令
为了解决 SETNX 和 EXPIRE 两个操作非原子性的问题，可以使用 Redis 的 SET 指令的扩展参数，使得 SETNX 和 EXPIRE 这两个操作可以原子执行，如下面代码所示。
```golang
func (d *dao) RedisLock(ctx context.Context, lockKey, lockValue string, ttl int64) (err error) {
	result, err := redis.String(d.redis.Do(ctx, "SET", lockKey, lockValue, "EX", ttl, "NX"))
	if err != nil || result != "OK" {
		if err == redis.ErrNil {
			err = nil
			return
		}
		log.Error("Error on acquiring lock for %s, %v", lockKey, err)
	}
```
在这个 SET 指令中：  
* NX 表示只有当 lockKey 对应的 key 值不存在的时候才能 SET 成功。保证了只有第一个请求的协程才能获得锁，而其它协程在锁被释放之前都无法获得锁。
* EX ttl 表示这个锁 ttl 秒钟后会自动过期，业务可以根据实际情况设置这个时间的大小。
其中 *EX* 也可以替换成 *PX* 可以使锁过期时间精确到毫秒。

但是这种方式仍然不能彻底解决分布式锁超时问题：

* 锁被提前释放。假如协程程 A 在加锁和释放锁之间的逻辑执行的时间过长（或者协程 A 执行过程中被堵塞），以至于超出了锁的过期时间后进行了释放，但协程 A 在想加锁部分的逻辑还没有执行完，那么这时候协程 B 就可以提前重新获取这把锁，导致代码不能严格的串行执行，而产生意外情况。

* 锁被误删。假如以上情形中的协程 A 执行完后，它并不知道此时的锁持有者是协程 B，协程 A 会继续执行 DEL 指令来释放锁，如果协程 B 在临界区的逻辑还没有执行完，协程 A 实际上释放了协程 B 的锁。

为了避免以上情况，建议不要在执行时间过长的场景中使用 Redis 分布式锁，同时一个比较安全的做法是在执行 DEL 释放锁之前对锁进行判断，验证当前锁的持有者是否是自己。  
具体实现就是在加锁时将 value 设置为一个唯一的随机数(可以使用 UUID 或者生成随机数)，释放锁时先判断随机数是否一致，然后再执行释放操作，确保不会错误地释放其它协程持有的锁，除非是锁过期了被服务器自动释放

#### Lua脚本实现
* Lua 脚本保证原子性，把多个操作在 Redis 中实现成一个操作，也就是单命令操作
* 使用了 set key value px milliseconds nx  
* value 具有唯一性
* 加锁时首先判断 key 的 value 是否和之前设置的一致，一致则修改过期时间
代码如下   
```golang
package redislock

import (
	"context"
	"crypto/sha1"
	"encoding/hex"
	"io"
	"math/rand"
	"strconv"
	"sync/atomic"
	"time"
)

const (
	letters     = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
	lockCommand = `if redis.call("GET", KEYS[1]) == ARGV[1] then
    redis.call("SET", KEYS[1], ARGV[1], "PX", ARGV[2])
    return "OK"
else
    return redis.call("SET", KEYS[1], ARGV[1], "NX", "PX", ARGV[2])
end`
	delCommand = `if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end`
	randomLen       = 16
	tolerance       = 500 // milliseconds
	millisPerSecond = 1000
)

// A RedisLock is a redis lock.
// 这里的 redis 是对 redigo 的一层内部封装
type RedisLock struct {
	store   *redis.Redis
	seconds uint32
	key     string
	id      string
}

type Script struct {
	keyCount int
	src      string
	hash     string
}

func init() {
	rand.Seed(time.Now().UnixNano())
}

// NewRedisLock returns a RedisLock.
func NewRedisLock(store *redis.Redis, key string) *RedisLock {
	return &RedisLock{
		store: store,
		key:   key,
		id:    randomStr(randomLen),
	}
}

func NewScript(keyCount int, src string) *Script {
	h := sha1.New()
	io.WriteString(h, src)
	return &Script{keyCount, src, hex.EncodeToString(h.Sum(nil))}
}

// Acquire acquires the lock.
func (rl *RedisLock) Acquire() (bool, error) {
	var (
		seconds = atomic.LoadUint32(&rl.seconds)
		keyCount = 1
		s = NewScript(keyCount, lockCommand)
		keysAndArgs = []interface{}{rl.key, rl.id, strconv.Itoa(int(seconds)*millisPerSecond + tolerance)}
	)
	conn := rl.store.Conn(context.TODO())
	defer conn.Close()
	resp, err := conn.Do("EVAL", s.args(s.src, keysAndArgs)...)
	if err == redis.ErrNil {
		return false, nil
	} else if err != nil {
		log.Error("Error on acquiring lock for %s, %v", rl.key, err)
		return false, err
	} else if resp == nil {
		return false, nil
	}

	reply, ok := resp.(string)
	if ok && reply == "OK" {
		return true, nil
	}

	log.Error("Unknown reply when acquiring lock for %s: %v", rl.key, resp)
	return false, nil
}

// Release releases the lock.
func (rl *RedisLock) Release() (bool, error) {
	var (
		keyCount = 1
		s = NewScript(keyCount, delCommand)
		keysAndArgs = []interface{}{rl.key, rl.id}
	)
	conn := rl.store.Conn(context.TODO())
	defer conn.Close()
	resp, err := conn.Do("EVAL", s.args(s.src, keysAndArgs)...)
	if err != nil {
		return false, err
	}

	reply, ok := resp.(int64)
	if !ok {
		return false, nil
	}

	return reply == 1, nil
}

// 设置锁的过期时间
func (rl *RedisLock) SetExpire(seconds int) {
	atomic.StoreUint32(&rl.seconds, uint32(seconds))
}

// 创建随机值
func randomStr(n int) string {
	b := make([]byte, n)
	for i := range b {
		b[i] = letters[rand.Intn(len(letters))]
	}
	return string(b)
}

// 构造执行 eval 命令的参数
func (s *Script) args(spec string, keysAndArgs []interface{}) []interface{} {
	var args []interface{}
	if s.keyCount < 0 {
		args = make([]interface{}, 1+len(keysAndArgs))
		args[0] = spec
		copy(args[1:], keysAndArgs)
	} else {
		args = make([]interface{}, 2+len(keysAndArgs))
		args[0] = spec
		args[1] = s.keyCount
		copy(args[2:], keysAndArgs)
	}
	return args
}
```
使用示例   
```golang 
lock := redislock.NewRedisLock(s.dao.GetRedis(), fmt.Sprintf("tortflow_lock_%d_%d", req.Aid, req.Cid))
lock.SetExpire(2)
ok, err := lock.Acquire()
defer lock.Release()
if !ok || err != nil {
	log.Error(ctx, "xxx do not get lock")
	return
}
// 待锁逻辑
...
```

#### 多实例 Redis 问题
加锁时只作用在一个 Redis 节点上，即使 Redis 通过 Sentinel 或者 redis cluster 保证了高可用，但由于 Redis 的复制是异步的，Master 节点获取到锁后在未完成数据同步的情况下发生故障转移，此时其他协程依然可以获取到锁，这样当然也会出现问题。  
在 Redis 的分布式环境中，Redis 的作者 antirez 提供了 RedLock 的算法来实现一个分布式锁。
简单介绍一下 RedLock 的核心逻辑就是，每次加锁的时候尝试向redis集群中每个节点申请加锁，当前节点加锁失败则跳过继续向下一个节点执行加锁请求，只有大于一半的节点加锁成功才认为分布式锁成功；释放锁时同样需配合 lua 脚本向所有的 redis 节点发起释放锁请求。
在 Golang 中有根据 RedLock 实现的[版本](https://github.com/go-redsync/redsync)。针对这个库就不做过多介绍，感兴趣的点链接直达。

RedLock 算法并不是没有问题的。在这篇[文章](https://github.com/go-redsync/redsync)中大佬就指出了相关问题，因为节点间时钟同步问题或者 GC 造成的停顿而使锁不被唯一占用。并且每次 RedLock 每次获取锁都要去所有实例上获取，那如果有某台实例响应慢，那就是会拖慢整体获取锁的速度，这在某些场景下获取是不太可以接受的。在我们的业务中我们使用的 redis 且都是有 proxy 的，已经屏蔽了 Redis 实例，所以对于我们来说是不可用的。

我们之所以用 Redis 作为分布式锁，很大程度上是因为 Redis 本身高效和原子性操作方便等特点，即使在高并发的情况下也能很好的保证性能。在需要严格保证数据安全的情况下就得加上其他兜底措施或者是才用其他分布式锁。
