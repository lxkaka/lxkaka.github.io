# Redis 多线程的学习和理解

在后端开发中面临分布式缓存选型时 Redis 已然成为了头号选手甚至可以说是事实上的标准。Redis 从本质上来讲是一个网络服务器，而对于一个网络服务器来说，网络模型是它的核心。而关于网络模型我们知道 Redis v6.0 版本引入了一个非常重要的特性-多线程 IO。在这篇文章里我们学习一下这个重要的特性，有助于我们更好的额理解 Redis 的底层实现。

### Redis 单线程
这里说的单线程指的是 Redis 的网络模型用单线程实现。单线程实现有以下优点  
* **避免过多的上下文切换开销**   
多线程调度过程中必然需要在 CPU 之间切换线程上下文 context，而上下文的切换又涉及程序计数器、堆栈指针和程序状态字等一系列的寄存器置换、程序堆栈重置甚至是高速缓存、TLB 快表的汰换，如果是进程内的多线程切换还好一些，因为单一进程内多线程共享进程地址空间，因此线程上下文比之进程上下文要小得多，如果是跨进程调度，则需要切换掉整个进程地址空间。  
如果是单线程则可以规避进程内频繁的线程切换开销，因为程序始终运行在进程中单个线程内，没有多线程切换的场景。  
* **可以实现无锁**  
如果 Redis 选择多线程模型，又因为 Redis 是一个数据库，那么势必涉及到底层数据同步的问题，则必然会引入某些同步机制，比如锁，而我们知道 Redis 不仅仅提供了简单的 key-value 数据结构，还有 list、set 和 hash 等等其他丰富的数据结构，而不同的数据结构对同步访问的加锁粒度又不尽相同，可能会导致在操作数据过程中带来很多加锁解锁的开销，增加程序复杂度的同时还会降低性能。
* **可维护性高**  
多线程的引入会使得程序不再保持代码逻辑上的串行性，代码执行的顺序将变成不可预测的，稍不注意就会导致程序出现各种并发编程的问题；其次，多线程模式也使得程序调试更加复杂和麻烦

#### 单线程事件循环
从 Redis 的 v1.0 到 v6.0 版本之前（在 v4.0 版本就已经引入了多线程处理异步任务），Redis 的核心网络模型一直是一个典型的单 Reactor 模型：利用 epoll/select/kqueue 等多路复用技术，在单线程的事件循环中不断去处理事件（客户端请求），最后回写响应数据到客户端。

![single-thread](https://pics.lxkaka.wang/redis-single-thread.png)
学习图上几个重要概念   
* client：客户端对象，Redis 是典型的 CS 架构（Client <---> Server），客户端通过 `socket` 与服务端建立网络通道然后发送请求命令，服务端执行请求的命令并回复。Redis 使用结构体 `client` 存储客户端的所有相关信息，包括但不限于封装的套接字连接 -- `conn，当前选择的数据库指针 -- `db，读入缓冲区 -- querybuf，写出缓冲区 -- buf，写出数据链表 -- reply等。

* aeApiPoll：I/O 多路复用 API，是基于 `epoll_wait/select/kevent` 等系统调用的封装，监听等待读写事件触发，然后处理，它是事件循环（Event Loop）中的核心函数，是事件驱动得以运行的基础。

* acceptTcpHandler：连接应答处理器，底层使用系统调用 `accept` 接受来自客户端的新连接，并为新连接注册绑定命令读取处理器，以备后续处理新的客户端 TCP 连接；除了这个处理器，还有对应的 `acceptUnixHandler` 负责处理 Unix Domain Socket 以及 `acceptTLSHandler` 负责处理 TLS 加密连接。
* readQueryFromClient：命令读取处理器，解析并执行客户端的请求命令。

* beforeSleep：事件循环中进入 `aeApiPoll` 等待事件到来之前会执行的函数，其中包含一些日常的任务，比如把 client->buf 或者 client->reply （后面会解释为什么这里需要两个缓冲区）中的响应写回到客户端，持久化 AOF 缓冲区的数据到磁盘等，相对应的还有一个 `afterSleep` 函数，在 aeApiPoll 之后执行。

* sendReplyToClient：命令回复处理器，当一次事件循环之后写出缓冲区中还有数据残留，则这个处理器会被注册绑定到相应的连接上，等连接触发写就绪事件时，它会将写出缓冲区剩余的数据回写到客户端。

结合上图学习客户端向 Redis 发起请求命令的工作原理   

1. Redis 服务器启动，开启主线程事件循环（Event Loop），注册 `acceptTcpHandler` 连接应答处理器到用户配置的监听端口对应的文件描述符，等待新连接到来；

2. 客户端和服务端建立网络连接；

3. `acceptTcpHandler` 被调用，主线程使用 AE 的 API 将 `readQueryFromClient` 命令读取处理器绑定到新连接对应的文件描述符上，并初始化一个 client 绑定这个客户端连接；

4. 客户端发送请求命令，触发读就绪事件，主线程调用 readQueryFromClient 通过 socket 读取客户端发送过来的命令存入 client->querybuf 读入缓冲区；

5. 接着调用 `processInputBuffer`，在其中使用 processInlineBuffer 或者 processMultibulkBuffer 根据 Redis 协议解析命令，最后调用 `processCommand` 执行命令；

6. 根据请求命令的类型（SET, GET, DEL, EXEC 等），分配相应的命令执行器去执行，最后调用 addReply 函数族的一系列函数将响应数据写入到对应 client 的写出缓冲区：client->buf 或者 client->reply ，client->buf 是首选的写出缓冲区，固定大小 16KB，一般来说可以缓冲足够多的响应数据，但是如果客户端在时间窗口内需要响应的数据非常大，那么则会自动切换到 client->reply 链表上去，使用链表理论上能够保存无限大的数据（受限于机器的物理内存），最后把 client 添加进一个 LIFO 队列 `clients_pending_write`；

7. 在事件循环（Event Loop）中，主线程执行 `beforeSleep` --> handleClientsWithPendingWrites，遍历 clients_pending_write 队列，调用 `writeToClient` 把 client 的写出缓冲区里的数据回写到客户端，如果写出缓冲区还有数据遗留，则注册 `sendReplyToClient` 命令回复处理器到该连接的写就绪事件，等待客户端可写时在事件循环中再继续回写残余的响应数据。

### Redis 多线程
CPU 通常不会成为性能瓶颈，瓶颈往往是内存和网络，因此单线程足够了。那么为什么现在 Redis 又要引入多线程呢？很简单，就是 Redis 的网络 I/O 瓶颈已经越来越明显了。互联网业务系统所要处理的线上流量越来越大，Redis 的单线程模式会导致系统消耗很多 CPU 时间在网络 I/O 上从而降低吞吐量，要提升 Redis 的性能有两个方向：
* 优化网络 I/O 模块  
* 提高机器内存读写的速度  

6.0 版本之后，Redis 正式在核心网络模型中引入了多线程，即 `I/O threading`
 Redis 多线程网络模型的总体设计如下图所示  

 ![io-threading](https://pics.lxkaka.wang/io-threading.png)

1. Redis 服务器启动，开启主线程事件循环（Event Loop），注册 `acceptTcpHandler` 连接应答处理器到用户配置的监听端口对应的文件描述符，等待新连接到来；
2. 客户端和服务端建立网络连接；
3. `acceptTcpHandler` 被调用，主线程使用 AE 的 API 将 `readQueryFromClient` 命令读取处理器绑定到新连接对应的文件描述符上，并初始化一个 client 绑定这个客户端连接；
4. 客户端发送请求命令，触发读就绪事件，服务端主线程不会通过 socket 去读取客户端的请求命令，而是先将 client 放入一个 LIFO 队列 `clients_pending_read`；
5. 在事件循环（Event Loop）中，主线程执行 `beforeSleep` -->handleClientsWithPendingReadsUsingThreads，利用 Round-Robin 轮询负载均衡策略，把 clients_pending_read队列中的连接均匀地分配给 I/O 线程各自的本地 FIFO 任务队列 `io_threads_list[id]` 和主线程自己，I/O 线程通过 socket 读取客户端的请求命令，存入 client->querybuf 并解析第一个命令，但不执行命令，主线程忙轮询，等待所有 I/O 线程完成读取任务；
6. 主线程和所有 I/O 线程都完成了读取任务，主线程结束忙轮询，遍历 clients_pending_read 队列，执行所有客户端连接的请求命令，先调用 processCommandAndResetClient 执行第一条已经解析好的命令，然后调用 processInputBuffer 解析并执行客户端连接的所有命令，在其中使用 processInlineBuffer 或者 processMultibulkBuffer 根据 Redis 协议解析命令，最后调用 processCommand 执行命令；
7. 根据请求命令的类型（SET, GET, DEL, EXEC 等），分配相应的命令执行器去执行，最后调用 addReply 函数族的一系列函数将响应数据写入到对应 client 的写出缓冲区：client->buf 或者 client->reply ，client->buf 是首选的写出缓冲区，固定大小 16KB，一般来说可以缓冲足够多的响应数据，但是如果客户端在时间窗口内需要响应的数据非常大，那么则会自动切换到 client->reply 链表上去，使用链表理论上能够保存无限大的数据（受限于机器的物理内存），最后把 client 添加进一个 LIFO 队列 clients_pending_write；
8. 在事件循环（Event Loop）中，主线程执行 beforeSleep --> handleClientsWithPendingWritesUsingThreads，利用 Round-Robin 轮询负载均衡策略，把 clients_pending_write 队列中的连接均匀地分配给 I/O 线程各自的本地 FIFO 任务队列 `io_threads_list[id]` 和主线程自己，I/O 线程通过调用 `writeToClient` 把 client 的写出缓冲区里的数据回写到客户端，主线程忙轮询，等待所有 I/O 线程完成写出任务；
9. 主线程和所有 I/O 线程都完成了写出任务， 主线程结束忙轮询，遍历 clients_pending_write 队列，如果 client 的写出缓冲区还有数据遗留，则注册 `sendReplyToClient` 到该连接的写就绪事件，等待客户端可写时在事件循环中再继续回写残余的响应数据。  
这里大部分逻辑和之前的单线程模型是一致的，变动的地方仅仅是把读取客户端请求命令和回写响应数据的逻辑异步化了，交给 I/O 线程去完成。这里需要特别注意的一点是 I/O 线程仅仅是读取和解析客户端命令而不会真正去执行命令，客户端命令的执行最终还是要回到主线程上完成。
我们把上述过程再通过流程图描述如下  

	![io-threading-flow](https://pics.lxkaka.wang/redis-io-threading-flow.png)

### benchmark 
单线程示例 benchmark 如下
```shell
root@be919f395fa3:/data# redis-benchmark -t get,set -c 32 -n 500000
====== SET ======
  500000 requests completed in 21.29 seconds
  32 parallel clients
  3 bytes payload
  keep alive: 1
  host configuration "save": 3600 1 300 100 60 10000
  host configuration "appendonly": no
  multi-thread: no

  Summary:
  throughput summary: 23483.00 requests per second

```
开启 `io-threads` 配置，多线程示例 benchmark 如下
```shell
root@be919f395fa3:/data# redis-benchmark -t get,set -c 160 --threads 4 -n 500000
====== SET ======
  500000 requests completed in 19.43 seconds
  160 parallel clients
  3 bytes payload
  keep alive: 1
  host configuration "save": 3600 1 300 100 60 10000
  host configuration "appendonly": no
  multi-thread: yes
  threads: 4

  Summary:
  throughput summary: 25736.05 requests per second
```
测试结果如图所示，上图是 `set` 测试结果，下图是 `get` 测试结果
![set-test](https://pics.lxkaka.wang/%E5%8D%95%E7%BA%BF%E7%A8%8B%E5%A4%9A%E7%BA%BF%E7%A8%8Bset.png)

![get-test](https://pics.lxkaka.wang/%E5%8D%95%E7%BA%BF%E7%A8%8B%E5%A4%9A%E7%BA%BF%E7%A8%8Bget.png)
GET/SET 分别提升 30% 多，并发连接小于 128 时性能差距不大。

总的来说 Redis 多线程网络模型在高并发场景下确实带来了性能提升(理论上高并发下能提升1倍 QPS)，这个方案是作者兼顾了性能和可维护性下的设计。其中 I/O 线程任务仅仅是通过 socket 读取客户端请求命令并解析，却没有真正去执行命令，所有客户端命令最后还需要回到主线程去执行，因此对多核的利用率并不算高，而且每次主线程都必须在分配完任务之后忙轮询等待所有 I/O 线程完成任务之后才能继续执行其他逻辑。在单机场景下我们确实可以利用这个特性来提升 Redis 性能，但是在高可用和高并发场景下选择 Redis-Cluster 我认为更合适。
