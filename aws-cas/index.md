# 如何把 AWS Console 登录集成到自己的 SSO


## 背景
任何一个公司都会有各种各样的内部系统，这些内部系统有可能是自建的也有可能是第三方的。这些系统很可能都带有一定的认证和鉴权，如果各个系统都需要一套用户名和密码，不仅给员工带来巨大的记忆负担，更重要的是会有很棘手的管理问题。在这中背景下我们就需要个 单点登录系统(SSO), 这样我们登录了单点系统后就能访问其他任意的系统。这篇文章的主题不是 SSO 的搭建， 所以这里不讲怎么建立一套单点登录系统。
我们建立自己的 SSO 系统使用的是 CAS(Central Authentication Service)协议。要把各种各样的系统与单点系统集成，会随着各系统不同的认证方式，集成的方案也不一样。这篇文章我们就讲一下怎么跟我们的基础设施提供者 AWS 的 web 管理后台集成。

AWS 支持用户使用外部身份登录，方案之一是利用身份提供商 (IdP)，可以管理 AWS 外部的用户身份，并向这些外部用户身份授予 AWS 资源的权限。
我们有自己的 CAS 但是不能作为 IdP 使用。
我们使用的方案总结下来就是 自建 SSO + AWS STS

## AWS STS
先简单介绍一下 STS (很好很强大)
AWS Security Token Service (AWS STS) 可以用来创建 AWS 资源的访问的临时安全凭证，并将这些凭证提供给可信用户。临时安全凭证的工作方式与 IAM 用户可使用的长期访问密钥凭证的工作方式几乎相同，仅存在以下差异：
* 顾名思义，临时安全凭证是短期凭证。可将这些凭证的有效时间配置几分钟到几小时。一旦这些凭证到期，AWS 将不再识别这些凭证或不再允许来自使用这些凭证发出的 API 请求的任何类型的访问。

* 临时安全凭证不随用户一起存储，而是动态生成并在用户提出请求时提供给用户。临时安全凭证到期时 (甚至之前)，用户可以请求新的凭证。

这些差异使得可利用临时凭证获得以下优势：

* 不必随应用程序分配或嵌入长期 AWS 安全凭证。

* 可允许用户访问 AWS 资源，而不必为这些用户定义 AWS 身份。临时凭证是角色和联合身份验证的基础。

* 临时安全凭证的使用期限有限，因此，在不需要这些证书时不必轮换或显式撤消这些证书。临时安全凭证到期后无法重复使用。可指定证书的有效期，但有最长限期。

## 集成步骤
下面这张图展示了 CAS 与 AWS 集成后，登录 console 的流程
![cas-aws](https://pics.lxkaka.wang/aws-cas.png)
1. 用户通过 CAS 认证和鉴权;
2. 当通过 CAS 的验证后，CAS 会根据用户的权限向 AWS STS 发起请求申请临时的安全凭证;
3. 获得STS 授予的安全凭证后，用安全凭证继续向 AWS STS 换取登录 token;
4. 获得登录 token 后， CAS 会拼接完整的登录 url 并且把用户 redirect 到 AWS Console.
这样一个通过我们自己单点登录系统验证的用户就可以登录 AWS Consol

### 1.创建 IAM Role for STS access
使用 **aws access key** 和 **aws access secret** 本身就存在安全隐患，所以为了最大程度的安全，我们没有直接使用 `access key` +  `access secret`与 AWS STS交互。
更加安全的方式是给 ec2 实例绑定 IAM role， 这样 ec2 会被授予相应 role 的权限，而我们不用考虑 access key 和 secret 的安全问题。
所以第一步创建一个 具有 STS assume role 权限的 IAM role
```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "VisualEditor0",
            "Effect": "Allow",
            "Action": "sts:AssumeRole",
            "Resource": "*"
        }
    ]
}
```
### 2. 创建 IAM role for user
这一步我们需要给用户创建具有一定权限的 IAM Role, 因为 STS 是根据这个 role 来生成对应的安全临时凭证。这一步创建 role 没有什么特别的，但是一定给要这个 role 的 trust relationship 添加我们 aws 的根账户, 这样我们在应用里才能跟 AWS STS 交互并且 assume role
```
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "",
      "Effect": "Allow",
      "Principal": {
        "Service": "monitoring.rds.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    },
    # 下面的 trust entity 一定要添加
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws-cn:iam::xxxxxx(根账号):root"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```
### 3. 绑定 STSAccessRole 到 ec2 实例
这一步比较简单，就是把我们在第一步中创建的 IAM Role 绑定到我们 CAS 的实例上。这样我们运行 CAS 的实例就被授权能与 AWS STS 交互

### 4. 与 AWS STS 交互
下面的 Python 代码片段展示了我们怎样去跟 STS 交互
```
client = boto3.client('sts', region_name='cn-north-1')

assumed_role = client.assume_role(
    RoleArn=role_arn,
    RoleSessionName=session_name,
    DurationSeconds=3600
)

temp_credentials = {
    'sessionId': assumed_role['Credentials']['AccessKeyId'],
    'sessionKey': assumed_role['Credentials']['SecretAccessKey'],
    'sessionToken': assumed_role['Credentials']['SessionToken']
}
temp_credentials = json.dumps(temp_credentials)

signin_token_parameters = '?Action=getSigninToken&SessionDuration=43200&Session={}'.format(
    urllib.parse.quote_plus(temp_credentials))
signin_url = 'https://signin.amazonaws.cn/federation'
get_token_url = signin_url + signin_token_parameters
res = requests.get(get_token_url)
if res.status_code == 200:
    signin_token = res.json()

    login_parameters = '?Action=login&Issuer=zaihui&Destination={}&SigninToken={}'.format(
        urllib.parse.quote_plus('https://console.amazonaws.cn/'),
        signin_token['SigninToken']
    )
    login_url = signin_url + login_parameters
```
完成以上步骤后，如果我们顺利拿到 `login_url` 就可以拿着这个 url 愉快的登录 AWS Console 了 :)

