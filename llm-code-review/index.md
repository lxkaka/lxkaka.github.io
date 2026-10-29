# AI 助力 Code Review 的高效方案

## 背景
随着 LLM 的日益强大，我们可以借助 LLM 来提高多方面的生产效率。很多的应用场景我们就不在这里展开，其中一方面就是用来给程序员提效，比如大名鼎鼎的 github Copilot。在这篇文章里我们就介绍一下借助 LLM 提效开发的一个点：Code Review.  LLM 能 revview 代码这个大家肯定都知道，但是选取哪个模型来实现呢？
可以说选择比较多如开源模型 StarCoder，CodeLLama, WizardCoder 等是代码方面评测结果比较优秀的存在，再比如闭源方案 GPT4, Claude 等综合能力超强的大模型。 
在经过了多种实际 case 的实验我们最终选了 Claude 作为 Code Reveiw 的底座。
首先从 Codew Reveiw 效果方面来看  
GPT4 > Claude > Wizardoder > CodeLLama，其中 Claude 相比 GPT4 代码理解能力并不逊色多少；
从成本方面来看     
GPT4 API 价格明显高于 Claude，而开源模型的显卡成本也不低 (至少需要一张 V100 才能把模型跑起来)。
再者 Claude 除了它超强的综合能力，超长的 context window(可以达到 100k) 也是非常强力的点，对于 Code Review 来说大的 context window 十分重要。
下面就介绍一下我们如何高效率低成本地实现 Code Review。

## 方案

### Slack Claude 
企业使用 Claude 首先可以通过 Claude API，但是需要申请，这个申请审核时间可能持续比较久。在我们做该方案时 API 暂时还没申请下来。所以我们把解决方案转向了 Slack 中的 Claude bot。
在 Slack 中我们首先在 App 中把 Claude 添加进来，然后创建 channel, 并把 Claude 加入到 channel。此后，就可以像普通同事一样 @Claude 进行对话。
我们可以借助 slack sdk 来实现于  Claude 的交互，从而使用 Claude 辅助 Code Review 就有了明确的实现方案。
总体来说实现方案如下：

![review-arch](https://pics.lxkaka.wang/review-arch.jpeg)

### 步骤
#### MR 处理
1. 开发在 gitlab 提交 Merge Request, 通过项目配置好的 webhook 触发请求把 MR 信息发给 bot service（bot service 用来处理各种 webhook）；
2. bot service 拿到 MR 后通过 API 获取 MR 的 diffs 和 commit message
```python
    # 获取 mr diffs
    url = f"{settings.GITLAB_API_URL}/projects/{pr.project_id}/merge_requests/{pr.iid}/diffs"
    headers = {"PRIVATE-TOKEN": settings.GITLAB_TOKEN}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        cls.make_new_thread(pr, "获取 mr diffs 失败")
        return

    # 获取 mr commits messages
    url = f"{settings.GITLAB_API_URL}/projects/{pr.project_id}/merge_requests/{pr.iid}/commits"
    response = requests.get(url, headers=headers)
```
3. 处理 diffs 中可能包含的敏感信息
这里可以有很多的实现方案，这里我们推荐一个库 `detect-secrets`再搭配一些正则表达式，可以来过滤敏感信息。

4.  组装 Prompt
不同的项目差别可能比较大，我们可能需要根据项目不同提供给模型不同的上下文来达到更好的 review 效果。在这里我们支持了项目模版自定义，每个 gitlab repository 通过 wiki 可以配置自己项目的 Prompt 模版。
bot service 在组装 Prompt 的时候会优先使用项目的配置模版。我们的默认模版如下
```python
    你将扮演一个资深的软件程序员进行代码审查，严格按照以下要求审查提供的合并请求（Merge Request, MR）内容。给出审查结果：
    1. 前提: 请务必用中文回复；
    2. 总结：请简洁准确地总结MR的改动内容；
    3. 问题与优化点识别：请识别MR中存在的问题和需要优化的地方，包括但不限于代码逻辑、代码风格、命名规范、拼写错误、性能和错误处理等；
    4. 优化建议：针对识别的问题和优化点，给出具体可执行的优化建议, 并详细说明为什么要这么改, 如果建议涉及代码改动，请直接提供优化后的代码；
    5. Commit Message 审查：请检查 commit message 是否准确反映了MR的改动内容，如果存在不一致，必须指出；
    6. MR原子性的审查：判断一个MR里是否包含了过多不同类型的改动，或者一个MR里包含了多个commit，如果有请指出。
    请确保审查结果的准确性和专业性。

    MR 内容如下:
    {content}
```
5. 调用 LLM service 
#### 获取 Review 结果
1. 对话历史   
slcak thread 可以保存完整的对话历史，所以我们不需要自己保存保存对话，这是一个十分方便的特性。只要我们记住每个 thread id，那么就能进行完整的对话。在 MR review 中我们也就可以持续和模型对话，来更好的 review 代码；
如果 MR 首次触发 review, 我们会创建并缓存 `thread ts`, 如果非首次对话那么就获取已有 `thread ts`继续对话。示例代码如下
```python
    key = f"claude_{body.user}"
    prompt = f"<@{CLAUDE_BOT_ID}> {body.prompt} "
    thread_ts = None
    value = await app.state.redis.get(key)
    if value:
        thread_ts = value.split("_")[0]
    last_ts = await client.chat(prompt, thread_ts=thread_ts)
    if not value:
        await app.state.redis.setex(name=key, time=3600, value=last_ts)
        thread_ts = last_ts
```
2. 超长文本
我们 MR 往往包含的文本非常多，而 slack server 对普通的消息提交有长度限制，所以我们这里把超长的消息体分成了多段组装成 `blocks` 提交。
```python
    if not self.CHANNEL_ID:
        raise Exception("Channel not found.")
    if len(text) <= self.MAX_LEN:
        resp = await self.chat_postMessage(channel=self.CHANNEL_ID, text=text, thread_ts=thread_ts)
    # slack server 会自动切分超长消息，为了解决此问题使用 blocks 传递消息
    else:
        texts = split_message(text, self.MAX_LEN)
        blocks = []
        for t in texts:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": t,
                }
            })
        resp = await self.chat_postMessage(channel=self.CHANNEL_ID, blocks=blocks, thread_ts=thread_ts)
```
3. 轮询结果
Claude 在 slack 中流式回复，我们这里需要等到回复完整了才能返回结果。所以需要轮询回复状态，并且得设置一定的超时策略防止异常 case
```python
    for _ in range(300):
        try:
            resp = await self.conversations_replies(channel=self.CHANNEL_ID, ts=thread_ts, oldest=last_ts, limit=1)
            msg = [msg["text"] for msg in resp["messages"] if msg["user"] == CLAUDE_BOT_ID]
            if msg and not msg[-1].endswith("Typing…_"):
                return unescape_text(msg[-1])
        except (SlackApiError, KeyError) as e:
            print(f"Get reply error: {e}")

        await asyncio.sleep(1)
```

####  结果 comment
当 bot service 拿到返回的 review 结果后需要以 `comment ` 的形式呈现到 gitlab 的 comment 列表中
```python
    url = f"{settings.GITLAB_API_URL}projects/{pr.project_id}/merge_requests/{pr.iid}/discussions"
    headers = {"PRIVATE-TOKEN": settings.GITLAB_TOKEN, "Content-Type": "application/json"}
    payload = json.dumps(
        {
            "body": content,
        }
    )
    response = requests.post(url, headers=headers, data=payload)
    if response.status_code >= 400:
        raise CodeBaseException("make mr thread failed")
```
基于模型 review 结果我们可以继续在 comment 列表和模型对话，把问题讨论清楚。

### 效果呈现
下面展示了某次 review 的 case 

![review-qa](https://pics.lxkaka.wang/reviw-qa.jpeg)

![review-result](https://pics.lxkaka.wang/review_result.jpeg)

在这篇文章里介绍了我们借助  LLM 辅助 Code Review 的实现过程，重要的细节和代码实现我们都有提到，希望能给需要的同学带来有指导性的参考。
在未来的工作中 Code Review 随着 LLM 的进步，我们可以随时切换更优秀的底座，并且把 review 结果精确到行。

