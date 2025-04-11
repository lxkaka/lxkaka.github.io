# 搭建微信公众号服务小记


## 需求
说起来都是泪。平时工作生活中习惯不好，脏话有点多了，比如 卧槽，沙比这种。虽然我认为这样的词在说的时候完全只是当语气词来用，但毕竟是脏话。所以，女朋友受不了，必须要纠正这样的恶习（她也会说脏话）。她说得记录我们说的次数，然后统计出来，我说好啊，每个月还要按照统计数发红包。于是，在这样的背景下我就想那就写个页面记录和展示吧。转念一下，这样需要女朋友这样的小白用户输入网址，提交表单不是太友好，于是想到了她经常用微信那不如搞一个微信公众号，除了这个功能还可以添加其他功能。So, 需求定下来了~~
## 实现
那么按照需求（文档）拆解了一下工作：  

    1. 本地开发，测试  
    2. 申请公众号
    3. 部署服务
    4. 调试运行
    5. 优化流程

### 本地开发
* web框架选用Tornado，因为Tornado本身就是 Web server + Web application 框架，并且自带异步库和协程库。而我选用Django或Flask这样的web 框架，还需要搭建web server比如uWSGI, gunicorn。     
* 存储用MongoDB和Redis
* 用Docker部署(轻松的迁移，维护和部署)

    Dockerfile示例：
    
    ```
    FROM python:3.6

    EXPOSE 8888

    ENV TZ Asia/Shanghai
    RUN echo $TZ > /etc/timezone && \
        apt-get update && apt-get install -y tzdata && \
        rm /etc/localtime && \
        ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
        dpkg-reconfigure -f noninteractive tzdata && \
        apt-get clean

    # ENV PIP_INDEX_URL http://mirrors.aliyun.com/pypi/simple
    # ENV PIP_TRUSTED_HOST mirrors.aliyun.com

    RUN mkdir -p /var/www/lxkaka
    WORKDIR /var/www/lxkaka
    COPY requirements.txt /var/www/lxkaka
    RUN pip install -r requirements.txt

    COPY ./lxkaka/ /var/www/lxkaka/
    CMD python server.py
    ```
    服务器相关配置统一写到server.conf，示例：

    ```
    port=8888

    APPID = "wxxxxxxxxxxxxx"
    TOKEN = "lxkaka"
    AES_KEY = "121234nmngvlkghkhlghghh"
    ```
    Tornado服务启动示例:
    ```python
    # app启动和入口
    class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r'/debug/', DebugHandler),
        ]
        settings = dict(
            blog_title='lxkaka',
            xsrf_cookies=False,
            cookie_secret='',
            login_url='/auth/login',
            debug=True,
        )
        super(Application, self).__init__(handlers, **settings)


    def main():
        tornado.options.parse_config_file('server.conf')
        tornado.options.parse_command_line()
        http_server = tornado.httpserver.HTTPServer(Application())
        http_server.listen(options.port)
        tornado.ioloop.IOLoop.current().start()


    if __name__ == '__main__':
        main()
    
    # 接口处理
    class DebugHandler(tornado.web.RequestHandler):
        async def get(self, *args, **kwargs):
            data = {
                'APPID': options.APPID,
                'TOKEN': options.TOKEN,
                'author': 'lxkaka',
            }
            self.finish(json.dumps(data, ensure_ascii=False)) 
    ```

### 申请公众号
* https://mp.weixin.qq.com/  
    ![申请公众号](https://pics.lxkaka.wang/%E5%85%AC%E4%BC%97%E5%8F%B7.jpeg)
* 公众号关键配置  
    ![公众号配](https://pics.lxkaka.wang/%E5%85%AC%E4%BC%97%E5%8F%B7%E9%85%8D%E7%BD%AE%E7%A4%BA%E4%BE%8B.jpeg)

### 服务部署
* 方案1 利用FTP推送代码
配置简单，直接可利用IDE的deploy功能一键发布代码  
    * 安装vsftpd  
    `sudo apt-get install vsftpd`
    * 创建FTP用户  
    为FTP创建特定用户，一是为了避免匿名用户登录，二是禁止用户越权访问其它文件目录内容。
    ```
    # 新建用户以及对应的用户目录，禁止登录系统
    sudo useradd -d /home/[username] -s /sbin/nologin -m [username]
    # 更改密码
    sudo passwd [username]
    # 调整权限
    sudo chmod a-w /home/[username]
    # 创建data目录，避免500错误。
    # data目录为ftp上传目录
    sudo mkdir /home/[username]/data
    sudo chown -R [username]:[username] /home/[username]/data
    ```
    * ftp配置文件
    vsftpd的配置文件在/etc/vsftpd.conf
    关键配置修改如下：
    ```
    # Allow anonymous FTP? (Disabled by default).
    anonymous_enable=NO
    # 配置文件末尾添加
    userlist_deny=NO
    userlist_enable=YES
    userlist_file=/etc/vsftpd.allowed_users
    ```
    * 创建文件 /etc/vsftpd.allowed_users，写入用户名
    ```
    # 创建并写入用户名
    vim /etc/vsftpd.allowed_users
    # 重启ftp服务
    sudo service vsftpd restart
    ```
    * 客户端配置  
    ![ftp客户端](https://pics.lxkaka.wang/ftp-client.png)

* 方案2 用git+git-hook发布和自动部署  
    * 搭建git服务器  
    ```
    # 新建远程仓库文件夹
    mkdir /home/lxkaka/server-repo
    # 初始化远程仓库
    git init --bare
    # 在本地repo添加origin 地址
    git remote add origin git@ip(或者host):/home/lxkaka/server-repo 
    ```
    至此本地开发测试完成，可直接push代码到远程仓库  
    * 配置git hook
    在/home/lxkaka/servr-repo/hooks下面存在许多hook的例子，配置post-update hook就能满足需求  
    在此目录下  
    `vim post-update`  
    # 写入以下脚本  
        ```sh
        #!/bin/sh
        #
        # An example hook script to prepare a packed repository for use over
        # dumb transports.
        #
        # To enable this hook, rename this file to "post-update".

        unset GIT_DIR
        # 代码库
        DIR=/home/lxkaka/server/
        cd $DIR
        # 更新代码
        git pull origin master

        docker-compose -f docker-compose.yml up --build -d
        ```
    查看 post-update是否有x权限, 没有添加   

    `chmod +x post-update`

### 用docker-compose管理多个容器应用
这里有web服务容器，redis容器，mongo容器。通过编写docker-compose.yml来关联不同的容器为一个项目(project)。
Compose 中有两个重要的概念：  
服务 (service)：一个应用的容器，实际上可以包括若干运行相同镜像的容器实例。  
项目 (project)：由一组关联的应用容器组成的一个完整业务单元，在 docker-compose.yml 文件中定义。  

Compose 的默认管理对象是项目，通过子命令对项目中的一组容器进行便捷地生命周期管理。
docker-compose.yml示例如下：
```yml
mongo:
  restart: always
  image: mongo:3.4.9
  volumes:
    - ./data/db:/data/db
redis:
  restart: always
  image: redis:4.0.2
lxkaka:
  restart: always
  build: .
  links:
    - mongo
    - redis
  environment:
    - PIP_INDEX_URL=http://mirrors.aliyun.com/pypi/simple
    - PIP_TRUSTED_HOST=mirrors.aliyun.com
  ports:
    - "8888:8888"
```

### Nginx配置
最重要的是虚拟主机部分的配置，这里有三种服务，通过不同的location匹配到不同的服服务。
```
server {
        listen 80;
        server_name www.lxkaka.wang lxkaka.wang;

        charset utf-8;

        root /home/lxkaka/blog;
        # Add index.php to the list if you are using PHP
        index index.html index.htm index.nginx-debian.html;

       location = / {
               root /home/lxkaka/blog;
               index index.html index.htm;
               autoindex on;
       }

        # pass the gallery request to node server listening on 127.0.0.1:3000
        location /gallery {
                proxy_pass http://127.0.0.1:3000/;
        }


        listen 443 ssl http2; # managed by Certbot
        ssl_certificate /etc/letsencrypt/live/lxkaka.wang/fullchain.pem; # managed by Certbot
        ssl_certificate_key /etc/letsencrypt/live/lxkaka.wang/privkey.pem; # managed by Certbot
        include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot

        # Allow file uploads
        client_max_body_size 50M;
        location ^~ /api/ {
            proxy_pass_header Server;
            proxy_set_header Host $http_host;
            proxy_redirect off;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Scheme $scheme;
            proxy_pass http://127.0.0.1:8888/;
        }
    }
```


