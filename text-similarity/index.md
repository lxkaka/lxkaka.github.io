# 快速搭建文本语义搜索

想象这样一个场景我们文案团队每天都会根据需求产出高质量的文案，随着需求的增加我们系统已经累积了很多优质文案。那么我们是否可以根据新的需求描述去搜索文案库里已有的文案呢？利用文本相似度检测我们能实现一个这样既能提高效率又能节省成本的文案搜索方案。
在这篇文章里我们介绍一下快速搭建文本语义搜索系统的方法。

### 文本处理
文本由两部分组成 *text* + *metadata*，这里的 metadata 可以理解成是 text 的一些属性。通过这些属性我们可以找到跟 text 关联的其他信息。
在我们这个例子里我们的每段 `text` 对应一个 `task_id `，并且 metadata 我们只关心这个 task id。部分数据如下
```
571600,"xxx豆花渎鱼——入口图文案：

1、宠粉双十二，桌桌有礼拿
2、「黔」方双十二，霸王餐送达
3、双十二来袭， 免单指到「礼」
4、12.12 | 抽奖赢好礼，这单老板请"
571599,"黔渔翁豆花渎鱼——商户通文案：

1、双十二「渔」你同乐，免单奖砸中「礼」了
2、<12.12剧透>抽奖大乐透，壕礼人人有 | 这一桌老板买单！
3、双十二提「黔」到，免单大奖播报 | 逢抽必中，来者就送
4、爱要「奖」出来，双十二特派🎁敢抽就敢送，霸王餐派送

+辅助文案：
凭买单小票抽奖
免单、霸王餐、代金券、神秘礼拼手气"
572021,"1、优雅姿造匠心制，现做鲜美宴贵宾
2、海鲜姿造聚高端食材，商务宴请迎八方贵客
3、深海鲜美入馔，视味姿造盛宴，静待诸位入席"
571440,"xxx核桃炭烤串 - 商户通
1. 烤肉局申请加入跨年PLAN！牛羊串X排骨筋，好友欢聚撸过瘾！
2. 元旦当“燃”这一串！牛羊日日鲜，老铁酷酷炫！
3. 2023-2024舌尖换乘点 | 和快乐“串”通，欢聚更尽兴！
4. “元”气开烤，“旦”愿美好！围炉聚老友，火热烤肉季！

"
570781,"xxx小酒馆——推荐菜文案：

【羊肉汤锅】
暖身汤力荐，领鲜三十年。慢火足时酝酿，开锅满室浓香，除了爱无添加。汤色乳白，汤味鲜香，羊肉无膻，香醇浓厚。人生百味，羊汤抚慰

【现烤羊腿】
技法炉火纯青，方得羊香四溢。千里挑一羊腿，传统炭火炙烤，披上油亮新装。外焦香酥脆，内鲜嫩多汁，撕着吃才够味！

【火焰鱼羊鲜】
双鲜论剑，唇齿流连。烈烈火焰之上，锡纸一方天地，鱼与羊尽释本味。鱼肉吸收羊肉浓香，羊肉吸收鱼肉鲜甜，尽释“鲜”字奥义。"
```
我们把历史数据先导出到 csv, 然后进行如下处理
```python
def load(file):
    documents = []
    with open(file) as f:
        reader = csv.reader(f)
        next(reader)
        for record in reader:
            documents.append(record)
    return documents
```

### 创建索引
想通过语义准确的匹配到文本，最关键的是把文本转换为 `embedding`然后建立向量索引库。这里我们用的模型是 openai 的 `text-embedding-ada-002`。为了高效的创建以及后续的查询，这些繁琐的工作我们不需要每行都自己实现，[llmindex](https://docs.llamaindex.ai/en/stable/index.html)可以帮助我们快速来搭建。
通过下面的代码我们创建了索引并持久化到了本地文件
```python
def context():
    embedding_llm = AzureOpenAIEmbedding(
        mode=OpenAIEmbeddingMode.SIMILARITY_MODE,
        model="text-embedding-ada-002",
        azure_deployment="text-embedding-ada-002",
        api_key=openai.api_key,
        azure_endpoint=endpoint,
        api_version=openai.api_version,
        max_retries=1,
        request_timeout=20, )

    # max LLM token input size
    max_input_size = 4096
    # set number of output tokens
    num_output = 500
    # set maximum chunk overlap
    max_chunk_overlap = 20
    chunk_size_limit = 1

    # prompt_helper = PromptHelper(max_input_size, num_output)
    service_context = ServiceContext.from_defaults(
        embed_model=embedding_llm,
        # prompt_helper=prompt_helper
    )
    return service_context

def make_index(file):
    service_context = context()
    documents = []
    docs = load(file)
    for doc in docs:
        documents.append(Document(
            text=doc[1],
            metadata={"id": doc[0]}
        ))
    index = VectorStoreIndex.from_documents(documents, service_context=service_context)
    index.storage_context.persist(persist_dir=store_dir)
    return index
```

### 查询
我们需要先把索引加载到内存中，然后查出相似度最高的 3 个文案
```python
def query(q):
    service_context = context()
    storage_context = StorageContext.from_defaults(persist_dir=store_dir)
    # load index
    index = load_index_from_storage(storage_context, service_context=service_context)
    retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=3,
    )
    res = retriever.retrieve(q)
    for node in res:
        print(node.score)
        print(node.text)
        print(node.metadata.get("id"))
```

结果示例：
```python
from redbook_notes.similarity.service_context import make_index
file = "/Users/wanglinxiao/Desktop/文案提需.csv"
make_index(file)
Out[4]: <llama_index.indices.vector_store.base.VectorStoreIndex at 0x1695375e0>
from redbook_notes.similarity.service_context import query
q = "羊肉推荐菜"
query(q)
0.8669767534968357
xx小酒馆——推荐菜文案：
【羊肉汤锅】
暖身汤力荐，领鲜三十年。慢火足时酝酿，开锅满室浓香，除了爱无添加。汤色乳白，汤味鲜香，羊肉无膻，香醇浓厚。人生百味，羊汤抚慰
【现烤羊腿】
技法炉火纯青，方得羊香四溢。千里挑一羊腿，传统炭火炙烤，披上油亮新装。外焦香酥脆，内鲜嫩多汁，撕着吃才够味！
【火焰鱼羊鲜】
双鲜论剑，唇齿流连。烈烈火焰之上，锡纸一方天地，鱼与羊尽释本味。鱼肉吸收羊肉浓香，羊肉吸收鱼肉鲜甜，尽释“鲜”字奥义。
570781
0.862087523108285
新鲜事：
寻欢主推•重磅食材
本店当家花旦，牛羊大有来头
澳洲谷饲牛肉，脂香浓郁，鲜嫩多汁
天然草原羊肉，口感细腻，味美无膻
缤纷串串尽情开涮，从这「娌」开启温暖冬日！
571812
0.8364552439695493
金都城——推荐菜文案：
【黄金脆皮猪手】
食指大动，肉控特供。寻味三峡库区，上乘巴东黑猪，蒸卤炸三部曲，十几小时工序，蜕变喷香油亮。咔滋咔滋入嘴，内里多汁Q弹，滋味妙不可言。
【酥不腻烤鸭】
金黄酥脆，京城至味。烹鸭自有金牌法则，×道工序换得焦糖鸭色。皮质酥脆入魂，鸭肉细嫩多汁，
味入肌理，带来酥而不腻的舌尖体验。
【石锅蝶鱼头】
锅气食足，心胃满足。水越深鱼越鲜，拾味深海海域，石锅慢入味，锁住丰腴鲜美，开盖满室鱼香。裹满汤汁入口，滑嫩味厚，回味绵长。
【金都特色脆皮肉丁】
金字招牌，下饭好菜。黄金六两松板肉，一头猪仅产半斤，辅以秘法烹制，释放无尽鲜美，口感层层递进。物以稀为贵，唇齿流连回味。
【梅干菜红烧肉】
人间尤物，味蕾倾慕。灵魂CP同烹，呈现酱红色泽。食之软烂醇香，口感肥而不腻。梅干菜增添清新气息，乍吃无波澜，再品回味长。
【酥皮虾】
热卖风味，快乐来会。刚捞出来的鲜虾，热油磨炼金皇甲。一口咔滋脆，一口Q弹爽，吮指回味，老少皆宜。
572779
```
可以看到最匹配的结果是我们示例数据中的第三段文案，内容还是比较匹配的。

### Redis Vector Search
上面的方案有两个问题
1. 索引持久化到了文件，对于容器化服务，发版之前我们需要把索引文件先上传，等待新容器启动后需要下载索引文件。整个过程容易出错和耗时，可用性不高；
2. 当文本量巨大不光需要更大的内存，更显著的问题是查询性能会下降的很厉害
为了解决上面的问题我们需要引入向量数据库，这里我们使用了 redis-search 来存储和查询 embedding。

#### 创建索引
```python
def new_make_index(file):
    service_context = context()
    documents = []
    docs = load(file)
    for doc in docs:
        documents.append(Document(
            text=doc[1],
            metadata={"id": doc[0]}
        ))
    vector_store = RedisVectorStore(
        index_name="vector_index",
        index_prefix="zh",
        redis_url="redis://localhost:6379",  # Default
        overwrite=True,
    )

    # create storage context
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_documents(documents, service_context=service_context, storage_context=storage_context)
    return index
```

#### 查询
```python
def new_query(d):
    service_context = context()
    vector_store = RedisVectorStore(
        index_name="vector_index",
        index_prefix="zh",
        redis_url="redis://localhost:6379",  # Default
        overwrite=True,
    )
    index = VectorStoreIndex.from_vector_store(vector_store=vector_store, service_context=service_context)
    retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=3,
    )
    res = retriever.retrieve(d)
    for node in res:
        print(node.score)
        print(node.text)
        print(node.metadata.get("id"))
```
结果示例
```python
from redbook_notes.similarity.service_context import new_make_index
file = "/Users/wanglinxiao/Desktop/文案提需.csv"
new_make_index(file)
Out[4]: <llama_index.indices.vector_store.base.VectorStoreIndex at 0x16f841a00>
from redbook_notes.similarity.service_context import new_query
q = "羊肉推荐菜"
new_query(q)
0.866977393627
太和小酒馆——推荐菜文案：
【羊肉汤锅】
暖身汤力荐，领鲜三十年。慢火足时酝酿，开锅满室浓香，除了爱无添加。汤色乳白，汤味鲜香，羊肉无膻，香醇浓厚。人生百味，羊汤抚慰
【现烤羊腿】
技法炉火纯青，方得羊香四溢。千里挑一羊腿，传统炭火炙烤，披上油亮新装。外焦香酥脆，内鲜嫩多汁，撕着吃才够味！
【火焰鱼羊鲜】
双鲜论剑，唇齿流连。烈烈火焰之上，锡纸一方天地，鱼与羊尽释本味。鱼肉吸收羊肉浓香，羊肉吸收鱼肉鲜甜，尽释“鲜”字奥义。
570781
```
可以看到和上面的内存索引结果是一致的

#### 更新索引
```python
    service_context = context()
    vector_store = RedisVectorStore(
        index_name="vector_index",
        index_prefix="zh",
        redis_url="redis://localhost:6379",  # Default
        overwrite=False,
    )
    index = VectorStoreIndex.from_vector_store(vector_store=vector_store, service_context=service_context)
    index.insert(Document(text="text", metadata={"id": 123}))
```
