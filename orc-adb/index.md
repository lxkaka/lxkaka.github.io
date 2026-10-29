# Hive To AnalyticDB 数据同步方案演进


在这篇文章里我接着讲述一下数仓数据同步到 ADB 的方案演进。随着数据规模纵向和横向的扩大，把 hive 作为同步的数据源瓶颈越来越明显。首先是单表的数据超过 3000w 后，分段（limit方法）的速度非常缓慢；再者表越来越多 hive 的 IO 压力凸显。在上一篇文末我已经提到了这个问题，当时的设想是把数据源变成 OSS, 这样数据源我们完全可以认为瓶颈不会出现在源头。下面我具体介绍一下方案的设计和实施过程。

## 目标改进  
首先我们的目标在此前的基础上做出了如下改进
* 延时
  数据源头切换成 OSS, 数仓里的表 location 全部在 OSS 的特定 bucket 里并且文件格式是 ORC, 也就说数据源的存储形态就是 OSS bucket 中的一个个的 ORC 文件。一个表可能有多个 ORC 文件组成，所以我们同步任务的粒度可以精细到单个 ORC 文件，多个 ORC 文件创建多个同步任务，这些任务同时同时进行，同步的效率可以达到 ADB 的写入上限。相比之前的方案，同步的效率有了巨大的提升。
* 容错
  同步任务的前置和后置分别抽成 task, 前置 task 负责中间表的清理和创建；后置 task 负责中间表的 rename 和原表的备份。这样的设计提高了容错率，比如当一张表的某一个同步任务失败，在有唯一键的情况下重新执行这个 task 即可；再比如当需要重新同步整张表，重置前置 task 即可重新同步；或者本次同步失败，只需要标记后置 task 为失败即可。
* 扩展性
  另外一个巨大的改进是基础设施的改进。在上一篇文章中我们讲过同步任务的调度框架是 Airflow, 每个 task 最终以消息的形式发送给 celery worker 执行。在 Airflow 1.10 后引入了一种新的 Executor--Kubernetes Executor, 这是我一直想引入的 Executor 终于可以投入到生产使用了。简单说就是每个 task 现在可以以 k8s Pod 的形式调度到 k8s 集群执行，task 执行完成则 Pod 自动被 remove。这类非常驻的任务可以搭配公有云厂商提供的 serverless k8s 集群可以说非常高效。


## 同步流程
改进的大致同步流程如下  
![oss_sync_flow](https://pics.lxkaka.wang/oss_sync_flow.png)

## 方案

### task 生成  
根据表的 location 前缀找到所有有效的 ORC 文件，有的表可能因为分区数很多，可能产生了数千甚至上万的小文件，如果每个文件生成一个 task, 小文件对应的 task 同步数据的时间比创建 pod 的时间还短，会十分的低效。所以，这里有两个方法，一是在 hive 层面我们可以使用命令例如 `alter table test_xxx partition(product_name='a',measure_name='b') CONCATENATE;` 来压缩小文件；二是我们把多个小文件组合成一个 task, 即多个小文件组合成一个 batch, 每个 batch 生成一个 task。 综合来看第二种方式更方便高效。
示例代码如下    
```python
result = []
res = oss_bucket.list_objects(oss_prefix)
index = 0
acc = 0
batch = []
while res.object_list:
    for f in res.object_list:
        if f.size > 0:
            s = f.size // 1000000
            acc += s
            batch.append(f)
            if acc > 50:
                index += 1
                result.extend(sync_operator(batch, dag, sync_task, index, memory_base=memory_base))
                acc = 0
                batch = []

    if res.next_marker:
        res = oss_bucket.list_objects(oss_prefix, marker=res.next_marker)
    else:
        break
index += 1
result.extend(sync_operator(batch, dag, sync_task, index, memory_base=memory_base))
return result
```

### ORC 解析  
ORC 文件的解析的关键就是解析表结构；如何获取一行数据    
示例代码如下    
```python
# 下载 oss 文件到本地
logger.info(f'start download oss file {file}....')
try:
    # 断点续传  
    oss2.resumable_download(oss_bucket, file, local_name, num_threads=3)
except Exception as e:
    logger.error(e)
    download(oss_bucket, local_name)

# 解析 orc 文件
with open(local_name, 'rb') as f:
    data = orc.ORCFile(f)
    table = data.read()
    # 表的 colum 数
    num_columns = table.num_columns
    logger.info(table.num_rows)
    logger.info(num_columns)

# 获取多行数据的集合
for i in table.to_batches():
    d = i.to_pydict()
    zip_data = [d[n] for n in table.schema.names]
    # 这里得到多行数据组成的元祖可以直接 insert 到 ADB 表中
    r = zip(*zip_data)

# 对于分区表我们解析文件的路径，从路径中获得分区并插入到行中  
partition = []
partition_value = []
for path in file_parts:
    if '=' in path:
        partition.append(path.split('=')[0])
        partition_value.append(path.split('=')[1])
columns = table.schema.names + partition
columns = ','.join(columns)  
```

其中数据的写入过程和容错过程与上篇文章所描述的基本一致，这里不再赘述。

### 使用 Kubernetes Executor  
在 Airflow 的部署上，我们只需要把 `Airflow webserver` 和 `scheduler` 通过 `deployment` 部署到 k8s 集群。
* 配置 
启用 k8s executor 需要基本配置如下   
```
executor = KubernetesExecutor

[kubernetes]
# The repository, tag and imagePullPolicy of the Kubernetes Image for the Worker to Run
worker_container_repository = {IMAGE_BASE}
worker_container_tag = {VERSION}
worker_container_image_pull_policy = Always

# If True (default), worker pods will be deleted upon termination
delete_worker_pods = True

# Number of Kubernetes Worker Pod creation calls per scheduler loop
worker_pods_creation_batch_size = 20

# The Kubernetes namespace where airflow workers should be created. Defaults to ``default``
namespace = default

# For docker image already contains DAGs, this is set to ``True``, and the worker will
# search for dags in dags_folder,
# otherwise use git sync or dags volume claim to mount DAGs
# 我们这里把 dag 打包到镜像里，官方推荐使用 git repo 同步的方式，这个需要 git sync 的一些配置，具体可参考官方文档
dags_in_image = True

# Use the service account kubernetes gives to pods to connect to kubernetes cluster.
# It's intended for clients that expect to be running inside a pod running on kubernetes.
# It will raise an exception if called from a process not running in a kubernetes environment.
in_cluster = False

# When running with in_cluster=False change the default cluster_context or config_file
# options to Kubernetes client. Leave blank these to use default behaviour like ``kubectl`` has.
# cluster_context =
config_file = /root/airflow/k8sconfig
```
Airfow 使用 Kubernetes Executor 我画了下面这张图来说明一下现在的架构     
* 通过浏览器我们可以访问到部署在 k8s 中的 Airflow Web服务，查看 task 的执行情况；  
* Airflow scheduler 负责调用集群（k8s集群可以是本集群或者是其他集群）的 API 根据 Airflow operator 的定义和其他 k8s 配置创建 Pod 执行 task;  
* task 执行完成 Pod 被删除，执行日志上传到 OSS  
![airflow_k8s](https://pics.lxkaka.wang/airflow_k8s.png)

由不同 batch 生成的 task 的 dag 示意图如下  
上面说到的前置 task 即图中的 start, 后者 task 即 finish, 同步任务即 batch_i  
![oss_dag](https://pics.lxkaka.wang/oss_dag.png)


## 存在的问题  
到这里 ORC 数据同步方案介绍完了，这个方案也不是最完善的。从示例代码中可以看出来，大量数据同步前都放到内存里了，在执行的同步过程中随着数据量的上升内存的占用会越来越高，如果同步前没有规划好 task 的内存资源(反应到 k8s 即 Pod 的内存占用)可能 task 会因为 OOM 被 kill。资源的优化，如何节省内存是下一步需要思考的问题。


