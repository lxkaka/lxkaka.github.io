# Django Signals小结


## Signals 用处

django有一个“信号分配器”（signal dispatcher）使得当一些动作在框架的其他地方发生的时候，解耦的应用可以得到提醒。简单说，就是一些动作发生的时候，信号允许特定的发送者去提醒一些接受者，这是很有用的设计，因为可能多处代码对某些事件是很感兴趣，比如删除动作。  

为此，django提供了很多内置的信号，当django触发某些动作时而通知到用户代码，包括：  

* `django.db.models.signals.pre_save & django.db.models.signals.post_save`  
	modle's `save()`被调用之前或之后，发送signal 
* `django.db.models.signals.pre_delete & django.db.models.signals.post_delete`
    model's `delete()`或者query_set's `delete()`被调用之前或之后，发送signal
* `django.db.models.signals.m2m_changed`
   当modle的 ` ManyToManyField`有修改时触发
* `django.core.signals.request_started & django.core.signals.request_finished`
 	当Django开始或者完成一个http请求  
 
 同样Django支持自定义Signal
 如:  

```python  
	from django.dispatch import Signal 
	my_signal = Signal(providing_args=['instance', 'content']) 
```

## 监听 signals
要想接受信号，首先要用`Signal.connect()`注册一个接收器函数。发送signal,则接收函数被调用

`Signal.connect(receiver[,sender=None,weak=True,dispatch_uid=None])` 
参数解释：

* receiver：连接到这个信号的回调函数
* sender：信号的发送者
* weak：是否是弱引用，默认是真。因此，如果你的接收器是是一个本地函数，会被当做垃圾回收，如果你不想，请在使用connect()方法的时候使用weak=False(1.9中以后被废弃）
* dispatch_uid：一个唯一的标识符给信号接收器，避免重复的信号被发送

## 定义接收函数

```python
def my_callback(sendr, **kwargs):
    print 'request finished'
```

注意的是所有的信号处理器都需要这两个参数：sender和 **kwargs。因为所有的信号都是发送关键字参数的，可能处理的时候没有任何参数，但不意味着在处理的过程中（在你写的处理函数之前）有任何的参数生成，如果没有传 kwargs参数的话，可能会发生问题；基于这样的考虑，这两个参数都是必须的。

## 连接接收函数
有两中方法可以使用

* 手动connect

```python
from django.core.signals import request_finished

request_finished.connect(my_callback)
```
* 用装饰器receiver

```python
from django.core.signals import request_finished
from django.dispatch import receiver

@receiver(request_finished)
def my_callback(sender, **kwargs):
    print("Request finished!")
```

## 使用完整示例

```python
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=GroupSettings)
def group_settings_post_save_trigger(sender, instance, created, *args, **kwargs):
    """
    本方法会在 GroupSettings.save() 后调用，量大，并且并不保证事务一定成功
    所以一定注意本方法内一定是调用异步任务，并且业务逻辑并没有严格的数据一致性需求
    :param sender:
    :type instance: GroupSettings
    :type created: bool
    :param args:
    :param kwargs:
    """
    from api.activity_manager import send_feed_message
    from api.constants import FeedType

    if created and instance.business_group:
        for business in Business.objects.filter(business_group=instance.business_group):
            send_feed_message(business, FeedType.REBOOT)
```

### 注意：
`update()` 并不会触发`pre_save, post_save`信号
所以当有这样的操作：
`GroupSettings.objects.filter(business_group=business_group).update(**filterd)`
想触发信号发送时，可以这样修改：

```python
group = GroupSettings.objects.filter(business_group=business_group).first()
if group:
    for key, value in fileted.items():
        setattr(group, key, value)
    group.save()
```

