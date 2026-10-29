# Django特殊使用场景集合(updated at 2017-12-21）


### 》query的时候 QuerySet.first()  和 QuerySet[0]的区别:  
* 指明了排序，即 `order_by('field')`的时候， **first()**和**[0]**是等价的 都是取出按照指定字段排序的第一个结果  
如：

    ```python  
reh = HuiPayTransaction.objects.using('read').values('account_id').annotate(count=Count('account_id')).order_by('-account_id')
reh.first()
Out[139]: {'account_id': 291589, 'count': 3}
reh[0]
Out[140]: {'account_id': 291589, 'count': 3}
    ```
 
* 如果没有指明排序，这个时候 **first()** 会默认用 `order_by('pk')`排序。返回的结果就是数据库里id最小的那一条记录，与**[0]**返回的不一致  
如： 

    ```python
reh = HuiPayTransaction.objects.using('read').filter(account_id__gte=0).values('account_id').annotate(count=Count('account_id'))
reh.first()
Out[154]: {'account_id': 911, 'count': 1}
reh[0]
Out[155]: {'account_id': 0, 'count': 27}
    ```

### 》 联表查的时候，重复字段指定表名
* 如下查询  

	```python
	query_set = MerchandiseLog.objects.using('read').select_related('merchandise').filter(**query).extra(
	    {'date_created': 'Date(created_at)'}).values_list('date_created')      
	```

	对应的sql

	```
	SELECT (Date(created_at)) AS "date_created" FROM "zmall_merchandiselog" INNER JOIN "zmall_merchandise" ON ( "zmall_merchandiselog"."merchandise_id" = "zmall_merchandise"."id" ) WHERE ("zmall_merchandiselog"."business_group_id" = 1 AND "zmall_merchandise"."folder_id" = 2 AND "zmall_merchandiselog"."created_at" >= 2017-09-01 00:00:00 AND "zmall_merchandiselog"."created_at" <= 2017-09-05 23:59:59.999999 AND "zmall_merchandiselog"."log_type" = points_buy)
	```
	<font color='red'>报错</font>：**`ambiguous column name: created_at`** 
	
	这个时候问题就很明显了，表 `zmall_merchandiselog` 和表 	`zmall_merchandise`都有字段 created_at,数据库当然不知道	你要用哪个 `created_at`

* **正确姿势**, 指明表名
	
	```python
	query_set = MerchandiseLog.objects.using('read').select_related('merchandise').filter(**query).extra(
        {'date_created': 'Date(zmall_merchandiselog.created_at)'}).values_list('date_created')
	```

	对应的sql
	
	```
	SELECT (Date(zmall_merchandiselog.created_at)) AS "date_created" FROM "zmall_merchandiselog" INNER JOIN "zmall_merchandise" ON ( "zmall_merchandiselog"."merchandise_id" = "zmall_merchandise"."id" ) WHERE ("zmall_merchandiselog"."created_at" <= 2017-09-05 23:59:59.999999 AND "zmall_merchandiselog"."log_type" = points_buy AND "zmall_merchandise"."folder_id" = 2 AND "zmall_merchandiselog"."created_at" >= 2017-09-01 00:00:00 AND "zmall_merchandiselog"."business_group_id" = 1)
	```
	
### 》多次aggragate合并成一次查询
* 如下查询，我们想按条件count某些字段，甚至其中的字段需要先annotate

	```python
    # last_visited_date 百分位数
    last_visited_date_rate = dw_membership.filter(last_visited_date__lte=member_data.get('last_visited_date')).\
        order_by('last_visited_date').count() / total_count
    # visit_count 百分位数
    visit_count_rate = dw_membership.filter(visit_count__lte=member_data.get('visit_count')).\
        order_by('visit_count').count() / total_count
    # consumptions_amount 百分位数
    consume_amount_rate = dw_membership.filter(consumptions_original_amount__lte=member_data.get('consume_amount')).\
        order_by('consumptions_original_amount').count() / total_count
    # average_consume 百分位数
    average_consume_rate = dw_membership.annotate(average_consume=ExpressionWrapper(
        F('consumptions_original_amount') / F('consumptions_count'), output_field=DecimalField())).filter(
        average_consume__lte=member_data.get('average_consume')).count() / total_count
   ```
  用 `Case` `When`合并以下操作为一个query
  
  ```python
  query_res = dw_membership.aggregate(
        last_visited_date_counter=Count(Case(   # 比当前会员到店间隔大的会员数
            When(last_visited_date__lte=member_data.get('last_visited_date'), then=F('membership_uid')))),
        visit_count_counter=Count(Case(  # 比当前会员到店次数少的会员数
            When(visit_count__lte=member_data.get('visit_count'), then=F('membership_uid')))),
        consume_amount_counter=Count(Case(  # 比当前会员消费金额低的会员数
            When(consumptions_original_amount__lte=member_data.get('consume_amount'), then=F('membership_uid')))))
```
合并操作时善用 `Case`, `When`再搭配上aggregate操作比如 `Count`, `Sum`, `Max`,`Min`等，会起到不错的效果。但最好充分测试，很可能因为Django的版本问题存在bug。  
比如这样使用:

	```python
dw_membership.annotate(average_consume=ExpressionWrapper(
        F('consumptions_original_amount') / F('consumptions_count'), output_field=DecimalField())).aggregate(average_consume_amount_counter=Count(Case(  # 比当前会员平均消费金额低的会员数
            When(average_consume__lte=member_data.get('average_consume'), then=F('membership_uid')))))
    ```
 会有这样的[bug](https://code.djangoproject.com/ticket/25307),  1.11以后应该已经修复了...


### 》 特殊场景执行raw sql可以大大提高性能   

场景举例，读取数据库里的数据并上传。  
我们看下面这样一个例子, 取到数据库的每行记录并写入文件。在测试过程中会发现4000多条数据竟然耗时要30多秒，性能是我们不能接受的。定位瓶颈不是一蹴而就的，从代码方面来说是需要逐步分析缩小范围，不确定的地方动用性能分析工具帮助定位。下面展示的代码和分析结果就是确定瓶颈范围后进行的最后一步的定位。

```python
def _fill_excel_data(sheet_name, columns, data):
    """
    * 通用的填充 Excel 数据的函数，返回文件的 BytesIO 对象, xls格式上限是65536 rows 
    * 这里data是QuerySet
    """
    wb = xlwt.Workbook(encoding='utf-8')
    ws = wb.add_sheet(sheet_name)
    for i, title in enumerate(columns.keys()):
        ws.write(0, i, title)
    for i, record in enumerate(data):
        row_num = i + 1
        for j, func in enumerate(columns.values()):
        		tmp = func(record)
            ws.write(row_num, j, tmp)
    attached_file = BytesIO()
    wb.save(attached_file)
    return attached_file
```
我们用 `line_profiler`分析这段代码的主要耗时在什么地方，下面是分析结果
![分析结果]( https://pics.lxkaka.wang/%E4%B8%8B%E8%BD%BD%E5%88%86%E6%9E%90.jpeg)
在分析结果我们清楚的看到，绝大部分耗时是在 `func(record)`这一行, 而`record`是QuerySet的一条记录，这行代码真正执行的操作时去数据库里拉取查询结果。所以我们找到了瓶颈。就是 **每一行记录都去数据库查询一次，巨大的IO开销**。  

* 解决方案：减少数据库查询次数。实际上就是避开Django ORM的 lazy load特性，一次数据库查询就把所需记录load到内存中，然后在进行写文件操作。实现方案就是**执行raw sql查询到所有记录**。
* 步骤：  
	1. 从 QuerySet.query解析raw sql
	2. 执行raw sql 
	3. 处理结果

	代码如下：
	
	```python
	sql, params = data.query.sql_with_params()
	def direct_fetch_with_sql(sql, params):
	    """一些特殊场景可以用此函数来performing raw sql"""
	    cursor = connections['read'].cursor()
	    cursor.execute(sql, params)
	    return dictfetchall(cursor)
	
	def dictfetchall(cursor):
	    """把fetchall返回的tuple转换为dict"""
	    columns = [col[0] for col in cursor.description]
	    return [
	        dict(zip(columns, row))
	        for row in cursor.fetchall()
    ]
	
	```
	最后优化代码如下：
	
	```python
	def _fill_excel_data(sheet_name, columns, data):
	    """ 通用的填充 Excel 数据的函数，返回文件的 BytesIO 对象, xls格式上限是65536 rows """
	    wb = xlwt.Workbook(encoding='utf-8')
	    ws = wb.add_sheet(sheet_name)
	    for i, title in enumerate(columns.keys()):
	        ws.write(0, i, title)
        sql, params = data.query.sql_with_params()
        data = direct_fetch_with_sql(sql, params)
	    for i, record in enumerate(data):
	        row_num = i + 1
	        for j, func in enumerate(columns.values()):
	            ws.write(row_num, j, func(record))
	    attached_file = BytesIO()
	    wb.save(attached_file)
	    return attached_file
	```
	经测试，性能得到几何级的提升。20万条记录写入文件并上传只需要30秒。
	
**注意**：对于大数据量的QuerySet进行适当的分隔，不要撑爆内存。
	
###《 单元测试是否需要覆写tearDown

* 如果使用`Python`内建的`unittest.TestCase`来作为UT的基类, 注意需要覆写`tearDown`来实现case执行完后的清理工作
如：

```python
class MyTestCae(unittest.TestCase):
    def setUp(self):
        self.business = Business.objects.create(name='test', province='ShangHai')
    
    def tearDown(self):
        Business.objects.all().delete()
```
* 如果使用`Django`的`rest_framework`的`APITestCase`则不需要实现数据库的清理工作。可以看到下面这段代码，在`setUp`里开启transaction，执行完每个case后，`tearDown`会roll back transaction。

```python
    @classmethod
    def setUpClass(cls):
        super(TestCase, cls).setUpClass()
        if not connections_support_transactions():
            return
        cls.cls_atomics = cls._enter_atomics()

        if cls.fixtures:
            for db_name in cls._databases_names(include_mirrors=False):
                    try:
                        call_command('loaddata', *cls.fixtures, **{
                            'verbosity': 0,
                            'commit': False,
                            'database': db_name,
                        })
                    except Exception:
                        cls._rollback_atomics(cls.cls_atomics)
                        raise
        try:
            cls.setUpTestData()
        except Exception:
            cls._rollback_atomics(cls.cls_atomics)
            raise

    @classmethod
    def tearDownClass(cls):
        if connections_support_transactions():
            cls._rollback_atomics(cls.cls_atomics)
            for conn in connections.all():
                conn.close()
        super(TestCase, cls).tearDownClass()

```
所以，在写UT时一定要注意case之间的环境隔离问题，不要出现脏数据污染了其他case的情况。需要手动清理时，一定要覆写`tearDown`方法

