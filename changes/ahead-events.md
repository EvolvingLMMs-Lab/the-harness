---
core: patch
---
An environment can declare events after which a program prepared ahead no longer fits
(`ahead_voiding_event_kinds` of its session). When it reports one while a program runs, the
next program prepared during that run is set aside whatever its `<assume>` check says, and
the `ahead` trace record names the event. No environment declares any yet, so nothing
changes until one does.
<!-- zh -->
环境可以声明哪些事件会使提前准备的程序作废（会话的 `ahead_voiding_event_kinds`）。程序运行
期间环境报告了这样的事件时，运行期间提前准备好的下一个程序无论 `<assume>` 检查结果如何都会
被放弃，`ahead` trace 记录会写明是哪个事件。目前没有环境声明这类事件，声明之前行为不变。
