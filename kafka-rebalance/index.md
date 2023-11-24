# 从一个消费慢的例子深入理解 kafka rebalance

消息队列是服务端必不可少的组件，其中 Kafka 可以说是数一数二的选择，对于大部分服务端的同学来说 Kafka 也是最熟悉的消息中间件之一。而当我们在生产上遇到 kafka 的使用问题时想要透过现象看到问题的本质，从而找到解决问题的办法。这就要求对 kafka 的设计和实现有这较为深刻的认识。在这篇文章里我们就以生产实际的例子来展开讨论 Kafka 在消费端中的一个重要设计 consumer group 的 rebalance。只有理解了 rebalance 我们才能对消息消费过程有着更全面的掌握。     
某一天我们收到消费端消费严重落后生产的告警。第一时间相关同学去看了 consumer group 的消费曲线监控，消费速率明显出现异常。下面这张示意图展示了这种情况。

![consume-abnormal](https://pics.lxkaka.wang/cosume%E5%AF%B9%E6%AF%94.png)
我们能清楚的看到整个消费组在消费异常的时间段内经常出现消费停滞的情况如图上消费速率为 0。为什么消费会卡主呢？同事去看了相关服务的日志看到很多 `err kafka data maybe rebalancing`。看了这篇文章后消费卡主的问题自然就知道答案了。  

### 重要概念
为了说清楚 rebalance 有必要把最相关的重要概念回顾一下    
#### Consumer Group  
consumer group 是 kafka 提供的可扩展且具有容错性的消费者机制。既然是一个组，那么组内必然可以有多个消费者或消费者实例(consumer instance)，它们共享一个公共的 ID，即 group ID。组内的所有消费者协调在一起来消费 topic 下的所有分区。总结一下就是以下几个关键点。  
* consumer group 下可以有一个或多个 consumer instance，consumer instance可以是一个进程，也可以是一个线程  
* group.id 是一个字符串，唯一标识一个 consumer group  
* consumer group 订阅的 topic 下的每个分区只能分配给某个 group 下的一个 consumer (当然该分区还可以被分配给其他 group)  

![consumer-group](https://pics.lxkaka.wang/cosumer-group.jpeg)


#### Coordinator
Group Coordinator 是一个服务，每个 Broker 在启动的时候都会启动一个该服务。Group Coordinator 的作用是用来存储 Group 的相关 Meta 信息，并将对应 Partition 的 Offset 信息记录到 Kafka 内置 Topic(__consumer_offsets)中。  

每个 Group 都会选择一个 Coordinator 来完成自己组内各 Partition 的 Offset 信息，选择的规则如下：

1，计算 Group 对应在__consumer_offsets 上的 Partition  
2，根据对应的 Partition 寻找该 Partition 的 leader 所对应的 Broker，该 Broker 上的 Group Coordinator 即就是该 Group 的 Coordinator   
Partition 计算规则  
`partition-Id(__consumer_offsets) = Math.abs(groupId.hashCode() % groupMetadataTopicPartitionCount)`  
其中groupMetadataTopicPartitionCount对应offsets.topic.num.partitions参数值，默认值是50个分区  

### Rebalance 目的  
我们知道 topic 的 partition 已经根据策略分配给了 consumer group 下的各个 consumer。那么当有新的 consumer 加入或者老的 consumer 离开这个 partition 与 consumer 的分配关系就会发生变化，如果这个时候不进行重新调配，就可能出现新 consumer 无 partition 消费或者有 partition 无消费者的情况。那么这个重新调配指的就是 consumer 和 partition 的 rebalance。    
consumer默认提供了2种分配策略：    

range 策略：将单个 topic 的分区按顺序排列，然后把这些分区划分成固定大小的分区段并依次分配给每个 consumer。      
round-robin：把 topi c的所有分区按顺序排开，以轮询的方式配给每个 consumer。  
下面给一个简单的例子，假设目前某个 consumer group A 有 2个 consumer C1 和 C2，当 C3 加入时，触发了 rebalance 条件，coordinator 会进行 rebalance，根据range 策略重新分配了 partition。  

![rebalance-example](https://pics.lxkaka.wang/rebalance-example.jpeg) 

### Rebalance 时机  
Rebalance 在以下情况会触发    
* consume group 中的成员个数发生变化。例如有新的 consumer 实例加入该消费组或者离开组
* 订阅 Topic 的分区数发生变化
* 取消订阅 Topic 或新增订阅 Topic

### Rebalance 过程    
kafka 中的重要设计也会随着版本的升级而优化。rebalance 也不例外，这里我们介绍的 kafka rebalance 流程以我们的线上版本 `1.1.1` 为例。  
1. 当前 consumer 准备加入 consumer group 或 GroupCoordinator 发生故障转移时，consumer 并不知道 GroupCoordinator 的 host 和 port，所以 consumer 会向 Kafka 集群中的任一 broker 节点发送 `FindCoordinatorRequest` 请求，收到请求的 broker 节点会返回 `ConsumerMetadataResponse` 响应，其中就包含了负责管理该 Consumer Group 的 GroupCoordinator 的地址  
2. 当 consumer 通过 `FindCoordinatorRequest` 查找到其 Consumer Group 对应的 GroupCoordinator 之后，就会进入 Join Group 阶段  
3. Consumer 先向 GroupCoordinator 发送 `JoinGroupRequest` 请求，其中包含 consumer 的相关信息
4. GroupCoordinator 收到 `JoinGroupRequest` 后会暂存该 consumer 信息，然后等待全部 consumer 的 `JoinGroupRequest` 请求。`JoinGroupRequest` 中的 session.timeout.ms 和 rebalance_timeout_ms（ max.poll.interval.ms）决定了 consumer 如果没有响应过多久会被踢出出组

	![joinggroup](https://pics.lxkaka.wang/rebalance-joingroup.jpeg)
5. GroupCoordinator 会根据全部 consumer 的 `JoinGroupRequest` 请求来确定 Consumer Group 中可用的 consumer，从中选取一个 consumer 成为 Group Leader，同时还会决定 partition 分配策略，最后会将这些信息封装成 `JoinGroupResponse` 返回给 Group Leader Consumer
6. 每个 consumer 都会收到 `JoinGroupResponse` 响应，但是只有 Group Leader 收到的 `JoinGroupResponse` 响应中封装的所有 consumer 信息以及 Group Leader 信息。当其中一个 consumer 确定了自己的 Group Leader后，会根据 consumer 信息、kafka 集群元数据以及 partition 分配策略计算 partition 的分片结果。其他非 Group Leader consumer 收到 JoinResponse 为空响应，也就不会进行任何操作，只是原地等待 

	![joinres](https://pics.lxkaka.wang/rebalance-joinres.jpeg)
7. 接下来，所有 consumer 进入 Synchronizing Group State 阶段，所有 consumer 会向 GroupCoordinator 发送 `SyncGroupRequest`。其中，Group Leader Consumer 的 `SyncGroupRequest` 请求包含了 partition 分配结果，普通 consumer 的 `SyncGroupRequest` 为空请求

	![syncgroup](https://pics.lxkaka.wang/rebalance-syncgroup.jpeg)
8. GroupCoordinator 接下来会将 partition 分配结果封装成 `SyncGroupResponse` 返回给所有 consumer, consumer 收到 `SyncGroupResponse` 后进行解析，就可以明确 partition 与 consumer 的映射关系

	![syncgroupres](https://pics.lxkaka.wang/rebalance-syncgroupres.jpeg) 
9. 后续 consumer 还是会与 GroupCoordinator 保持定期的心跳(heartbeat.interval.ms)。当 rebalance 正在进行中 coordinator 会通过 hearbeat response 告诉 consumers 是否要 rejoin group 触发。即心跳响应中包含 IllegalGeneration 异常

	![heartbeat](https://pics.lxkaka.wang/rebalance-heartbeat.jpeg)

### Rebalance 问题    
在整个 rebalance 的过程中，所有 partition 都会被回收，consumer 是无法消费任何 partition 的。Join 阶段会等待原先组内存活的成员发送 `JoinGroupRequest` 过来，如果原先组内的成员因为业务处理一直没有发送请求过来，服务端就会一直等待，直到超时。这个超时时间就是 max.poll.interval.ms 的值，默认是5分钟，因此这种情况下 rebalance 的耗时就会长达5分钟，导致所有消费者都无法进行正常消费，这对生产来说是个很大的问题。  

### Rebalance 改进
#### Static Membership  
为了减少因为 consumer 短暂不可用造成的 rebalance，kafka 在 2.3 版本中引入了 Static Membership。  
Static Membership 优化的核心是：

* 在 consumer 端增加 group.instance.id 配置（group.instance.id 是 consumer 的唯一标识）。如果 consumer 启动的时候明确指定了 group.instance.id 配置值，consumer 会在 JoinGroup Request 中携带该值，表示该 consumer 为 static member。 为了保证 group.instance.id 的唯一性，我们可以考虑使用 hostname、ip 等。
* 在 GroupCoordinator 端会记录 group.instance.id → member.id 的映射关系，以及已有的 partition 分配关系。当 GroupCoordinator 收到已知 group.instance.id 的 consumer 的 JoinGroup Request 时，不会进行 rebalance，而是将其原来对应的 partition 分配给它。
Static Membership 可以让 consumer group 只在下面的 4 种情况下进行 rebalance：    
	* 有新 consumer 加入 consumer group 
	* Group Leader 重新加入 Group 时
	* consumer 下线时间超过阈值（session.timeout.ms）
	* GroupCoordinator 收到 static member 的 LeaveGroup Request 

这样的话，在使用 Static Membership 场景下，只要在 consumer 重新启动的时候，不发送 LeaveGroup Request 且在 session.timeout.ms 时长内重启成功，就不会触发 rebalance。所以，这里推荐设置一个足够 consumer 重启的时长 session.timeout.ms，这样能有效降低因 consumer 短暂不可用导致的 reblance 次数。 

#### Incremental Cooperative Rebalancing
从名字中我们就能看出这个版本的 rebalance 过程两个关键词**增量和协作**，增量指的是原先版本的 rebalance 被分解成了多次小规模的 rebalance, 协作自然指的是 consumer 之间的关系。
核心思想： 
* consumer 比较新旧两个 partition 分配结果，只停止消费回收（revoke）的 partition，对于两次都分配给自己的 partition，consumer 不需要停止消费
* 通过多轮的局部 rebalance 来最终实现全局的 rebalance  
我们以文章开始的例子来理解一下这个版本的改进  
首先 C1 -> {P0, p3} C2 -> {P1} C3 -> {P2} 这是 consumer 和 partition 的分配关系，我们假设 C2 宕机超过了 `session.timeout.ms`, 此时 GroupCoordinator 会触发第一轮 rebalance  
##### 第一轮 Rebalance 
1. GroupCoordinator 会在下一轮心跳响应中通知 C1 和 C3 发起第一轮 rebalance 
2. C1 和 C3 会将自己当前正在处理的 partition 信息封装到 `JoinGroupRequest` 中（metadata 字段）发往 GroupCoordinator：
	* C1 发送的 `JoinGroupRequest`（assigned: P0、P3)
	* C3 发送的 `JoinGroupRequest`（assigned: P2）
3. 假设 GroupCoordinator 在这里选择 1 作为 Group Leader，GroupCoordinator 会将 partition 目前的分配状态通过 JoinGroupResponse 发送给 C1
4. C1 发现 P1 并未出现（处于 lost 状态），此时 C1 并不会立即解决当前的不平衡问题，返回的 partition 分配结果不变（同时会携带一个 delay 时间，`scheduled.rebalance.max.delay.ms`，默认 5 分钟）。GroupCoordinator 会根据 C1 的 `SyncGroupRequest`，生成 `SyncGroupResponse` 返回给两个存活的 consumer 
	* C1 收到的 SyncGroup Response（delay，assigned: P0、P3，revoked：）  
	* C3 收到的 SyncGroup Response（delay，assigned: P2，revoked：）    

到此为止，第一轮 rebalance 结束。整个 rebalance 过程中，C1 和 C3 并不会停止消费。
 
##### 第二轮 Rebalance
1. 在 `scheduled.rebalance.max.delay.ms` 这个时间段内，C2 故障恢复，重新加入到 consumer group 时，会向 GroupCoordinator 发送 JoinGroup Request，触发第二轮的 rebalance。GroupCoordinator 在下一次心跳响应中会通知 C1 和 C3 参与第二轮 rebalance
2. C1 和 C3 在收到心跳之后，会发送 `JoinGroupRequest` 参与第二轮 rebalance： 
	* C1 发送的 `JoinGroupRequest`（assigned: P0、P3）
	* C3 发送的 `JoinGroupRequest`（assigned: P2) 
3. 在第二轮 rebalance 中，C1 依旧被选为 Group Leader，它会检查 delay 的时间（scheduled.rebalance.max.delay.ms）是否已经到了，如果没到，则依旧不会立即解决当前的不平衡问题，继续返回目前的分配结果，并且返回的 `SyncGroupResponse` 中更新了 delay 的剩余时间（remaining delay = delay - pass_time) 到此为止，第二轮 rebalance 结束。整个 rebalance 过程中，C1 和 C3 并不会停止消费。
	* C1 收到的 SyncGroup Response（remaining delay，assigned: P0、P3，revoked：）
	* C2 收到的 SyncGroup Response（remaining delay，assigned:，revoked：）
	* C3 收到的 SyncGroup Response（remaining delay，assigned: P2，revoked：） 
##### 第三轮 Rebalance
1. 当 remaining delay 时间到期之后，consumer 全部重新送 `JoinGroupRequest`，触发第三轮 rebalance  
	* C1 发送的 `JoinGroupRequest`（assigned: P0、P3）
	* C2 发送的 `JoinGroupRequest`（assigned: ）
	* C3 发送的 `JoinGroupRequest`（assigned: P2
2. 在此次 rebalance 中，C1 依旧被选为 Group Leader，它会发现 delay 已经到期了，开始解决不平衡的问题，对 partition 进行重新分配。最新的分配结果最终通过 `SyncGroupResponse` 返回到各个 consumer：   
  到此为止，第三轮 rebalance 结束。整个 rebalance 过程中，C1 和 C3 的消费都不会停止  
	* C1 收到的 SyncGroup Response（assigned：P0、P3，revoked：）
	* C2 收到的 SyncGroup Response（assigned：P1，revoked：）
	* C3 收到的 SyncGroup Response（assigned：P2，revoked：）

下面这张图展示了上述的 Rebalance 过程  
![incremental](https://pics.lxkaka.wang/rebalance-incremental.png)

通过上述我们应该对 Kafka 的 Rebalance 有了比较完整的认识。我们现在来回答文章开始提出的消费卡主问题：消费端拿到了异常的消息，这样的消息业务上处理时间过超过了 `max.poll.interval.ms`, 从而触发了 rebalance, 在 rebalance 过程中所有消费者都暂停了消费。   
为了解决这个问题我们首先优化业务逻辑尽可能提高处理消息速度，对异常消息做特殊处理；然后合理的设置 `max.poll.interval.ms` cover 住业务的处理时间。   
为了尽可能减少 Rebalance 次数我们也要注意设置 `session.timeout.ms` 和 `heartbeat.interval.ms` 的值。一种推荐的方案 `session.timeout.ms` >= 3 * `heartbeat.interval.ms`, 比如 session.timeout.ms = 6s; heartbeat.interval.ms = 2s。这样 consumer 如果宕机且 6s 之内未恢复， Coordinator 能够较快地定位已经挂掉的 consumer，把它踢出 Group。  
