# 使用 zing-gallery 添加相册


## 实现方法总述
1. 用 **zing-gallery** 启动一个相册服务(nodejs), 使用很简单, 一个命令 `npm run start`就启动了。
2. 修改blog页面代码
3. 把相册页面链接到blog菜单栏  

有点像把🐘装进冰箱的操作哈！！

## 分步走起
### 1. 安装启动相册服务
* clone zing-gallery 到服务器上  
`git clone https://github.com/lxkaka/zing-gallery.git`

* 把照片放到 *resources/photos* 下，相册的相关配置比如封面，密码都在 *config.js* 下设置。修改方式可参照文件里的配置。举例：

	```
module.exports = {
        title: 'lxkaka Gallery',
        wording: {
                noAccess: '抱歉，你没有权限访问'
        },
        albums: {
                "个人": {
                  description : "私密",
                  name: "个人",
                  password: "233",
                 //passwordTips: "密码是233"
                },
                "landscape": {
                  description : "风光掠影",
                  thumbnail : "WechatIMG24.jpg"
                },
                "cj2017": {
                  description : "2017cj 小记",
                  thumbnail : "IMG_1646.jpg"
                }
        }
} 
```
* 启动相册服务进程  
前提 npm 已经安装  
`npm run start`  
默认端口是3000, 可在 *app.js* 里修改

现在访问 **服务器域名或ip:3000** 应该就能看到自己的相册

### 2. 修改主菜单ejs,添加相册入口
在 *layout/_partial/left_col* 下修改主菜单部分

```
<nav class="header-menu">
    <ul>
    <% for (var i in theme.menu){ %>
             <li><a href="<%- url_for(theme.menu[i]) %>"><%= i %></a></li>
     <%} %>
     <li><a href="http://lxkaka.wang/gallery/">我的相册</a></li>
    </ul>
</nav>
```

### 3. 配置nginx监听相册请求
修改ningx配置文件，添加转发配置

```
# pass the gallery request to node server listening on 127.0.0.1:3000
location /gallery/ {
        proxy_pass http://127.0.0.1:3000/;
}
```
这里需要注意nginx的 **proxy_pass** 路径的问题，代理转发时，如果在 **proxy_pass**后面的url带上 **/**，表示绝对路径；没有 **/**则为相对路径。

所以上面例子，当nignx匹配到 */gallery/* 的路径时，转发路径是 http://127.0.0.1:3000/ 而不是 http://127.0.0.1:3000/gallery

### 4. 用supervisor管理进程
supervisor这里就不多说了，直接来使用方法。 
   
* 首先 ubuntu下推荐用 apt-get 方式安装supervisor, 因为这种方式自动生成配置文件，会开机自动启动supervisord，不需要手动设置。（当然可以选择 pip install）  
`apt-get install supervisor` 
 
* 修改配置supervisor服务端配置文件 *supervisord.conf* 默认位置 */etc/supervisord.conf*
增加进程管理配置文件，推荐用 **include** 方式。

	```
	[include]
	files = /etc/supervisor/conf.d/*.conf
	```
在上面include路径下添加进程管理配置文件 node_gallery.conf

	```
	[program:zing-gallery]   ;进程名，对应supervisor客户端supervisorctl中对进程管理的名字
	command=npm run start    ;启动命令
	autostart=true           ;supervisord启动的时候启动
	directory=/home/lxkaka/zing-gallery   ;进程的启动目录
	autorestart=true         ;进程异常退出后自动重启 
	startsecs=10             ;进程启动多少秒之后，此时状态如果是running，则认为启动成功
	startretries=5           ;最大启动重试次数
	```
其他详细配置可参看 http://www.cnblogs.com/ajianbeyourself/p/5534737.html

至此，相册服务也实现了自动启动和重启。相册功能算是添加完成了。

zing-gallery项目地址 https://github.com/litten/zing-gallery 

