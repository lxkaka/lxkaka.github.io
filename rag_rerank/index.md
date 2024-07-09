# RAG 应用的关键步骤 - 优化搜索结果

在这篇[文章](https://www.lxkaka.wang/text-similarity/)里我们介绍了快速搭建语义搜索的实践方案。在这里我们会介绍语义搜索的进阶方案，包括使用开源模型构建文本  embedding、更好用的向量数据库以及介绍如何提高搜索的准确率。

### 开源 embedding 模型
我们之前使用的是 OpenAI 的 `text-embedding-ada-002`，目前有一些国内的开源模型在中文领域效果比 `text-embedding-ada-002` 要好。评测结果可以参考这个[排行榜](https://huggingface.co/spaces/mteb/leaderboard)。
这里我们以模型 `BAAI/bge-large-zh-v1.5` 为例演示如何使用开源模型。
我们还是使用 [llmindex](https://docs.llamaindex.ai/en/stable/index.html) 来作为工具包创建向量索引。

```python
def new_context(index_name):
    endpoint = "xxxx"
    api_version = "2023-05-15"

    llm = AOpenAI(
        engine="gpt35",
        model="gpt-35-turbo-16k",
        temperature=0.7,
        azure_endpoint=endpoint,
        api_key=key,
        api_version=api_version, )

    # 这部分代码展示了使用开源模型的方式
    if 'Bge' in index_name:
        model_name = "BAAI/bge-large-zh-v1.5"
        model_kwargs = {"device": "cpu"}
        encode_kwargs = {"normalize_embeddings": True}
        embedding = HuggingFaceBgeEmbeddings(
            model_name=model_name, model_kwargs=model_kwargs, encode_kwargs=encode_kwargs
        )
    elif 'Openai' in index_name:
        embedding = AzureOpenAIEmbedding(
            mode=OpenAIEmbeddingMode.SIMILARITY_MODE,
            model="text-embedding-ada-002",
            azure_deployment="text-embedding-ada-002",
            api_key=key,
            azure_endpoint=endpoint,
            api_version=api_version,
            max_retries=1,
            request_timeout=20, )
    else:
        raise ValueError('no valid model')

    service_context = ServiceContext.from_defaults(
        llm=llm,
        embed_model=embedding
    )
    return service_contex
```

### 向量数据库
目前可供选择的 vector database 还是很多的，大家可以参考这个[榜单](https://db-engines.com/en/ranking/vector+dbms)。
从部署成本、使用便捷、文档易读和性能等角度调研下来我们选择的是 [weaviate](https://weaviate.io/)。
>Weaviate 是一个低延迟矢量数据库，对不同媒体类型（文本、图像等）提供开箱即用的支持。它提供语义搜索、问答提取、分类、可定制模型 (PyTorch/TensorFlow/Keras) 等。Weaviate 在 Go 中从头开始构建，可存储对象和向量，允许将向量搜索与结构化过滤以及容错能力相结合。云原生数据库。这一切都可以通过 GraphQL、REST 和各种客户端编程语言进行访问。  
>快速查询    
Weaviate 通常在不到 100 毫秒的时间内对数百万个对象执行最近邻 (NN) 搜索。您可以在我们的基准页面上找到更多信息。
使用 Weaviate 模块摄取任何媒体类型 
使用最先进的 AI 模型推理（例如 Transformer）在搜索和查询时访问数据（文本、图像等），让 Weaviate 为您管理数据矢量化过程 - 或提供您自己的数据矢量化过程 向量。
组合向量和标量搜索  
Weaviate 允许高效、组合的矢量和标量搜索。例如，“过去 7 天内发表的与 COVID-19 大流行相关的文章”。Weaviate 存储对象和向量，并确保两者的检索始终高效。不需要第三方对象存储。
实时且持久  
即使当前正在导入或更新数据，Weaviate 也可让您搜索数据。此外，每次写入都会写入预写日志 (WAL)，以便立即持久写入 - 即使发生崩溃也是如此。  
水平扩展性  
根据您的具体需求扩展 Weaviate，例如最大摄取量、最大可能的数据集大小、每秒最大查询数等。  
成本效益  
非常大的数据集不需要完全保存在 Weaviate 的内存中。同时，可以利用可用内存来提高查询速度。这样可以有意识地进行速度/成本权衡，以适应每个用例。  
对象之间类似图形的连接  
以类似图形的方式在对象之间建立任意连接，以类似于数据点之间的现实生活连接。使用 GraphQL 遍历这些连接。  

使用示例如下：
```python
def create_weavite_vectorstore():
    service_context = context()
    storage_context = StorageContext.from_defaults(persist_dir=store_dir)
    # load old index
    index = load_index_from_storage(storage_context)

    embed_dict = index._vector_store._data.embedding_dict
    node_dict = index._docstore.docs

    nodes = []
    for node_id, node in node_dict.items():
        vector = embed_dict[node_id]
        node.embedding = vector
        nodes.append(node)

    # create client and a new collection
    weaviate_client = weaviate.Client(
        url="xxx",
    )
    vector_store = WeaviateVectorStore(
        weaviate_client=weaviate_client,
        index_name="TestIndex",
    )
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex(nodes, storage_context=storage_context, service_context=service_context)
    return index
```

### 管理索引
我们先实现一个工具类，每次都能使用这个类来方便的创建索引，更新索引或者查询。
```python
class VectorModel:
    def __init__(self, index_name=None):
        if not index_name:
            raise ValueError('no index')
        self.index_name = index_name
        logger.info("model init download and load index...")
        service_context = new_context(index_name)
        weaviate_client = weaviate.Client(
            url="xxxx",
            timeout_config=(3, 30),
        )
        vector_store = WeaviateVectorStore(
            weaviate_client=weaviate_client,
            index_name=self.index_name,
        )
        # load index
        self.index = VectorStoreIndex.from_vector_store(vector_store=vector_store, service_context=service_context)
        self.retriever = VectorIndexRetriever(
            index=self.index,
            similarity_top_k=10,
            # vector_store_query_mode=VectorStoreQueryMode.HYBRID,
        )
```
#### 创建索引
测试数据格式如下所示  

| id | biz |描述|
|---|-----|-----------|
|5|业务 1|["查看客户拜访记录", "浏览陪同拜访资料", "检索客户拜访详情", "筛选按姓名查找拜访记录", "按拜访地址寻找记录", "根据联系方式查询拜访信息"]|   
|6|业务 2|["创建和发布公司通知", "根据部门发送公告", "按工作年限筛选接收公告的员工", "向特定群体发送消息", "定向发布内部通知", "管理和发送组织公告"]|  
...

根据上面的数据创建索引     
```python
def make_index():
    file = '/test.csv'
    vm = VectorModel(index_name="TestIndex_Bge")
    documents = []
    with open(file) as f:
        reader = csv.reader(f)
        for i, r in enumerate(reader):
            id = r[0]
            biz = r[1]
            try:
                fns = json.loads(r[2])
            except:
                print(i, id)
                continue
            for fn in fns:
                documents.append(Document(
                    text=fn,
                    metadata={"page_id": id, "biz": biz}
                ))
                print(id, biz, fn)

    vm.index.refresh_ref_docs(documents)
```
#### 删除部分索引
删除部分索引示例  
```python
def update_objects():
    client = weaviate.Client("xxx")
    all_objects = client.data_object.get(class_name="TestIndex_Bge", limit=100)
    print('total objects: ', all_objects['totalResults'])
    for ob in all_objects['objects']:
        if ob['properties']['page_id'] in ['10', '27', '29', '42', '49']:
            print(ob['properties']['page_id'], ob['properties']['text'])
            client.data_object.delete(
                uuid=ob['id'],
                class_name=ob['class']
            )
```
#### 查询
```python
vm = VectorModel(index_name="Testndex_Bge")
res = m1.retriever.retrieve(query)[0]
```
示例结果如下  
```
Node ID: c7436e4d-db8b-4bd5-a891-b86ae8b2e550
Text: 浏览陪同拜访资料
Score:  0.486
```

### Rerank
Rerank 模型通过对候选文档列表进行重新排序，以提高其与用户查询语义的匹配度，从而优化排序结果。该模型的核心在于评估用户问题与每个候选文档之间的关联程度，并基于这种相关性给文档排序，使得与用户问题更为相关的文档排在更前的位置。这种模型的实现通常涉及计算相关性分数，然后按照这些分数从高到低排列文档。
这里我们使用并测试了两种 rerank 模型：闭源的 Cohere Rerank 模型 `rerank-multilingual-v2.0` 和 开源的 `bge-reranker-large`。   
使用示例如下：  
```python
reranker = CohereRerank(model="rerank-multilingual-v2.0", api_key="xxx")  

def bge_rerank(nodes, query):
    reranker = FlagReranker('BAAI/bge-reranker-large', use_fp16=True)
    reqs = [[query, n.text] for n in nodes]
    scores = reranker.compute_score(reqs)
    scores_with_index = [(i, s) for i, s in enumerate(scores)]
    return [nodes[s[0]] for s in sorted(scores_with_index, key=lambda x: x[1], reverse=True)]
```

#### 完整示例  
完整的评测代码如下  
```python
    file = '/test.csv'
    data = []
    m1 = VectorModel(index_name="TestIndex_Openai")
    m2 = VectorModel(index_name="TestIndex_Bge")
    with open(file) as f:
        reader = csv.reader(f)
        header = next(reader)
        for i, r in enumerate(reader):
            if not r[1]:
                continue
            res1 = m1.retriever.retrieve(r[1])
            r[3] = f"{res1[0].score} {res1[0].text} {res1[0].metadata}"
            r[4] = 'False'
            if res1[0].metadata.get('url') in r[2]:
                r[4] = 'True'

            res2 = m2.retriever.retrieve(r[1])
            r[5] = f"{res2[0].score} {res2[0].text} {res2[0].metadata}"
            r[6] = 'False'
            if res2[0].metadata.get('url') in r[2]:
                r[6] = 'True'

            # cohere rerank
            res4 = m1.reranker.postprocess_nodes(res1, query_str=r[1])[0]

            # bge rerank
            res5 = bge_rerank(res2, r[1])[0]

            r[7] = f"{res4.score} {res4.text} {res4.metadata}"
            r[8] = 'False'
            if res4.metadata.get('url') in r[2]:
                r[8] = 'True'
            r[9] = f"{res5.score} {res5.text} {res5.metadata}"
            r[10] = 'False'
            if res4.metadata.get('url') in r[2]:
                r[10] = 'True'
            data.append(r)
            print(i, r[1])

    with open('/test_res.csv', 'w') as w:
        writer = csv.writer(w)
        writer.writerow(header)
        for d in data:
            writer.writerow(d)
```
测试结果如下所示（省略内容）

| query | 预期 id | openai | bge | openai+cohere rerank | bge+bge rerank |
| ----- | ------- | ------ | --- | -------------------- | -------------- |
| 看拜访记录 | 5 | 5 | 5 | 5 | 5 |
| 查看商户数据 | 10 | 8 | 46 | 10 | 10 |
...
| - | - | 72.5% | 67.5% | 77.5% | 85% |


在这篇文章里介绍了我们怎么去创建 RAG 应用的思路和实践，相信能提供一些实际的帮助。
