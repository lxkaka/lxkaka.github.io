# Celery 监控方案落地


## 背景
[Celery](http://www.celeryproject.org/) 是一个强大的分布式异步任务处理和调度框架。基本上 Python 项目的异步任务，定时任务首先处理框架就是 Celery. 正因为 Celery 的处理时异步的并且是分布式的，当任务出现问题时追踪和调查就不是很容易。官方提供了 [flower](https://github.com/mher/flower) 可以用来查看任务的执行情况和执行时间。flower 带来的任务监控能力十分有限，最主要的是没有全局性的统计功能，只能查看单个任务；再者支持查找的时间段很短。随着我们异步任务量的和重要性的增加，增强对 celery 的监控变得十分必要。

## 监控方案    
### 方案1  
exporter + prometheus + grafana 
* 优势   
  这种方案的好处是可以利用我们现有的基础设施 prometheus + grafana
* 劣势
  没有可供部署的 exporter 使用，需要自己开发针对 celery 的exporter, 成本很高

### 方案2
celery signal + graphite + grafana
* 优势
  指标采集比较角度，利用 celery 提供的 hook就能做到
* 劣势  
  需要部署新的组件 graphite, 具有一定的学习成本

经过比较，最终我选择方案2来完成。

## 原理介绍
* Graphite
Graphite是一个开源实时的、显示时间序列度量数据的图形系统。Graphite并不收集度量数据本身，而是像一个数据库，通过其后端接收度量数据，然后以实时方式查询、转换、组合这些度量数据。Graphite支持内建的Web界面，它允许用户浏览度量数据和图。
三个主要模块  
    * Carbon (监控数据的 Twisted 守护进程)  
        Carbon是基于Twisted实现,是Graphite的后端实现。
        Carbon的主要作用，是接收被监控节点的连接，收集各个指标的数据，将这些数据写入缓存并最终持久化到whisper存储文件中去。Carbonr能保证Graphite web 绘制出实时接到的指标更新，其原理也很简单位，有点类似lucence，carbon接收到的数据会先存在缓存中，然后再一起写入whisper的硬盘存储。Graphite web通过向carbon-cache发起请求，会同时查询位于缓存与硬盘中的数据。
    * Whisper  
        whisper 是一个固定大小的数据库，在设计上类似于RRD(round-robin-database)。它可以为随时间不断变化的数值型数据提供快速，可靠的存储。Whisper还可以把高精度的指标数据转换成低精度的指标数据以满足存储长期的历史数据的需求。比如说把按秒采集的指标转换成按分钟采集的指标，以减少数据量，进行长期存储。
    * Graphite-web
        Graphite web是基于Django实现的webapp，其主要功能自然是绘制报表与展示。但界面真的不好看（很少使用）
* Statsd
   statsd 其实就是一个监听UDP（默认）或者TCP的守护程序，根据简单的协议收集statsd客户端发送来的数据，聚合之后，定时推送给后端, 我们这里指的就是 graphite。 statsd 有多种语言的客户端实现，这里我们使用 python实现的 statsd 来采集 celery 指标。

下图是我们 celery 监控的架构
![celery-monitor](https://pics.lxkaka.wang/celery-monitor.png)

## 搭建
* celery hook
  下面示例代码，使用 statsd 接收 celery hook设置的指标并发送到 graphite
    ```python
    #!/usr/bin/env python3
    # -*- coding: utf-8 -*-

    import time

    import statsd
    from celery.signals import (
        task_failure,
        task_postrun,
        task_prerun,
        task_success,
    )
    from django.conf import settings

    statsd_conn = statsd.StatsClient(
        host=settings.GRAPHITE_HOST,
        port=8125,
    )

    task_time = {}


    @task_prerun.connect
    def task_prerun_handler(task_id, task, *args, **kwargs):
        task_time[task_id] = time.time()
        statsd_conn.incr('{}.prerun'.format(task.name))


    @task_postrun.connect
    def task_postrun_handler(task_id, task, *args, **kwargs):
        statsd_conn.incr('{}.postrun'.format(task.name))
        delta_seconds = time.time() - task_time[task_id]
        # 任务执行时间
        statsd_conn.timing('{}.runtime'.format(task.name), int(1000 * delta_seconds))


    @task_success.connect
    def task_success_handler(sender, result, **kwargs):
        # 成功任务数
        statsd_conn.incr('{}.success'.format(sender.name))


    @task_failure.connect
    def task_failure_handler(sender, result, **kwargs):
        # 失败任务数
        statsd_conn.incr('{}.failure'.format(sender.name))
    ```

    * graphite 部署  
    使用 docker 部署, Dockerfile 在[这里](https://github.com/graphite-project/docker-graphite-statsd/blob/master/Dockerfile)

        ```
        docker run -d\
        --name graphite\
        --restart=always\
        -p 8888:80\
        -p 2003-2004:2003-2004\
        -p 2023-2024:2023-2024\
        -p 8125:8125/udp\
        -p 8126:8126\
        graphiteapp/graphite-statsd
        ```
    * 使用 nginx 反向代理  
      nginx 配置就非常简单了
        ```
        server {
            server_name  example.com;

            location / {
                proxy_set_header Host $host;
                proxy_set_header X-Forwarded-Host $host;
                proxy_set_header X-Forwarded-Server $host;
                proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                proxy_pass http://xx.xx.xx.xx:8888;
                client_max_body_size 200m;
            }
        }
        ```
    如果以上步骤全部完成， 访问 graphite的地址，应该已经能看到收集到的指标。  
    ![graphite](https://pics.lxkaka.wang/graphite.png)

    但就像我们说的还必须有数据可视化，所以下一步就是使用 Grafana 从 Graphite 获取指标并在 dashboard 上展示

    * Grafana 配置  
        * 添加 Graphite 数据源  
        ![data_source](https://pics.lxkaka.wang/data_source.png)

        * dashoboard 配置
        这里 dashboard 的配置我们不具体展开，说明一些比较重要的步骤。我们的异步任务目录层级比较多，为了更好的筛选必须配置各层的 **Variables**  
        如下图所示    
        ![grafana-variables](https://pics.lxkaka.wang/grafana-variables.png)  

        * 指标配置  
        这里指标的配置比较多样，可以有各种aggregate，比如 min, sum, max, mean, mean90  
        下面展示一张示例的效果图    
        ![grafana-dashboard](https://pics.lxkaka.wang/dashboard.png)

