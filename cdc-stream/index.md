# 实时数据入湖的选型和实践

Hudi 作为最热的数据湖技术框架之一，用于构建具有增量数据处理管道的流式数据湖。其核心的能力包括对象存储上数据行级别的快速更新和删除，增量查询 (Incremental queries,Time Travel)，小文件管理和查询优化 (Clustering,Compactions,Built-in metadata)，ACID 和并发写支持。Hudi 不是一个 Server，它本身不存储数据，也不是计算引擎，不提供计算能力。其数据存储在 S3(也支持其它对象存储和 HDFS)，Hudi 来决定数据以什么格式存储在 S3(Parquet,Avro,…), 什么方式组织数据能让实时摄入的同时支持更新，删除，ACID 等特性。Hudi 通过 Spark，Flink 计算引擎提供数据写入，计算能力，同时也提供与 OLAP 引擎集成的能力，使 OLAP 引擎能够查询 Hudi 表。从使用上看 Hudi 就是一个 JAR 包，启动 Spark, Flink 作业的时候带上这个 JAR 包即可。Amazon EMR 上的 Spark，Flink，Presto，Trino 原生集成 Hudi, 且 EMR 的 Runtime 在 Spark，Presto 引擎上相比开源有 2 倍以上的性能提升。在多库多表的场景下 (比如：百级别库表)，当我们需要将数据库 (mysql,postgres,sqlserver,oracle,mongodb 等) 中的数据通过 CDC 的方式以分钟级别 (1minute+) 延迟写入 Hudi，并以增量查询的方式构建数仓层次，对数据进行实时高效的查询分析时。我们要解决三个问题： 

 一. 如何使用统一的代码完成百级别库表 CDC 数据并行写入 Hudi，降低开发维护成本。      
 二.  源端 Schema 变更如何同步到 Hudi 表。      
 三. 使用 Hudi 增量查询构建数仓层次比如 ODS->DWD->DWS(各层均是 Hudi 表)，DWS 层的增量聚合如何实现。    

 这篇文章里我们的选型方案是：使用 Flink CDC DataStream API(非 SQL) 先将 CDC 数据写入 Kafka，而不是直接通过 Flink SQL 写入到 Hudi 表，主要原因如下   
 第一，在多库表且 Schema 不同的场景下，使用 SQL 的方式会在源端建立多个 CDC 同步线程，对源端造成压力，影响同步性能。   
 第二，没有 kafka 做 CDC 数据上下游的解耦和数据缓冲层，下游的多端消费和数据回溯比较困难。  
 CDC 数据写入到 kafka 后，推荐使用 Spark Structured Streaming DataFrame API 或者 Flink StatementSet 封装多库表的写入逻辑，但如果需要源端 Schema 变更自动同步到 Hudi 表，使用 Spark Structured Streaming DataFrame API 实现更为简单，使用 Flink 则需要基于 `HoodieFlinkStreamer` 做额外的开发。Hudi 增量 ETL 在 DWS 层需要数据聚合的场景的下，可以通过 Flink Streaming Read 将 Hudi 作为一个无界流，通过 Flink 计算引擎完成数据实时聚合计算写入到 Hudi 表。  

 ### 架构设计和方案
 
 ![cdc-hudi](https://pics.lxkaka.wang/emr-cdc-hudi-arch.png)

#### CDC 数据实时写入 kafka
图中标号 1, 2 是将数据库中的数据通过 CDC 方式实时发送到 kafka。[flink-cdc-connectors](https://github.com/ververica/flink-cdc-connectors) 是当前比较流行的 CDC 开源工具。它内嵌 debezium 引擎，支持多种数据源，对于 MySQL 支持 Batch 阶段 (全量同步阶段) 并行，无锁，Checkpoint(可以从失败位置恢复，无需重新读取，对大表友好)。支持 Flink SQL API 和 DataStream API，这里需要注意的是如果使用 SQL API 对于库中的每张表都会单独创建一个链接，独立的线程去执行 binlog dump。如果需要同步的表比较多，会对源端产生较大的压力。在需要整库同步表非常多的场景下，应该使用 DataStream API 写代码的方式只建一个 binlog dump 同步所有需要的库表。另一种场景是如果只同步分库分表的数据，比如 user 表做了分库，分表，其表 Schema 都是一样的，Flink CDC 的 SQL API 支持正则匹配多个库表，这时使用 SQL API 同步依然只会建立一个 binlog dump 线程。需要说明的是通过 Flink CDC 可以直接将数据 Sink 到 Hudi, 中间无需 kaffka，但考虑到上下游的解耦，数据的回溯，多业务端消费，多表管理维护，依然建议 CDC 数据先到 kafka，下游再从 kafka 消费写入 Hudi。

#### Spark Structured Streaming 多库表并行写 Hudi 及 Schema 变更
图中标号 4，CDC 数据到了 kafka 之后，可以通过 Spark/Flink 计算引擎消费数据写入到 Hudi 表，我们把这一层我们称之为 ODS 层。无论 Spark 还是 Flink 都可以做到数据 ODS 层的数据落地，使用哪一个我们需要综合考量，这里阐述一些相对重要的点。首先对于 Spark 引擎，我们一定是使用 Spark Structured Streaming 消费 kafka 写入 Hudi，由于可以使用 DataFrame API 写 Hudi, 因此在 Spark 中可以方便的实现消费 CDC Topic 并根据其每条数据中的元信息字段 (数据库名称，表名称等) 在单作业内分流写入不同的 Hudi 表，封装多表并行写入逻辑，一个 Job 即可实现整库多表同步的逻辑。  

CDC 数据中是带着 I(insert)、U(update)、D(delete) 信息的，不同的 CDC 工具数据格式不同，但要表达的含义是一致的。使用 Spark 写入 Hudi 我们主要关注 U、D 信息，数据带着 `U` 信息表示该条数据是一个更新操作，对于 Hudi 而言只要设定源表的主键为 Hudi 的 `recordKey`，同时根据需求场景设定 `precombineKey` 即可。这里对 precombineKey 做一个说明，它表示的是当数据需要更新时 (recordKey 相同), 默认选择两条数据中 precombineKey 的大保留在 Hudi 中。其实 Hudi 有非常灵活的 Payload 机制，通过参数 `hoodie.datasource.write.payload.class` 可以选择不同的 Payload 实现，比如 Partial Update(部分字段更新) 的 Payload 实现 `OverwriteNonDefaultsWithLatestAvroPayload`，也可以自定义 Payload 实现类，它核心要做的就是如何根据 precombineKey 指定的字段更新数据。所以对于 CDC 数据 Sink Hudi 而言，我们需要保证上游的消息顺序，只要我们表中有能判断哪条数据是最新的数据的字段即可，那这个字段在 MySQL 中往往我们设计成数据更新时间 `modify_time timestamp DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP`。如果没有类似字段，建议定义设计规范加上这个字段，否则就必须保证数据有序 (这会给架构设计和性能带来更多的阻力)，不然数据在 Hudi 中 Updata 的结果可能就是错的。对于带着 `D` 信息的数据，它表示这条数据在源端被删除，Hudi 是提供删除能力的，其中一种方式是当一条数据中包含 `_hoodie_is_deleted` 字段，且值为 true 是，Hudi 会自动删除此条数据，这在 Spark Structured Streaming 代码中很容易实现，只需在 map 操作实现添加一个字段且当数据中包含 `D` 信息设定字段值为 true 即可。

#### Flink StatementSet 多库表 CDC 并行写 Hudi
对于使用 Flink 引擎消费 kafka 中的 CDC 数据落地到 ODS 层 Hudi 表，如果想要在一个 JOB 实现整库多张表的同步，Flink StatementSet 来实现通过一个 Kafka 的 CDC Source 表，根据元信息选择库表 Sink 到 Hudi 中。但这里需要注意的是由于 Flink 和 Hudi 集成，是以 SQL 方式先创建表，再执行 Insert 语句写入到该表中的，如果需要同步的表有上百之多，封装一个自动化的逻辑能够减轻我们的工作，你会发现 SQL 方式写入 Hudi 虽然对于单表写入使用上很方便，不用编程只需要写 SQL 即可，但也带来了一些限制，由于写入 Hudi 时是通过 SQL 先建表，Schema 在建表时已将定义，如果源端 Schema 变更，通过 SQL 方式是很难实现下游 Hudi 表 Schema 的自动变更的。虽然在 Hudi 的官网并未提供 Flink DataStream API 写入 Hudi 的例子，但 Flink 写入 Hudi 是可以通过 `HoodieFlinkStreamer` 以 DataStream API 的方式实现，在 Hudi 源码中可以找到。因此如果想要更加灵活简单的实现多表的同步，以及 Schema 的自动变更，需要自行参照 `HoodieFlinkStreamer` 代码以 DataStream API 的方式写 Hudi。对于 I,U,D 信息，Flink 的 debezium ,maxwell,canal format 会直接将消息解析 为 Flink 的 changelog 流，换句话说就是 Flink 会将 I,U,D 操作直接解析成 Flink 内部的数据结构 RowData，直接 Sink 到 Hudi 表即可，我们同样需要在 SQL 中设定 recordKey，precombineKey，也可以设定 Payload class 的不同实现类。

#### Flink Streaming Read 模式读 Hudi 实现 ODS 层聚合
图中标号 5，数据通过 Spark/Flink 落地到 ODS 层后，我们可能需要构建 DWD 和 DWS 层对数据做进一步的加工处理，（DWD 和 DWS 并非必须的，根据你的场景而定，你可以直接让 OLAP 引擎查询 ODS 层的 Hudi 表）我们希望能够使用到 Hudi 的增量查询能力，只查询变更的数据来做后续 DWD 和 DWS 的 ETL，这样能够加速构建同时减少资源消耗。对于 Spark 引擎，在 DWD 层如果仅仅是对数据做 map,fliter 等相关类型操作，是可以使用增量查询的，但如果 DWD 层的构建有 Join 操作，是无法通过增量查询实现的，只能全表 (或者分区) 扫描。DWS 层的构建如果聚合类型的操作没有去重，窗口类型的操作，只是 SUM, AVG，MIN, MAX 等类型的操作，可以通过增量查询之后和目标表做 Merge 实现，反之，只能全表 (或者分区) 扫描。对于 Flink 引擎来构建 DWD 和 DWS, 由于 Flink 支持 Hudi 表的 streaming read, 在 SQL 设定 `read.streaming.enabled=true`,`changelog.enabled=true` 等相关流式读取的参数即可。设定后 Flink 把 Hudi 表当做了一个无界的 changelog 流表，无论怎样做 ETL 都是支持的，Flink 会自身存储状态信息，整个 ETL 的链路是流式的。

#### OLAP 引擎查询 Hudi 表
图中标号 6, EMR Hive/Presto/Trino 都可以查询 Hudi 表，但需要注意的是不同引擎对于查询的支持是不同的，参见官网，这些引擎对于 Hudi 表只能查询，不能写入。关于 Schema 的自动变更，首先 Hudi 自身是支持 Schema Evolution，我们想要做到源端 Schema 变更自动同步到 Hudi 表，通过上文的描述，可以知道如果使用 Spark 引擎，可以通过 DataFrame API 操作数据，通过 from_json 动态生成 DataFrame，因此可以较为方便的实现自动添加列。如果使用 Flink 引擎上文已经说明想要自动实现 Schema 的变更，通过 `HoodieFlinkStreamer` 以 DataStream API 的方式实现 Hudi 写入的同时融入 Schema 变更的逻辑。

上述我们介绍了实时数据入湖的各个阶段以及各阶段采用的方案以及背后的原因。下面我们以一个实际的例子来实践上述方案。

### 方案实践
实践中选择 RDS MySQL 作为数据源，Flink CDC DataStream API 同步库中的所有表到 Kafka，使用 Spark 引擎消费 Kafka 中 binlog 数据实现多表写入 ODS 层 Hudi，使用 Flink 引擎以 streaming read 的模式做 DWD 和 DWS 层的 Hudi 表构建。
#### 环境信息
```
EMR 6.9.0 
Hudi 0.12.1
Spark 3.3.0 
Flink 1.15.2  
MySQL 8.0.22
```

####  创建源表
在 MySQL 中创建 test_db 库及 user,product,user_order 三张表，插入样例数据，后续 CDC 先加载表中已有的数据，之后源添加新数据并修改表结构添加新字段，验证 Schema 变更自动同步到 Hudi 表。
```sql
-- create databases
create database if not exists test_db default character set utf8mb4 collate utf8mb4_general_ci;
use test_db;

-- create  user table
drop table if exists user;
create table if not exists user
(
    id           int auto_increment primary key,
    name         varchar(155)                        null,
    device_model varchar(155)                        null,
    email        varchar(50)                         null,
    phone        varchar(50)                         null,
    create_time  timestamp default CURRENT_TIMESTAMP not null,
    modify_time  timestamp default CURRENT_TIMESTAMP null on update CURRENT_TIMESTAMP
)charset = utf8mb4;

-- insert data
insert into user(name,device_model,email,phone) values
('customer-01','dm-01','abc01@email.com','188776xxxxx'),
('customer-02','dm-02','abc02@email.com','166776xxxxx');

-- create product table
drop table if exists product;
create table if not exists product
(
    pid          int not null primary key,
    pname        varchar(155)                        null,
    pprice       decimal(10,2)                           ,
    create_time  timestamp default CURRENT_TIMESTAMP not null,
    modify_time  timestamp default CURRENT_TIMESTAMP null on update CURRENT_TIMESTAMP
)charset = utf8mb4;

-- insert data
insert into product(pid,pname,pprice) values
('1','prodcut-001',125.12),
('2','prodcut-002',225.31);

-- create order table
drop table if exists user_order;
create table if not exists user_order
(
    id           int auto_increment primary key,
    oid          varchar(155)                        not null,
    uid          int                                         ,
    pid          int                                         ,
    onum         int                                         ,
    create_time  timestamp default CURRENT_TIMESTAMP not null,
    modify_time  timestamp default CURRENT_TIMESTAMP null on update CURRENT_TIMESTAMP
)charset = utf8mb4;

-- insert data
insert into user_order(oid,uid,pid,onum) values 
('o10001',1,1,100),
('o10002',1,2,30),
('o10001',2,1,22),
('o10002',2,2,16);
```

####  Flink CDC 发送数据到 Kafka
示例代码片段
```java
  def main(args: Array[String]): Unit = {

    val env = StreamExecutionEnvironment.getExecutionEnvironment
    val params = Config.parseConfig(MySQLCDC, args)
    env.enableCheckpointing(params.checkpointInterval.toInt ` 1000)
    env.getCheckpointConfig.setCheckpointingMode(CheckpointingMode.EXACTLY_ONCE)
    env.getCheckpointConfig.setMinPauseBetweenCheckpoints(500)
    env.getCheckpointConfig.setCheckpointTimeout(60000)
    env.getCheckpointConfig.enableExternalizedCheckpoints(ExternalizedCheckpointCleanup.RETAIN_ON_CANCELLATION)
    val rocksBackend: StateBackend = new RocksDBStateBackend(params.checkpointDir)
    env.setStateBackend(rocksBackend)

    env.fromSource(createCDCSource(params), WatermarkStrategy.noWatermarks(), "mysql cdc source")
      .addSink(createKafkaSink(params)).name("cdc sink kafka")
      .setParallelism(params.parallel.toInt)

    env.execute("MySQL Binlog CDC")
  }
```
打包和提交 flink 任务
```shell
# 创建topic, bs为 kafka broker地址
kafka-topics.sh --create ----bootstrap-server ${bs}  --replication-factor 2 --partitions 8  --topic cdc_topic
# 编译打包
mvn clean package  -Dscope.type=provided  -DskipTests
# disalbe check-leaked-classloader
sudo sed -i -e '$a\classloader.check-leaked-classloader: false' /etc/flink/conf/flink-conf.yaml
# 启动flink cdc 发送数据到Kafka
sudo flink run -m yarn-cluster \
-yjm 1024 -ytm 2048 -d \
-ys 4 -p 8 \
-c  com.kezaihui.MySQLCDC  \
/home/hadoop/emr-flink-cdc-1.0-SNAPSHOT.jar \
-b xxxxx.amazonaws.com:9092 \
-t cdc_topic \
-c s3://xxxxx/flink/checkpoint/ \
-l 30 -h xxxxx.rds.amazonaws.com:3306 -u admin \
-P admin123456 \
-d test_db -T test_db.` \
-p 4 \
-e 5400-5408
```
下图是在 flink dashboard 上查看到任务状态    
 ![flink-cdc-ui](https://pics.lxkaka.wang/flink-cdc.png)

#### Spark 消费 CDC 数据整库同步
示例代码片段
```java
    val ds = df.selectExpr("CAST(value AS STRING)").as[String]
    val query = ds
      .writeStream
      .queryName("debezium2hudi")
      .option("checkpointLocation", params.checkpointDir)
      // if set 0, as fast as possible
      .trigger(Trigger.ProcessingTime(params.trigger + " seconds"))
      .foreachBatch { (batchDF: Dataset[String], batchId: Long) =>
        log.warn("current batch: " + batchId.toString)
        val pool = Executors.newFixedThreadPool(50)
        implicit val xc: ExecutionContextExecutor = ExecutionContext.fromExecutor(pool)

        val newsDF = batchDF.map(cdc => DebeziumParser.apply().debezium2Hudi(cdc))
          .filter(_ != null)
        if (!newsDF.isEmpty) {
          val tasks = Seq[Future[Unit]]()
          for (tableInfo <- tableInfoList.tableInfo) {
            val insertORUpsertDF = newsDF
              .filter($"database" === tableInfo.database && $"table" === tableInfo.table)
              .filter($"operationType" === HudiOP.UPSERT || $"operationType" === HudiOP.INSERT)
              .select($"data".as("jsonData"))
            if (!insertORUpsertDF.isEmpty) {
              val json_schema = ss.read.json(insertORUpsertDF.select("jsonData").as[String]).schema
              val cdcDF = insertORUpsertDF.select(from_json($"jsonData", json_schema).as("cdc_data"))
              val cdcPartitionDF = cdcDF.select($"cdc_data.`")
                .withColumn(tableInfo.hudiPartitionField, sqlPartitionFunc(col(tableInfo.partitionTimeColumn)))
              params.concurrent match {
                case "true" => {
                  val runTask = HudiWriteTask.run(cdcPartitionDF, params, tableInfo)(xc)
                  tasks :+ runTask
                }
                case _ => HudiWriteTask.runSerial(cdcPartitionDF, params, tableInfo)
              }
            }
          }
          if (params.concurrent == "true" && tasks.nonEmpty) {
            Await.result(Future.sequence(tasks), Duration(60, MINUTES))
            pool.shutdown()
            //            ()
          }

        }
      }.start()
    query.awaitTermination()
```
打包和提交 spark 任务
```shell
# 编译打包
mvn clean package  -Dscope.type=provided  -DskipTests
# bs 为 kafka broker 地址
sudo spark-submit --master yarn \
--deploy-mode client \
--driver-memory 1g \
--executor-memory 1g \
--executor-cores 2 \
--num-executors  2 \
--conf spark.dynamicAllocation.enabled=false \
--conf spark.serializer=org.apache.spark.serializer.KryoSerializer \
--conf spark.sql.extensions=org.apache.spark.sql.hudi.HoodieSparkSessionExtension \
--conf spark.sql.parquet.binaryAsString=true \
--jars  /usr/lib/hudi/hudi-spark-bundle.jar \
--class com.kezaihui.Debezium2Hudi /home/zaihui/cdc-jar/emr-hudi-spark-1.0-SNAPSHOT-jar-with-dependencies.jar \
-e dev -b $bs \
-t cdc_t -p emr-cdc-group-0 -s true \
-o earliest \
-i 60 -y cow -p 10 \
-c s3://xxxx/spark-checkpoint/emr-cdc-grpup-0/ \
-g s3://xxx/emr-cdc-grpup-0/ \
-w upsert  \
-s hms \
-z thrift://xxx:9083 \
--concurrent true \
-m "{\"tableInfo\":[{\"database\":\"test_db\",\"table\":\"user\",\"hudiTable\":\"user\",\"hiveDatabase\":\"ods\",\"recordKey\":\"id\",\"precombineKey\":\"modify_time\",\"partitionTimeColumn\":\"create_time\",\"hudiPartitionField\":\"year_month\"},
{\"database\":\"test_db\",\"table\":\"user_order\",\"hudiTable\":\"user_order\",\"hiveDatabase\":\"ods\",\"recordKey\":\"id\",\"precombineKey\":\"modify_time\",\"partitionTimeColumn\":\"create_time\",\"hudiPartitionField\":\"year_month\"},{\"database\":\"test_db\",\"table\":\"product\",\"hudiTable\":\"product\",\"hiveDatabase\":\"ods\",\"recordKey\":\"pid\",\"precombineKey\":\"modify_time\",\"partitionTimeColumn\":\"create_time\",\"hudiPartitionField\":\"year_month\"}]}"

```

#### Flink Streaming Read 实时聚合
```shell
# checkpoint 地址
checkpoints=s3://xxxxx/flink/checkpoints/datagen/
# 创建 yarn-session,后续的 flink 任务将会提交到这个 cluster 执行
flink-yarn-session -jm 1024 -tm 4096 -s 2  \
-D state.backend=rocksdb \
-D state.checkpoint-storage=filesystem \
-D state.checkpoints.dir=${checkpoints} \
-D execution.checkpointing.interval=5000 \
-D state.checkpoints.num-retained=5 \
-D execution.checkpointing.mode=EXACTLY_ONCE \
-D execution.checkpointing.externalized-checkpoint-retention=RETAIN_ON_CANCELLATION \
-D state.backend.incremental=true \
-D execution.checkpointing.max-concurrent-checkpoints=1 \
-D rest.flamegraph.enabled=true \
-d \
```
示例流式聚合 sql
```sql
CREATE TABLE `user`(
   id string,
   name STRING,
   device_model STRING,
   email STRING,
   phone STRING,
   age string,
   create_time STRING,
   modify_time STRING,
   year_month STRING
)
PARTITIONED BY (`year_month`)
WITH (
  'connector' = 'hudi',
  'path' = 's3://xxx/emr-cdc-grpup-0/test_db/user/',
  'hoodie.datasource.write.recordkey.field' = 'id',
  'table.type' = 'COPY_ON_WRITE',
  'index.bootstrap.enabled' = 'true',
  'read.streaming.enabled' = 'true',
  'read.start-commit' = '20230223014223',
  'changelog.enabled' = 'false',
  'read.streaming.check-interval' = '1'
);

CREATE TABLE `user_order`(
   id string,
   oid string,
   uid STRING,
   pid STRING,
   onum STRING,
   remark STRING,
   create_time STRING,
   modify_time STRING,
   year_month STRING
)
    PARTITIONED BY (`year_month`)
WITH (
  'connector' = 'hudi',
  'path' = 's3://xxx/emr-cdc-grpup-0/test_db/user_order/',
  'hoodie.datasource.write.recordkey.field' = 'id',
  'table.type' = 'COPY_ON_WRITE',
  'index.bootstrap.enabled' = 'true',
  'read.streaming.enabled' = 'true',
  'read.start-commit' = '20230223014223',
  'changelog.enabled' = 'false',
  'read.streaming.check-interval' = '1'
);

-- Flink 聚合操作 Sink 到 Hudi 表
-- batch
CREATE TABLE  user_order_agg(
  oid STRING,
  uid INT,
  pid INT,
  name STRING,
  phone STRING,
  onum BIGINT,
  remark STRING,
  year_month STRING
)   PARTITIONED BY (`year_month`)
WITH(
 'connector' = 'hudi',
 'path' = 's3://xxx/emr-cdc-grpup-0/dws/user_order_agg',
 'table.type' = 'COPY_ON_WRITE',
 'write.precombine.field' = 'oid',
 'write.operation' = 'upsert',
 'hoodie.datasource.write.recordkey.field' = 'oid',
 'hive_sync.enable' = 'true',
 'hive_sync.db' = 'dws',
 'hive_sync.mode' = 'hms',
 'hive_sync.metastore.uris' = 'thrift://xxx:9083'
 );

Insert Into user_order_agg select o.oid, cast(o.uid as int), cast(o.pid as int), u.name, u.phone, cast(o.onum as bigint), o.remark, o.year_month from user_order as o inner join `user` as u on o.uid=u.id;
```
提交 flink sql 执行     

`sudo /usr/lib/flink/bin/sql-client.sh embedded -j /usr/lib/hudi/hudi-flink-bundle.jar -s yarn-session -f agg-user-product.sql`  

下图是同步到  hive 里查询到的聚合结果

![flink-agg-res](https://pics.lxkaka.wang/flink-agg-res.png)

在这篇文章里我们介绍了实时数据入数据湖的架构选型和方案实施。在后续工作中更多的实践经验和总结更待分享。


