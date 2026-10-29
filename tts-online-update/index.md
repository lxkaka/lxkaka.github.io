# 服务在线更新配置或文件的方案设计

在 TTS 算法服务中我们的词典可能会经常更新，但如果是离线更新，那么势必要重新构建和服务发布。这样的带来的问题一是更新成本高，二是降低了服务稳定性。为了解决上述问题我们需要设计一套在线更新机制。在这篇文章里我们介绍一下我们的实践思路。

### 词典管理
词典我们可以理解成是服务的配置文件，但是与一般配置文件不同的是它可能包含多个并且每个尺寸可能还不小，大的能达到 20MB。首先我们不需要词典的更新实时生效，那么我们就可以不采用更新主动推送的机制（这样的开发成本很高), 而我们可以采用主动拉取的方式。这里我们选择了 `git` 来维护和管理词典，符合我们 `pull` 的方式，并且使用 `git` 有以下好处 
* git 本身就是版本管理工具，能非常方便迭代词典；
* gitlab 这样的的仓库方便 review 和权限控制；
* 文件大小和层级都不会成为障碍

### 方案
设计流程如下 

![tts-update](https://pics.lxkaka.wang/tts-update)  

#### 克隆词典
在服务首次启动的时候，容器里是没有任何词典配置的，这个时我们需要先把词典从 gitlab clone 下来。首先就是 repo 访问权限的问题，这里我们推荐使用 `deploy key` 访问 repo。
##### 创建项目级别的 deploy key 

![deploy-key](https://pics.lxkaka.wang/deploy_key)

##### 配置密钥  
我们可以在 CI 中通过 Protected Variable 把密钥写入到镜像，然后使得容器能访问 repo
```shell
#!/bin/bash

keydir=/root/.ssh
if [ ! -d "$keydir" ]; then
        mkdir -p $keydir
fi

echo "$Key" > /root/.ssh/id_ed25519
chmod 400 /root/.ssh/id_ed25519
ssh-keyscan git.example.com >> ~/.ssh/known_hosts
```

服务初次启动执行
```shell
#!/bin/bash

# clone 词典
bash /data/app/rubick_tts/online_update/clone.sh
# 启动词典更新进程
python /data/app/rubick_tts/update_lexicon.py &
```

#### 触发更新
更新过程如下  
```shell
#!/bin/bash

SCRIPTNAME="dict"
BRANCH="main"

self_update() {
    cd /data/app/BTTS/checkpoints/tts-lexicon
    git fetch

    # 检查特定目录是否有更新
    val=$(git diff --name-only origin/$BRANCH | grep $SCRIPTNAME)
    echo "$val"
    if [ -n "$val" ];then
        echo "Found a new version, updating..."
        git checkout $BRANCH
        git pull --force
        echo "Running the new version..."

        # 异步进程号
        pid=$(ps -ef | grep "/data/app/start/__init__.py" | grep -v grep | awk '{print $2}')
        if [ -z "$pid"];then
            # 同步进程号
            pid=$(ps -ef | grep "/data/app/grpc_server/server.py" | grep -v grep | awk '{print $2}')
        fi
        # 发送信号
        # 触发进程更新
        kill -SIGHUP $pid
        echo "$pid 更新完成"
        exit 1
    # 没有内容更新，跳过   
    else
      echo "Already the latest version."
    fi
}

self_update
```

#### 监听信号
在上一步我们看到如果有内容更新会发送信号 `SIGHUP`，为了完成更新，我们需要在服务里监听此信号并进行词典的更新。
```python
# 在服务的入口我们监听 SIGHUP 信号，然后触发词典更新函数
signal.signal(signal.SIGHUP, lexicon_update)

# 更新词典
# 这里 CVModel 是一个单例，所以我们的操作就是重新触发 CVModel 类的构造方法 __init__
# __init__ 里会重新加载词典
def lexicon_update(signum, frame):
    logger.warn('lexicon update')
    module = importlib.import_module(app_name)
    module.CVModel(**{'update': update})
```

##### 单例更新 
``` python
def singleton(cls):
    _instances = {}

    def get_instance(**kwargs):
        if cls not in _instances or kwargs.get('update'):
            _instances[cls] = cls(**kwargs)
        return _instances[cls]

    return get_instance


@singleton
class CVModel:
    def __init__(self, **kwargs):
        # 重新加载词典
        ...
    def run()   
        ...
```
我们在线更新词典就完成了。上面介绍的在线更新方案其实是非常通用的，有类似不通过重启服务实现远程配置或者文件的更新的需求都可以借鉴这样的方案。
