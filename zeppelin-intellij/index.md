# 在 IntelliJ 中使用 Zeppelin 提速数据开发


[Apache Zeppelin](https://zeppelin.apache.org/) 是一个可以通过浏览器实现交互式数据查询、数据分析、数据可视化并且能多人协作开发的 NoteBook(如果用过 jupyter 对此应该会很熟悉)。其前端提供丰富的可视化图形库，不限于 SparkSQL，后端支持 HBase、Flink 等大数据系统以插件扩展的方式，并支持 Spark、Python、JDBC、Markdown、Shell 等各种常用 Interpreter，这使得开发者可以方便地使用 SQL，SCALA, Python 等其他语言 在 Zeppelin 中做数据开发。
我们在用 Scala 基于 Spark 做数据开发的时候，代码调试是必不可少的，这个过程可能是反复多次的，最基本的要求就是我们得有完整的 Spark 环境。随之而来的是需要在本地搭建和维护这样的环境，当我们有实时数据的需求的时候可能会需要用到其他的组件比如 kafka。本地环境和不方便就会成为开发的一个大问题。此外很多场景我们可能只是需要调试一段代码或一个小的模块，如果我们想达到这个“块级别”的调试不借助别的工具就很难实现。
在这里我们介绍一下如何使用 Zeppelin 来解决上述的痛点，帮助我们有效提高开发效率。

### Zeppelin 原理
在此之前，我们有必要了解 Zeppelin 的工作原理。我们最关心的是两个模块 Notebook 和 Interpreter.
#### Notebook
* Notebook 可以理解成多个代码片段的交互式容器
* 一个 Notebook 可以包含不同语言写成的代码片段
* Notebook 可以导入导出，对于一个 Notebook下的所有代码片段可以一起执行、停止和删除的操作  

#### Interpreter
解释器是 Zeppelin 的语言后端。例如，在 Zeppelin 中使用 scala 代码，您需要一个 scala 解释器、使用 Python 需要 Python 的解释器，每个解释器都属于一个解释器组。相同解释器组中的解释器可以互相引用。例如 Spark、SparkSQL、Pyspark、SparkR 都属于同一个解释器组，同一个实例中他们之间可以相互引用，RDD 也可以共享，在用户发起执行请求时 Zeppelin Server 会通过代码中的 repl 找到相应的解释器，调用解释器的 interpreter 方法执行，Zeppelin Server 会通过 WebSocket 实时的把进度反馈到web前端。
架构图如下  
![zeppelin-arch](https://pics.lxkaka.wang/zeppelin-arch.jpeg)
解释器有两种启动形式，本地或者远程，本地解释器通过 classLoader 动态加载到 JVM 直接调用，远程解释器会在本地重启一个进程，启动一个Thrift Server 通过 Thrift 远程调用,以 Spark 插件为例, Spark 插件本身就是一个常驻的 Spark 任务，在 Spark 的 Driver 端启动一个 Thirft Server，然后通过 Thirft 和 Zeppelin Server 进行通信,接受执行 SQL、Scala、Python等任务、反馈执行进度等。

### Zeppelin 依赖配置
我们想要让代码跑起来，代码所用到依赖必须在 Zeppelin 中先配置好。这里有两种方式可以来加载依赖包。(以 Spark interpreter 示例), 包括如下功能  
* 从 maven 仓库加载  
* 从本地文件系统加载  
* 添加指定的仓库地址       

#### 通过 `%sprak.dep` 动态加载
当我们的代码需要用到第三方库时,不需要手动下载包和重启 Zepplin, 可以通过 `spark.dep`实现动态加载

使用示例如下     

    ```
    %spark.dep
    z.reset() // clean up previously added artifact and repository

    // add maven repository
    z.addRepo("RepoName").url("RepoURL")

    // add maven snapshot repository
    z.addRepo("RepoName").url("RepoURL").snapshot()

    // add credentials for private maven repository
    z.addRepo("RepoName").url("RepoURL").username("username").password("password")

    // add artifact from filesystem
    z.load("/path/to.jar")

    // add artifact from maven repository, with no dependency
    z.load("groupId:artifactId:version").excludeAll()

    // add artifact recursively
    z.load("groupId:artifactId:version")

    // add artifact recursively except comma separated GroupID:ArtifactId list
    z.load("groupId:artifactId:version").exclude("groupId:artifactId,groupId:artifactId, ...")

    // exclude with pattern
    z.load("groupId:artifactId:version").exclude(*)
    z.load("groupId:artifactId:version").exclude("groupId:artifactId:*")
    z.load("groupId:artifactId:version").exclude("groupId:*")

    // local() skips adding artifact to spark clusters (skipping sc.addJar())
    z.load("groupId:artifactId:version").local()
    ```
#### Web UI 通过 Interpreter 设置
* 配置依赖的源  
![add-repo](https://pics.lxkaka.wang/add-repo.png)

* 加载依赖到相应的 interpreter
配置包的 artifact、group和版本信息或者本地路径  
![add-jar](https://pics.lxkaka.wang/add-jar.png)

### Intellij Big Data Tools
在依赖配置好后，我们就可以创建 Notebook 开始开发了，但是有一点遗憾在 Zeppelin 的 Notebook 中编写代码并没有 IDE 中的代码提示等帮助我们提高开发效率的功能。所幸的是 IntelliJ IDEA 2019.2 及以后的版本提供了插件 [**Big Data tools**](https://plugins.jetbrains.com/plugin/12494-big-data-tools)。这个插件集成了 Zeppelin, Spark等，我们使用 Zeppelin 搭配 Big data tools 插件即可以实现高效的本地数据开发和调试。

#### 环境配置
* Intellij 安装插件
    * Big Data Tools
    * Scala 
* 创建 project 
* 配置 Zeppelin 连接  
  ![zeppelin-conn](https://pics.lxkaka.wang/zeppelin-conn.png)

### 开发示例  
* 创建 Notebook 和调试
![exaam-run](https://pics.lxkaka.wang/exam-run.png)

* 输出结果 
![exam-out](https://pics.lxkaka.wang/exam-out.png)


