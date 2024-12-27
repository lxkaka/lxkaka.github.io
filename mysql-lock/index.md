# MySQL InnoDB 加锁实践分析


在使用 MySQL 和存储引擎是 InnoDB 的情况下，当我们想从一个 SQL 语句分析出这个语句对应的加锁情况需要掌握哪些知识呢？
在这篇文章我就想总结一下 InnoDB 的锁类型和这些不同的锁用在什么场景。
影响加锁的因素有这几个：
* 事务隔离级别
  事务的隔离级别以及他们能解决的事务问题这里就不做介绍了，这里我们只针对常用的 *Read Committed*, *Repeatable Read* 分析。
* SQL 语句本身(一致性非锁定读还是一致性锁定读；DML(update,insert,delete))
  普通的 *SELECT* 对应的就是一致性非锁定读，即不需要加锁，InnoDB 使用 MVCC(multiversion concurrency control)来增加读操作的并发性, MVCC是指，InnoDB 使用基于时间点的快照来获取查询结果，读取时在访问的表上不加锁，因此，在事务T1读取的同一时刻，事务 T2 可以自由的修改事务 T1 所读取的数据。
  *SELECT for share* 和 *SELECT for update* 对应的则是锁定读，即在搜索到的每条索引记录(index record) 加共享锁或排他锁。
* 使用的索引类型(主键索引，唯一索引，非唯一索引，没有用到索引)

## InnoDB 锁类型
InnoDB 一共有8种锁类型，其中，意向锁(Intention Locks)和自增锁(AUTO-INC Locks)是表级锁，剩余全部都是行级锁。此外，共享锁或排它锁(Shared and Exclusive Locks)尽管也作为8种锁类型之一，它却并不是具体的锁，它是锁的模式，用来“修饰”其他各种类型的锁。

* 共享锁或排它锁(Shared and Exclusive Locks)
  它并不是一种锁的类型，而是其他各种锁的模式，每种锁都有shard或exclusive两种模式。
   S 锁和 X 锁兼容情况如下
    假设 T1 持有数据行 r 上的 S 锁，则当 T2 请求 r 上的锁时：
    1. T2 请求 r 上的 S 锁，则，T2 立即获得 S 锁。T1 和T2 同时都持有 r 上的 S 锁。
    2. T2 请求 r 上的 X 锁，则，T2 无法获得 X 锁。T2 必须要等待直到 T1 释放 r 上的 S 锁。
    假设 T1 持有 r 上的X锁，则当 T2 请求 r 上的锁时：
    T2 请求 r 上的任何类型的锁时，T2 都无法获得锁，此时，T2 必须要等待直到 T1 释放 r 上的 X 锁

* 意向锁(Intention Locks)
  表锁。含义是已经持有了表锁，稍候将获取该表上某个/些行的行锁。有 shard 或 exclusive 两种模式。
  LOCK_MODE分别是：IS 或 IX  
  意向锁的目的是告知其他事务，某事务已经锁定了或即将锁定某个/些数据行。事务在获取行锁之前，首先要获取到意向锁，即：
  1. 事务在获取行上的 S 锁之前，事务必须首先获取 表上的 IS 锁或表上的更强的锁。
  2. 事务在获取行上的 X 锁之前，事务必须首先获取 表上的 IX 锁。
  意向锁和任何行锁都是兼容的，它只会阻塞全表请求(如 *lock tables...write*)

* 索引记录锁(Record Locks)
  即行锁，在某个索引的特定索引记录（或称索引条目、索引项、索引入口）上设置锁。有 shard 或 exclusive 两种模式。 
  LOCK_MODE分别是：S,REC_NOT_GAP 或 X,REC_NOT_GAP  

* 间隙锁(Gap Locks)
  索引记录之间的间隙上的锁，锁定尚未存在的记录，即索引记录之间的间隙。有 shard 或 exclusive 两种模式，二者等价。
  LOCK_MODE分别是：S,GAP 或 X,GAP  
  gap lock 锁住的间隙可以是第一个索引记录前面的间隙，或相邻两条索引记录之间的间隙，或最后一个索引记录后面的间隙。
  gap lock 存在的唯一目的就是阻止其他事务向gap中插入数据行，它用于在隔离级别为RR时，阻止幻影行(phantom row)的产生；隔离级别为RC时，搜索和索引扫描时，gap lock 是被禁用的，只在外键约束检查和重复 key 检查时 gap lock 才有效，正是因为此，RC 时会有幻影行问题。

* Next-Key Locks
  next-key lock 是 (索引记录上的索引记录锁) + (该索引记录前面的间隙上的锁) 二者的合体，它锁定索引记录以及该索引记录前面的间隙。有 shard 或e xclusive两种模式。
 LOCK_MODE分别是：S 或 X  
 当 InnoDB 搜索或扫描索引时，InnoDB 在它遇到的索引记录上所设置的锁就是 next-key lock，它会锁定索引记录本身以及该索引记录前面的 gap("gap" immediately before that index record)。即：如果事务T1 在索引记录r 上有一个next-key lock，则 T2 无法在 紧靠着 r 前面的那个间隙中插入新的索引记录(gap immediately before r in the index order)。
 next-key lock 还会加在 *supremum pseudo-record*(索引中的伪记录(pseudo-record)，代表此索引中可能存在的最大值) 上，该 next-key lock实际上锁定了“此索引中可能存在的最大值”前面的间隙，也就是此索引中当前实际存在的最大值后面的间隙。

* 插入意向锁(Insert Intention Locks)
  INSERT 操作插入成功后，会在新插入的行上设置 index record lock，但在插入行之前，INSERT 操作会首先在索引记录之间的间隙上设置 insert intention lock，该锁的范围是(插入值, 向下的一个索引值)。有 shard 或 exclusive 两种模式，二者等价。
  LOCK_MODE分别是：S,GAP,INSERT_INTENTION 或 X,GAP,INSERT_INTENTION  
  insert intention lock 相互不会阻塞，即多个事务向同一个 index gap 并发进行插入时，多个事务无需相互等待，极大提高了插入的并发性。那么为什么需要 insert intenton lock 呢？答案就是上面我们提到的 gap lock 或 next-key lock 会阻塞 insert intention lock, 这个特性解决了 *RR* 隔离级别中的 phantom row。

* 自增锁(AUTO-INC Locks)
  表锁。向带有AUTO_INCREMENT列 的表时插入数据行时，事务需要首先获取到该表的AUTO-INC表级锁，以便可以生成连续的自增值。插入语句开始时请求该锁，插入语句结束后释放该锁(不是事务结束)
  我们日常开发中大部分场景都是 simple-inserts, 即待插入的条数提前可以确定，那么自增值的个数也可以别提前确定就不需要 auto-inc 锁。

* 空间索引(Predicate Locks for Spatial Indexes)
  平时很少用到，这里不涉及

## 加锁分析
这里使用的环境是 MySQL 8.0.19  
测试表如下  
```
 CREATE TABLE `test` (
  `id` int NOT NULL AUTO_INCREMENT,
  `a` varchar(10) DEFAULT NULL,
  `b` varchar(10) DEFAULT NULL,
  `n` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `index_n` (`n`),
  KEY `index_b` (`b`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```

* 没有使用索引，全表扫描   
  这种情况下，InnoDB 会在所有记录上加行锁
    ```
    mysql> begin;
    Query OK, 0 rows affected (0.00 sec)
    mysql> select * from test where a='a' for update;
    Empty set (0.00 sec)

    # 查看加锁情况，结果如下  
    # 可以看到全部记录加了 next-key lock(X)  
    +----------+------------+-----------+-----------+-------------+------------------------+
    | trans_id | index_name | lock_type | lock_mode | lock_status | lock_data              |
    +----------+------------+-----------+-----------+-------------+------------------------+
    |     2091 | NULL       | TABLE     | IX        | GRANTED     | NULL                   |
    |     2091 | PRIMARY    | RECORD    | X         | GRANTED     | supremum pseudo-record |
    |     2091 | PRIMARY    | RECORD    | X         | GRANTED     | 1                      |
    |     2091 | PRIMARY    | RECORD    | X         | GRANTED     | 2                      |
    +----------+------------+-----------+-----------+-------------+------------------------+
    ```
  上面看到了，查询条件无法使用索引则不得不全部行加锁，可见索引的重要性。

* 使用了唯一索引
  首先如果是等值查询，只需要索引记录锁(index record lock)
    ```
    mysql> begin;
    Query OK, 0 rows affected (0.00 sec)

    mysql> select * from test where n=5 for update;
    +----+------+------+---+
    | id | a    | b    | n |
    +----+------+------+---+
    |  1 | s    | ss   | 5 |
    +----+------+------+---+
    1 row in set (0.00 sec)

    # 查看加锁情况，结果如下
    # 在 index_n 上只加了 index record lock(X,REC_NOT_GAP)  
    +----------+------------+-----------+---------------+-------------+-----------+
    | trans_id | index_name | lock_type | lock_mode     | lock_status | lock_data |
    +----------+------------+-----------+---------------+-------------+-----------+
    |     2116 | NULL       | TABLE     | IX            | GRANTED     | NULL      |
    |     2116 | index_n    | RECORD    | X,REC_NOT_GAP | GRANTED     | 5, 1      |
    |     2116 | PRIMARY    | RECORD    | X,REC_NOT_GAP | GRANTED     | 1         |
    +----------+------------+-----------+---------------+-------------+-----------+
    ```
  
  范围查询，对符合条件的每条记录加 next-key lock 和在第一个不满足条件的索引记录上设置next-key lock   
    ```
    # 目前表中的所有记录  
    mysql> select * from test;
    +----+------+------+----+
    | id | a    | b    | n  |
    +----+------+------+----+
    |  1 | s    | ss   |  5 |
    |  2 | d    | dd   | 10 |
    |  4 | g    | gg   | 20 |
    |  6 | l    | ll   | 50 |
    +----+------+------+----+

    mysql> select * from test where n > 1 and n <=15 for update;
    +----+------+------+----+
    | id | a    | b    | n  |
    +----+------+------+----+
    |  1 | s    | ss   |  5 |
    |  2 | d    | dd   | 10 |
    +----+------+------+----+
    
    # 加锁情况如下  
    # 可以看到符合条件(5，10)的记录都被加上了 next-key lock(X)， 不符合条件的第一条(20)也加上了 next-key lock  
    +----------+------------+-----------+---------------+-------------+-----------+
    | trans_id | index_name | lock_type | lock_mode     | lock_status | lock_data |
    +----------+------------+-----------+---------------+-------------+-----------+
    |     2119 | NULL       | TABLE     | IX            | GRANTED     | NULL      |
    |     2119 | index_n    | RECORD    | X             | GRANTED     | 5, 1      |
    |     2119 | index_n    | RECORD    | X             | GRANTED     | 10, 2     |
    |     2119 | index_n    | RECORD    | X             | GRANTED     | 20, 4     |
    |     2119 | PRIMARY    | RECORD    | X,REC_NOT_GAP | GRANTED     | 1         |
    |     2119 | PRIMARY    | RECORD    | X,REC_NOT_GAP | GRANTED     | 2         |
    +----------+------------+-----------+---------------+-------------+-----------+
    ```

* 使用非唯一索引
  InnoDB 会锁住索引本身，还会锁住索引记录前面的间隙会对所有满足条件的记录 即加 next-key lock。
    ```
    mysql> select * from test where b > 'gg' for update;
    +----+------+------+----+
    | id | a    | b    | n  |
    +----+------+------+----+
    |  6 | l    | ll   | 50 |
    |  1 | s    | ss   |  5 |
    +----+------+------+----+

    # 加锁情况如下，可以看到在非唯一索引 index_b 加的是 next-key lock    
    +----------+------------+-----------+---------------+-------------+------------------------+
    | trans_id | index_name | lock_type | lock_mode     | lock_status | lock_data              |
    +----------+------------+-----------+---------------+-------------+------------------------+
    |     2159 | NULL       | TABLE     | IX            | GRANTED     | NULL                   |
    |     2159 | index_b    | RECORD    | X             | GRANTED     | supremum pseudo-record |
    |     2159 | index_b    | RECORD    | X             | GRANTED     | 'ss', 1                |
    |     2159 | index_b    | RECORD    | X             | GRANTED     | 'll', 6                |
    |     2159 | PRIMARY    | RECORD    | X,REC_NOT_GAP | GRANTED     | 1                      |
    |     2159 | PRIMARY    | RECORD    | X,REC_NOT_GAP | GRANTED     | 6                      |
    +----------+------------+-----------+---------------+-------------+------------------------+
    ```
  
  在等值条件下，除了加 next-key lock 还会在搜索第一个不满足条件的索引记录上加 gap lock  
    ```
    mysql> select * from test where b = 'gg' for update;
    +----+------+------+----+
    | id | a    | b    | n  |
    +----+------+------+----+
    |  4 | g    | gg   | 20 |
    +----+------+------+----+
    
    # 加锁情况如下    
    # 可以看到在第一条不满足条件的记录('ll') 的索引上加了 gap lock  
    +----------+------------+-----------+---------------+-------------+-----------+
    | trans_id | index_name | lock_type | lock_mode     | lock_status | lock_data |
    +----------+------------+-----------+---------------+-------------+-----------+
    |     2161 | NULL       | TABLE     | IX            | GRANTED     | NULL      |
    |     2161 | index_b    | RECORD    | X             | GRANTED     | 'gg', 4   |
    |     2161 | PRIMARY    | RECORD    | X,REC_NOT_GAP | GRANTED     | 4         |
    |     2161 | index_b    | RECORD    | X,GAP         | GRANTED     | 'll', 6   |
    +----------+------------+-----------+---------------+-------------+-----------+
    ```
上面分析的情况都是在事务隔离级别为 *Reaptable Read* 的情况下，我们说过加锁情况跟事务隔离级别是密切相关的。下面我们分析在 *Read Committed* 下的加锁情况  

* *RC* 事务隔离级别  
   RC 下不加 next-key 或者 gap lock， 只加 index record lock(当然无论何种隔离级别，PRIMARY 上的 index record lock 总是会加的)  
   ```
    mysql> set session transaction isolation level read committed;
    Query OK, 0 rows affected (0.00 sec)
    mysql> select @@session.transaction_isolation;
    +---------------------------------+
    | @@session.transaction_isolation |
    +---------------------------------+
    | READ-COMMITTED                  |
    +---------------------------------+

    mysql> begin;
    Query OK, 0 rows affected (0.00 sec)
    mysql> select * from test where b='gg' for update;
    +----+------+------+----+
    | id | a    | b    | n  |
    +----+------+------+----+
    |  4 | g    | gg   | 20 |
    +----+------+------+----+

    # 加锁情况如下，我们看到只有 index reord lock(X,REC_NOT_GAP)     
    +----------+------------+-----------+---------------+-------------+-----------+
    | trans_id | index_name | lock_type | lock_mode     | lock_status | lock_data |
    +----------+------------+-----------+---------------+-------------+-----------+
    |     2125 | NULL       | TABLE     | IX            | GRANTED     | NULL      |
    |     2125 | index_b    | RECORD    | X,REC_NOT_GAP | GRANTED     | 'gg', 4   |
    |     2125 | PRIMARY    | RECORD    | X,REC_NOT_GAP | GRANTED     | 4         |
    +----------+------------+-----------+---------------+-------------+-----------+
   ```
* 查看 insert intention lock   
  上面我们看到了 *X*，*X,GAP*, *X,REC_NOT_GAP* 这几种锁都是锁定读和 update/delete 中很常见的锁。下面我们分析一下插入时加的锁    
    ```
    # 我们首先开启事务 T1 更新一条记录  
    mysql> begin;
    Query OK, 0 rows affected (0.00 sec)

    mysql> update test set a='kk' where b='gg';
    Query OK, 1 row affected (0.02 sec)
    Rows matched: 1  Changed: 1  Warnings: 0
    # 上面 update 的加速情况我们现在应该很清楚了，('dd''gg']有锁，('gg', 'ss')有锁 
    # 那么如果我们插入一条记录 b='jj' 是不是插需要锁呢？

    # 开启事务 T2 插入一条记录
    mysql> begin;
    Query OK, 0 rows affected (0.00 sec)
    mysql> insert into test(a, b , n) values('j', 'jj', 50);
    # 这里我们发现等待锁的获取直到超时退出

    # 这时的加锁情况如下   
    # 我们清楚的看到次此时 T2(2127) 等待获取 insert intention lock，所以无法插入，和我们的预期完全一致。这样就防止了 phantom row 的产生。      
    +----------+------------+-----------+------------------------+-------------+-----------+
    | trans_id | index_name | lock_type | lock_mode              | lock_status | lock_data |
    +----------+------------+-----------+------------------------+-------------+-----------+
    |     2127 | NULL       | TABLE     | IX                     | GRANTED     | NULL      |
    |     2127 | index_b    | RECORD    | X,GAP,INSERT_INTENTION | WAITING     | 'ss', 1   |
    |     2126 | NULL       | TABLE     | IX                     | GRANTED     | NULL      |
    |     2126 | index_b    | RECORD    | X                      | GRANTED     | 'gg', 4   |
    |     2126 | PRIMARY    | RECORD    | X,REC_NOT_GAP          | GRANTED     | 4         |
    |     2126 | index_b    | RECORD    | X,GAP                  | GRANTED     | 'ss', 1   |
    +----------+------------+-----------+------------------------+-------------+-----------+
   ```

**注意**: performance_schema.data_locks 显示的并不是全部的加锁，SQL实际执行时所没有使用的索引加上的锁则不会显示在表中(实际上是加了锁)    
下面的这个例子说明了这种情况      
    ```
    # 事务 T1
    mysql> begin;
    Query OK, 0 rows affected (0.02 sec)

    mysql> update test set b='gh' where n=20;
    Query OK, 1 row affected (0.00 sec)
    Rows matched: 1  Changed: 1  Warnings: 0

    # 查看加锁情况     
    # 可以看到表里只有 index_n 加了锁 
    +----------+------------+-----------+---------------+-------------+-----------+
    | trans_id | index_name | lock_type | lock_mode     | lock_status | lock_data |
    +----------+------------+-----------+---------------+-------------+-----------+
    |     2143 | NULL       | TABLE     | IX            | GRANTED     | NULL      |
    |     2143 | index_n    | RECORD    | X,REC_NOT_GAP | GRANTED     | 20, 4     |
    |     2143 | PRIMARY    | RECORD    | X,REC_NOT_GAP | GRANTED     | 4         |
    +----------+------------+-----------+---------------+-------------+-----------+

    # 事务 T2
    mysql> begin;
    Query OK, 0 rows affected (0.00 sec)

    mysql> update test set b='gg' where b='gh';
    如果 T1 不提交，上面的更新会等待锁直到超时    

    # 加锁情况如下  
    # 显然在 T1(2143) 中 index_b 加了 next-key lock 但并未显示出来    
    +----------+------------+-----------+---------------+-------------+-----------+
    | trans_id | index_name | lock_type | lock_mode     | lock_status | lock_data |
    +----------+------------+-----------+---------------+-------------+-----------+
    |     2148 | NULL       | TABLE     | IX            | GRANTED     | NULL      |
    |     2148 | index_b    | RECORD    | X             | WAITING     | 'gh', 4   |
    |     2143 | NULL       | TABLE     | IX            | GRANTED     | NULL      |
    |     2143 | index_n    | RECORD    | X,REC_NOT_GAP | GRANTED     | 20, 4     |
    |     2143 | PRIMARY    | RECORD    | X,REC_NOT_GAP | GRANTED     | 4         |
    |     2143 | index_b    | RECORD    | X,REC_NOT_GAP | GRANTED     | 'gh', 4   |
    +----------+------------+-----------+---------------+-------------+-----------+
    ```

