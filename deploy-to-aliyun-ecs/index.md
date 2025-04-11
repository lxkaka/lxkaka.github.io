# Hexo blog部署到阿里云ecs小结


## 部署架构
* 目的很简单，就是在服务器上搭建git服务(自己服务器上的GitHub). hexo部署的时候，把本地repo推到远程repo.  
* 利用 git hook触发远程repo更新
* 服务器的根目录指向远程repo

![blog部署架构](https://pics.lxkaka.wang/194667281-5760cfced0e4f_articlex.png)

## 部署步骤
### 1.服务器搭建git服务
* 安装git 
  以 Ubuntu为例，user.name user.email配置随意
`sudo apt-get install git`

* 建立远程repo

	```
   mkdir /home/lxkaka/blog  
   cd /hoem/lxkaka/blog  
   git init --bare blog.git  ## --bare指明为裸仓库，看不到内容
	```
* 编写hook脚本  
`vi blog.git/hooks/post-receive`
 
 ```
 # !/bin/sh
 echo "Upstate Start..."
 unset GIT_DIR
 git pull origin master
 echo "Upstate Success!"
 ```
保存并修改为可执行权限：  
`chmod +x hoos/post-receive`
### 2. Nginx安装及配置
服务器上如果没有安装，先`apt-get install`  
然后修改nginx 配置文件
`/etc/nginx/nginx.conf`  
看到里面并没有*server*部分，引入了别的配置文件。
编辑`/etc/nginx/sites-enabled`下的配置文件

	```
	server {
		listen      80;     #端口
		server_name localhost 你的域名或者ip;     #域名或IP
		root       /home/lxkaka/blog;      #站点根目录
		charset     utf-8;              #文件编码
		index       index.html index.htm;    #首页
		error_page  404     /404.html;   #404页面
		error_page  500 502 503 504     /50x.html;   #服务端错误页面
		#url访问匹配路径，可以添加多个
		location / {
		     index       index.html index.htm;
		     root        /home/lxkaka/blog;   #这里可以是绝对路径或者相对路径，基于站点根目录
		 }
	}
```

* 检查nginx配置  
`nginx -t -c /etc/nginx/nginx.conf`
`nignx -t ## 在当前配置文件目录下,简写形式`
* 重启nignx  
`/etc/init.d/nignx restart` 

至此远端服务器的工作完成

### 3. 本地修改配置
* 修改hexo目录下的_config.yml

	```
	deploy:
		type: git
		repo: 用户@域名或ip:/home/lxkaka/blog/bog.git
		branch: master
	```
* 测试：  
 修改或新建某篇blog后
`hexo g --d`
* 在服务器上clone一下repo,才能看到发布的静态文件  
 `cd /home/lxkaka/blog`  
 `git clone blog.git` 
  
如果一切顺利，访问你的域名，博客就呈现出来了。

### 4. 可能遇到的问题：
* nginx配置好后，访问500  
 解决：问题是ecs的安全组规则拒绝80端口的访问，去管理后台配置一下安全组规则。
* 访问403  
解决: 查看nginx进程的拥有者看是否具有相关文件的权限 `ps aux|grep nginx`, 发现 `worker`的拥有者是www-data. 修改`nignx.conf`的user 为`root`或者具有权限的用户。
* cannot run hooks/post-receive: No such file or directory  
解决：检查脚本内容是否正确，是否拥有权限。





