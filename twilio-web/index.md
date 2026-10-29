# 利用 Twilio 快速构建 web 语音聊天

web 应用程序越来越强调交互性和实时通信功能。无论是在线客服、网络会议,还是网络电话等,都需要将语音和视频通信无缝集成到应用程序中,以提供更丰富的用户体验。然而,构建自己的实时通信基础设施是一项艰巨的任务,需要处理复杂的信令、编解码、NAT/防火墙遍历等问题。  
这就是 [Twilio](https://www.twilio.com/en-us/voice) 的用武之地。Twilio 作为一个云通信平台,为我们屏蔽了通信基础设施的复杂性,通过强大而简单的 API, 我们可以比较容器的在应用中集成语音、视频、消息等通信功能。Twilio 拥有遍布全球的通信基础设施,确保高质量的实时通信体验。  
其中 [Twilio JS Voice SDK](https://www.twilio.com/docs/voice/sdks/javascript/get-started) 专门面向 Web 应用,利用 WebRTC 技术,让我们可以在浏览器中直接实现语音通话功能,无需用户安装任何插件或应用程序。该SDK提供了丰富的 API,支持拨打、接听、保持、静音等基本通话控制,还支持高级功能如录制、监控等。
通过Twilio JS Voice SDK, 我们可以轻松构建网络电话、在线会议、网上客服等富有互动性的实时通信应用。不仅节省了开发成本,还能为用户带来流畅的通信体验。  
我们在构建实时语音聊天机器人，希望能把这里面 web 实时语音构建的实践方案分享出来。这对于任何希望在 web 应用中集成语音通信的开发者来说,都是一个很好的入门和参考。

### 原理
![twilio-web](https://pics.lxkaka.wang/20240529-172253.jpeg)

Twilio Voice JavaScript SDK 允许在网页浏览器和 Twilio TwiML 语音应用程序之间建立语音通话连接。以下是该 SDK 运作原理的说明：

#### 1. 设备初始化与连接
开发者需要使用 Twilio.Device 对象来设置用户的设备，并建立与 Twilio 的连接。这个过程涉及到从用户的设备（如电脑或移动设备）捕获麦克风音频，并将其发送到 Twilio。同时，从 Twilio 返回的音频会通过设备的扬声器播放出来，类似于普通电话通话的过程。

#### 2. 呼叫控制 
与使用传统电话不同，使用 Twilio.Device 发起的呼叫不是直接拨打到另一台电话的号码，而是连接到 Twilio 服务器，并指示 Twilio 从开发者的服务器获取 TwiML（Twilio Markup Language）来处理呼叫的逻辑。这与 Twilio 处理来自真实电话的来电类似。

#### 3. TwiML 应用程序
TwiML 是一套 XML 指令，用于控制 Twilio 服务器如何处理通信。由于 Twilio.Device 发起的呼叫没有特定的电话号码目标，Twilio 依赖于开发者账户中的 TwiML 应用程序来确定如何与服务器交互。TwiML 应用程序包含了一组 URL，这些 URL 会在呼叫时被 Twilio 请求，以获取如何处理呼叫的指令。这种方式允许开发者灵活地控制呼叫的流程，而不需要将逻辑绑定到特定的电话号码。

#### 4. 呼叫流程
当 Twilio.Device 发起呼叫时，Twilio 会向账户中的应用程序的 VoiceUrl 发送请求。开发者通过一个访问令牌（Access Token）来指定要连接的 TwiML 应用程序。Twilio 根据该应用程序的 VoiceUrl 返回的 TwiML 响应来指导呼叫的进一步操作。

### 实践
#### 创建 TwiML app
明白了原理后。我们首先要在 Twilio 后台创建一个 application, 这个应用关键的配置是要配置一个我们自己服务器的 url。这个 url 就是当 web 发起连接后，twilio 会回调这个 url 获取后续处理的指令。

![twilio-app](https://pics.lxkaka.wang/20240529-181854.jpeg)

#### 提供 access token
web 应用需要服务端提供 access token 来与 Twilio 交互  
```python
def token():
    """
    generate JWT token for js voice sdk
    """
    # Generate a random user name and store it
    alphanumeric_only = re.compile(r"[\W_]+")
    identity = alphanumeric_only.sub("", faker.user_name())

    # Create access token with credentials
    token = AccessToken(
        SETTINGS.TWILIO_ACCOUNT_SID, SETTINGS.TWILIO_API_KEY, SETTINGS.TWILIO_API_SECRET, identity=identity
    )

    # Create a Voice grant and add to token
    voice_grant = VoiceGrant(
        outgoing_application_sid=SETTINGS.TWILIO_APPLICATION_SID,
        incoming_allow=True,
    )
    token.add_grant(voice_grant)

    # Return token info as JSON
    token = token.to_jwt()
    # Return token info as JSON
    print(token, identity)
    return {"token": token, "identity": identity}
```

#### 回调指令
通过回调接口指示 twilio 后续与服务器的交互，这里我们告诉 twilio 通过 websocket 与服务器进行通信。后续直接在 websocket 进行语音数据的交互。
```python
def start(request: Request, sid: str | None = None):
    """
    stream webhook
    """
    form_data = await request.form()
    if sid is None:
        sid = form_data.get("sid")
    logger.info("start streaming......sid:%s", sid)
    response = VoiceResponse()
    webhook = SETTINGS.WEBHOOK_URL.replace("https", "wss") + "/ws"
    logger.info("webhook:%s", webhook)
    connect = Connect()
    stream = connect.stream(
        name="test stream",
        url=webhook,
    )
    stream.parameter("sid", sid)

    response.append(connect)

    response.pause(length=1000)

    return Response(str(response), media_type="application/xml")
```
注意 twilio 收发 stream message 都需要遵循数据格式  
收到的数据如下所示    
```
{ 
 "event": "media",
 "sequenceNumber": "3", 
 "media": { 
   "track": "outbound", 
   "chunk": "1", 
   "timestamp": "5",
   "payload": "no+JhoaJjpz..."
 } ,
 "streamSid": "MZXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
}
```
发送的数据如下所示  
```
{
  "event": "media",
  "streamSid": "MZXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
  "media": {
    "payload": "a3242sa..."
  }
}
```

#### 与其他设备通信
上面的回调示例是直接 web 与服务器进行语音交互的例子。我们当然也可用用其他指令来指示与其他设备交互。
```python
from twilio.twiml.voice_response import Dial, VoiceResponse

response = VoiceResponse()
dial = Dial()
# Route to the client 
dial.client(identity="test_123")
response.append(dial)
```
这样我们就可以和设备 id 为 "test_123"直接语音交互。

