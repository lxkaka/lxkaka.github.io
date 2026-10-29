# ELK stack日志系统搭建


### ELK简要说明  
> ELK 不是一款软件，而是 Elasticsearch、Logstash 和 Kibana 三种软件产品的首字母缩写。这三者都是开源软件，通常配合使用，而且又先后归于 Elastic.co 公司名下，所以被简称为 ELK Stack。根据 Google Trend 的信息显示，ELK Stack 已经成为目前最流行的集中式日志解决方案。
> 
* Elasticsearch：分布式搜索和分析引擎，具有高可伸缩、高可靠和易管理等特点。基于 Apache Lucene 构建，能对大容量的数据进行接近实时的存储、搜索和分析操作。通常被用作某些应用的基础搜索引擎，使其具有复杂的搜索功能；  
* Logstash：数据收集引擎。它支持动态的从各种数据源搜集数据，并对数据进行过滤、分析、丰富、统一格式等操作，然后存储到用户指定的位置；  
* Kibana：数据分析和可视化平台。通常与 Elasticsearch 配合使用，对其中数据进行搜索、分析和以统计图表的方式展示；  
* Filebeat：ELK 协议栈的新成员，一个轻量级开源日志文件数据搜集器，基于 Logstash-Forwarder 源代码开发，是对它的替代。在需要采集日志数据的 server 上安装 Filebeat，并指定日志目录或日志文件后，Filebeat 就能读取数据，迅速发送到 Logstash 进行解析，亦或直接发送到 Elasticsearch 进行集中式存储和分析。

### 基于Filebeat的架构
Filebeat作为客户端，轻量及安全。我们采用Filebeat来作为日志的收集器，下图是整个ELK stack日志系统的架构。
![els stack](https://pics.lxkaka.wang/elk-stack.png)
因为免费的 ELK 没有任何安全机制，所以这里使用了 Nginx 作反向代理，避免用户直接访问 Kibana 服务器。加上配置 Nginx 实现简单的用户认证，一定程度上提高安全性。另外，Nginx 本身具有负载均衡的作用，能够提高系统访问性能。

### 搭建过程
环境为 Unbuntu 16.04
#### 1. 安装 JAVA
Elasticsearch 运行依赖java 8 ，推荐安装 Oracle JDK 1.8。我从ppa仓库安装java8

* 安装 **python-software-properties**，可以轻松添加repo

	```
	sudo apt-get update
	sudo apt-get install -y python-software-properties soft-common-properties apt-transport-https
	
	```
* 用 **apt-add-repository**添加 java8 PPA repo

	```
	sudo apt-add-repository ppa:webupd8team/java -y
	sudo apt-get update
	```
* 安装 java8
	
	```
 	sudo apt-get install -y oracle-java8-installer
 	java -version  # 验证下 
 	```
 	
#### 2. 安装配置Elasticsearch
从 elastic repository安装

* 首先添加 elastic repo key 到机器  
`wget -qO - https://artifacts.elastic.co/GPG-KEY-elasticsearch | sudo apt-key add -` 
   
* 添加 elastic 5.x repository 到 source.list.d 目录
`echo "deb https://artifacts.elastic.co/packages/5.x/apt stable main" | sudo tee -a /etc/apt/sources.list.d/elastic-5.x.list`

* 生效elastic安装源，并安装

	```
	sudo apt-get update
	sudp apt-get install -y elasticsearch
	```
* Elasticsearch安装完毕，然后配置 elasticsearch.yml

	```
	cd /etc/elasticsearch
	vim elasticsearch.yml
	```
	**memory** 部分，关闭内存交换，避免系统负载过高  
	*bootstrap.memorylock: true*
	
   **Network** 部分：  
   *network.host: localhost*  
   *http.port: 9200*  
   保存并推出vim
   
   修改 elasticsearch service 文件
   `vim /usr/lib/systemd/elasticsearch.service`
   *LimitMEMLOCK=infinity*
   
   修改默认配置
   `vim /etc/default/elasticsearch`
   *MAX_LOCKED_MEMORY=unlimited*
   
* 配置完毕，启动服务
  启动并设置成开机自动启动
  
  ```
  sudo systemctl daemon-reload
  sudo systemctl enable elasticsearch
  sudo systemctl start elasticsearch
  ```
  检查是否正常启动，是否在监听端口9200
  `netstat -plnt`  
  显示如下，则正确启动 
 
  ```
tcp6       0      0 :::9200                 :::*                    LISTEN      -
tcp6       0      0 :::9300                 :::*                    LISTEN      -
tcp6       0      0 :::22                   :::*                    LISTEN      -
tcp6       0      0 127.0.0.1:9600          :::*                    LISTEN      -
```
访问下9200端口  
`curl -XGET 'localhost:9200'`  
返回如下结果, 则elasticseach已经正常工作
	
	```
	{
	  "name" : "node-1",
	  "cluster_name" : "zaihui-elk",
	  "cluster_uuid" : "L_BrQy4PRO2ed_8CXt3IuA",
	  "version" : {
	    "number" : "5.5.2",
	    "build_hash" : "b2f0c09",
	    "build_date" : "2017-08-14T12:33:14.154Z",
	    "build_snapshot" : false,
	    "lucene_version" : "6.6.0"
	  },
	  "tagline" : "You Know, for Search"
	}
	```
	
#### 3. 安装和配置Kibana
ELK stack的各个组件安装配置方法基本一致  

```
sudo apt-get install -y kibana  # 安装
vim /etc/kibana/kibana.yml   # 配置
```
配置如下必选项

```
server.port: 5601
server.host: "localhost"
elasticsearch.url: "http://localhost:9200"
```
启动并设置开机自动启动

```
sudo systemctl enable kibana
sudo systemctl start kibana
```
检查是否正常启动（kibana是一个node服务）  
`netstat -plnt`  
输出如下，则正确安装配置

```
Active Internet connections (only servers)
Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name
tcp        0      0 0.0.0.0:80              0.0.0.0:*               LISTEN      -
tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      -
tcp        0      0 127.0.0.1:5601          0.0.0.0:*               LISTEN      -
```

### 4. 配置Nginx反向代理Kibana
* 安装 Nginx 和 apache2-utils包
`sudo apt-get install -y nginx apache2-utils`  
Nginx可以用apache2-utils来添加一些辅助功能，比如用 htpasswd 来管理用户访问权限  

* 配置kibana服务
	
	```
	cd /etc/niginx/
	vim /conf.d/kibana.conf
	```
配置如下

	```
	server {
	    listen 80;
	 
	    server_name localhost;
	 
	    auth_basic "Restricted Access";
	    auth_basic_user_file /etc/nginx/.kibana-user;
	 
	    location / {
	        proxy_pass http://localhost:5601;
	        proxy_http_version 1.1;
	        proxy_set_header Upgrade $http_upgrade;
	        proxy_set_header Connection 'upgrade';
	        proxy_set_header Host $host;
	        proxy_cache_bypass $http_upgrade;
	    }
	}
	```
	
* 用 htpasswd创建一个可访问账号
`sudo htppasswd -c /etc/nginx/.kibana-user lxkaka`
* 验证nginx配置正确，并启动nginx
	
	```
	nginx -t
	systemctl enable nginx
	systemctl restart nginx
	```

#### 5. 安装和配置Logstash
* 安装和生成SSL证书  
`sudo apt-get install -y logstash`

	logstash 支持SSL协议，可以用OpenSSL生成SSL证书来增加安全性，client可以此来验证elastic server。

	```
	cd /etc/logstash
	openssl req -subj /CN=elk-master -x509 -days 3650 -batch -nodes -newkey rsa:4096 -keyout logstash.key -out logstash.crt
	```
* 配置输入，解析，输出三份配置  
当然三份配置都可以写到一个文件中，不过为了维护和清晰我觉得分开配置比较合适。

	编辑来自filebeat的输入配置

	```
	cd /etc/logstash/
	vim conf.d/filebeat-input.conf
	```
	如下：

	```
	input {
	  beats {
	    port => 5443
	    type => log
	    ssl => true
	    ssl_certificate => "/etc/logstash/logstash.crt"
	    ssl_key => "/etc/logstash/logstash.key"
	  }
	}
	```
	编辑过滤解析配置文件(这里以解析niginx accesslog为例）
	`vim conf.d/nginxlog-filter.conf`
	
	```
	filter {
	    grok {
	        match => { "message" => "%{IPORHOST:clientip} \[%{HTTPDATE:time}\] \"%{WORD:verb} %{URIPATHPARAM:request} HTTP/%{NUMBER:httpversion}\" %{NUMBER:http_status_code} %{NUMBER:bytes} \"(?<http_referer>\S+)\" \"(?<http_user_agent>\S+)\" \"(?<http_x_forwarded_for>\S+)\"" }
	
	    }
	    date {
	      match => [ "timestamp","dd/MMM/yyyy:HH:mm:ss Z"]
	    }
	```
	Logstash用插件 **gork**来按配置好的规则解析日志

	编辑输出配置文件
	`vim conf.d/output-elasticsearch.conf`
	
	```
	output {
	    elasticsearch {
	        hosts => ["localhost:9200"]
	        index => "logstash-nginx-access-%{+YYYY.MM.dd}"
	    }
	    stdout {codec => rubydebug}
	}
	```

* 配置完成，启动服务

	```
	sudo systemctl enable logstash
	sudo systemctl start logstash
	```
	
至此ELK在服务器上的搭建就算完成了，分别启动了以下服务

```
Active Internet connections (only servers)
Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name
tcp        0      0 0.0.0.0:80              0.0.0.0:*               LISTEN      8931/nginx -g daemo
tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      1048/sshd
tcp        0      0 127.0.0.1:5601          0.0.0.0:*               LISTEN      8570/node
tcp6       0      0 :::9200                 :::*                    LISTEN      537/java
tcp6       0      0 :::9300                 :::*                    LISTEN      537/java
tcp6       0      0 :::22                   :::*                    LISTEN      1048/sshd
tcp6       0      0 127.0.0.1:9600          :::*                    LISTEN      709/java
tcp6       0      0 :::5443                 :::*                    LISTEN      709/java
```
#### 6. 在客户机上安装Filebeat

* 安装和配置Filebeagt

	```
	sudo apt-get install -y filebeat
	cd /etc/filebeat/
	vim filebeat.yml
	```
	配置日志路径：  
	
	```
	paths
	 - /var/log/nginx/access.log
	```

	注释掉 Elasticsearch output  
	配置Logsstash output
	
	```
	output.logstash:
  # The Logstash hosts
  hosts: ["elk-server:5443"]
  bulk_max_size: 2048
  ssl.certificate_authorities: ["/etc/filebeat/logstash.crt"]
  template.name: "filebeat"
  template.path: "filebeat.template.json"
  template.overwrite: false
 	```
 
* 复制 SSL证书  
先前，已经在服务器端创建好了SSL证书，复制到客户端上(按照实际修改用户名，和host)  
`scp name@els-server:/etc/logstash/logstash.crt /etc/filebeat/`
* 启动并设置开机自动启动

	```
	sudo systemctl enable filebeat
	sudo systemctl start filebeat
	```
检查filebeat正常启动
`sudo systemctl status filebeat`  
输出如下
	
	```
	● filebeat.service - filebeat
	   Loaded: loaded (/lib/systemd/system/filebeat.service; enabled; vendor preset: enabled)
	   Active: active (running) since Mon 2017-08-21 22:10:12 CST; 4 days ago
	     Docs: https://www.elastic.co/guide/en/beats/filebeat/current/index.html
	 Main PID: 1666 (filebeat)
	    Tasks: 8
	   Memory: 13.3M
	      CPU: 1min 5.628s
	   CGroup: /system.slice/filebeat.service
	           └─1666 /usr/share/filebeat/bin/filebeat -c /etc/filebeat/filebeat.yml -path.home /usr/share/filebeat -path.config /etc/filebeat -pat
	```

### 7. 验证测试
* 访问elasticsearch server的地址  
输入设置的用户名和密码即能访问kibana
* 创建默认index 'logstash-*'
* kibana遨游开始

![kibana](https://pics.lxkaka.wang/kibana.jpg)

ELK stack日志系统搭建至此完成，要让工具发挥它的价值，需要花更多的功夫来研究它。


  

