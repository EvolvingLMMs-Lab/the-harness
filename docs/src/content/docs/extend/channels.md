---
title: "Write a chat channel"
description: "Declare a chat service as a channel: its fields, its login, its groups, its owner and the verbs the agent uses."
---

A **channel** is a chat service an agent identity is reachable in: your private chat with it
there joins the main conversation, a group it was let into is a chat of its own. The Harness
knows no chat service by name. A channel comes from a package, and everything the app, the
terminal chat and the command line ask and show when an account is connected comes from what
that package declares.

With no channel package installed, the list of kinds is empty, and every frontend says where
channels come from: `harness list --available` lists the registry's packages, `harness
install NAME` installs one.

## What a channel is

A channel is a [space](/docs/concepts/spaces/) the package serves, with one more table in
its declaration:

```toml
# spaces/chat.toml in the package
line = "An account of Example Chat"
entry = "example_chat.space:main"      # runs the space for one account

[channel]
name = { en = "Example Chat", zh = "示例聊天" }
about = { en = "One account of the Example Chat service", zh = "示例聊天服务的一个账号" }
serve = ["--config", "{config}", "--server", "{server}"]
```

The file's name is the kind (`chat` here). `serve` is what the entry is called with for one
account: `{config}` is the account's own file, `{account}` its name, `{identity}` the
identity it belongs to, and `{<id>}` the value of one of its fields. The entry also gets
`--owner IDENTITY` (who may take the owner role in the space) and prints `{"space":
"ws://..."}` once it listens, as every served space does.

A text is given in English and Chinese (`{ en = "...", zh = "..." }`); one string stands for
both.

## The four steps

Connecting an account always goes in this order. The identity is chosen first by the
frontend; the rest is declared.

### 1. Identity and policies: `fields`

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

A frontend draws one control for each field. The values go into the account's file
(`channels/<account>.json` in the identity's folder, next to `identity`). A `secret` is kept
with the credentials instead, never in that file, and reaches the entry in the environment
variable it names.

### 2. Login: `login`

```toml
[channel.login]
text = { en = "Scan the code with Example Chat on your phone.", zh = "用手机上的示例聊天扫码。" }
verb = "chat.login"       # optional: what the login shows now
online = "chat.online"    # the event that says it logged in or out (data.online)
```

While the account waits, a frontend shows `text` (with `{<id>}` of a field filled in). When
`verb` is declared, it is asked as the owner and its result is shown too: `qr` (an image as
a `data:` URL), `url` (a link to open), `text` (a line). The account counts as logged in
once the `online` event said so, or once its list of groups answers.

### 3. Groups: `groups`

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

The account enters no group by default; the owner ticks the ones it may enter. A channel
without groups leaves this table out, and the step is not shown.

### 4. The owner: `owner`

```toml
[channel.owner]
code = "chat.owner_code"      # -> {code, expires}
bound = "chat.owner_bound"    # the event once the code arrived (data.user)
text = { en = "From your own account, send this code to it.", zh = "用你自己的账号把这个码发给它。" }
```

The one-time code is shown with `text`, here and in the main conversation. Once the `bound`
event comes, that account is the owner: its private chat is the main conversation, and
approval requests reach it there.

## Messages and pairing

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

In a message event, `chat` is `private:<user>` for a private chat and anything else for a
group; `owner` says the sender is the bound owner; `addressed` that it names the account or
is meant for it; `message` is what `reply` takes as its object. A pairing request appears in
the main conversation.

The space keeps what it learns in the account's file under these names, which is where the
list of accounts reads them: `owner`, `paired` (a list), `pending` (`{code: {user, name,
expires}}`), `groups` (`{group: mode}`).

## Try it

```bash
harness install ./example-chat          # the package's folder
harness channels kinds                  # the kind, its fields and its steps
harness channels add chat --dm pairing  # asks for the rest in a terminal
harness channels                        # the accounts and pairing requests
```

The same steps are `GET` and `POST /api/agent/channels` for a page, and
`Agent.channel_kinds()`, `channel_add()`, `channel_groups()`, `channel_owner_code()` in
Python ([Python API](/docs/extend/python-api/)).
