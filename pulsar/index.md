# Pulsar(新一代高性能消息系统)核心总结


消息中间件是后端服务系统中一个非常重要的组件，它可以在分布式环境下提供应用解耦、流量削峰、异步通信、数据同步等关键功能。在我们的应用中首先 rabbimq 和 kafka 这两个消息队列产品。
这二者虽然我们都叫消息队列，但他们的实现和应用场景都是不一样的。我们根据不同的应用场景会选择不同的产品。
一般情况下  
* 实时性要求极高，单条消息不大的，routing 复杂可选 RabbitMQ;
* 吞吐量要求高，实时性要求可稍微降低，流式数据可选 Kafka   

现在我们可以有更好的选择 [Pulsar](http://pulsar.apache.org/docs/en/concepts-overview/)，一个分布式高性能消息系统。  
Pulsar 的优势在哪里？我们为什么要选它?

## 系统架构    
 Pulsar 和其他消息系统最根本的不同是采用分层架构。 Apache Pulsar 集群由两层组成：无状态服务层，由一组接收和传递消息的 Broker 组成；以及一个有状态持久层，由一组名为 bookies 的 Apache BookKeeper 存储节点组成，可持久化地存储消息。下图显示了 Pulsar 的主体架构。  
 ![puslar-arch](https://pics.lxkaka.wang/puslar-arch.png)  

Pulsar 非常核心的设计逻辑就是消息服务和消息存储的分离, 即Broker 消息服务层和 BookKeeper 消息存储层。
### Broker
Broker 不存储消息本身，每个 topic 的消息都存储到了分布式日志存储系统 BookKeeper 中。 每个 partitioned topic 会被分配给某个 broker, 而生产者和消费者都连接到这个 broker 分别发送和消息消息。  
如果一个 Broker 失败，Pulsar 会自动将其拥有的主题分区移动到群集中剩余的某一个可用 Broker 中。由于 Broker 是无状态的，当发生 Topic 的迁移时，Pulsar 只是将所有权从一个 Broker 转移到另一个 Broker，在这个过程中，不会有任何数据复制发生。Broker 层的示意图如下所示  
![broker](https://pics.lxkaka.wang/broker.png)

### BookKeeper
BookKeeper 作为 puslar 的持久化层，负责存储每个 topic 的 partitions，本质上是分布式日志。每个分布式日志又被分为 Segment 分段。 每个 Segment 分段作为 BookKeeper 中的一个 Ledger，均匀分布并存储在 BookKeeper 群集中的多个 Bookie（BookKeeper 的存储节点）中。
Segment 创建的条件是基于配置的 serment 大小；基于配置的滚动时间, 或者 segment 的所有者发生了变化。通过 Segment 分段的方式，topic partition 中的消息可以均匀和平衡地分布在群集中的所有 Bookie 中。 因此一个 topic partition 的容量不受一个节点容量的限制；相反，它可以扩展到整个 BookKeeper 集群的总容量。 
下图展示了一个 topic partition 存储示意    
![bookkeeper](https://pics.lxkaka.wang/bookkeeper.png)  

正是因为分层架构和以 segment 为中心存储的设计思想让 Pular 相比其他消息队列产品有了以下优势 
* 无限制的 topic partition 存储；    
  topic patition 可以扩展到整个 BookKeeper 集群的总容量，只需添加 Bookie 节点即可扩展集群容量。
* 即时扩展，无需数据迁移；  
  * 无缝 Broker 故障恢复
  * 无缝集群容量扩展 
  * 无缝 Bookie 故障恢复
* 独立的扩展性  

## 消息模型  
消息系统的模型可以分为两类 队列式(queuing)和流式(streaming)。   
**queuing** 模型主要是采用无序或者共享的方式来消费消息，当一条消息从队列发送出来后，多个消费者中的只有一个（任何一个都有可能）接收和消费这条消息。queuing 模型通常与无状态应用程序一起结合使用, 无状态应用程序不关心排序，但需要能够确认（ack）或删除单条消息，以及尽可能地扩展消费并行的能力。RabbitMQ 就是典型的 queuing 模型。
**streaming** 模型要求消息的消费严格排序或独占消息消费，对于一个 message channel 只会有一个消费者消费消息。流模型通常与有状态应用程序相关联。有状态的应用程序更加关注消息的顺序及其状态。消息的消费顺序决定了有状态应用程序的状态。消息的顺序将影响应用程序处理逻辑的正确性。kafka 就是 streaming 模型。
Pulsar 的消息模型既支持 queuing，也支持 streaming。  
在 Pulsar 的消息消费模型中，Topic 是用于发送消息的通道, 消费者被组合在一起消费消息，每个消费组是一个订阅。每组消费者可以拥有自己不同的消费方式： 独占（Exclusive），故障切换（Failover）或共享（Share）。Pulsar 通过这种模型，将队列模型和流模型这两种模型结合在了一起，提供了统一的 API 接口。 这种模型，既不会影响消息系统的性能，也不会带来额外的开销，同时还为用户提供了更多灵活性，方便用户程序以最匹配模式来使用消息系统。  
Exclusive 和 Failover 订阅，仅允许一个消费者来使用和消费每个对主题的订阅。这两种模式都按主题分区顺序使用消息。它们最适用于需要严格消息顺序的流（Stream）用例。
Share 订阅允许每个主题分区有多个消费者。同一订阅中的每个消费者仅接收主题分区的一部分消息。共享订阅最适用于不需要保证消息顺序的队列（Queue）的使用模式，并且可以按照需要任意扩展消费者的数量。
下图展示了3个不同类型的订阅和消息的流向  
![message-model](https://pics.lxkaka.wang/message-model.png)

## 对比 Kafka
* 消息模型
    * Pulsar 提供了统一的消息模型和 API。streaming 模式——独占和故障切换订阅方式; queuing 模式——共享订阅的方式。
    * Kafka 主要集中在 streaming 模式，对单个 partition 是独占消费，没有共享（Queue）的消费模式；
* 架构
    * Pulsar Broker是无状态的，与存储相互分离 
      可以轻松添加和删除节点，而无需重新平衡整个集群
    * Kafka的数据直接存储在Broker上(有状态的)
      任何容量扩展都需要重新平衡分区，同时还需要将被平衡的分区重新拷贝到新添加的Broker上
* Ack   
    * Pulsar使用专门的 Cursor 管理。累积确认(cumulative acknowledgment)和 Kafka 效果一样；提供单条确认(individual ack)。
    * Kafka使用偏移 Offset
* Retention  
    * Pulsar 消息只有被所有订阅消费后才会删除，不会丢失数据。也允许设置保留期，保留被消费的数据。支持 TTL
    * Kafka根据设置的保留期来删除消息。有可能消息没被消费，过期后被删除。 不支持 TTL。


总结一下，文章开始问题的答案就是    
Pulsar 将高性能的 streaming（Kafka）和灵活的 queuing（RabbitMQ）结合到一个统一的消息模型和 API 中。 Pulsar 使用统一的 API 为用户提供一个支持 streaming 和 queuing 的系统，且具有同样的高性能。



