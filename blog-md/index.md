# Github Page+Hexo搭建blog


## 1.创建自己的Github page
登录 *`https://github.com/lxkaka`* ,创建一个新repository，repository name 设置为 lxkaka.github.io,其他选项默认。点确认
然后在这个仓库的页面 *`https://github.com/lxkaka/lxkaka.github.io`* 的右边栏点Settings 往下拉找到GitHub Pages -> Automatic Page generator.  
访问 *https://lxkaka.github.io* 就能看到页面。
## 2. 安装Hexo
首先安装 hexo modul  
`$ npm install -g hexo`

建立一个文件夹，在次文件夹下  
`$ hexo init `   
`$ npm install`  
本地的Hexo博客已经初步搭建起来，输入以下指令:  
`$ hexo generate`//可以简写为 hexo g  
`$ hexo server`//可以简写为 hexo s

## 3. 部署Hexo到GitHub上
将本地博客deploy到GitHub上,输入以下指令  
`$ npm install hexo-deployer-git --save`  
然后打开博客目录的_config.yml文件，设置 url: http://lxkaka.github.io/ deploy的type为git，repository(repo)
为：*https://github.com/lxkaka/lxkaka.github.io.git*（需要在type和repo后面加上一个空格再填写）。（这一步是绑定自己域名）最后在Hexo目录中找到source文件夹，在其中新建一个文件CNAME，没有后缀名（建议使用Sublime Text新建）内容为你的域名（即ＸXXXXX．XXXXXX，不要加ＷＷＷ之类的前缀），保存。输入以下指令：  
`$ hexo g `   
`$ hexo deploy`//可简写为 hexo d

在执行 `hexo deploy` 后,出现 *error deployer not found:git* 的错误处理  输入代码：  
`npm install hexo-deployer-git --save`

目前还没绑定自己的域名。所以只能lxkaka.github.io 访问

## 发表新文章
用hexo发表新文章

`$ hexo n ''my new post‘’ `  
其中my new post为文章标题，执行命令后，会在项目\source_posts中生成my new post.md文件，用编辑器打开编写即可。

当然，也可以直接在\source_posts中新建一个md文件。
写完后，推送到服务器上，执行

`$ hexo g` #生成  
`$ hexo d` #部署 # 可与hexo g合并为 hexo d -g

## *Note:*
头像不显示解决办法:
接修改layout/_partial/left-col.ejs的第六行和第八行为：

        <img src="<%=theme.avatar%>" class="js-avatar show">
        <img src="<%=theme.avatar%>" class="js-avatar show" style="width: 100%;height: 100%;opacity: 1;">


