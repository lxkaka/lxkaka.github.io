# Kafka 和 Pulsar 存储结构对比

在我们当前业务场景下使用消息中间件是必不可少的，其中 kafka 和 pulsar 是我们消息中间件的首选项。在之前的一篇[文章](https://www.lxkaka.wang/pulsar/) 中我们提到过这两种消息队列，而在我们了解和评价和他们的性能和可用性时我认为底层的存储结构是非常重要的或者说是最重要的的一个因素。所以，在这篇文章里我们对二者的存储结构做一个对比和汇总。

## Kafka
关于 [Kafka](https://kafka.apache.org/) 的介绍和使用有很多资料可以供大家参考，这里我们不做介绍。
### Kafka 的 Partition
Kakfa 的一个 topic 在物理上被分成多个 partition 用以存储消息，各 partition 以目录形式在 leader broker 及其多副本 brokers 上持久化存储。partiton命名规则为topic名称+有序序号，第一个partiton序号从0开始，序号最大值为partitions数量减1。
下面是两个实例 topic ，在 kafka 数据目录下的分区存储情况： 
```
|--test_topic-0 
|--test_topic-1 
|--test_topic-2 
|--test_log-0 
|--tesst_log-1 
|--test_log-2 
```

### Partition 的组成
* 每个 partion(目录)相当于一个巨型文件被平均分配到多个大小相等 segment(段)数据文件中。但每个段 segment file 消息数量不一定相等，这种特性方便 old segment file 快速被删除。
* 每个 partiton 只需要支持顺序读写就行了，segment 文件生命周期由服务端配置参数决定。
下面这张图展示了 partition 的文件存储  

   ![kafka-partition](https://pics.lxkaka.wang/kafka-partition.png)

### Segment 存储结构
Partition 中的 segment file 存储结构
* segment file组成：由2大部分组成，分别为 index 文件和 data 文件，这两个文件一一对应，成对出现，后缀 ".index" 和 ".log" 分别表示为 segment 索引文件、数据文件.
* segment 文件命名规则：partion 全局的第一个 segment 从0开始，后续每个s egment 文件名为上一个 segment 文件最后一条消息的 offset 值。数值最大为64位 long 大小，19位数字字符长度，没有数字用0填充。
创建一个 topic 只包含一个 partition，设置每个 segment 大小为 500MB,并启动 producer 向 Kafka broker 写入大量数据,如下图所示 partiton test_topic-0 文件内容   

   ![kafka-segment](https://pics.lxkaka.wang/kafka-segment.png)

index file 存储元数据，log file 存储消息，index file 中元数据指向对应 log file 中 message 的物理偏移地址。其中以 index file 中元数据3,497为例，依次在 log file 中表示第3个message(在全局partiton表示第368772个message)、以及该消息的物理偏移地址为497。
以下图展示说明 segmen t中 index file<—->log file对应关系物理结构如下  

   ![kafka-index](https://pics.lxkaka.wang/kafka-index.png)  
其中 message 的物理结构如下    

   ![kafka-message](https://pics.lxkaka.wang/kafka-message.png)

### 消息查找    
例如读取offset=368776的message，需要通过下面2个步骤查找。  
1. 查找segment file 上述图2为例，其中 00000000000000000000.index 表示最开始的文件，起始偏移量(offset)为0.第二个文件 00000000000000368769.index 的消息量起始偏移量为368770 = 368769 + 1.同样，第三个文件 00000000000000737337.index 的起始偏移量为737338=737337 + 1，其他后续文件依次类推，以起始偏移量命名并排序这些文件，只要根据offset **二分查找**文件列表，就可以快速定位到具体文件。 当offset=368776时定位到 00000000000000368769.index|log

2. 通过segment file查找message 通过第一步定位到segment file，当offset=368776时，依次定位到 00000000000000368769.index 的元数据物理位置和00000000000000368769.log 的物理偏移地址，然后再通过 00000000000000368769.log 顺序查找直到offset=368776为止。

index file 采取稀疏索引存储方式，它减少索引文件大小，通过 mmap 可以直接内存操作，稀疏索引为数据文件的每个对应 message 设置一个元数据指针,它比稠密索引节省了更多的存储空间，但查找起来需要消耗更多的时间。 

## Pulsar 
Pulsar 的底层存储使用的是 [Apache Bookkeeper](https://bookkeeper.apache.org/docs/latest/getting-started/concepts/), 所以要了解 pulsar 的存储结构就是理解 bookkeeper 的存储原理。
BookKeeper集群由两大部分组成：
* 一组独立的存储服务器，成为bookies
* 一个元数据存储系统，提供服务发现以及元数据管理服务 
 BookKeeper 架构属于典型的 slave-slave 架构，zk 存储其集群的 meta 信息，这种模式的好处显而易见，server 端变得非常简单，所有节点都是一样的角色和处理逻辑，能够这样设计的主要原因是其副本没有 leader 和 follower 之分。
![bk-cluster](https://pics.lxkaka.wang/bk-cluster.jpeg)

### Bookkeeper 存储实现  
在 bookkeeper 中一个 Log/Stream/Topic 可以由下面的部分组成  
![bk-st](https://pics.lxkaka.wang/bk-store.png)
* Ledger：它是 BK 的一个基本存储单元（本质上还是一种抽象），BK Client 的读写操作也都是以 Ledger 为粒度的；
* Fragment：BK 的最小分布单元（实际上也是物理上的最小存储单元），也是 Ledger 的组成单位，默认情况下一个 Ledger 会对应的一个 Fragment（一个 Ledger 也可能由多个 Fragment 组成）；
* Entry：每条日志都是一个 Entry，它代表一个 record，每条 record 都会有一个对应的 entry id；
关于 Fragment，它是 Ledger 的物理组成单元，也是最小的物理存储单元，在以下两种情况下会创建新的 Fragment： 
当创建新的 Ledger 时；
当前 Fragment 使用的 Bookies 发生写入错误或超时，系统会在剩下的 Bookie 中新建 Fragment，但这时并不会新建 Ledger，因为 Ledger 的创建和关闭是由 Client 控制的，这里只是新建了 Fragment（需要注意的是：这两个 Fragment 对应的 Ensemble Bookie 已经不一样了，但它们都属于一个 Ledger，这里并不一定是一个 Ensemble Change 操作）。

#### 新建 ledger   
Ledger 是一组追加有序的记录，它是由 Client 创建的，然后由其进行追加写操作。每个 Ledger 在创建时会被赋予全局唯一的 ID，其他的 Client 可以根据 Ledger ID，对其进行读取操作。创建 Ledger 及 Entry 写入的相关过程如下：  

1. Client 在创建 Ledger 的时候，从 Bookie Pool 里面按照指定的数据放置策略挑选出一定数量的 Bookie，构成一个 Ensemble；  
2. 每条 Entry 会被并行地发送给 Ensemble 里面的部分 Bookies（每条 Entry 发送多少个 Bookie 是由 Write Quorum size 设置、具体发送哪些 Bookie 是由 Round Robin 算法来计算），并且所有 Entry 的发送以流水线的方式进行，也就是意味着发送第 N + 1 条记录的写请求不需要等待发送第 N 条记录的写请求返回；  
3. 对于每条 Entry 的写操作而言，当它收到 Ensemble 里面大多数 Bookie 的确认后（这个由 Ack Quorum size 来设置），Client 认为这条记录已经持久化到这个 Ensemble 中，并且有大多数副本。

这里引入了三个重要的概念，它们也是 BookKeeper 一致性的基础：  

* Ensemble size(E)：Set of Bookies across which a ledger is striped；  
* Write Quorum Size（Qw）：Number of replica；  
* Ack Quorum Size（Qa）：Number of responses needed before client’s write is satisfied。   
示意图如下  

![bk-ledger](https://pics.lxkaka.wang/bk-ledger.png)

#### Bookkeeper 读写分离    
bookeeper 采取了读写分离的设计   
下图描述了读写分离是如何实现的 

![bk-rw](https://pics.lxkaka.wang/bk-rw.png)   
写入（writes）、末尾读（trailing reads）和中间读（catch-up reads）这三种常见的 I/O 操作都被隔离到了三种物理上不同的 I/O 子系统中。
* 所有写入都被顺序地追加到磁盘上的日志文件，再批量提交到硬盘上。
* 在写操作持久化到磁盘上之后，它们就会放到一个 Memtable 中，再向客户端发回响应。Memtable 中的数据会被异步刷新到交叉存取的索引数据结构中：记录被追加到日志文件中，偏移量则在 ledger 的索引文件中根据记录 ID 索引起来。
* 最新的数据肯定在 Memtable 中，供末尾读操作使用。中间读会从记录日志文件中获取数据。由于物理隔离的存在，Bookie 节点可以充分利用网络流入带宽和磁盘的顺序写入特性来满足写请求，以及利用网络流出代宽和多个磁盘共同提供的IOPS处理能力来满足读请求，彼此之间不会相互干扰。  

我们用来自于 streaml.io 的一张图来总结 Kafka 和 Pulsar 在存储结构的上的区别  

![kafka-pulsar-partiton](https://pics.lxkaka.wang/kakfa-pulsar-partition.jpg)  

## 总结
在 pulsar准确说是 bookkeeper 以相较于 kafka 更复杂的存储设计换来了更强的扩展性   
从集群扩展性来说 
* kafka 增加 broker需要重新分配分区，以使得整个集群负载均衡。需要严密观察每个分区的状态，保证迁移操作不会打满网络带宽和磁盘 IO;
* pulsar 增加 broker 或 bookie 不需要做数据重新分布，新的分区会自动分配到新扩容的 bookie 上
从读写扩展性来说
* kafka 没有物理 I/O 隔离，依靠文件系统缓冲；
* pulsar 可以通过 bookie 挂载不同磁盘实现物理 I/O 隔离，读写分离   
