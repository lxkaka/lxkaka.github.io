# 易于使用的性能测试工具-Locust

当我们对外提供服务的时候调用方经常会问这样一个问题：你们的服务能提供多大的 QPS？ 那么就要求我们在服务上线之前就应该清楚的知道服务的极限 QPS 是多少。大家都知道这个数值的得来就得靠压测。在这里我就给大家介绍一款简单易用并且自带可视化界面的压测工具-[Locust](http://docs.locust.io/en/stable/what-is-locust.html)。

### Locust 优点
* 测试场景脚本化
Locust 采用 Python 脚本描述测试场景，对于最常见的HTTP(S)协议的系统，Locust 采用 Python 的 `requests` 库作为客户端，使得脚本编写大大简化。而对于其它协议类型的系统，Locust也提供了接口，只要我们能采用 Python 编写对应的请求客户端，就能方便地采用Locust实现压力测试。

* 协程并发机制
采用多线程来模拟多用户时，线程数会随着并发数的增加而增加，而线程之间的切换是需要占用资源的，IO 的阻塞和线程的 sleep 会不可避免的导致并发效率下降。Locust 的并发机制摒弃了进程和线程，采用协程（gevent）的机制。协程避免了系统级资源调度，由此可以大幅提高单机的并发能力。

### Locust 使用
#### 安装
就和其他 Python 包一样，安装非常简单
```
pip install locust
# check 版本
locust -V
```

#### 使用示例
编写一个 locustfile，定义测试场景
```python
import time
from locust import HttpUser, task, between

# 这个类是我们用来模拟发起请求的用户
# 此类继承自 HttpUser, HttpUser 类包含的 client 属性就是一个用来发 Http 请求的 HttpSession
# 当开始运行测试，locust 会给每个模拟的 user 创建一个此类的实例
class QuickstartUser(HttpUser):
    # wait_time 定义了模拟用户的请求间隔时间，这里的含义是每个 user 会在一个请求结束后随机等 1-5s	
    wait_time = between(1, 5)

    # task 装饰架定义了模拟用户的行为，即发送什么样的 http 请求
    # 每个 user 都会起一个 greenlet 执行这些方法
    @task
    def hello_world(self):
        self.client.get("/hello")
        self.client.get("/world")

    # 这里的 3 是定义了这个待执行的行为相比上一个具有更高的优先级，或者说这个行为被执行的概率是上一个的 3 倍
    @task(3)
    def view_items(self):
        for item_id in range(10):
            self.client.get(f"/item?id={item_id}", name="/item")

    # 在每个 user 执行真的方法之前，定义的初始化操作，比如这里的模拟用户登录，那么后续用户就会保持响应的 session
    def on_start(self):
        self.client.post("/login", json={"username":"foo", "password":"bar"})
```
#### 重点方法
##### wait_time
  * constant: 请求间隔固定时间
  * between: 在最大值和最小值之间随机
  * constant_throughput: 每秒触发固定次数 task
  * constant_pacing: 固定秒数里执行一次 task(其实就是上面指标的倒数)

##### client  
client  是 `HttpSession` 的一个实例， 我们可以理解成它就是 Python 包 `requests.Session` 的扩展版。所以我们完全可以按照使用 `requests`的方式使用 `client`。  
例如    
`self.client.post(url=url, data=data_param, headers=headers, catch_response=True)`

##### 验证 response  
我们经常需要根据接口的实际返回内容来看某一次请求是否成功。下面的例子展示了在 locustfile 中如何定义测试的失败或者成功
```
with self.client.get("/", catch_response=True) as response:
    if response.text != "Success":
        response.failure("Got wrong response")
    elif response.elapsed.total_seconds() > 0.5:
        response.failure("Request took too long")
```

##### 请求分组    
经常会遇到某一个接口参数是动态的，比如根据 item id 查询 item `/item?id=abc"`。 默认情况下测试统计数据里 id 不同则每个请求都单独展示，而这一般不是我们想要到结果，我们往往只关注这一个接口的统计情况，所以需要把这样的请求分组。我们可以通过参数 `name`进行请求分组     
例如     
```python
# Statistics for these requests will be grouped under: /blog/?id=[id]
for i in range(10):
    self.client.get("/blog?id=%i" % i, name="/blog?id=[id]")
```

##### 代码组织  
我们经常会压测很多项目，把这些 locustfile 组织到一起是一个很好的实践方式。
下面是一种推荐方式
	* Project root

		* common/

			* __init__.py

			* auth.py

			* config.py

		* my_locustfiles/

			* api.py

			* website.py

		* requirements.txt


### 完整的示例
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 用locust
import json
import logging
import time

import requests
from locust import HttpUser, between, task

logHandler = logging.FileHandler('../logs/test.log')
logger = logging.getLogger()
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)


class MyUser(HttpUser):
    wait_time = between(0.3, 0.5)


    @task
    def my_task(self):
        url = "http://example.co/byp/api/interface/tts/task"
        payload = {
            "raw_params": {
                "biz_id": "tts389693391320943355",
                "voice": "db8",
                "method": 0,
                "logid": "",
                "text": [
                    "阿Test正经比比"
                ],
                "format": "wav",
                "sample_rate": 22050,
                "volume": 50,
                "speech_rate": 0,
                "pitch_rate": 0
            }
        }
        headers = {
            'Content-Type': 'application/json'
        }
        res = requests.post(url=url, data=json.dumps(payload), headers=headers)
        task_id = res.json()['data']['task_id']
        st = time.time()
        # logger.info(f'task: {task_id} {time.time()}')

        time.sleep(10)
        res_url = 'http://example.co/byp/api/interface/tts/task/result'
        with self.client.get(url=f'{res_url}?task_id={task_id}', name="/result", catch_response=True) as response:
            logger.info(f'task res:{task_id} {time.time()-st}')
            res = response.json()
            if res['code'] == 0 and res['data']['state'] == 4:
                response.success()
            else:
                response.failure(res.get('data'))
                logger.error(f'{task_id}')

```
在上面的这个 locustfile 里我们模拟的场景是用户提交任务立即返回，服务进行异步处理。在 10s 内如果能查询到任务结果我们认为对用户来说都是服务可用的。

* 压测  

```
$ locust -f locustfile.py
[2022-01-26 19:15:18,393] MacBook-Pro-3.local/INFO/locust.main: Starting web interface at http://0.0.0.0:8089 (accepting connections from all network interfaces)
[2022-01-26 19:15:18,399] MacBook-Pro-3.local/INFO/locust.main: Starting Locust 1.6.0
[2022-01-26 19:15:37,970] MacBook-Pro-3.local/INFO/locust.runners: Spawning 50 users at the rate 30 users/s (0 users already running)...
[2022-01-26 19:15:39,692] MacBook-Pro-3.local/INFO/locust.runners: All users spawned: MyUser: 50 (50 total running)
[2022-01-26 19:15:48,024] MacBook-Pro-3.local/INFO/root: task res:ts392026726928003325 10.019779205322266
[2022-01-26 19:15:48,044] MacBook-Pro-3.local/INFO/root: task res:ts392026726961557757 10.017950057983398

```
* 压测结果  

![locust-res](https://pics.lxkaka.wang/locust-res.png)  
我们通过多次调整 user 数找到了在不出现失败的情况下稳定的服务 QPS。    

其他场景或者需求可以查阅官方文档进一步探索。
