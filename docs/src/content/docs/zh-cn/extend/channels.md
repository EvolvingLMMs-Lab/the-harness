---
title: "写一个聊天渠道"
description: "把一个聊天服务声明成渠道：它的字段、登录方式、群、主人，以及 agent 使用的动词。"
---

**渠道**是一个 agent 身份能被找到的聊天服务：你在那里和它的私聊并进主对话，它被放进的每个群各自成为一个对话。The Harness 不认识任何一种具体的聊天服务。渠道来自扩展包；接入一个账号时，app、终端聊天和命令行要问什么、显示什么，全部来自这个包的声明。

一个渠道包都没有安装时，渠道类型的列表是空的，每个前端都会说明渠道从哪里来：`harness list --available` 列出 registry 里的包，`harness install NAME` 安装一个。

## 渠道是什么

渠道是包提供的一个[空间](/docs/zh-cn/concepts/spaces/)，它的声明里多一张表：

```toml
# spaces/chat.toml in the package
line = "An account of Example Chat"
entry = "example_chat.space:main"      # runs the space for one account

[channel]
name = { en = "Example Chat", zh = "示例聊天" }
about = { en = "One account of the Example Chat service", zh = "示例聊天服务的一个账号" }
serve = ["--config", "{config}", "--server", "{server}"]
```

文件名就是渠道类型（这里是 `chat`）。`serve` 是为一个账号调用 entry 时的参数：`{config}` 是这个账号自己的文件，`{account}` 是账号名，`{identity}` 是它归属的身份，`{<id>}` 是某个字段的值。entry 还会收到 `--owner IDENTITY`（谁可以在这个空间里取得主人角色），并在开始监听后打印 `{"space": "ws://..."}`，和所有由包提供的空间一样。

文字用中英两种语言给出（`{ en = "...", zh = "..." }`）；只写一个字符串时两种语言都用它。

## 四步

接入一个账号总是按这个顺序进行。归属身份由前端先选好，其余的都来自声明。

### 1. 身份和策略：`fields`

```toml
[[channel.fields]]
id = "dm"
kind = "choice"                        # choice, text, bool or secret
label = { en = "Private messages from strangers", zh = "陌生人私聊" }
help = { en = "You and paired people can always talk to it", zh = "你和已配对的人始终可以和它私聊" }
default = "pairing"
choices = [
    { value = "pairing", en = "Give a pairing code", zh = "给一个配对码" },
    { value = "open", en = "Anyone", zh = "任何人" },
]

[[channel.fields]]
id = "server"
label = "Server address"
default = "wss://chat.example"

[[channel.fields]]
id = "token"
kind = "secret"
env = "EXAMPLE_CHAT_TOKEN"             # how the entry receives it
required = true
label = { en = "Bot token", zh = "机器人 token" }
```

前端为每个字段画一个控件。字段的值写进账号的文件（身份文件夹里的 `channels/<account>.json`，和 `identity` 放在一起）。`secret` 不写进这个文件，而是和凭据存在一起，通过它指定的环境变量交给 entry。

### 2. 登录：`login`

```toml
[channel.login]
text = { en = "Scan the code with Example Chat on your phone.", zh = "用手机上的示例聊天扫码。" }
verb = "chat.login"       # optional: what the login shows now
online = "chat.online"    # the event that says it logged in or out (data.online)
```

账号等待登录时，前端显示 `text`（其中的 `{<id>}` 换成字段的值）。声明了 `verb` 时，会以主人的身份调用它，并把它的结果也显示出来：`qr`（一张图片，`data:` URL）、`url`（一个要打开的链接）、`text`（一行文字）。收到 `online` 事件，或者它的群列表能够返回时，这个账号就算登录了。

### 3. 群：`groups`

```toml
[channel.groups]
list = "chat.groups"          # -> {groups: [{group, name, entered}]}
enter = "chat.enter_group"    # args {group, mode}
leave = "chat.leave_group"    # args {group}
modes = [
    { value = "mention", en = "When it is named", zh = "被点名时" },
    { value = "all", en = "Every message", zh = "每条消息" },
]
```

账号默认不进任何群；由主人勾选它可以进的群。没有群的渠道不写这张表，这一步也就不显示。

### 4. 主人：`owner`

```toml
[channel.owner]
code = "chat.owner_code"      # -> {code, expires}
bound = "chat.owner_bound"    # the event once the code arrived (data.user)
text = { en = "From your own account, send this code to it.", zh = "用你自己的账号把这个码发给它。" }
```

一次性码和 `text` 一起显示，这里和主对话里都有。收到 `bound` 事件后，那个账号就是主人：它的私聊并进主对话，批准请求也会发到那里。

## 消息和配对

```toml
[channel.messages]
event = "chat.message"   # data: chat, text, message, name, owner, addressed, group_name
reply = "chat.reply"     # object: the message; args {text}
send = "chat.send"       # object: the chat; args {text}

[channel.pairing]
requested = "chat.pairing_requested"   # data: user, name, code, expires
approve = "chat.pair"                  # args {code} -> {user}
revoke = "chat.unpair"                 # args {user}
```

消息事件里，`chat` 是 `private:<user>` 时表示私聊，其余的都是群；`owner` 表示发送者是已绑定的主人；`addressed` 表示这条消息点名了这个账号，或者是发给它的；`message` 是 `reply` 的对象。配对请求会出现在主对话里。

空间把它了解到的东西用下面这些名字写进账号的文件，账号列表就是从这里读的：`owner`、`paired`（列表）、`pending`（`{code: {user, name, expires}}`）、`groups`（`{group: mode}`）。

## 试一下

```bash
harness install ./example-chat          # the package's folder
harness channels kinds                  # the kind, its fields and its steps
harness channels add chat --dm pairing  # asks for the rest in a terminal
harness channels                        # the accounts and pairing requests
```

同样的步骤，页面用 `GET` 和 `POST /api/agent/channels`，Python 用 `Agent.channel_kinds()`、`channel_add()`、`channel_groups()`、`channel_owner_code()`（[Python API](/docs/zh-cn/extend/python-api/)）。
