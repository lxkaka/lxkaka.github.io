# 基于文档的 RAG 应用优化方案

基于内部文档的知识问答是我们内部 AI 助手的一个模块，这个模块构建在之前[文章](https://www.lxkaka.wang/rag_rerank/)基础之上即完整的 RAG(Retrieval-Augmented Generation) 应用。
我们知道对于 RAG 应用来说，生成结果准确与否的关键因素是检索的结果即给 LLM 提供的上下文，在这篇文章里我们介绍基于文档类型的 RAG 构建并介绍如何优化检索结果。

###  一般的 Pipeline
#### 1. 索引工具类 
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
```
#### 2. 构建索引
```python
def make_index():
    node_parser = SentenceSplitter()

    documents = SimpleDirectoryReader(
        input_files=["//Downloads/公司制度文档/人力资源制度/员工福利管理制度.pdf"],
        # input_dir="/Downloads/公司制度文档",
        recursive=True,
    ).load_data()

    # extract nodes
    nodes = node_parser.get_nodes_from_documents(documents)
    # build index
    vm = VectorModel(index_name="TestIndex_v1")
    vm.index.build_index_from_nodes(nodes)
```
#### 3.  retriver
```python
from llama_index.core.retrievers import VectorIndexRetriever

retriever = VectorIndexRetriever(
    index=vm.index,
    similarity_top_k=3,
    vector_store_query_mode=VectorStoreQueryMode.HYBRID,
)
```
#### 4. 构建 chatengine
```python
def query(q, index=None):
    vm = VectorModel(index_name=index)
    chat_engine = vm.index.as_chat_engine(
        chat_mode="context",
        similarity_top_k=2,
        vector_store_query_mode=VectorStoreQueryMode.HYBRID,
        # alpha=0.5,
        system_prompt="你是一个公司内部的智能助手，你会根据 context 回答用户的问题。当没有 context information 或者 context information 没有提供与用户问题相关且有用的信息你必须提示用户没找到相关信息并且不做进一步的回答。",
        # the target key defaults to `window` to match the node_parser's default
        node_postprocessors=[
            # reranker,
            MetadataReplacementPostProcessor(target_metadata_key="window"),
        ]
    )
    answer = chat_engine.chat(q)
    return answer
```
示例结果如下   
```python
query('婚假有几天', index='TestIndex_v1')

# answer 如下
婚假的具体天数并未在给出的上下文中明确说明，但公司会根据工作地城市政策给予婚假，并且员工需要提前15天提交休假申请。建议您查看最新的工作地城市政策或直接咨询人力资源部门获取准确的婚假天数信息。
```
我们的文档中其实包含了婚假的信息，但最终 LLM 并没有正确回答。通过 debug 我们发现问题是检索到的参考信息缺失了一部分。
通过分析具体的文档和对应的索引我们发现主要存在两类主要问题
1. PDF 文档带有表格或者其他类型的格式，解析后的文本可能会出现错乱  
2.  默认的 PDF 文档解析器按照 page 读取，同一段上下文分属连续的两页就可能导致检索的信息不完整      
优化方案如下  


### 自定义 PDFReader     
为了兼容不同格式的 PDF 我们自定义了 PDF  读取类，在这里我们引入了 llmsherpa [LayoutPDFReader](https://github.com/nlmatics/llmsherpa?tab=readme-ov-file#layoutpdfreader)
```python
"""Custom PDF Loader."""
from typing import List, Optional

from llama_index.core import SimpleDirectoryReader
from llama_index.core.readers.base import BaseReader
from llama_index.core.schema import Document


class CustomPDFLoader(BaseReader):
    """CustomPDFLoader uses nested layout information such as sections, paragraphs, lists and tables to smartly chunk PDFs for optimal usage of LLM context window.

    Args:
        llmsherpa_api_url (str): Address of the service hosting llmsherpa PDF parser
    """

    def __init__(
            self,
            llmsherpa_api_url: str = None,
            input_dir: Optional[str] = None,
            input_files: Optional[List] = None,
    ) -> None:
        super().__init__()
        from llmsherpa.readers import LayoutPDFReader
        self.base_reader = SimpleDirectoryReader(input_dir=input_dir, input_files=input_files, recursive=True)

        self.pdf_reader = LayoutPDFReader(llmsherpa_api_url)

    def load_data(self) -> List[Document]:
        """Load data and extract table from PDF file.

        Returns:
            List[Document]: List of documents.
        """
        documents = []

        files = self.base_reader.input_files
        for file in files:
            filename = str(file)
            metadata = self.base_reader.file_metadata(filename)

            doc = self.pdf_reader.read_pdf(filename)
            for chunk in doc.chunks():
                metadata.update({"chunk_type": chunk.tag})
                document = Document(
                    text=chunk.to_context_text(), metadata=metadata
                )
                document.excluded_embed_metadata_keys.extend(
                    [
                        "chunk_type"
                        "file_name",
                        "file_type",
                        "file_size",
                        "creation_date",
                        "last_modified_date",
                        "last_accessed_date",
                    ]
                )
                document.excluded_llm_metadata_keys.extend(
                    [
                        "chunk_type"
                        "file_name",
                        "file_type",
                        "file_size",
                        "creation_date",
                        "last_modified_date",
                        "last_accessed_date",
                    ]
                )
                documents.append(document)
        return documents

```

###  SentenceWindowNodeParser
SentenceWindowNodeParser 将所有文档拆分为单独的句子。生成的节点还包含元数据中每个节点周围的句子“窗口”，结合 MetadataReplacementNodePostProcessor，在将 node 发送到 LLM 之前将句子替换为其周围的上下文。
这个 node parser 对于比较大的文档非常有用，能帮助我们检索更细粒度的详细信息。
```python
llmsherpa_api_url = "xxx"

reader = CustomPDFLoader(
    llmsherpa_api_url=llmsherpa_api_url,
    # input_files=["/Downloads/公司制度文档/人力资源制度/ZH-rl-2024-13 员工福利管理制度.pdf"],
    input_dir="/Users/wanglinxiao/Downloads/公司制度文档",
)
documents = reader.load_data()
node_parser = SentenceWindowNodeParser.from_defaults(
    window_size=3,
    window_metadata_key="window",
    original_text_metadata_key="original_text",
)
nodes = node_parser.get_nodes_from_documents(documents)
# build index
vm = VectorModel(index_name="TestIndex_v2")
vm.index.build_index_from_nodes(nodes)
```

### SemanticSplitterNodeParser
SemanticSplitterNodeParser 不使用固定块大小对文本进行分块，而是使用嵌入相似性 (embedding similarity) 自适应地选择句子之间的断点。这样确保了 "chunk" 包含语义上彼此相关的句子。
但是这个分割器有个比较大的缺点是大量文档下构建索引速度会很慢（毕竟要计算 embedding similarity）。
```python
embed_model = get_bge_embedding()
node_parser = SemanticSplitterNodeParser(
    buffer_size=1, breakpoint_percentile_threshold=95, embed_model=embed_model
)
```
### 三种 NodeParser 检索对比
检索结果里省略了部分与 query 无关的信息    

`SentenceSplitter `   
```
假和地方法规规定的额外婚假。
●休婚假须提前15天通过企业微信—再惠人事自助平台提交
休假申请，由部门负责人安排人员接替其工作，并需将结婚证以照片
形式上传到企业微信—再惠人事自助平台“附件”一栏，经批准后方
可休假。
●按照工作地城市政策发放婚假工资。
●婚假为连续日假期，须在结婚证书颁发日期后6个月内一次
休完。
5.丧假
xxx
6.工伤假
xxx
```

`SentenceWindowNodeParser + CustomPDFReader`   
```
original_text:    
婚假 ● 员工符合法定结婚年龄，即男方不早于 22 周岁，女方不早 于 20 周岁，可享受婚假。 ● 员工在公司工作期间依法登记结婚的可享有 3 个日历日婚 休婚假须提前 15 天通过企业微信—再惠人事自助平台提交 休假申请，由部门负责人安排人员接替其工作，并需将结婚证以照片 形式上传到企业微信—再惠人事自助平台“附件”一栏，经批准后方 可休假。 ● 按照工作地城市政策发放婚假工资。 ● 婚假为连续日假期，须在结婚证书颁发日期后 6 个月内一次 休完。 5.

window:     
4.  婚假 ● 员工符合法定结婚年龄，即男方不早于 22 周岁，女方不早 于 20 周岁，可享受婚假。 ● 员工在公司工作期间依法登记结婚的可享有 3 个日历日婚 休婚假须提前 15 天通过企业微信—再惠人事自助平台提交 休假申请，由部门负责人安排人员接替其工作，并需将结婚证以照片 形式上传到企业微信—再惠人事自助平台“附件”一栏，经批准后方 可休假。 ● 按照工作地城市政策发放婚假工资。 ● 婚假为连续日假期，须在结婚证书颁发日期后 6 个月内一次 休完。 5.
 丧假 ● xxx 7.
 产假 ● xxx8.
```

`SemanticSplitterNodeParser + CustomPDFReader`
```
婚假 ● 员工符合法定结婚年龄，即男方不早于 22 周岁，女方不早 于 20 周岁，可享受婚假。 ● 员工在公司工作期间依法登记结婚的可享有 3 个日历日婚 休婚假须提前 15 天通过企业微信—再惠人事自助平台提交 休假申请，由部门负责人安排人员接替其工作，并需将结婚证以照片 形式上传到企业微信—再惠人事自助平台“附件”一栏，经批准后方 可休假。 ● 按照工作地城市政策发放婚假工资。 ● 婚假为连续日假期，须在结婚证书颁发日期后 6 个月内一次 休完。 5.
丧假 ● xxx 7.
产假 ● xxx。 8.
产检假 ● xxx 9.
陪产假 ● xxx 10.
哺乳假 ● xxx
```

我们可以看到上面方案 2 和方案 3 检索“婚假有几天”的结果更完整，包含了我们需要的所有上下文信息。
最终我们采用的方案是 `SentenceWindowNodeParser + CustomPDFReader`  
示例结果如下：
```python
query('婚假有几天', index='TestIndex_v2')

# answer 如下
员工在公司工作期间依法登记结婚的可享有 3 个日历日的婚假。
```
