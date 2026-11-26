---
core: minor
agent: minor
---
Every entry of the agent is in the terminal, on the command line and in Python as in the app.
`harness` in a terminal opens the identity's main conversation on the session host, so it shows
the same life as the app; what happens in its other chats is told in lines starting with "—",
and `/sessions` switches among its chats. New: `/calendar` and `harness calendar list | add |
move | remove | pause` (what it did, who began it, the outcome, refusals, when it slept;
pausing what it does on its own), `/channels` and `harness channels list | add | remove |
pair` (the identity and policies first, then the login, the groups, the owner's one-time code,
pairing requests), and `/library` and `harness library skills | tree [PATH] | memory | undo`
(skills with evidence, uses and source; the tree of reactions one level at a time like folders;
memory with scope and source). `/usage` lists today's spending by chat and by task, and the
status line shows today's spending. `harness host` shows how the session host runs and the
identities it holds; `harness host stop` stops it. `harness.sdk.Agent` gains the same calls:
`chats()`, `memory()`, `reactions(path)`, `learned()`, `calendar()`, `channels()`, `usage()`
and the changes beside them, all through the session host.
<!-- zh -->
agent 的每个入口在终端、命令行和 Python 里都和 app 一样。终端里的 `harness` 打开当前身份在 session host 上的主对话，和 app 显示同一个生活；其他对话里发生的事以"—"开头的行提示，`/sessions` 在它的对话之间切换。新增：`/calendar` 和 `harness calendar list | add | move | remove | pause`（做了什么、谁发起、结果、被拒绝、何时睡觉；暂停它主动做的事），`/channels` 和 `harness channels list | add | remove | pair`（先选身份和策略，再登录、选群、用一次性口令绑定主人、处理配对请求），`/library` 和 `harness library skills | tree [PATH] | memory | undo`（技能的证据、使用次数和来源；反射树像文件夹一样一层层浏览；记忆的范围和来源）。`/usage` 按对话和任务列出今天的花费，状态栏显示今天的花费。`harness host` 显示 session host 的运行情况和它承载的身份，`harness host stop` 停止它。`harness.sdk.Agent` 有一一对应的调用：`chats()`、`memory()`、`reactions(path)`、`learned()`、`calendar()`、`channels()`、`usage()` 以及相应的修改，都经过 session host。
