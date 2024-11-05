# Mongodb 高可用方案及副本集搭建


如果业务场景不需要强力的事务支持及复杂的join, 数据模型变化频繁，数据需要落地，查询 QPS 超过200。 那么 Mongodb 作为数据库非常合适。
在我们的业务中我们就选用了 mongo 来存储账单，菜单，交易信息等数据。随着 mongodb 在我们的业务场景中应用的地方越来越广，mongo 必须是高可用的。
这里主要介绍一下 Mongodb 高可用方案以及其中的 replicaset(副本集)方案在生产上的搭建。

## 高可用方案

### Master-Slave 主从架构
主从架构一般用于备份或者做读写分离。一般有一主一从设计和一主多从设计。
![master-slave](https://pics.lxkaka.wang/master-slave.png)

由两种角色构成：

* 主(Master)
可读可写，当数据有修改的时候，会将oplog同步到所有连接的salve上去。

* 从(Slave)
只读不可写，自动从Master同步数据。
特别的，对于 Mongodb 来说，并不推荐使用 Master-Slave 架构，因为 Master-Slave 其中 Master 宕机后不能自动恢复
在主从结构中，主节点的操作记录成为 oplog（operation log), oplog 存储在一个系统数据库local的集合oplog.$main中，这个集合的每个文档都代表主节点上执行的一个操作。   
从服务器会定期从主服务器中获取 oplog 记录，然后在本机上执行。对于存储 oplog 的集合，MongoDB采用的是固定集合，也就是说随着操作过多，新的操作会覆盖旧的操作。

### ReplicaSet(副本集)
Mongodb的 ReplicaSet 即副本集方式主要有两个目的，一个是数据冗余做故障恢复使用，当发生硬件故障或者其它原因造成的宕机时，可以使用副本进行恢复。
另一个是做读写分离，读的请求分流到副本上，减轻主（Primary）的读压力。
![replica-set](https://pics.lxkaka.wang/replica-set-primary-with-two-secondaries.bakedsvg.svg)
Replica Set是mongod的实例集合，它们有着同样的数据内容。包含三类角色：

* 主节点（Primary）
接收所有的写请求，然后把修改同步到所有Secondary。一个Replica Set只能有一个Primary节点，当Primary挂掉后，其他Secondary或者Arbiter节点会重新选举出来一个主节点。
默认读请求也是发到 Primary 节点处理的，需要转发到 Secondary 需要客户端修改一下连接配置。

* 副本节点（Secondary）
副本节点同样使用 oplog 进行数据同步来与主节点保持同样的数据集。当主节点挂掉的时候，副本节点参与选主。

* 仲裁者（Arbiter）
不保有数据，不参与选主，只进行选主投票。使用Arbiter可以减轻数据存储的硬件需求，Arbiter跑起来几乎没什么大的硬件资源需求，但重要的一点是，在生产环境下它和其他数据节点不要部署在同一台机器上。
注意，一个自动failover的 ReplicaSet 节点数必须为奇数，目的是选主投票的时候要有一个大多数才能进行选主决策。

![rs-arbiter](https://pics.lxkaka.wang/replica-set-primary-with-secondary-and-arbiter.bakedsvg.svg)

#### 自动故障转移
![failover](https://pics.lxkaka.wang/replica-set-trigger-election.bakedsvg.svg)  
当主节点与其他节点通信失联的时间超过选举超时时间（默认是10s）, 副本节点会提名自己成为主节点候选者。然后完成选主，集群则完成故障转移。
在故障转移过程中，写操作失败，副本节点仍然能正常的完成读操作。

### Sharding(分片)
当数据量比较大的时候，我们需要把数据分片运行在不同的机器中，以降低CPU、内存和IO的压力，Sharding就是数据库分片。
MongodB 分片技术类似MySQL的水平切分和垂直切分，数据库主要由两种方式做 Sharding：垂直扩展和横向切分。  
* 垂直扩展的方式就是进行集群扩展，添加更多的CPU，内存，磁盘空间等。  
* 横向切分则是通过数据分片的方式，通过集群统一提供服务  

Mongodb sharded cluster 架构图如下
![shard-cluster](https://pics.lxkaka.wang/sharded-cluster-production-architecture.bakedsvg.svg)  
Mongodb sharded cluster中的组件包含以下三大部分：
* shards
用来保存数据，保证数据的高可用性和一致性。可以是一个单独的mongod实例，也可以是一个副本集。
在生产环境下Shard一般是一个Replica Set，以防止该数据片的单点故障。

* mongos
mongos承担客户端请求路由的作用。客户端直接连接mongos，由mongos把读写请求路由到指定的Shard上去。
一个Sharding集群，可以有一个mongos，也可以有多mongos以减轻客户端请求的压力。

* config server
保存集群的元数据（metadata），包含各个Shard的路由规则。
下面这张图是我对 Mongodb 分片架构重点的总结  
![draw](https://pics.lxkaka.wang/draw.jpeg)  

## ReplicaSet 搭建
这里我们根据自己的业务场景和数据量我们选取的 mongo 高可用架构是 **包含arbiter的三节点副本集**。
搭建环境是 Ubuntu, Mongodb 版本是4.0
* 配置国内的 deb 源  
``echo "deb [ arch=amd64,arm64 ] http://mirrors.aliyun.com/mongodb/apt/ubuntu xenial/mongodb-org/4.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-4.0.list``
* 安装 mongo 4.0
    ```
    sudo apt-get update
    sudo apt-get install -y mongodb-org=4.0.0 mongodb-org-server=4.0.0 mongodb-org-shell=4.0.0 mongodb-org-mongos=4.0.0 mongodb-org-tools=4.0.0 --allow-unauthenticated
    ```
* 修改配置  /etc/mongod.conf
    ```
    # mongod.conf

    # for documentation of all options, see:
    #   http://docs.mongodb.org/manual/reference/configuration-options/

    # Where and how to store data.
    storage:
    dbPath: /var/lib/mongodb
    # 重点，arbiter节点置为 false, 主副节点置为 true
    journal:
        enabled: false
    #  engine:
    #  mmapv1:
    #  wiredTiger:

    # where to write logging data.
    systemLog:
    destination: file
    logAppend: true
    path: /var/log/mongodb/mongod.log

    # network interfaces
    net:
    port: 27017
    bindIp: 0.0.0.0

    # 重点，副本集的名字
    replication:
    replSetName: waimai_rs

    #processManagement:

    security:
    authorization: enabled
    keyFile: /home/zaihui/keys/mongodb/mongodb-keyfile
    ```

* 启动 mongo 实例  
 `sudo service mongod start`  
  如果 monod.service not found 使用 `sudo systemctl unmask mongodb`

* 重复上面的步骤，启动三个实例

* 初始化副本集  
  进入  mongo shell
    ```
    rs.initiate({_id:"waimai_rs",members:[
    {_id:0,host:"172.31.41.20:27017",priority:1},
    {_id:1,host:"172.31.48.196:27017",priority:0.5},
    {_id:2, host:"172.31.48.227:27017",arbiterOnly:true}
    ]})
    ```
    在这里，我们把 priority 设置的不一样是为了指明主节点为 priority 最高的那个。

* 检查副本集配置  
`rs.conf()`  
看到如下配置  
    ```
    {
        "_id" : "waimai_rs",
        "version" : 1,
        "protocolVersion" : NumberLong(1),
        "writeConcernMajorityJournalDefault" : true,
        "members" : [
            {
                "_id" : 0,
                "host" : "172.31.41.20:27017",
                "arbiterOnly" : false,
                "buildIndexes" : true,
                "hidden" : false,
                "priority" : 1,
                "tags" : {

                },
                "slaveDelay" : NumberLong(0),
                "votes" : 1
            },
        ....
    ```
* 查看副本集状态  
`rs.status()`  
看到如下输出，检查各个节点是否正常  
    ```
    "members" : [
            {
                "_id" : 0,
                "name" : "172.31.41.20:27017",
                "health" : 1,
                "state" : 1,
                "stateStr" : "PRIMARY",
                "uptime" : 1215722,
                "optime" : {
                    "ts" : Timestamp(1537330095, 1),
                    "t" : NumberLong(2)
                },
                "optimeDurable" : {
                    "ts" : Timestamp(1537330095, 1),
                    "t" : NumberLong(2)
                },
                "optimeDate" : ISODate("2018-09-19T04:08:15Z"),
                "optimeDurableDate" : ISODate("2018-09-19T04:08:15Z"),
                "lastHeartbeat" : ISODate("2018-09-19T04:08:19.593Z"),
                "lastHeartbeatRecv" : ISODate("2018-09-19T04:08:18.644Z"),
                "pingMs" : NumberLong(1),
                "lastHeartbeatMessage" : "",
                "syncingTo" : "",
                "syncSourceHost" : "",
                "syncSourceId" : -1,
                "infoMessage" : "",
                "electionTime" : Timestamp(1536114379, 1),
                "electionDate" : ISODate("2018-09-05T02:26:19Z"),
                "configVersion" : 1
            },
        ...
    ```

* 验证  
主从服务器数据是否同步，从服务器没有读写权限  
   * 向主节点写入数据 ok 后台自动同步到副本节点，副本节点有数据  
   * 向副本节点写入数据 false 副本节点不能写
   * 主节点读取数据 ok
   * 副本节点读取数据 false 副本节点不能读  
   * 配置副本节点可读  
   * 副本节点读取数据 ok 
 
注意，遇到问题时要仔细查看日志信息，能帮助我们快速定位问题。 

