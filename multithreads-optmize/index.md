# 记一次优化I/O密集型任务



### 发现问题
当我们发现脚本或者任务执行的时间不符合我们的预期，这个时候就应该想办法优化了。   

* 首先分析**慢**，慢的原因是什么  
  这个时候可以借助像 pfofile 或者性能更好的 cprofile 来调查函数的运行的耗时。借助 line_profiler分析每行代码的耗时。  

此次的优化直接分析代码：

```python
recon_db = ReconciliationMongo(NODE_DEFAULT).transaction
cil_db = CILMongo(NODE_DEFAULT).transaction
cil_transactions = list(cil_db.find(query))
count = len(cil_transactions)
index = 1
for cil_transaction in cil_transactions:
    try:
        merchant_code = cil_transaction['merchant_id']
        business_config = BusinessConfig.objects.filter(merchant_code=merchant_code).first()
        business_uid = business_config.business.uid.hex if business_config else None
        business_name = business_config.business.name if business_config else None
        order_number = None
```
发现上面代码的耗时其实主要就是在与mongo的网络IO上。

### 优化办法
* 问题既然是在IO上，自然想到利用多线程应该能加快执行时间
* 引入Python的并发库 **concurrent.futures**来启用多线程

```python
cil_db = CILMongo(NODE_DEFAULT).transaction
cil_transactions = cil_db.find(query)
count = cil_transactions.count()
with concurrent.futures.ThreadPoolExecutor(max_workers=threads_num) as executor:
    index = 1
    futures = (executor.submit(process, cil_transaction) for cil_transaction in cil_transactions)
    for future in concurrent.futures.as_completed(futures):
        if future.done():
            print('{}/{}'.format(index, count))
            index += 1

def process(cil_transaction):
    # 一波操作
```
这里启用多少线程数量，一般推荐 处理器数量 * 5。 应该根据CPU的使用情况测试找到一个比较合适的数量，这样效果比较理想。

### 测试运行(本地)
* 优化之前跑完指定的数据量，耗时 *340-350s*
* 优化之后跑完相同的数据量，10个线程 耗时 *40-45s*；15个线程*30-32s*
  
此次优化只是任务的一部分，继续》》》》》  

### 问题2
利用collection.Counter对字典做累加操作 

```python
counter = Counter({
    'amount': 0,
    'fee': 0,
    'original_amount': 0,
    'settlement_amount': 0,
    'deduct_points_amount': 0,
    'deduct_prepay_amount': 0,
    'deduct_pay_buff_amount': 0,
    'deduct_direct_amount': 0,
    'deduct_tracker_amount': 0,
    'deduct_huipay_amount': 0,
})
for transaction in transactions:
    counter += Counter({
        'amount': float(transaction['merchant_amount'].to_decimal()),
        'fee': float(transaction['merchant_processing_fee'].to_decimal()),
        'original_amount': float(transaction['original_amount'].to_decimal()),
        'settlement_amount': float(transaction['merchant_settlement_amount'].to_decimal()),
        'deduct_points_amount': float(transaction.get('deduct_points_amount', Decimal128('0')).to_decimal()),
        'deduct_prepay_amount': float(transaction.get('deduct_prepay_amount', Decimal128('0')).to_decimal()),
        'deduct_pay_buff_amount': float(
            transaction.get('deduct_pay_buff_amount', Decimal128('0')).to_decimal()),
        'deduct_direct_amount': float(transaction.get('deduct_direct_amount', Decimal128('0')).to_decimal()),
        'deduct_tracker_amount': float(transaction.get('deduct_tracker_amount', Decimal128('0')).to_decimal()),
        'deduct_huipay_amount': float(transaction.get('deduct_huipay_amount', Decimal128('0')).to_decimal()),
    })
``` 
分析Counter做累加性能可能不如直接对字典做累加操作，在ipython中做如下测试  

* 用 `%prun func()`   # profile 粗粒度分析整个函数的运行时间
* 用 `%lprun -f func func()`  # line_profiler 分析每一行代码的运行时间。首先通过 `%load_ext line_profiler`显示导入line__profiler 才能运行 %lprun  

下面为测试结果：
	![测试结果](https://pics.lxkaka.wang/test_counter_dict.jpeg)

上面测试结果清晰的展示 Counter 没给我们带来性能上的提升。所以，我们在写代码爽快的同时，当对代码性能有要求时，不确定的时候应该多验证，多测试，找到比较理想的方案。

