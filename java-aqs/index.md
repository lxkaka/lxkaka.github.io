# Java 线程同步实现探究


在 Java 开发中，多线程的应用十分频繁，所以在多线程协作完成同一个任务的情况下，线程间同步的需求会非常常见。比如这样一个场景，主线程需要从10个站点下载数据，此时新建一个大小为 5 的线程池来分别从站点下载数据，主线程则必须等到子线程全部下载完成后，拿到完整数据才能进行下一步的处理。Java 给我们提供了一个类 `CountDownLatch` 可以方便的帮助我们来实现这样的场景。

### 代码示例

```java
public class CountdownLatchDe {


    private static CountDownLatch guests = new CountDownLatch(5);

    public static void main(String[] args) throws InterruptedException {
        ExecutorService executorService = Executors.newFixedThreadPool(5);
        for (int i = 0; i < 5; i++) {
            executorService.execute(() -> {
                System.out.println(Thread.currentThread().getName() + ": 游戏开始");
                System.out.println(Thread.currentThread().getName() + ": 完成");
                guests.countDown();
            });
        }
        guests.await();
        System.out.println(Thread.currentThread().getName() + "： 全部结束, 开始一下项");
        executorService.shutdown();
    }
}
```

输出如下:  
![countdownshow](https://pics.lxkaka.wang/countdowndemo.png)  
上面这个 demo 展示了这样一个场景，在一场有主持人的活动中，主持人必须等参与者都完成了一个游戏，才能宣布进入下一个环节。主线程模拟的是主持人，主线程调用方法`await` 会被阻塞住，子线程模拟的参与者每次执行方法`countDown`, 则`CountDownLatch` 维护的计数器会减一，直到全部子线程执行完，计数器也变为0，主线程才被唤醒可以继续往下执行。

### 源码查看  

- 属性和构造函数

```java
public class CountDownLatch {
    // 这是 CountDownLatch 定义的一个继承自 AQS 的内部类，数据结构就是使用 AQS 提供的两个队列 sync queue 和 condition queue
    private final Sync sync;

    // 构造给定计数的 CountDownLatch, 完成 sync 初识化
    public CountDownLatch(int count) {
        if (count < 0) throw new IllegalArgumentException("count < 0");
        // 初始化状态数
        this.sync = new Sync(count);
    }
}
```

- 核心函数  

```java
// 会阻塞调用线程一直到计数器为0或者被中断  
public void await() throws InterruptedException {
    // 真正调用 sync 对象的方法
    sync.acquireSharedInterruptibly(1);
}
```

`await` 主要调用链如下所示  
![await](https://pics.lxkaka.wang/countdownlatch.png)  
总结一下核心流程:

- 判读当前计数器是否为 0；
- 计数器不是0， 调用 `doAcquireSharedInterruptibly` 加入到同步阻塞队列；
- 尝试获取锁，获取失败则调用 `shouldParkAfterFailedAcquire` 判断是否需要阻塞等待，如果需要阻塞等待则调用 `parkAndCheckInterrupt` 阻塞当前线程并让出cup资源直到被前一个节点唤醒

```java
// 计数器减一，如果减为0，则释放所有等待线程
public void countDown() {
    sync.releaseShared(1);
}
```

`countDown` 主要调用链如下所示  
![conuntdown](https://pics.lxkaka.wang/countdown.png)  
总结一下核心流程(`doReleaseShared`)：  

- 获取头结点，头结点不为空且有下一个结点；
- 头结点状态为 `Signal`, 调用 `unparkSuccessor` 唤醒；
- 获取当前节点状态，当前节点正常情况则设置成0，获取下一个状态为非 `CANCELLED`的节点，调用 `LockSupport.unpark` 唤醒此结点  

考虑另外一个场景，子线程需要同时执行一个操作，怎么让这些线程同时开始呢？ 我们可以借助 Java 提供的 CyclicBarrier 来实现此目的。

### 代码实例

```java
public class CyclicBarrierDe {

    private static CyclicBarrier barrier = new CyclicBarrier(5, () -> {
        System.out.println("下一阶段 go ->");});

    public static void main(String[] args) {
        ExecutorService executorService = Executors.newFixedThreadPool(5);
        for (int i = 0; i < 5; i++) {
            executorService.execute(() -> {
                try {
                    System.out.println(Thread.currentThread().getName() + ": 热身活动");
                    barrier.await();
                    System.out.println(Thread.currentThread().getName() + ": 比赛开始");
                    System.out.println(Thread.currentThread().getName() + ": 比赛结束");
                    barrier.await();
                    System.out.println(Thread.currentThread().getName() + ": 参加记者招待会");
                } catch (InterruptedException | BrokenBarrierException e) {
                    e.printStackTrace();
                }
            });
        }
    }

}
```

输出如下：  
![cyclicshow](https://pics.lxkaka.wang/cyclicshow.png)
上面的 demo 展示了每个子线程都调用了 `await` 则都到达了 barrier, 才能执行后续的代码，否则被阻塞住。

### 源码查看

- 属性和构造函数

```java
public class CyclicBarrier {
    /** The lock for guarding barrier entry */
    // 可重入锁
    private final ReentrantLock lock = new ReentrantLock();
    /** Condition to wait on until tripped */
    // 条件队列
    private final Condition trip = lock.newCondition();
    /** The number of parties */
    // 参与的线程数量
    private final int parties;
    /* The command to run when tripped */
    // 由最后一个进入 barrier 的线程执行的操作
    private final Runnable barrierCommand;
    /** The current generation */
    // 当前代
    private Generation generation = new Generation();
    // 正在等待进入屏障的线程数量
    private int count;

    public CyclicBarrier(int parties, Runnable barrierAction) {
        // 参与的线程数量小于等于0，抛出异常
        if (parties <= 0) throw new IllegalArgumentException();
        // 设置parties
        this.parties = parties;
        // 设置count
        this.count = parties;
        // 设置barrierCommand
        this.barrierCommand = barrierAction;
    }

    public CyclicBarrier(int parties) {
        // 调用含有两个参数的构造函数
        this(parties, null);
    }
}
```

- 核心函数  

```java
private int dowait(boolean timed, long nanos)
    throws InterruptedException, BrokenBarrierException,
            TimeoutException {
    // 保存当前锁
    final ReentrantLock lock = this.lock;
    // 锁定
    lock.lock();
    try {
        // 保存当前代
        final Generation g = generation;
        if (g.broken) // 屏障被破坏，抛出异常
            throw new BrokenBarrierException();

        if (Thread.interrupted()) { // 线程被中断
            // 损坏当前屏障，并且唤醒所有的线程，只有拥有锁的时候才会调用
            breakBarrier();
            // 抛出异常
            throw new InterruptedException();
        }
        // 减少正在等待进入屏障的线程数量
        int index = --count;
        if (index == 0) {  // 正在等待进入屏障的线程数量为0，所有线程都已经进入
            // 运行的动作标识
            boolean ranAction = false;
            try {
                // 保存运行动作
                final Runnable command = barrierCommand;
                if (command != null) // 动作不为空
                    // 运行
                    command.run();
                // 设置ranAction状态
                ranAction = true;
                // 进入下一代
                nextGeneration();
                return 0;
            } finally {
                if (!ranAction) // 没有运行的动作
                    // 损坏当前屏障
                    breakBarrier();
            }
        }

        // loop until tripped, broken, interrupted, or timed out
        // 无限循环
        for (;;) {
            try {
                if (!timed) // 没有设置等待时间
                    // 等待
                    trip.await(); 
                else if (nanos > 0L) // 设置了等待时间，并且等待时间大于0
                    // 等待指定时长
                    nanos = trip.awaitNanos(nanos);
            } catch (InterruptedException ie) { 
                if (g == generation && ! g.broken) { // 等于当前代并且屏障没有被损坏
                    // 损坏当前屏障
                    breakBarrier();
                    // 抛出异常
                    throw ie;
                } else { // 不等于当前带后者是屏障被损坏
                    // We're about to finish waiting even if we had not
                    // been interrupted, so this interrupt is deemed to
                    // "belong" to subsequent execution.
                    // 中断当前线程
                    Thread.currentThread().interrupt();
                }
            }

            if (g.broken) // 屏障被损坏，抛出异常
                throw new BrokenBarrierException();

            if (g != generation) // 不等于当前代
                // 返回索引
                return index;

            if (timed && nanos <= 0L) { // 设置了等待时间，并且等待时间小于0
                // 损坏屏障
                breakBarrier();
                // 抛出异常
                throw new TimeoutException();
            }
        }
    } finally {
        // 释放锁
        lock.unlock();
    }
}
```

CyclicBarrier 与 CountDownLatch 对比:  

- 二者都可以用来做线程同步；
- CyclicBarrier 到达 barrier 后唤醒全部线程，CountDownLatch 计数为0，则是一个个传播唤醒；  
- CyclicBarrier 支持配置 Runnable 任务 CountDownLatch 不支持；CyclicBarrier 可重用 CountDownLatch 不可重用.  

