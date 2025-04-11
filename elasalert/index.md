# 基于elastalert的监控报警系统


监控报警一般都是基于日志数据来做，总结起来就是根据监控指标查询一定时间段内的该指标的变化情况，当该指标超过设定的阈值时则触发报警规则，发出报警信息包括邮件，短信，微信甚至自动拨打电话等。
要实现监控报警的功能应该几步来做：  
1. 指定日志规范，生成日志  
2. 收集日志  
3. 查询分析日志  
4. 触发报警规则  
5. 报警

其中第二步日志收集就是一项不小的工作。一般会有这三部分组成
* Agent : 部署在各个应用服务器收集应用的日志

* Collector: 日志收集中心，把分散在Agent的日志统一收集到日志中心

* Storage: 存储层，日志收集之后的存储
当数据量大的时候，可以采用 kafaka,redis这样的中间件来缓冲日志发送量，提高系统的可靠性。
可以采用的方案有: Flume日志收集，ELK方案等

我们因为已经搭建了ELK日志收集平台，已经完成了第二步，要做监控报警自然就基于ELK来做。

## 方案选择
先简单分析一下我们要做的事情
* 设置报警规则
* 查询ES中的特定指标
* 分析是否达到阈值
* 发报警邮件，微信  

经过调研，有这么几个选择：
* 自己开发
* ELK提供了XPack, 具有报警的作用
* 第三方开源方案
首先试用了 Xpack本身的功能还是挺吸引人的 **权限控制 + ELK集群监控**，但因为监控报警功能不够灵活，达不到自己的需求且是收费的（穷.jpg);
yelp开源了[`Elastalert`](https://elastalert.readthedocs.io/en/latest/), yelp也是先有了自己的ELK, 而后需要搭建监控报警系统的时候，开发了 Elastalert。跟我们的路线和需求非常匹配，那果断放弃重复造轮子。Elastalert非常灵活，除了通过配置进行报警规则设置，还可以自己开发独有的报警规则。
经过在测试系统的对比，决定采用 `Elastalert`做作为监控报警系统的核心。

下图展示了我们监控系统的组件及架构简图  
![elastalert](https://pics.lxkaka.wang/elastalert.png)

# 服务搭建
1. 安装依赖
    * 新建 pyhton2.7 虚拟环境  
    ```
    & sudo apt install -y virtualenv 
    & sudo apt install -y python-dev libffi-dev libssl-dev
    & virtualenv env
    ```
    激活env 

    * 安装 pip
    ```
    $ sudo apt-get install python-setuptools python-dev build-essential 
    $ sudo easy_install pip 
    ```
2. 安装 elastalert
    先安装这个版本，解决依赖包boto3的问题, `error: python-dateutil 2.7.0 is installed but python-dateutil<2.7.0,>=2.1 is required by set(['botocore'])`
    ```
    $ pip install "python-dateutil<2.7.0,>=2.1"
    & pip install elastalert
    & pip install elasticsearch 
    ```
    如果报错 permission则 denied pip install --user elastalert

3. 设置 elasticsearch
    把查询和报警的信息和元数据存到 elasticsearch 中。这样可以在 kibana 中查询到报警的错误，异常和执行情况。
    ```
    $ elastalert-create-index
    New index name (Default elastalert_status)
    Name of existing index to copy (Default None)
    New index elastalert_status created
    Done!
    ```

4. 配置和设置规则
    * 把公共的配置写到 config.yaml  
    `vim config.yaml`  

    示例:
    ```
    # The Elasticsearch hostname for metadata writeback
    # Note that every rule can have its own Elasticsearch host
    es_host: localhost

    # The Elasticsearch port
    es_port: 9200
    ```
    * 创建报警规则
    `vim alert_rules/alert_frquency.yaml`  

    示例:
    ```
    name: Example rule
    type: frequency
    index: access
    num_events: 50
    timeframe:
        minutes: 5
    filter:
    - term:
        some_field: "some_value"
    alert:
    - "email"
    email:
    - "elastalert@example.com"
    ```

5. 测试报警规则  
`$ elastalert-test-rule alert_rules/alert_frequency.yam`

6. 启动服务
`$ python -m elastalert.elastalert --verbose --rule alert_frequency.yaml`

7. 用supervisor管理监控服务
    * 安装 supervisor
    `sudo apt install -y supervisor`  
    * 配置elastalert
    ```
    [program:elastalert]
    command=/home/xxx/elastalert/env/bin/elastalert --config /home/xxx/elastalert/config.yaml --verbose
    autostart=true
    autorestart=true
    stdout_logfile=/var/log/supervisor/elastalert.log
    stderr_logfile=/var/log/supervisor/elastalert_error.log
    stopsignal=INT
    stderr_logfile_maxbytes=5MB
    stdout_logfile_maxbytes=5MB
    ```
    * 启动服务   
    `sudo supervisorctl start elastalert`

## 开发报警规则和报警方式
* 报警类型
    ```python
    class AwesomeNewRule(RuleType):
    # ...
        def add_data(self, data):
        # ...
        def get_match_str(self, match):
        # ...
        def garbage_collect(self, timestamp):
        # ...

    ```
* 报警方式
    ```python
    class AwesomeNewAlerter(Alerter):
        required_options = set(['some_config_option'])

        def alert(self, matches):
        ...
        def get_info(self):
        ...
    ```
* 报警 on-the-fly
    ```python
    class MyEnhancement(BaseEnhancement):
        def process(self, match):
            # Drops a match if "field_1" == "field_2"
            if match['field_1'] == match['field_2']:
                raise DropMatchException()
    ```


