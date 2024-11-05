# 从Charles抓包理解HTTPS


### 抓包
当我们想分析线上请求的数据和响应是否符合预期，这个时候抓包就成了一种好的选择。抓包工具charles原理很简单用来做代理服务器，中途截获请求，即可展示request和response的内容。当想抓取 https 的请求，就需要做些额外的工作呢。首先得搞清楚抓取 https请求的原理吧，那么就得先挖一挖https。

### HTTPS原理总结
引用一段常见的概述：
> HTTPS(Hyper Text Transfer Protocol Secure)，是一种基于SSL/TLS的HTTP，所有的HTTP数据都是在SSL/TLS协议封装之上进行传输的。HTTPS协议是在HTTP协议的基础上，添加了SSL/TLS握手以及数据加密传输，也属于应用层协议。所以，研究HTTPS协议原理，最终就是研究SSL/TLS协议。  

简单说来，HTTPS就是增强HTTP的安全性，加密传输内容。为了保证这个加密的有效，有了SSL/TSL握手。所以，理解https就是理解这个握手过程。我画了下面这个图展示这个握手过程  
![握手过程](https://pics.lxkaka.wang/HTTPS.JPG)
针对此图，注明3点   
1. **核心是为了用对称加密(如AES）对传输内容进行加密**  
2. **为了保证这个这个加密密钥的安全，采用非对称加密(如RSA）来传递密钥**  
3. **为了防止中间人攻击，而必须验证服务器公钥的有效性，所以有了数字证书来做验证**

其中数字证书验证是一个关键步骤，其实这个数字证书是一个证书信任链。因为网站的数字证书不是由root CA直接颁发的，而是由intermediate CA颁发的。   

* 证书链是从网站证书开始，逐级向上，一直到根证书。每个证书的数字签名都是上级证书的私钥签署的。
* 浏览器和系统预置了受信任的根证书
* 验证到受信任的根证书，则验证通过(已经被浏览器信任，这是验证过程有效的前提）  

一次验证过程如图展示
![验证过程](https://pics.lxkaka.wang/%E9%AA%8C%E8%AF%81.png)
以X.509v3证书举例，server返回的证书其包含三部分：tbsCertificate、SignatureAlgorithm、SignatureValue；    
浏览器读取证书中的tbsCertificate部分（明文），使用SignatureAlgorithm中的散列函数计算得到信息摘要，并利用tbsCertificate中的公钥解密SignatureValue得到信息摘要，然后对比双方的信息摘要，判断是否一致；如果一致，则成功；如果不一致，则失败。

HTTPS就挖到这里，接下来理解Charles抓取HTTPS的包就水到渠成了。

### Charles抓HTTPS原理
* 我们的终端手机或电脑安装charles的根证书，表示信任Charles的根证书
*  charles作为代理，接收server返回的证书，而向终端返回自己伪造的证书
*  对终端来说不care，证书验证通过后，生成密钥用charles证书的公钥加密返回给了charles, charles自认能解密拿到这个密钥，然后再用server的公钥加密，发送给server
*  两端的HTTPS通信，就都被charles捕获到了

### 抓包步骤
1. 配置HTTP代理
`proxy > Proxy settings > `选择在8888端口上监听，然后确定; 勾选SOCKS proxy，还能截获到浏览器的http访问请求。
2. 配置SSL代理
 `proxy > SSL Proxy settings >`勾选 `Enable SSL Proxying`; 点add添加需要监视的域名，支持 *号通配符，端口一般都是443
3. 电脑安装charles根证书(抓取电脑流量)
`Help > SSL Proxying > Install Charles Root Certificate`
4. 手机安装charles根证书（抓取手机流量）  
   在Safri上打开Charles的根证书下载网址： chls.pro/ssl；点击安装
 
配置完成，手机端wifi设置里开启手动开启代理，ip为电脑IP，端口为8888(charles配置）
 


