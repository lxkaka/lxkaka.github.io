# 怎么使用 Promethues 监控 Spark 应用


我们用 Spark 处理数据的时候，Spark 应用和它的 job 运行状态的监控十分重要。关于 Spark 的监控从[官方文档](https://spark.apache.org/docs/latest/monitoring.html)上我们看到有这三种方式 **Web UI**, **Metrics**, **其他辅助工具**。  
这里简单提一下 Web UI 提供的监控信息。 

#### Spark Web
每个SparkContext启动一个Web UI， 缺省接口为4040,用来显示应用的有用信息， 包括:

* scheduler stages 和 tasks列表
* RDD 大小和内存使用率的汇总
* 环境变量(配置)
* 运行中的 executor 的信息

#### Spark history server 
如果开启了 spark event log ，我们可以通过访问 spark histroy server 看到应用的信息，包括正在运行和已完成的应用。

Web UI 上只提供应用的运行的状态和信息，但是当应用出现异常和失败，我们并不能及时知道。也就是说缺失失败报警的功能。
Spark有一个基于 Dropwizard Metrics Library 的可配置的 metrics 系统，允许用户通过各种方式呈现 metrics， 如 HTTP, JMX 和 CSV 文件方式。我们可以通过 $SPARK_HOME/conf/metrics.properties 配置或者通过 spark.metrics.conf 指定一个自定义的配置文件. Spark metrics 根据不同的组件被解耦成不同的实例。每个实例中都可以可以配置多个 sinks 来接收 metrics。   
包括以下实例:  
* master: The Spark standalone master process.
* applications: A component within the master which reports on various applications.
* worker: A Spark standalone worker process.
* executor: A Spark executor.
* driver: The Spark driver process (the process in which your SparkContext is created).
* shuffleService: The Spark shuffle service.
* applicationMaster: The Spark ApplicationMaster when running on YARN.

目前 Spark 支持的 sinks 全部在 org.apache.spark.metrics.sink package 里面，包括：
* ConsoleSink: 在控制台中显示 metrics.
* CSVSink: 以 CSV 文件的方式定期提供报告.
* JmxSink: 以 JMX 方式提供.
* MetricsServlet: 以 servlet 方式在 Spark UI 中提供 JSON 数据.
* GraphiteSink: 发送给 Graphite 节点.
* Slf4jSink: 记录到日志中.
* StatsdSink: 发送给 Statsd 节点.

我们现在的监控报警系统核心是 Promethues，所以 Spark 的监控报警我们想的方案也是要基于 Prometheus。我们看到 Spark 支持的 sink 里有 jmx, 顺着这个思路我们可以采取 JMXSink + JmxExporter(https://github.com/prometheus/jmx_exporter) 的方式。另外一种思路更直接，我们可以自己开发一个 sink 把 metrics 推到 Prometheus。
在调研的过程中发现别人也有使用 Prometheus 监控 Spark 的需求，于是发现了这样一个包 https://github.com/banzaicloud/spark-metrics，自定义的 **Prometheus Sink**。  
下面介绍一下怎么使用这样的 Prometheus Sink 监控 Spark。  

### Prometheus Sink 配置
因为这里是利用 Prometheus 的 pushgateway，先把 metrics 推给 pushgateway, 所以配置文件里一定要配置 pushgateway 的地址。配置文件就是我们上面所说的 $SPARK_HOME/conf/metrics.properties 或者 spark.metrics.conf 配置的自定义配置文件   
* metrics.conf  
    ```
    # Enable Prometheus for all instances by class name
    *.sink.prometheus.class=org.apache.spark.banzaicloud.metrics.sink.PrometheusSink
    # Prometheus pushgateway address
    *.sink.prometheus.pushgateway-address-protocol=http
    *.sink.prometheus.pushgateway-address=11.22.33.44:9091
    *.sink.prometheus.period=15
    #*.sink.prometheus.unit=< unit> - defaults to seconds (TimeUnit.SECONDS)
    #*.sink.prometheus.pushgateway-enable-timestamp=<enable/disable metrics timestamp> - defaults to false
    # Metrics name processing (version 2.3-1.1.0 +)
    #*.sink.prometheus.metrics-name-capture-regex=<regular expression to capture sections metric name sections to be replaces>
    #*.sink.prometheus.metrics-name-replacement=<replacement captured sections to be replaced with>
    #*.sink.prometheus.labels=<labels in label=value format separated by comma>
    # Support for JMX Collector (version 2.3-2.0.0 +)
    *.sink.prometheus.enable-dropwizard-collector=false
    *.sink.prometheus.enable-jmx-collector=true
    *.sink.prometheus.jmx-collector-config=/home/hadoop/jmxCollector.yaml

    # Enable HostName in Instance instead of Appid (Default value is false i.e. instance=${appid})
    *.sink.prometheus.enable-hostname-in-instance=true

    # Enable JVM metrics source for all instances by class name
    *.sink.jmx.class=org.apache.spark.metrics.sink.JmxSink
    *.source.jvm.class=org.apache.spark.metrics.source.JvmSource
    ```
    这里需要特别注意的一点，默认情况下 dirver 和 executor 的 metrics 使用的命名空间是 application id, 例如 `metrics_application_1584587365518_0205_1_executor_bytesRead_Count`, 但因为这个 app id 是随着每个 Spark app 变的，我们往往关心的是所有 app 的 metrics， 所以这里我们通过配置 **sprak.metrics.namespace** 来达到目的，可以修改成 app 的名字 **${spark.app.name}** 或是一个固定值。  

* jmxCollector 配置  
可以配置收集或不收集哪些对象的指标，这个配置文件可以灵活选择目录。
    ```yaml
    lowercaseOutputName: false
    lowercaseOutputLabelNames: false
    whitelistObjectNames: ["*:*"]
    blacklistObjectNames: ["java.lang:*", "kafka.consumer:*"]
    ```
### 依赖
我们知道添加 Spark 的第三方依赖包，我们可以在 spark-submit 通过 --package 指定  
例如    
`spark-submit --master yarn --package com.banzaicloud:spark-metrics_2.11:2.4-1.0.5 --class Test`   
为了全局生效和省去命令行配置我们把相关的依赖都添加到 Spark 的 CLass Path 下, 这里列出所有需要的依赖包的中央仓库地址。版本可以换根据自己使用的 Spark 版本调整。     

```yaml
https://repo1.maven.org/maven2/com/banzaicloud/spark-metrics_2.11/2.4-1.0.5/spark-metrics_2.11-2.4-1.0.5.jar
https://repo1.maven.org/maven2/io/prometheus/simpleclient/0.8.1/simpleclient-0.8.1.jar
https://repo1.maven.org/maven2/io/prometheus/simpleclient_dropwizard/0.8.1/simpleclient_dropwizard-0.8.1.jar
https://repo1.maven.org/maven2/io/prometheus/simpleclient_pushgateway/0.8.1/simpleclient_pushgateway-0.8.1.jar
https://repo1.maven.org/maven2/io/prometheus/simpleclient_common/0.8.1/simpleclient_common-0.8.1.jar
https://repo1.maven.org/maven2/io/prometheus/jmx/collector/0.12.0/collector-0.12.0.jar
https://repo1.maven.org/maven2/org/yaml/snakeyaml/1.26/snakeyaml-1.26.jar
```       

### Prometheus 报警配置  
当我们完成上述步骤后，我们应该就能在 Promethues pushgateway 中看到 spark 应用的 metrics, 那么 prometheus 中自然也会收集到 metrics。
通过其中的一些指标我们可以监控和告警包括 stage, executor, app 等的执行，如果有失败我们就你能及时收到告警，从而能快速处理。      
下面是 Prometheus  部分告警规则的示例配置  

```yaml
- name: spark
rules:
- alert: spark executor fail
    expr: "{__name__=~'metrics_application.+applicationMaster_numExecutorsFailed_Value'} > 0"
    for: 1m
    labels:
    severity: critical
    annotations:
    summary: "spark {{ $labels.__name__ }} 大于 0, 达到 {{ $value }}"
    description: "spark executor 有失败应用"

- alert: spark stage fail
    expr: metrics_zaihui_driver_DAGScheduler_stage_failedStages_Value > 0
    for: 1m
    labels:
    severity: critical
    annotations:
    summary: "spark 应用 {{ $labels.app_name }} failed stage 达到 {{ $value }}"
    description: "spark 应用有 stage 失败"

- alert: spark app run fail
    expr: delta(metrics_zaihui_driver_LiveListenerBus_listenerProcessingTime_org_apache_spark_HeartbeatReceiver_Count[5m]) == 0
        for: 5m
        labels:
        severity: critical
        group: alert-admin
        annotations:
        summary: "spark 应用 {{ $labels.app_name }} 5min 之内没有心跳，应用可能已经挂掉"
        description: "spark 应用挂掉，请注意"
```  



