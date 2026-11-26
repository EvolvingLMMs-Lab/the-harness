---
core: patch
agent: minor
qq: minor
---
A chat channel is whatever an installed package declares: its kind, the fields it asks for, how it logs in, its groups, how its owner is bound, and the verbs and events the agent uses (a `[channel]` table in the package's `spaces/<kind>.toml`; see "Write a chat channel"). The agent, the app and the terminal chat name no channel themselves. With no channel package installed the list of kinds is empty and says where channels come from. `harness channels kinds` lists the kinds; `harness channels add KIND` takes the kind's own fields as `--FIELD VALUE` (the earlier `--groups mention|all` and the channel-specific flags are gone: a group's mode is given when it is entered, `--mode`); `harness channels set`, `groups` and `owner-code` are new. In the API, `POST /api/agent/channels` `add` takes `values`, and accounts carry `values` and `state` (`starting`, `waiting_login`, `logged_in`). A stranger's pairing request now also appears in the main conversation.
<!-- zh -->
聊天渠道完全由已安装的扩展包声明：类型、要填的字段、怎么登录、群、怎么绑定主人，以及 agent 使用的动词和事件（包的 `spaces/<类型>.toml` 里的 `[channel]` 表，见“写一个聊天渠道”）。agent、app 和终端聊天自己不再认识任何一种渠道。一个渠道包都没装时，类型列表为空，并说明渠道从哪里来。`harness channels kinds` 列出类型；`harness channels add 类型` 用 `--字段 值` 给出这个类型自己的字段（原来的 `--groups mention|all` 和某一种渠道专用的参数没有了：群的模式在进群时用 `--mode` 给）；新增 `harness channels set`、`groups`、`owner-code`。API 里 `POST /api/agent/channels` 的 `add` 接收 `values`，账号带 `values` 和 `state`（`starting`、`waiting_login`、`logged_in`）。陌生人的配对请求现在也出现在主对话里。
