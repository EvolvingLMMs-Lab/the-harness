---
core: minor
agent: minor
workspace: minor
---
An agent identity is now always working. The session host keeps every identity's life running
(it no longer exits while one is alive): one tree of reactions per identity is judged all the
time, the model is woken only when something is worth thinking about (it is named, an action
fails, an intention it left or something on its calendar comes due), and it decides within its
daily budget and authority whether to do something. Each connected place (a QQ group, a project
folder, a browser) is a chat of its own beside the main conversation; every frontend shares one
queue. A safety layer of fixed rules refuses its desktop input while you use the desktop, waits
for your approval before sending, publishing, paying or deleting (a push counts as sending;
"A7 approve" in your private chat answers), and limits what other people can ask of it. A
calendar shows when it did what, and a summary waits each morning. It learns by default: a
review after each turn and dreaming at 0:30 turn what it did into skills with their own tests,
compatible with `SKILL.md`. New settings: `agent.reserve`, `agent.proactive`,
`agent.stale_hours`, `spaces.<place>.proactive`, `approvals.timeout_minutes`, and
`learning.mode` gains `review_first` and `off`.
<!-- zh -->
agent 身份现在一直在工作。session host 让每个身份的生活一直运行（有身份活着时不再退出）：每个身份一棵反射树
随时判断，只有值得想的事（被点名、动作失败、它留下的意图或日历上的事到时间）才叫醒模型，它在每日预算和权限里
决定要不要做事。每个接上的地方（QQ 群、项目文件夹、浏览器）都是主对话旁边的一个对话；所有前端共用一个队列。
安全层的固定规则在你用桌面时拒绝它的输入，发送、发布、付款、删除前等你批准（推送算发送；在私聊里回
“A7 同意”即可），并限制别人能让它做的事。日历上看得见它什么时候做了什么，每天早上有一份摘要。它默认学习：
每个回合后的回看和 0:30 的 dreaming 把做过的事变成带自测的技能，兼容 `SKILL.md`。新设置：`agent.reserve`、
`agent.proactive`、`agent.stale_hours`、`spaces.<地方>.proactive`、`approvals.timeout_minutes`，
`learning.mode` 增加 `review_first` 和 `off`。
