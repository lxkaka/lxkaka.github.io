# Django中sentry怎么抓取异常


[Sentry](https://docs.sentry.io/)是我们查看线上bug最适用和好用的工具。因为sentry能帮我们完整记录bug或异常的上下文，能有效帮助我们定位和分析问题，查看方便并且具有通知功能，受到我们开发者的热烈拥护。具体在Django中使用sentry还是比较简单的，[官方文档](https://docs.sentry.io/clients/python/integrations/django/)清晰明了。
在我们的项目中，只要是`Exception`都能被sentry捕获并且发送至sentry服务器，那么代码中抛出的`Exception`是怎么被sentry捕获到的呢？

这篇小记就是分析记录sentry的客户端raven在Django中的工作原理。
在我们的项目中包含两类`Exception`  
* 意料之中的或者说已知的`Exception`, 即`try, except`捕获的
* 未知的`Exception`,即bug或未知的异常

## 捕获已知的异常
对于已知的并且需要记录的`Exception`，我们一般会调用python自带日志模块`logging`处理，此时`raven`就发挥作用了
代码如下
```python
# 代码位置 raven.handlers.logging.py
# SentryHandler继承自loggging.Handler,并且覆写了emit()方法
class SentryHandler(logging.Handler, object):
    def __init__(self, *args, **kwargs):
        client = kwargs.get('client_cls', Client)
        if len(args) == 1:
            arg = args[0]
            if isinstance(arg, string_types):
                self.client = client(dsn=arg, **kwargs)
            elif isinstance(arg, Client):
                self.client = arg
            else:
                raise ValueError('The first argument to %s must be either a '
                                 'Client instance or a DSN, got %r instead.' %
                                 (self.__class__.__name__, arg,))
        elif 'client' in kwargs:
            self.client = kwargs['client']
        else:
            self.client = client(*args, **kwargs)

        self.tags = kwargs.pop('tags', None)

        logging.Handler.__init__(self, level=kwargs.get('level', logging.NOTSET))

        def emit(self, record):
            # 其他部分略去，只列出关键流程
            ...
            self._emit(record)
        
        def _emit(record, **kwargs):
            ...
            # 这个方法里sentry会把拿到的exception进行处理（build_msg方法）并且发送到服务器（send方法）
            return self.client.capture(
            event_type, stack=stack, data=data,
            extra=extra, date=date, sample_rate=sample_rate,
            **kwargs)
```
一句话就是说当我们用`logging`日志模块处理异常时, 只要我们正确配置了sentry，改异常同时会被`raven`捕获进行处理并发送到sentry服务器。

## 捕获未知的异常
代码中的bug, 我们没法做预处理, 所以也就不可能用logging模块提前去记录。而raven捕获处理这种异常的流程如下:
#### 1. 在django工程初识化时，会调用`install()`起一个`Signal实例`绑定raven的异常处理handler

```python 
    # 代码位置 raven.contrib.django.models.py
    def install(self):
        request_started.connect(self.before_request, weak=False)
        # Signal实例绑定一个receiver(self.exception_handler)
        got_request_exception.connect(self.exception_handler, weak=False)

        if self.has_celery:
            try:
                self.install_celery()
            except Exception:
                logger.exception('Failed to install Celery error handler')
```
#### 2.在业务中未被捕获的异常在Django处理请求的入口`BaseHandler`也是请求返回的出口会被最终捕获，在这里会通过signal发送给receiver

```python
# 代码位置django.core.handlers.base.py
class BaseHandler(object):
    ...

    def get_response(self, request):
        ...
        # Signal实例把异常发送给receiver
        signals.got_request_exception.send(sender=self.__class__, request=request)
        response = self.handle_uncaught_exception(request, resolver, sys.exc_info())
```
#### 3. receiver接收到异常，处理异常并发送到sentry服务器

```python
    # 代码位置raven.contrib.django.models.py
    # raven的receiver
    def exception_handler(self, request=None, **kwargs):
        try:
            # 处理异常
            self.client.captureException(exc_info=sys.exc_info(), request=request)
        except Exception as exc:
            try:
                logger.exception('Unable to process log entry: %s' % (exc,))
            except Exception as exc:
                warnings.warn('Unable to process log entry: %s' % (exc,))

    # 代码位置raven.base.py
     def capture(self, event_type, data=None, date=None, time_spent=None,
                extra=None, stack=None, tags=None, sample_rate=None,
                **kwargs):
        
        if not self.is_enabled():
            return

        exc_info = kwargs.get('exc_info')
        if exc_info is not None:
            if self.skip_error_for_logging(exc_info):
                return
            elif not self.should_capture(exc_info):
                self.logger.info(
                    'Not capturing exception due to filters: %s', exc_info[0],
                    exc_info=sys.exc_info())
                return
            self.record_exception_seen(exc_info)

        # 组装拼接异常信息,构造成一个dict
        data = self.build_msg(
            event_type, data, date, time_spent, extra, stack, tags=tags,
            **kwargs)
        # should this event be sampled?
        if sample_rate is None:
            sample_rate = self.sample_rate
        # 序列化，编码,压缩信息并发送到服务器器
        if self._random.random() < sample_rate:
            self.send(**data)

        self._local_state.last_event_id = data['event_id']

        return data['event_id']
```
上面就是raven处理未知异常的主流程。一句话总结:  
`Exception`--> (通过Signal) --> `exception_handler` --> `capture` --> `build&send`


