# ELK进阶之Logstash配置和Kibana应用


在搭建好ELK之后，我们可能会有不同的类型的日志。当我们想把这些不同的日志收集起来并需要查看分析，这个时候就需要合理的配置logstash, 才能达到我们想要的结果。
### 配置Logstash
这里我们以三种日志为例，首先需要配置日志来源，即filebeat里的配置需要指明三种不同的日志，为了便于logstash的过配置，这里添加 **tags**来做区分。也可以添加field。    
示例如下：

```python
- input_type: log
  paths:
    - /var/log/nginx/access.log
  tags: ["nginx"]
- input_type: log
  paths:
    - /home/zaihui/server/logs/track.log
  tags: ["track"]
- input_type: log
  paths:
    - /home/zaihui/server/logs/access.log
  tags: ["access"]
```

然后针对不同的日志格式，我们采用logstash插件grok来匹配过滤。logstash配置实际上可以分为三种 *input*, *filter*, *output* 这三部分配置可以在同一文件中配置，不过我选择将这三部分配置分别放在三个文件中。这样配置起来既方便又清晰。

* input 示例如下:  

	```
	input {
	  beats {
	    port => 5443
	    type => log
	    ssl => false
	  }
	}
	```
* filter 示例如下

	```
	filter {
	  if "nginx" in [tags] {
	    grok {
	      match => { "message" => "\[%{HTTPDATE:time}\] %{IPORHOST:client} \"%{WORD:method} %{URIPATHPARAM:request} HTTP/%{NUMBER:httpversion}\" %{NUMBER:status_code} %{NUMBER:bytes} \"(?<http_referer>\S+)\" \"%{GREEDYDATA:http_user_agent}\" \"%{GREEDYDATA:data}\"" }
	    }
	  }
	  else if "access" in [tags] {
	    grok {
	      match => { "message" => "%{TIMESTAMP_ISO8601:datetime} %{IPORHOST:client} %{WORD:method} %{URIPATHPARAM:request} \$%{GREEDYDATA:payload}\$ %{NOTSPACE:protocol} %{NUMBER:status_code} %{NUMBER:duration} %{QUOTEDSTRING:agent}" }
	    }
	  }
	  else if "track" in [tags] {
	    grok {
	      match => { "message" => "%{LOGLEVEL:log_level} %{TIMESTAMP_ISO8601:log_time} %{PATH:path} %{WORD:function} %{GREEDYDATA:content}"}
	      }
	  }
	  else if "_grokparsefailure" in [tags] {
	    grok {
	      remove_tag => ["_grokparsefailure"]
	    }
	  }
	  mutate {
	    remove_filed => ["offset", "@version", "beat.name", "input_type"]
	  }
	}
	```
其中关键部分是 grok的pattern要写正确。这里常用的patterns在[这里查看](https://github.com/logstash-plugins/logstash-patterns-core/blob/master/patterns/grok-patterns).  
校验自己写的pattern对不对，在[这里验证](http://grokconstructor.appspot.com/do/match).
比如下面的就是正确的姿势
![pattern match](https://pics.lxkaka.wang/pattern_match.jpeg)

 如果需要解析nginx accec log 
 日志格式形如   
 *[12/Oct/2017:22:00:15 +0800] 54.223.140.204 "GET /api/v1/auths/jssdk_signature/?category=Customer HTTP/1.1" 200 142 "http://www.wozaihui.com/web/customer#/illegal" "Mozilla/5.0 (linux) AppleWebKit/537.36 (KHTML, like Gecko) jsdom/11.1.0" "-"*  
 
	可参考如下pattern
 
 `\[%{HTTPDATE:time}\] %{IPORHOST:client} \"%{WORD:method} %{URIPATHPARAM:request} HTTP/%{NUMBER:httpversion}\" %{NUMBER:status_code} %{NUMBER:bytes} \"(?<http_referer>\S+)\" \"%{GREEDYDATA:http_user_agent}\" \"%{GREEDYDATA:data}\"
`
* output示例  
按照**tags**给日志添加 **index**
	
	```
	output {
	  if "nginx" in [tags] {
	    elasticsearch {
	      hosts => ["localhost:9200"]
	      index => "nginx-access-%{+YYYY.MM.dd}"
	    }
	  }
	  if "track" in [tags] {
	    elasticsearch {
	      hosts => ["localhost:9200"]
	      index => "track-%{+YYYY.MM.dd}"
	    }
	  }
	  if "access" in [tags] {
	    elasticsearch {
	      hosts => ["localhost:9200"]
	      index => "access-%{+YYYY.MM.dd}"
	    }
	  }
	  stdout {codec => rubydebug}
	  ```
	  
### Kibana应用
* 按照logstash的output在 `Kibana > Management > Index Patterns`配置**index**
* `Kibana > Discover` 提供一系列交互方式能非常直观的浏览并搜索数据。对数据定制过滤的过程是会被记录下来，可以理解成在查询过程中每一步操作都形成了报表，并以URL的方式可被调用，这样你就可以把URL发给其他人，在远端查看相同的过滤结果。
* `Kibana > Visualize` 可以根据自己的需求对不同的field定制图表，比如饼图，直方图，云图

 ![kibana visualize](https://pics.lxkaka.wang/kibana_visualize.jpeg)
 
* `Kibana > Dashboard` 添加Visualize中的图表创建Dashboard。
点“+”号按钮，选择已创建好的图表，然后在页面上拖拽布局。

 ![kibana dashboard](https://pics.lxkaka.wang/kibana_dashboard.jpeg)

	2018.07.12更新

### elasticsearch 删除历史数据
随着日志量的上升，机器硬盘总会达到上限，这就需要我们必须对历史数据做处理，释放硬盘空间。这里可以用两种方法来达到我们的目的。

#### 使用es api **_delete_by_query**
比如下面的示例，删除10天前的所有index
```
curl -H'Content-Type:application/json' -d'{
    "query": {
        "range": {
            "@timestamp": {
                "lt": "now-10d",
                "format": "epoch_millis"
            }
        }
    }
}
' -XPOST "http://127.0.0.1:9200/*/_delete_by_query?pretty"
```
然后使用 crontab 来定时执行上面的命令  
每5分钟执行一次  
`sudo crontal -e`  
`*/5 * * * * /usr/bin/curl -u username:password  -H'Content-Type:application/json' -d'{"query":{"range":{"@timestamp":{"lt":"now-7d","format":"epoch_millis"}}}}' -XPOST "http://127.0.0.1:9200/*-*/_delete_by_query?pretty" > /tmp/elk_clean.txt`

这种方法简单，易用。但是效率很低不适用大量数据的删除

#### 使用 [curator](https://www.elastic.co/guide/en/elasticsearch/client/curator/5.x/index.html)

* pip isntall elasticsearch-curator
* 配置文件
  ```yaml
	---
	client:
		hosts:
		- 127.0.0.1
		port: 9200
	logging:
		loglevel: INFO
		logfile: "/home/curator/logs/actions.log"
		logformat: default
		blacklist: ['elasticsearch', 'urllib3']
	```
* 定义删除操作
	
	```yaml
	---
	actions:
		1:
			action: delete_indices
			description: >-
				Delete indices older than 90 days (based on index name), for regex indices.
				Ignore the error if the filter does not result in an
				actionable list of indices (ignore_empty_list) and exit cleanly.
			options:
				ignore_empty_list: True
				timeout_override:
				continue_if_exception: False
				disable_action: False
			filters:
			- filtertype: pattern
				kind: regex
				value: ^.*
				exclude:
			- filtertype: age
				source: name
				direction: older
				timestring: '%Y.%m.%d'
				unit: days
				unit_count: 120
				exclude:
	```
	上面的示例表示删除120天前所有的索引  

* 执行`curator --config config.yml action.yml`  
当然也可以加入crontab来定时执行

这种方法虽然复杂，配置的条件需要详细阅读文档，但是功能强大，执行效率非常高。

