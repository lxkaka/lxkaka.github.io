# Hive To AnalyticDB 数据同步方案设计


最近在做同步数仓数据的工作，从设计到实现整个过程其实是挺有意思的。这里记录和分享一下我们的实施方案，也能给有类似需求的同学提供一些参考价值。
## 需求
在调研了阿里云的 AnalyticDB MySQL 后，我们决定把业务系统使用 Presto 查询 Hive 数据的过程替换成业直接查询 ADB(文中 ADB 都指的是 AnalyticDB MySQL)。具体原因这里就不做展开，简单说三点就是第一解耦我们目前业务直接依赖 EMR， 第二是性能上有很好的提升， 第三点用钱买服务省心。  
所以简单来说我们需要把数仓 DWS 层的数据同步到 ADB。

## 目标
在明确了需求后，数仓数据同步的任务需要达到以下目标
* 扩展性高
  新建的表或者删除表都不需要改动同步逻辑，或者其他代码
* 延时低
  数仓的数据生产完毕或者更新完毕，相关的表就能开始同步
* 容错率高
  不会出现漏同步，或者重复同步  

## 方案设计
为了达到上述的目标，数据同步的主要流程如下    
![sync-flow](https://pics.lxkaka.wang/sync-flow.png)

首先我们的同步任务最终执行的形式是 Airflow 中的一个 task，各个不同表的同步任务组成了 Airflow 中的一个 dag。 
#### 扩展性    
为了达到扩展性的要求，我们把需要同步的 table 和他的依赖 task 以及一些别的信息存入 mysql 表中(表名 sync_task)。上面提到的 dag 就是根据 sync_task 的有效记录动态生成的。所以无论新建同步任务或者删除同步任务，只需要更新 sync_task， 那么 dag 也会动态调整。  
dag 示例代码如下    
```python 
# 读取同步记录
sync_tasks = get_mysql_dataset(
        mysql_conn_id="mysql_metadata",
        schema="metadata",
        sql=f"select * from sync_task where status = 1",
    )

# 生成 dag 里的同步 task
for sync_task in sync_tasks:
    adb_table = sync_task["adb_table"]
    sync_task_id = sync_task["id"]
    sync_conditions = sync_task["conditions"]
    if not sync_conditions or sync_conditions == "None":
        sync_conditions = ""
    HiveRecordToMySqlOperator(
        task_id=f"sync_to_adb_{adb_table}_{sync_task_id}",
        dag=dag,
        hive_table=sync_task["hive_table"],
        mysql_table=sync_task["adb_table"],
        mysql_conn_id=sync_task["mysql_conn_id"],
        dml_operator=sync_task["dml_operator"],
        conditions=sync_conditions,
        sync_task_record_id=sync_task_id,
    )
```

#### 延时低      
为了达到高效的同步，我们做了以下几点来保证    
* 多线程读取和写入      
我们知道在 Python 中多线程真正能分配到 CPU 时间片的只有一线程，所以很多情况下多线程没有太多用处。但是我们这个同步数据过程是典型的 IO 密集型任务，如果单线程的话 CPU 大部分时间处于空闲状态，这个时候多线程就有意义了，能显著的提高同步效率。    
示例代码如下          
```python  
with ThreadPoolExecutor(5 * multiprocessing.cpu_count()) as executor:
while rows:
    serialize_rows = []
    for row in rows:
        lst = []
        for cell in row:
            lst.append(self._serialize_cell(cell))
        serialize_rows.append(tuple(lst))
    placeholders = ",".join(["%s"] * len(serialize_rows[0]))
    sql = f"{self.dml_operator} {tmp_mysql_table} {target_fields} VALUES ({placeholders})"
    task = executor.submit(
        self._mysql_run, sql, serialize_rows, mysql, tmp_mysql_table
    )
    all_tasks.append(task)
    rows = hive_cursor.fetchmany(self.query_every)
```

* 数据分片      
上面我们提到的多线程只利用了 airflow worker 的一个进程，所以如果我们把数据分片，每一片数据是一个独立的同步任务，那么自然就能生成一个 dag 中的 task, 多个数据分片就同时生成多个同步任务，这些任务能被 airflow scheduler 调度给不同的 worker 或者同一个 worker 的不同进程。        
示例代码如下          
```pyhton 
# 获取同步数据量  
# 这里为了不消耗 EMR 的资源，我们去 hive metastore 表中获取待同步表的数据量，而不是使用 select count(*) 
hive_conn = HiveCliHook(hive_cli_conn_id="hive_cli_default")
hive_conn.run_cli("ANALYZE TABLE dm.delphi_membership_properties COMPUTE STATISTICS;")
table_rows = get_mysql_dataset(
    mysql_conn_id="hivemeta_db",
    schema="hivemeta",
    sql="select PARAM_KEY, PARAM_VALUE from TBLS as tb inner join TABLE_PARAMS as tp on(tb.TBL_ID=tp.TBL_ID) "
        "where tb.TBL_NAME='delphi_membership_properties' and tp.PARAM_KEY='numRows';"
)
if table_rows:
    table_count = int(table_rows[0]["PARAM_VALUE"])
# 这里分片数量可以根据实际的 worker 数和 worker 进程数，动态调整
# 下面只是一个简单的示例  
workers = multiprocessing.cpu_count() // 2
step = math.ceil(table_count / workers)
conf_ids = get_mysql_dataset(
    mysql_conn_id="mysql_metadata",
    schema="metadata",
    sql="select id from adb_sync_task where hive_table='dm.delphi_membership_properties' and status=1",
)
mysql = MySqlHook(mysql_conn_id="mysql_metadata")
if conf_ids:
    conf_ids = [item["id"] for item in conf_ids]
# 根据分片数，生成同步记录  
for i in range(workers):
    conditions = f"limit {i * step},{step}"
    if i < len(conf_ids) and conf_ids[i]:
        sql = f"update adb_sync_task set conditions='{conditions}' where id={conf_ids[i]}"
    else:
        sql = (
            f"insert into adb_sync_task (dag_id, task_id, hive_table, adb_table, dml_operator, "
            f"conditions, extra_sql) values ('ods_to_delphi_membership_dm','update_membership_properties_trigger_conf',"
            f"'dm.delphi_membership_properties','delphi_membership_properties','REPLACE INTO','{conditions}',"
            f"'primary key (membership_id));')"
        )
    mysql.run(sql)
```

* 调整 dag 执行频率      
我们可以根据实际情况调整 dag 的执行频率， 比如可以调整到分钟级别，这样能尽快的跟上同步任务的依赖，能及时触发同步操作。      

#### 容错率高        
为了保证同步任务的正确执行，我们充分利用了 airflow 中的 task_instace, 每一次 task 的执行都会生成记录被 airflow 写入 mysql。     
* 不漏跑    
每次执行同步任务需要先确保依赖已经在当前时间之前成功执行        
示例代码如下       
```python       
# 筛选出同步任务依赖的 dag 最近的执行时间
dep_sql = f"select end_date from task_instance where dag_id='{dag_id}' and task_id='{task_id}' and state='success' order by end_date desc limit 1"
dep_res = get_mysql_dataset(
    mysql_conn_id="airflow_db", schema="airflow", sql=dep_sql
)
print('dep：', dep_sql, dep_res)
# 筛选出同步任务最近成功的执行时间
sync_task_id = f"sync_to_adb_{self.mysql_table}_{self.sync_task_record_id}"
sql = f"select end_date from task_instance where task_id='{sync_task_id}' and state='success' order by end_date desc limit 1"
res = get_mysql_dataset(mysql_conn_id="airflow_db", schema="airflow", sql=sql)   
```

* 不重复跑          
因为没次任务的触发都会成 task_instace, 所以我们必须当前只有一个同步任务在跑，不能重复执行。  
    示例代码如下     
    ```python 
    # 筛选出上次成功执行后的执行记录
    task_state_sql = f"select state from task_instance where task_id='{self.task_id}' and execution_date > '{upstream_task_latest_success_time}'"
    target_tasks = get_mysql_dataset(
        mysql_conn_id="airflow_db", schema="airflow", sql=task_state_sql
    )
    unfinished_tasks = [_ for _ in target_tasks if _["state"] in State.unfinished()]
    # 是否还有其他任务在执行  
    return len(unfinished_tasks) > 1
    ```

* 一致性  
在数据一致性方面，我们首先把数据写入中间表，完成后把目标表 rename 成 backup, 再把中间表 rename 为目标表。如果出现异常，我们还能使用 backup 表执行回滚操作。    

dag 执行同步的示例效果如下图    
![sync-result](https://pics.lxkaka.wang/sync-result.png)  

## 存在的问题    
当同步任务特别多且在同一时间段触发了较多的同步操作，那么我们的数据源 hive 和 airflow worker 都可能成为瓶颈，影响到数据同步。airflow worker 我们可以通过限制 task concurrency 和增加 worker（worker扩展比较容易）才解决。hive 的并发瓶颈需要我们去思考更好的方案，未来考虑直接从 OSS 同步数据。  

