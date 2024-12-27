# 自定义 Wordpress URL 的方案

   
WordPress 是全球最流行的内容管理系统(CMS),截至2024年,已有超过43%的网站使用WordPress构建。作为一个开源项目,WordPress 始于2003年,从一个简单的博客平台发展成为一个功能强大的网站管理系统。它具有以下特点:
灵活的URL结构: WordPress 支持多种URL结构配置,包括普通链接和永久链接(Permalinks)
多站点支持: 可以在同一个WordPress安装中管理多个网站
目录灵活性: 支持安装在网站根目录或子目录中
可扩展性: 通过主题和插件系统,可以实现各种定制化需求

## Wordpress 两个关于 url 的重要概念  
### WP_HOME  
定义: 网站的公开访问地址，即用户在浏览器中访问您网站时使用的URL
用途: 决定了网站前台的访问路径
影响: 影响所有前台页面的URL生成，包括文章链接、分类页面等

### WP_SITEURL  
定义: WordPress核心文件所在的地址
用途: 指定WordPress系统文件的位置

一个场景 abc.com 是某公司的的主站，他们部署了一套 wordpress 生产一些内容。但是 wordpress 不可能和主站的前端部署到一起，就意味着 wordpress 可能是通过域名 def.com 来暴露。
这里 wordpress 的内容是为主站 SEO 服务的，所以必须让搜索引擎认为 wordpress 也是直接部署在 abc.com 下。
最直接的想法就是 abc.com/post 转发到 def.com 对于其他站点或者服务这是可行的，但是对于 wordpress 的 blog 会在静态页面里包含较多 def.com 也就是上面 **WP_HOME** 的信息。这样会严重影响 SEO。

# 解决方案
### 1. 域名转发
abc.com 网关这一层把 /post 前缀的请求转发到 k8s 集群的 Loadbalancer IP(假设 wordpress 部署在 k8s 中)而不是 redirect 到 def.com

### 2. k8s ingress 配置
在 k8s 中我们需要配置 ingress rule 把接受 host 为 abc.com 转发到 wordpress
如下配置    
```yaml
  - host: abc.com
    http:
      paths:
      - backend:
          service:
            name: wordpress-1-wordpress-svc
            port:
              number: 80
        pathType: ImplementationSpecific
```

### 3. WP_HOME 和 WP_SITEURL 定义
修改 wordpress 配置文件把默认配置   
```shell
define('WP_SITEURL', 'http://' . $_SERVER['HTTP_HOST'] . '/');
define('WP_HOME', 'http://' . $_SERVER['HTTP_HOST'] . '/');
```
修改为    
```
define('WP_HOME', 'https://abc.com/devpost');
define('WP_SITEURL', 'https://abc.com/devpost');
```

默认情况下 wordpress 的 apache 理由规则是从根目录 / 下加载静态资源，到这里会有两个明显问题  
1. 静态资源404: CSS、JavaScript等资源文件路径不正确  
2. 重定向循环: 不当的URL配置导致的无限重定向   

所以还必须调整 wordpress 的部署目录和转发规则   

### 4. 定义部署目录
```yaml
  volumeMounts:
  - mountPath: /var/www/html/post
    name: wordpress-1-wordpress-pvc
    subPath: wp
```

### 5. 修改 apache 转发规则
修改 .htaccess 如下  
```
# BEGIN WordPress
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteBase /devpost/
RewriteRule ^index\.php$ - [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
# Allow Apache mod_status
RewriteCond %{REQUEST_URI} !=/server-status
RewriteRule . /devpost/index.php [L]
</IfModule>
# END WordPress
```

