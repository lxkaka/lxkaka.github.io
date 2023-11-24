# uWSGI--一个WSGI server


* **相关背景知识，从 WSGI 说起:**

	Web应用框架的选择将限制可用的Web服务器的选择，反之亦然。那时的Python应用程序通常是为CGI，FastCGI，mod_python中的一个而设计，甚至是为特定Web服务器的自定义的API接口而设计的。WSGI 是为Python语言定义的Web服务器和Web应用程序或框架之间的一种简单而通用的接口。WSGI区分为两个部分：一为“服务器”或“网关”，另一为“应用程序”或“应用框架”。在处理一个WSGI请求时，服务器会为应用程序提供环境信息及一个回调函数（Callback Function）。当应用程序完成处理请求后，通过前述的回调函数，将结果回传给服务器。

	![uwsgi](https://pics.lxkaka.wang/uwsgi1.png)

	wsgi server可以理解为一个符合wsgi规范的web server，接收request请求，封装一系列环境变量，按照wsgi规范调用注册的wsgi app，最后将response返回给客户端。
	![process](https://pics.lxkaka.wang/req_process.png)
	
 <pre>
    a. 服务器创建socket，监听端口，等待客户端连接  
    b. 当有请求来时，服务器解析客户端信息放到环境变量environ中，并调用绑定的handler来处理请求
    c. handler解析这个http请求，将请求信息例如method，path等放到environ中  
    d. wsgi handler再将一些服务器端信息也放到environ中，最后服务器信息，客户端信息，本次请求信息全部都保存到了环境变量environ中  
    e. wsgi handler 调用注册的wsgi app，并将environ和回调函数（start_response)传给wsgi app  
    f. wsgi app 将reponse header/status/body 回传给wsgi handler  
    g. 最终handler还是通过socket将response信息塞回给客户端。  
  </pre>	

* CGI:

	外部应用程序（CGI程序）与Web服务器之间的接口标准，是在CGI程序和Web服务器之间传递信息的规程。简单点说CGI就是规定Web server要传哪些数据、以什么样的格式传递给 CGI 程序。CGI方式在遇到连接请求（用户请求）先要创建cgi的子进程，激活一个CGI进程，然后处理请求，处理完后结束这个子进程。这就是fork-and-execute模式。所以用cgi方式的服务器有多少连接请求就会有多少cgi子进程，子进程反复加载是cgi性能低下的主要原因。当用户请求数量非常多时，会大量挤占系统的资源如内存，CPU时间等，造成效能低下。
* FASTCGI：

	FastCGI是从CGI发展改进而来的。Fastcgi会先启一个master，解析配置文件，初始化执行环境，然后再启动多个worker。当请求过来时，master会传递给一个worker，然后立即可以接受下一个请求。这样就避免了重复的劳动，效率自然是高。而且当worker不够用时，master可以根据配置预先启动几个worker等着。
* uWSGI
	
	uWSGI是一个Web服务器，它实现了WSGI协议、uwsgi、http等协议。uWSGI，既不用wsgi协议也不用FastCGI协议，而是自创了一个uwsgi的协议，uwsgi协议是一个uWSGI服务器自有的协议，
	它是一个二进制协议,能够携带任意类型的信息，每一个uwsgi packet前4byte为传输信息类型描述，它与WSGI相比是两样东西。
	uWSGI 保留了 fastcgi 的优点，实现进程控制，预先设置好启动多个worker处理请求。
	
	![nginx-uwsgi](https://pics.lxkaka.wang/Nginx_uwsgi.jpg)
	
	nginx 通过 ngx_http_uwsgi_module模块把请求传递个 uWSGI 服务器。
	
	示例配置	
	
	```
	 location / {
    	include uwsgi_params;
    	uwsgi_pass localhost:9000;
  }
  ```
	常用配置参数
	
	```
	 uwsgi_pass [protocol://]address;   
	 设置uwsgi服务器的协议和地址，协议可是uwsgi或suwsgi（uwsgi over ssl）； 
	 地址可以是ip地址，域名，和可选的端口：
	 uwsgi_pass localhost:9000;
	 uwsgi_pass uwsgi://localhost:9000; 
	 uwsgi_pass suwsgi://[2001:db8::1]:9090; 
	 也可是unix socket： 
	 uwsgi_pass unix:/tmp/uwsgi.socket;
	 
	 uwsgi_read_timeout time;
	 Default:uwsgi_read_timeout 60s; 
	 定义从uwsgi服务器读取响应的超时时间，如果在超时时间内uwsgi服务器没有传输任何东西，连接会被断开。
```
	uwsgi_params 定义了传递到uWSGI服务器的参数，示例：
	
  <pre>
    uwsgi_param  QUERY_STRING       $query_string;  
    uwsgi_param  REQUEST_METHOD     $request_method;  
    uwsgi_param  CONTENT_TYPE       $content_type;  
    uwsgi_param  CONTENT_LENGTH     $content_length;  
    uwsgi_param  REQUEST_URI        $request_uri;  
    uwsgi_param  PATH_INFO          $document_uri;  
    uwsgi_param  DOCUMENT_ROOT      $document_root;  
    uwsgi_param  SERVER_PROTOCOL    $server_protocol;  
    uwsgi_param  REMOTE_ADDR        $remote_addr;  
    uwsgi_param  REMOTE_PORT        $remote_port;  
    uwsgi_param  SERVER_PORT        $server_port;  
    uwsgi_param  SERVER_NAME        $server_name;  
  </pre>	
	![nignx-uwsgi2](https://pics.lxkaka.wang/nginx_uwsgi2.png)

* uWSGI 常用配置项
	
	**socket or uwsgi-socket**  
	指定uwsgi的客户端将要连接的socket的路径（使用UNIX socket的情况）或者地址（使用网络地址的情况）。你最多可以同时指定8个socket选项。当使用命令行变量时，可以使用“-s”这个缩写。
	`--socket /tmp/uwsgi.sock`
		
	以上配置将会绑定到 /tmp/uwsgi.sock 指定的UNIX socket
	
	**protocol**  
	设置默认的通信协议（uwsgi，http，fastcgi）
	`--protocol <protocol>`
		
	**processes or workers**  
	为预先派生模式设置工作进程的数量。这个设置是app能实现简单并且安全的并发能力的基础。设置的工作进程越多，就能越快的处理请求。每一个工作进程都等同于一个系统进程，它消耗内存，所以需要小心设置工作进程的数量。如果设置的数量太多，就有可能是系统崩溃。	
	`--processes 8`
	
	以上配置会产生8个工作进程
		
	**harakiri**  
	这个选项会设置harakiri超时时间。如果一个请求花费的时间超过了这个harakiri超时时间，那么这个请求都会被丢弃，并且当前处理这个请求的工作进程会被回收再利用（即重启）。
	`--harakiri 60`
	
	这个设置会使uwsgi丢弃所有需要60秒才能处理完成的请求。
	harakiri-verbose
	当一个请求被harakiri杀掉以后，你将在uWSGI日志中得到一条消息。激活这个选项会打印出额外的信息（例如，在linux中会打印出当前的syscall）
	`--harakiri-verbose`
	
	以上配置会开启harakiri的额外信息。
	
	**daemonize**  
	使进程在后台运行，并将日志打到指定的日志文件或者udp服务器--daemonize /var/log/uwsgi.log 这个指令会让uWSGI在后台运行并将日志打到 /var/log/uwsgi.log文件中。
	
	**buffer-size**  
	设置用于uwsgi包解析的内部缓存区大小。默认是4k。如果接受一个拥有很多请求头的大请求，可以增加这个值到64k。  
	`--buffer-size 32768`
	  
	这个命令会允许uWSGI服务器接收最大为32k的uwsgi包，再大的包就会被拒绝。
	
	**auto-procname**  
	这个选项将自动给uWSGI的进程设置一些有意义的名字，例如“uWSGI master”， “uWSGI worker 1”， “uWSGI worker 2”。
	
	**procname-prefix**  
	这个选项为进程名指定前缀。
	
	`--procname-prefix <value>`
	
	**procname-prefix-spaced**  
	用这个选项给进程名指定前缀时，前缀和进程名之间有空格分隔。
	
	`--procname-prefix-spaced <value>`
	
	**procname-append**  
	这个选项为进程名增加指定的后缀。
	`--procname-append <value>`
		
	**master**  
	启动主进程。
	
	**max-requests**  
	为每个工作进程设置请求数的上限。当一个工作进程处理的请求数达到这个值，那么该工作进程就会被回收重用（重启）。你可以使用这个选项来默默地对抗内存泄漏（尽管这类情况使用reload-on-as和reload-on-rss选项更有用）。
	
	`
	[uwsgi]
	max-requests = 1000
	`
	上述配置设置工作进程没处理1000个请求就会被回收重用。
	
	**socket-timeout**  
	为所有的socket操作设置内部超时时间（默认4秒）。
	`--socket-timeout 10`
	
	这个配置会结束那些处于不活动状态超过10秒的连接。
	
	**module [python plugin required]**  
	加载指定的python WSGI模块（模块路径必须在PYTHONPATH里）
	
  ![simple](https://pics.lxkaka.wang/simple.png "简单架构实例")
   

		
		

	

