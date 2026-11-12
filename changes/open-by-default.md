---
core: minor
---
A conversation you start is no longer isolated: the agent's programs run on your computer as you. They read your files, and what they do beyond their own folder goes by your approvals: `approvals.programs` (`never`, `ask_each`, `ask_once_session` by default, `allow`) and `approvals.rules` (`{level, action, match}` for `command`, `network` or `write`) decide whether a program may run a command, reach the network or write a file elsewhere; opening a file of credentials and deleting elsewhere always wait for you. Where nobody can be asked, a level that asks refuses and tells the program why. Isolation stays what it was, as the setting of evaluations: experiments keep `runtime.isolation = "auto"`.

Programs can read a page with `fetch(url)` and search with `search(query)` (the `web` skill, on in the app's conversations; a search needs `runtime.search`, a model on OpenRouter whose web plugin searches).
<!-- zh -->
你发起的对话不再隔离：agent 的程序以你的身份在你的电脑上运行。它们能读你的文件，超出自己文件夹的事按你的审批处理：`approvals.programs`（`never`、`ask_each`、默认 `ask_once_session`、`allow`）和 `approvals.rules`（针对 `command`、`network`、`write` 的 `{level, action, match}`）决定程序能否运行命令、访问网络、在别处写文件；打开凭据文件和在别处删除永远等你点头。没有人可问时，需要询问的级别会拒绝，并告诉程序原因。隔离保持原样，作为评测的设置：实验仍是 `runtime.isolation = "auto"`。

程序可以用 `fetch(url)` 读网页、用 `search(query)` 搜索（`web` skill，app 的对话默认启用；搜索需要 `runtime.search`，即 OpenRouter 上一个带联网搜索插件的模型）。
