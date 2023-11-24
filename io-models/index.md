# 操作系统IO模式(重整)


## 1.关键概念理解
* 	同步：发起一个调用，得到结果才返回。  
*	异步：调用发起后，调用直接返回；调用方主动询问被调用方获取结果，或被调用方通过回调函数。  
*	阻塞：调用是指调用结果返回之前，当前线程会被挂起。调用线程只有在得到结果之后才会返回。  
*	非阻塞：调用指在不能立刻得到结果之前，该调用不会阻塞当前线程。  

	同步才有阻塞和非阻塞之分；  
	阻塞与非阻塞关乎如何对待事情产生的结果（阻塞：不等到想要的结果我就不走了）


## 2.明确进程状态
理解进程的状态转换 
 
*  就绪状态 -> 运行状态：处于就绪状态的进程被调度后，获得CPU资源（分派CPU时间片），于是进程由就绪状态转换为运行状态。  
* 运行状态 -> 就绪状态：处于运行状态的进程在时间片用完后，不得不让出CPU，从而进程由运行状态转换为就绪状态。此外，在可剥夺的操作系统中，当有更高优先级的进程就 、 绪时，调度程度将正执行的进程转换为就绪状态，让更高优先级的进程执行。  
* 运行状态 -> 阻塞状态：当进程请求某一资源（如外设）的使用和分配或等待某一事件的发生（如I/O操作的完成）时，它就从运行状态转换为阻塞状态。进程以系统调用的形式请求操作系统提供服务，这是一种特殊的、由运行用户态程序调用操作系统内核过程的形式。  	
* 阻塞状态 -> 就绪状态：当进程等待的事件到来时，如I/O操作结束或中断结束时，中断处理程序必须把相应进程的状态由阻塞状态转换为就绪状态。
![进程状态转换](https://pics.lxkaka.wang/%E8%BF%9B%E7%A8%8B%E7%8A%B6%E6%80%81.png)

## 3.从操作系统层面执行应用程序理解 IO 模型
### 阻塞IO模型：  
* 简介：进程会一直阻塞，直到数据拷贝完成应用程序调用一个IO函数，导致应用程序阻塞，等待数据准备好。 如果数据没有准备好，一直等待….数据准备好了，从内核拷贝到用户空间，IO函数返回成功指示。
我们 第一次接触到的网络编程都是从 listen()、send()、recv()等接口开始的。使用这些接口可以很方便的构建服务器 /客户机的模型。  
* 阻塞I/O模型图：在调用recv()/recvfrom（）函数时，发生在内核中等待数据和复制数据的过程。
![阻塞IO](https://pics.lxkaka.wang/blockio.png)
 当调用recv()函数时，系统首先查是否有准备好的数据。如果数据没有准备好，那么系统就处于等待状态。当数据准备好后，将数据从系统缓冲区复制到用户空间，然后该函数返回。在套接应用程序中，当调用recv()函数时，未必用户空间就已经存在数据，那么此时recv()函数就会处于等待状态。    
阻塞模式给网络编程带来了一个很大的问题，如在调用 send()的同时，线程将被阻塞，在此期间，线程将无法执行任何运算或响应任何的网络请求。这给多客户机、多业务逻辑的网络编程带来了挑战。这时，我们可能会选择多线程的方式来解决这个问题。  
应对多客户机的网络应用，最简单的解决方式是在服务器端使用多线程（或多进程）。多线程（或多进程）的目的是让每个连接都拥有独立的线程（或进程），这样任何一个连接的阻塞都不会影响其他的连接。  
具体使用多进程还是多线程，并没有一个特定的模式。传统意义上，进程的开销要远远大于线程，所以，如果需要同时为较多的客户机提供服务，则不推荐使用多进程；如果单个服务执行体需要消耗较多的 CPU 资源，譬如需要进行大规模或长时间的数据运算或文件访问，则进程较为安全。

### 非阻塞IO模型
* 简介：非阻塞IO通过进程反复调用IO函数（多次系统调用，并马上返回）；在数据拷贝的过程中，进程是阻塞的；
我们把一个SOCKET接口设置为非阻塞就是告诉内核，当所请求的I/O操作无法完成时，不要将进程睡眠，而是返回一个错误。这样我们的I/O操作函数将不断的测试数据是否已经准备好，如果没有准备好，继续测试，直到数据准备好为止。在这个不断测试的过程中，会大量的占用CPU的时间。
![非阻塞IO](https://pics.lxkaka.wang/nonblock.png)

### IO复用模型：
* 简介：IO multiplexing就是我们说的select，poll，epoll，有些地方也称这种IO方式为event driven IO。select/epoll的好处就在于单个process就可以同时处理多个网络连接的 IO。它的基本原理就是select，poll，epoll这个function会不断的轮询所负责的所有socket，当某个socket有数据到达了，就通知用户进程。
![io多路复用](https://pics.lxkaka.wang/iomultiplex.png)
当用户进程调用了select，那么整个进程会被block，而同时，kernel会“监视”所有select负责的socket，当任何一个socket中的数据准备好了，select就会返回。这个时候用户进程再调用read操作，将数据从kernel拷贝到用户进程。  
所以，I/O 多路复用的特点是通过一种机制一个进程能同时等待多个文件描述符，而这些文件描述符（套接字描述符）其中的任意一个进入读就绪状态，select()函数就可以返回。

### 异步IO模型
* 简介：用户进程发起read操作之后，立刻就可以开始去做其它的事。而另一方面，从kernel的角度，当它受到一个asynchronous read之后，首先它会立刻返回，所以不会对用户进程产生任何block。然后，kernel会等待数据准备完成，然后将数据拷贝到用户内存，当这一切都完成之后，kernel会给用户进程发送一个signal，告诉它read操作完成了。
![asyncio](https://pics.lxkaka.wang/ayscio.png)

## 4.区别IO多路复用中的select poll epoll 
### select
`int select (int n, fd_set *readfds, fd_set *writefds, fd_set *exceptfds, struct timeval *timeout);`    
`select` 函数监视的文件描述符分3类，分别是`writefds`、`readfds`、和`exceptfds`。调用后select函数会阻塞，直到有描述符就绪（有数据 可读、可写、或者有except），或者超时（timeout指定等待时间，如果立即返回设为null即可），函数返回。当select函数返回后，可以 通过遍历fdset，来找到就绪的描述符
### poll
`int poll (struct pollfd *fds, unsigned int nfds, int timeout);`
不同与select使用三个位图来表示三个fdset的方式，poll使用一个 `pollfd`的指针实现。pollfd并没有最大数量限制（但是数量过大后性能也是会下降）。 和select函数一样，poll返回后，需要轮询pollfd来获取就绪的描述符。
### epoll
epoll是通过事件的就绪通知方式，调用`epoll_create`创建实例，调用`epoll_ctl`添加或删除监控的文件描述符，调用`epoll_wait`阻塞住，直到有就绪的文件描述符，通过`epoll_event`参数返回就绪状态的文件描述符和事件。
  
epoll操作过程需要三个接口，分别如下：
`int epoll_create(int size)；//创建一个epoll的句柄`，size用来告诉内核这个监听的数目一共有多大
生成一个 epoll 专用的文件描述符，其实是申请一个内核空间，用来存放想关注的 socket fd 上是否发生以及发生了什么事件。
  
`int epoll_ctl(int epfd, int op, int fd, struct epoll_event *event)；`  
控制某个 epoll 文件描述符上的事件：注册、修改、删除。其中参数 epfd 是 epoll_create() 创建 epoll 专用的文件描述符。

`int epoll_wait(int epfd, struct epoll_event * events, int maxevents, int timeout);`  
等待 I/O 事件的发生；返回发生事件数。参数说明：  
`epfd`: 由 epoll_create() 生成的 Epoll 专用的文件描述符；  
`epoll_event`: 用于回传代处理事件的数组；  
`maxevents`: 每次能处理的事件数；  
`timeout`: 等待 I/O 事件发生的超时值； 
### 区别总结
（1）select，poll实现需要自己不断轮询所有fd集合，直到设备就绪，期间可能要睡眠和唤醒多次交替。而epoll其实也需要调用epoll_wait不断轮询就绪链表，期间也可能多次睡眠和唤醒交替，但是它是设备就绪时，调用回调函数，把就绪fd放入就绪链表中，并唤醒在epoll_wait中进入睡眠的进程。虽然都要睡眠和交替，但是select和poll在“醒着”的时候要遍历整个fd集合，而epoll在“醒着”的时候只要判断一下就绪链表是否为空就行了，这节省了大量的CPU时间。这就是回调机制带来的性能提升。  
（2）select，poll每次调用都要把fd集合从用户态往内核态拷贝一次，epoll 通过 mmap 把内核空间和用户空间映射到同一块内存，省去了拷贝的操作。 
### 应用举例
* Tornado：  
	* 使用单线程的方式，避免线程切换的性能开销，同时避免在使用一些函数接口时出现线程不安全的情况  
	* 支持异步非阻塞网络IO模型，避免主进程阻塞等待。     

	tornado 的 IOLoop 模块 是异步机制的核心，它包含了一系列已经打开的文件描述符和每个描述符的处理器	（handlers）。这些 handlers 就是对 select， poll , epoll等的封装。（所以本质上说是 IO 复用）  
* Django  
 没有用异步，通过使用多进程的WSGI server（比如uWSGI）来实现并发，这也是WSGI普遍的做法。
