# Mongo查询优化-借助explain分析查询计划和执行信息


### 背景
有这样的的批量查询需求，从mongo里要查每一个月内符合条件的交易流水总和。单条查询如下，可以看到查询条件其实很简单。但是测试的时候，发现每次执行的时候mongo的机器的cpu都跑满了，然后结果就是所有查询都拖拖慢了，甚至卡住。

```python
query = {
    'transaction_date': {'$gte': int_start, '$lte': int_end},
    'business_uid': {'$in': [business.uid.hex for business in businesses]},
}
result = db.aggregate([
	{'$match': query},
	{'$group': {
    	'_id': '',
    	'total_transaction_amount': {'$sum': '$transaction_amount'},
	}}
])
```
针对这种情况，从两方面来排查。  
**1.** 看单条查询本身是否慢查询  
**2.** 看mongo server是否cpu确实性能有限。

### 解决方案
从CPU跑满的问题出发，首先cpu杀手会有下面几种case:   
 
* 全表扫描    
* 索引不合理
* 大量的数据排序

回到我们之前的查询，我们只是做了aggregate的操作，首先排除存在大量的数据排序的问题。
这时候需要分析一波查询计划，需要用到 `explain`。  
**explain**有三种模式：

* queryPlanner  
这是默认模式，queryPlanner模式下并不会去真正进行query语句查询，而是针对query语句进行执行计划分析并选出winning plan。简单来说就是优化查询
* executionStats  
字面意思，返回优化查询（winning plan）执行的详细信息
* allPlansExecution  
这种模式除了winning plan 还包括其他方案的执行的详细信息
详细信息可查看官方文档[这里](https://docs.mongodb.com/manual/reference/method/db.collection.explain/index.html)。

这里需要**注意**: `aggregate`只支持*queryPlanner*模式，查看pipline是怎么执行的。

回到之前的查询，用`expalain`分析查询如下:

```
db.transaction.find({
    transaction_date: {
        $gte: 20170901,
        $lte: 20170930
    }
    ,
    business_uid: {
        $in: [
            "911c98acc17a4b9c8fd7cf200f3325f8",
            "8e870721395b46b4be2f257ef45a8547"
        ]
    }
}).explain("executionStats");
```
结果如下(这里为了展示一下explain的返回结果就全部显示)：

```
{ 
    "queryPlanner" : {
        "plannerVersion" : 1.0, 
        "namespace" : "reconciliation.transaction", 
        "indexFilterSet" : false, 
        "parsedQuery" : {
            "$and" : [
                {
                    "transaction_date" : {
                        "$lte" : 20170930.0
                    }
                }, 
                {
                    "transaction_date" : {
                        "$gte" : 20170901.0
                    }
                }, 
                {
                    "business_uid" : {
                        "$in" : [
                            "8e870721395b46b4be2f257ef45a8547", 
                            "911c98acc17a4b9c8fd7cf200f3325f8"
                        ]
                    }
                }
            ]
        }, 
        "winningPlan" : {
            "stage" : "COLLSCAN", 
            "filter" : {
                "$and" : [
                    {
                        "transaction_date" : {
                            "$lte" : 20170930.0
                        }
                    }, 
                    {
                        "transaction_date" : {
                            "$gte" : 20170901.0
                        }
                    }, 
                    {
                        "business_uid" : {
                            "$in" : [
                                "8e870721395b46b4be2f257ef45a8547", 
                                "911c98acc17a4b9c8fd7cf200f3325f8"
                            ]
                        }
                    }
                ]
            }, 
            "direction" : "forward"
        }, 
        "rejectedPlans" : [

        ]
    }, 
    "executionStats" : {
        "executionSuccess" : true, 
        "nReturned" : 1123.0, 
        "executionTimeMillis" : 1413.0, 
        "totalKeysExamined" : 0.0, 
        "totalDocsExamined" : 927973.0, 
        "executionStages" : {
            "stage" : "COLLSCAN", 
            "filter" : {
                "$and" : [
                    {
                        "transaction_date" : {
                            "$lte" : 20170930.0
                        }
                    }, 
                    {
                        "transaction_date" : {
                            "$gte" : 20170901.0
                        }
                    }, 
                    {
                        "business_uid" : {
                            "$in" : [
                                "8e870721395b46b4be2f257ef45a8547", 
                                "911c98acc17a4b9c8fd7cf200f3325f8"
                            ]
                        }
                    }
                ]
            }, 
            "nReturned" : 1123.0, 
            "executionTimeMillisEstimate" : 1388.0, 
            "works" : 927975.0, 
            "advanced" : 1123.0, 
            "needTime" : 926851.0, 
            "needYield" : 0.0, 
            "saveState" : 7259.0, 
            "restoreState" : 7259.0, 
            "isEOF" : 1.0, 
            "invalidates" : 0.0, 
            "direction" : "forward", 
            "docsExamined" : 927973.0
        }
    }, 
    "serverInfo" : {
        "host" : "ip-172-31-7-170", 
        "port" : 27017.0, 
        "version" : "3.4.5", 
        "gitVersion" : "520b8f3092c48d934f0cd78ab5f40fe594f96863"
    }, 
    "ok" : 1.0
}

```
通过分析返回结果，看到 winningPlan 和executionStats里stage(查询方式)都是 **COLLSCAN** 即全表扫描。所以，cpu跑满的原因就是查询的时候是全表扫描。

解决: 很自然，我们已有的索引没用。需要针对查询建立复合索引

```
db.transaction.createIndex({transaction_date: 1, business_uid: 1})
```

在看查询分析结果(这里只展示关键部分)

```
"executionStats" : {
        "executionSuccess" : true, 
        "nReturned" : 1123.0, 
        "executionTimeMillis" : 7.0, 
        "totalKeysExamined" : 1185.0, 
        "totalDocsExamined" : 1123.0, 
        "executionStages" : {
            "stage" : "FETCH", 
            "nReturned" : 1123.0, 
            "executionTimeMillisEstimate" : 10.0, 
            "works" : 1186.0, 
            "advanced" : 1123.0, 
            "needTime" : 62.0, 
            "needYield" : 0.0, 
            "saveState" : 9.0, 
            "restoreState" : 9.0, 
            "isEOF" : 1.0, 
            "invalidates" : 0.0, 
            "docsExamined" : 1123.0, 
            "alreadyHasObj" : 0.0, 
            "inputStage" : {
                "stage" : "IXSCAN", 
                "nReturned" : 1123.0, 
                "executionTimeMillisEstimate" : 10.0, 
                "works" : 1186.0, 
                "advanced" : 1123.0, 
                "needTime" : 62.0, 
                "needYield" : 0.0, 
                "saveState" : 9.0, 
                "restoreState" : 9.0, 
                "isEOF" : 1.0, 
                "invalidates" : 0.0, 
                "keyPattern" : {
                    "transaction_date" : 1.0, 
                    "business_uid" : 1.0
                }, 
                "indexName" : "transaction_date_1_business_uid_1", 
                "isMultiKey" : false, 
                "multiKeyPaths" : {
                    "transaction_date" : [

                    ], 
                    "business_uid" : [

                    ]
                }, 
                "isUnique" : false, 
                "isSparse" : false, 
                "isPartial" : false, 
                "indexVersion" : 2.0, 
                "direction" : "forward", 
                "indexBounds" : {
                    "transaction_date" : [
                        "[20170901.0, 20170930.0]"
                    ], 
                    "business_uid" : [
                        "[\"8e870721395b46b4be2f257ef45a8547\", \"8e870721395b46b4be2f257ef45a8547\"]", 
                        "[\"911c98acc17a4b9c8fd7cf200f3325f8\", \"911c98acc17a4b9c8fd7cf200f3325f8\"]"
                    ]
                }, 
                "keysExamined" : 1185.0, 
                "seeks" : 63.0, 
                "dupsTested" : 0.0, 
                "dupsDropped" : 0.0, 
                "seenInvalidated" : 0.0
            }
        }
    }
```
`stage`已经变为 **FETCH**(根据索引去检索指定document, inputStage是 IXSCAN),
关键指标 **executionTimeMillis**为7（由1413将为7).
测试，查询速度飞起来了，观察CPU占用也是正常水平。

总结：  
当查询mongo遇到性能或速度问题时，要善用explain或者在服务器端开启profile帮助分析查询计划和执行信息，然后针对查询做出相应的优化；  
当优化过后，发现查询都比较合理，都用上了高效的索引，还有性能问题，很可能真的需要升级一波服务器了（毕竟mongo相对mysql真的更占cpu和内存）。






