---
core: patch
---
A program prepared while another one ran is no longer used when the environment itself
reported an event during that program (one of the session's observation events): it was
written before the event, so it is set aside whatever its `<assume>` check says, and the
`ahead` trace record names the event.
<!-- zh -->
程序运行期间环境自己报告了事件（会话声明的观察事件）时，运行期间提前准备好的下一个程序
不再被采用：它写在事件发生之前，所以无论它的 `<assume>` 检查结果如何都会被放弃，`ahead`
trace 记录会写明是哪个事件。
