# Hexo 迁移 Hugo

如果大家有想把博客 Hexo 迁移到 Hugo 的可以参考此文。
Hugo 的优势：
* 不需要额外的依赖，一个二进制文件 Hugo 就行，这样的话维护成本会降低
* 编译生成静态文件非常快

## 安装 Hugo 
Hugo 的安装非常简单，mac 我并不推荐使用 brew 安装，实在太慢，即使更换了代理源速度也不快。这里我推荐直接下载二进制文件，简单又快捷。
* 下载地址 `https://github.com/gohugoio/hugo/releases/download/v0.71.1/hugo_extended_0.71.1_macOS-64bit.tar.gz `
   版本可以自由选择，但推荐下载 extended version, 有些主题需要 extended version 的支持
* 解压得到二进制文件
  `tar xzvf hugo_extended_0.71.1_macOS-64bit.tar.gz `
* 创建一个 bin 目录，把二进制执行文件 `hugo` 放到 bin 目录
* 把创建的 bin 目录添加到环境变量 PATH 中,例如 `export PATH=$PATH:/Users/lxkaka/bin`
* 重新打开 terminal 或者 `source .zshrc`, 让 PATH 生效
* 验证安装 `hugo version`

## 配置主题
Hugo 支持的主题也非常多，大家可以去 Hugo theme [网站](https://themes.gohugo.io)上看到很多主题，挑选自己喜欢的。
* 新建站点
 `hugo new site mySite`
  cd mySite 看到由以下文件和目录组成
  ```
    drwxr-xr-x  3 lxkaka  staff  96  7 24 16:20 archetypes
    -rw-r--r--  1 lxkaka  staff  82  7 24 16:20 config.toml
    drwxr-xr-x  2 lxkaka  staff  64  7 24 16:20 content
    drwxr-xr-x  2 lxkaka  staff  64  7 24 16:20 data
    drwxr-xr-x  2 lxkaka  staff  64  7 24 16:20 layouts
    drwxr-xr-x  2 lxkaka  staff  64  7 24 16:20 static
    drwxr-xr-x  2 lxkaka  staff  64  7 24 16:20 themes
  ```
* 进入的 `themes` 目录 clone 自己喜欢的主题
  复制 clone 的主题目录 exampleSite 下的配置文件夹 `config.toml` 到站点的的根目录。例如
  `cp themes/color-your-world/exampleSite/config.toml .`

* 按照需求修改 `config.toml`

## 迁移
Hexo 和 Hugo 对 markdown 文件中 Front Matter 的格式定义不同。需要修改所有的文章来适配 Hugo 的 Front matter。
这里推荐一个脚本 `https://github.com/wd/hexo2hugo/blob/master/hexo2hugo.py`  
* 安装依赖
  ```
  python3 -m pip install pyyaml
  python3 -m pip install pytoml
  ```
* 转换文件格式
  ```
  # src 是原来所有文章的目录；dest 是转换后要放文章的目录
  python3 hexotohugo.py --src=~/mySpace/source/_posts/ --dest=./posts/converted --remove-date-from-name --verbose

  # 转换前文章 front matter 如下
  title: 基于 CAS 实现 SSO
  date: 2019-04-19 16:24:31
  tags:
    - cas
    - sso
  ---
  # 转换后文章 front matter 如下
  +++
  title = "基于 CAS 实现 SSO"
  date = "2019-04-19T16:24:31+08:00"
  tags = ["cas", "sso"]
  description = ""
  +++
  ```
* url 格式
  在 Hexo 一般 url 的格式配置成这样 `permalink: :year/:month/:day/:title/`,  为了不让以前的 url 实效，我们在 Hugo 的配置文件 config.toml 需要配置如下  
  ```toml
  [Permalinks]
  posts = "/:year/:month/:day/:filename/"
  ```
  
## deploy
Hugo 的命令行没有直接支持 deploy, 这里我们用简单脚本可以来代替。
在站点目录下执行 `hugo` 在 `public` 目录下生成我们部署所需的全部静态文件，我们只需要把 public 下的静态文件通过 rsync 上传到服务器即可。
这个过程用脚本描述如下  
```bash
#!/bin/sh
USER=my-user
HOST=my-server.com             
DIR=my/directory/to/topologix.fr/   # the directory where your web site files should go

hugo && rsync -avz --delete public/ ${USER}@${HOST}:~/${DIR}

exit 0
```
执行 `bash deploy.sh`则完成了部署。
服务器上 Nginx 示例配置如下  
```
server {
    root /home/lxkaka/hugo;

    location = / {
        root /home/lxkaka/hugo;
        index index.html index.htm;
   }
...
}
```

至此，迁移 Hugo 的主要过程就是这样，如果大家遇到啥问题欢迎交流。
