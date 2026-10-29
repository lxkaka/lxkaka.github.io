# 数据编排技术-Alluxio 的原理介绍

在当前的业务系统中我们会遇到多种多样的数据存储和读取场景。在对于大量数据(G以上级别)的存储和读取我们就基本会采用分布式文件系统比如 Amazon S3、Apache HDFS。目前为了系统的可用性和稳定性计算和存储往往是分开部署，在这样的背景下对于大数据的读写性能和兼容性就会成为很大的挑战。于是我们看到了一种解决方案 [Alluxio](https://www.alluxio.io/)。

### Alluxio 简介
>Alluxio 是世界上第一个面向基于云的数据分析和人工智能的开源的数据编排技术。 它为数据驱动型应用和存储系统构建了桥梁, 将数据从存储层移动到距离数据驱动型应用更近的位置从而能够更容易被访问。 这还使得应用程序能够通过一个公共接口连接到许多存储系统。 Alluxio内存至上的层次化架构使得数据的访问速度能比现有方案快几个数量级。

>在大数据生态系统中，Alluxio 位于数据驱动框架或应用（如 Apache Spark、Presto、Tensorflow、Apache Hive 或 Apache Flink）和各种持久化存储系统（如 Amazon S3、Google Cloud Storage、OpenStack Swift、HDFS、IBM Cleversafe、EMC ECS、Ceph、NFS 、Minio和 Alibaba OSS）之间。 Alluxio 统一了存储在这些不同存储系统中的数据，为其上层数据驱动型应用提供统一的客户端 API 和全局命名空间。

![overview](https://pics.lxkaka.wang/alluxio-overview.png)

### Alluxio 重要特性
1. 统一数据访问接口    
  Alluxio 通过挂载功能在不同的存储系统之间实现高效的数据管理。并且，透明命名在持久化这些对象到底层存储系统时可以保留这些对象的文件名和目录层次结构。如下图, 可将 HDFS、S3 的数据 mount 到 Alluxio 的随意目录下，这样就可以通过一个 API 访问不同的主流的持久化存储系统，这样也解决了存储系统的单一依赖性。 

2. 内存速度 I/O   
   Alluxio 能够用作分布式共享缓存服务，这样与 Alluxio 通信的计算应用程序可以透明地缓存频繁访问的数据（尤其是从远程位置），以提供内存级 I/O 吞吐率。此外，Alluxio的层次化存储机制能够充分利用内存、固态硬盘或者磁盘，降低具有弹性扩张特性的数据驱动型应用的成本开销。

3. 简化数据管理   
    Alluxio 提供对多数据源的单点访问。除了连接不同类型的数据源之外，Alluxio 还允许用户同时连接同一存储系统的不同版本，如多个版本的 HDFS，并且无需复杂的系统配置和管理。

4. 应用程序部署简易   
     Alluxio 管理应用程序和文件或对象存储之间的通信，将应用程序的数据访问请求转换为底层存储接口的请求。Alluxio 与 Hadoop 兼容,现有的数据分析应用程序,如Spark 和 MapReduce 程序,无需更改任何代码就能在 Alluxio 上运行。

5. 智能多层缓存  
   Alluxio 集群能够充当底层存储系统中数据的读写缓存。可配置自动优化数据放置策略，以实现跨内存和磁盘（SSD/HDD）的性能和可靠性。缓存对用户是透明的，使用缓冲来保持与持久存储的一致性

6. 方便迁移可插拔  
   在容错方面，Alluxio 备份内存数据到底层存储系统。Alluxio 提供了通用接口以简化插入不同的底层存储系统。

7. 数据共享  
  Alluxio可以帮助实现跨计算、作业间的数据快速复用和共享。

对于用户应用程序和大数据计算框架来说，Alluxio 存储通常与计算框架并置。这种部署方式使 Alluxio 可以提供快速存储，促进作业之间的数据共享，无论它们是否在同一计算

### Alluxio 架构

Alluxio 由 master、worker 、client 组成；
1. master 支持1主多从的高可用架构，master 之前通过 raft 协议或 zookeeper 进行选主    
2. 主 master 用于对外提供 RPC 服务和管理全局的元数据。这里面包含文件系统元数据（文件系统节点树）、数据块元数据（数据块位置）、以及 worker 元数据（存储空间等）   
3. 备用 master 读取主 master 写入的 journa 日志，以保持与主 master 的状态同步。它们会对 journal 日志写入检查点，用于快速恢复。它们不处理来自 Alluxio 组件的任何请求     
4. worker 会定期向 master上报心跳    
5. worker 主要是管理存储资源和底层文件系统的操作，将远程文件存储到本地的内存/SSD/HDD 中   
6. 硬件资源是有限的，worker 还需要根据策略，负责多级智能缓存，数据淘汰、数据过期删除   
7. Client 在应用侧，负责向 master 请求文件的元信息，然后从 worker 中取回文件数据；Client 不会直接访问远程存储   

![arch](https://pics.lxkaka.wang/alluxio-arch.png)

### 数据流
Alluxio 与计算集群部署在一起，持久化存储系统可以为远程存储系统或云存储。在底层存储和计算集群间，Alluxio是作为一个缓存层存在的。
#### 读
1. 本地缓存命中  
  本地缓存命中发生在请求数据位于本地 Alluxio worker。举例说明，如果一个应用通过 Alluxio client 请求数据，client 向 Alluxio master 请求数据所在的worker。如果数据在本地可用，Alluxio client 使用“短路”读取来绕过 Alluxio worker，并直接通过本地文件系统读取文件。短路读取避免通过TCP套接字传输数据，并提供数据的直接访问。
  还要注意，Alluxio 除了内存之外还可以管理其他存储介质(例如SSD、HDD)，因此本地数据访问速度可能会因本地存储介质的不同而有所不同

2. 远程缓存命中  
  当请求的数据存储在 Alluxio 中，而不是存储在 client 的本地 worker 上时，client 将对具有数据的 worker 进行远程读取。client 完成读取后，会要求本地的worker（如果存在）创建一个copy，这样以后读取的时候可以在本地读取相同的数据。远程缓存击中提供了网络级别速度的数据读取。Alluxio 优先从远程 worker 读取数据，而不是从底层存储，因为 Alluxio worker 间的速度一般会快过 Alluxio workers 和底层存储的速度。

3. 缓存 miss  
  如果数据在 Alluxio 中找不到，则会发生缓存丢失，应用将不得不从底层存储读取数据。Alluxio client 会将数据读取请求委托给 worker（有限本地worker）。这个worker 会从底层存储读取数据并缓存。缓存丢失通常会导致最大的延迟，因为数据必须从底层存储获取。   
  当 client 只读取块的一部分或不按照顺序读取块时，client 将指示 worker 异步缓存整个块。异步缓存不会阻塞 client，但是如果 Alluxio 和底层存储系统之间的网络带宽是瓶颈，那么异步缓存仍然可能影响性能。

	![read](https://pics.lxkaka.wang/alluxio-read.png)   
	图中绿色示意为命中本地缓存，蓝色为命中远程缓存，红色为缓存 miss

#### 写  
 用户可以通过选择不同的写类型来配置应该如何写数据。写类型可以通过Alluxio API设置，也可以通过在客户机中配置属性Alluxio .user.file.writetype.default来设置。    
1. 写缓存    
  当写类型设置为 `MUST_CACHE`，Alluxio client 将数据写入本地 Alluxio worker，而不会写入到底层存储。如果“短路”写可用，Alluxio client 直接写入到本地 RAM 的文件，绕过 Alluxio worker，避免网络传输。由于数据没有持久存储在 under storage 中，因此如果机器崩溃或需要释放数据以进行更新的写操作，数据可能会丢失。当可以容忍数据丢失时，MUST_CACHE 设置对于写临时数据非常有用。

2. 同步持久化写  
  使用 `CACHE_THROUGH` 写类型，数据被同步地写到一个Alluxio worker 和底层存储。Alluxio client 将写操作委托给本地 worker，而 worker 同时将对本地内存和底层存储进行写操作。由于底层存储的写入速度通常比本地存储慢，所以 client 的写入速度将与底层存储的速度相匹配。当需要数据持久化时，建议使用 CACHE_THROUGH 写类型。在本地还存了一份副本，以便可以直接从本地内存中读取数据。

3. 异步持久化写  
  Alluxio 提供了一个叫做`ASYNC_THROUGH` 的写类型。数据被同步地写入到一个 Alluxio worker，并异步地写入到底层存储。ASYNC_THROUGH 可以在持久化数据的同时以内存速度提供数据写入。  
  
  	![must-cahce](https://pics.lxkaka.wang/alluxio-must-cache.png)    

  	这张图示意了写缓存的流程，绿色示意为 bypass 机制，黑色和蓝色线表示数据缓存到 worker  

  	![cache-through](https://pics.lxkaka.wang/alluxion-cache-through.png)
  	这张图展示了持久化写的过程 

在这篇文章里我们介绍了 Alluxio 的基本原理，知道了 Alluxio 是什么东西。在后面的文章里我们再来介绍 Alluxio 在实际业务中的使用。
