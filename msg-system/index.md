# 消息系统方案设计之站内消息和事件提醒

消息系统可以说是每个应用不可缺少的系统。从功能上来说一个消息系统至少有两大部分组成

* 消息的存储
* 消息的通知
消息系统的复杂程度和用户规模和业务规模呈正相关。这里先做站内消息系统的设计和实现。  

我们把消息分为三类  

* 系统通知
* 事件提醒
* 私信
这里我们先设计当前需要的系统通知和事件提醒。  

### 系统通知
系统通知一般是由后台管理员创建并且可指定某一类（全体，个人等）用户接收。 

基于此设计两张表来存储相关信息

* 消息内容表
* 用户通知表
消息内容表设计如下

#### 结构设计
##### 消息内容表  
```sql
CREATE TABLE `message_info`
(
    `id`           int(11) unsigned    NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `msg_id`       varchar(32)         NOT NULL DEFAULT '' COMMENT '消息ID',
    `title`        varchar(50)         NOT NULL DEFAULT '' COMMENT '标题',
    `content`      varchar(500)        NOT NULL DEFAULT '' COMMENT '正文',
    `image`        varchar(1024)       NOT NULL DEFAULT '' COMMENT '图片地址',
    `jump_url`     varchar(1024)       NOT NULL DEFAULT '' COMMENT '跳转链接',
    `type`         tinyint(1)          NOT NULL DEFAULT 0 COMMENT '消息类型 1-系统消息 2-创作邀请 100-其他',
    `sender`       bigint(20) unsigned NOT NULL DEFAULT 0 COMMENT '发送者ID',
    `channel`      tinyint(1)          NOT NULL DEFAULT 0 COMMENT '发送渠道 1-站内 2-短信 3-推送',
    `receive_type` tinyint(1)          NOT NULL DEFAULT 0 COMMENT '发送渠道 1-白名单 2-黑名单 3-单一用户 100-全部',
    `ctime`        datetime            NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `mtime`        datetime            NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '修改时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_msg_id` (`msg_id`),
    KEY `ix_mtime` (`mtime`)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4 COMMENT ='消息内容表';
```

用户通知表设计如下
##### 用户通知表
```sql
CREATE TABLE `message_notice`
(
    `id`     int(11) unsigned    NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `msg_id` varchar(32)         NOT NULL DEFAULT '' COMMENT '消息ID',
    `state`  tinyint(1)          NOT NULL DEFAULT 0 COMMENT '已读状态 0-未读 1-已读',
    `mid`    bigint(20) unsigned NOT NULL DEFAULT 0 COMMENT '接收者ID',
    `type`   tinyint(1)          NOT NULL DEFAULT 0 COMMENT '消息类型 1-系统消息 2-创作邀请 100-其他',
    `ctime`  datetime            NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `mtime`  datetime            NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '修改时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mid_msg` (`mid`, `msg_id`),
    KEY `ix_mtime` (`mtime`)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4 COMMENT ='消息通知表';
```
当创建一条系统通知后，数据插入到消息内容表。消息内容包含了发送渠道，根据发送渠道决定后续动作。我们先只针对站内通知做设计，其他渠道后续扩展即可。  

如果是站内渠道，在插入消息内容后异步的插入记录到用户通知表。

#### 扩展设计
* 针对全体用户发送通知时，可以根据一定策略过滤掉活跃度很低的用户
* 用户量较大，用户通知表可根据用户 id 分表

### 事件提醒
当用户点赞你的弹幕，回复了你的评论我们把这样的行为称之为事件。此类用户行为需要触达到对应的用户，就是事件提醒。当我们收到提醒时，还需要从提醒能跳转到事件发生的地方，比如某条弹幕，某条评论。  

在我们的业务场景里定义了一类事件邀请

为此设计了事件表如下 

#### 事件表
```sql
CREATE TABLE `message_event`
(
    `id`       int(11) unsigned    NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `msg_id`   varchar(32)         NOT NULL DEFAULT '' COMMENT '消息ID',
    `event_id` varchar(32)         NOT NULL DEFAULT '' COMMENT '事件ID',
    `type`     tinyint(1)          NOT NULL DEFAULT 0 COMMENT '事件类型 2-故事邀请',
    `action`   varchar(20)         NOT NULL DEFAULT '' COMMENT '动作类型',
    `receiver` bigint(20) unsigned NOT NULL DEFAULT 0 COMMENT '接收者ID',
    `ctime`    datetime            NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `mtime`    datetime            NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '修改时间',
    PRIMARY KEY (`id`),
    KEY `ix_msg_id` (`msg_id`),
    KEY `ix_event_receiver` (`event_id`, `receiver`),
    KEY `ix_mtime` (`mtime`)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4 COMMENT ='消息关联事件表';
```
事件的提醒本质上还是消息的通知。所以事件的通知的内容和通知的状态还是依靠上面的两张表来存储。

在用户 A 发起对 用户 B 的邀请首选会往消息内容表插入一条数据记录邀请的具体内容，然后插入一条用户 B 的通知到消息通知表，最后消息和事件的关联关系会在事件表插入一条记录。

#### 消息获取 
在上面的设计下，从消息通知表就能取到用户的系统通知和事件提醒未读数量

```sql
select msg_id from message_notice where mid = 'xxx' and state = 0 group by type;
```

通过 msg_id 查到具体的消息内容  
事件通知通过 msg_id 查到事件信息  

```sql
select * from message_info where msg_id in (xxx, xxx) order by mtime desc;
select * from message_event where msg_id in (xxx, xxx) order by mtime desc;
```
#### 扩展设计
用户规模和消息规模比较庞大下用 redis 缓存提高性能

维护用户消息未读数量的缓存比如使用哈希表 如下 `HMSET user_id_unread 1 10 2 20  (1, 2 表示消息类型)`
维护用户已读消息的最大 id 比如 `HMSET user_id_read 1 247 2 189  (1, 2 表示消息类型)`

到此站内的系统消息和时间提醒的设计就介绍到这。后续随着消息种类的增加和用户规模的扩大我们再介绍进一步的方案设计。
