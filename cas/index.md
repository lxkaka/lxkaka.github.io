# 基于 CAS 实现 SSO


在之前的一些文章中我提到过我们的单点登录系统，作为我们内部系统的第一道门起着鉴权和验权的作用，总之是内部系统强有力的安全保障。
这里我们就以 CAS 协议为起点介绍一下单点登录系统的开发和搭建。
在当前的各个企业或公司都会有众多的内部系统，而且这些系统都需要身份验证成功才能访问，但是如果每个系统各自独立维护一套身份验证系统成本高不说对用户来说也是一个巨大的负担。那么能不能有一个中心的身份认证系统，只需要通过这个身份验证系统登录了众多系统中的一个，其他系统也能直接登录，自然从一个系统登出了，其他系统也就访问不了。这就是 SSO(单点登录)需要解决的问题。
CAS(Central Authentication Service) 是 Yale 大学发起的一个企业级的、开源的项目，旨在为 Web 应用系统提供一种可靠的单点登录解决方法。
### CAS 结构
CAS 有服务端和客户端组成
* 服务端：负责用户的身份验证工作，存储用户的安全凭证，作为一个身份验证的中心自然是需要独立部署的；
* 客户端：其实就是我们的各个应用，当用户访问到应用，需要对请求方进行身份认证时，重定向到 CAS Server 进行认证。
### 重要概念
* Service Ticket(ST): cas server 生成的一次性票据，用于验证服务的有效性，无论验证是否成功 ST 在使用后都已失效
* Ticket-granting Cookie(TGC): 存放用户身份认证凭证的 cookie ，在浏览器和 CAS Server 间通讯时使用，并且只能基于安全通道传输(https)，是 CAS Server 用来明确用户身份的凭证

### 访问流程
我们结合 CAS 的访问时序图来介绍一下 CAS 的原理。  
![flow-diagram](https://pics.lxkaka.wang/flow-diagram.png)
1. 访问目标应用一；
2. 需要身份验证，目标应用把用户重定向到 cas server 登录页面并且带上目标服务的访问地址作为请求参数；
3. cas server 检查用户没有 session, 则展示用户身份凭证输入框如用户名和密码；
4. 用户输入身份凭证，提交 post 请求到 cas server;
5. cas server 验证用户身份成功，cas 创建 sso session，返回 cookie 和 ST 给客户端；
6. 用户带着 ST 访问目标应用;
7. 目标应用携带 ST 访问 cas server 验证 ST 的合法性；
8. cas server 验证 ST 成功后，返回给目标应用 xml document 来说明用户身份校验成功；
9. 目标应用建立自己的 session， 并把 cookie 返回给客户端；
10. 客户端携带目标应用返回的 cookie 直接访问；
11. 目标应用验证 cookie 成功，返回对应的请求内容给客户端
至此，用户第弟一次访问成功。

如果用户第二次访问目标应用，流程则如下所示   
![second](https://pics.lxkaka.wang/second.png)
访问目标应用一  
客户端因为已经存储了目标应用第一次返回的 cookie, 则第二次访问目标应用验证成功后直接返回响应内容。

现在，用户访问另外一个应用，则流程如下   
![second-app](https://pics.lxkaka.wang/second-app.png)
1. 访问目标应用二
2. 需要身份验证，目标应用把用户重定向到 cas server 并且带上目标服务的访问地址作为请求参数； 
3. cas server 发现重定向过来的请求已经携带有 TGC 验证成功后，返回 ST 给客户端；
下面的步骤与用户访问应用一一致不在重复解释。
至此，用户不需要二次登陆就能成功访问应用二。  

### 集成  
我们简单把应用归一下类，自己开发的系统和利用第三方软件搭建的系统，如 Jenkins, Jira 这类。
* 首先自己开发的系统只要按照 CAS 协议调用 cas server 的接口就能完成集成；
* 例如 Jenkins, Jira 这类系统本身具有 CAS 插件，也能比较方便的利用插件完成 CAS 的集成
* 另外一类系统不是由自己开发，也不方便内部改造的，我们可以不完全按照 CAS 协议，在系统外部加上 cas server 的身份验证  

这里我们举一个例子，例如我们使用 Kibana 来查看 es 中的日志。Kibana 使用 Nginx 做反向代理，那么我们可以利用 Nginx 的 **auth_request** 模块集成 cas server, 来达到身份验证的目的。   
示例配置如下   
```
server {
    server_name  kibana.example.com;

    location / {
        auth_request /auth;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Server $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_pass http://kibana_server;
        client_max_body_size 200m;
    }
    location = /auth {
        internal;
        proxy_pass https://cas_server;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $request_uri;
    }

    error_page 401 https://cas_server/login/?service=https://$host$request_uri;
    error_page 403 https://cas_server/no_permission;
}
```

