---
core: minor
---
A program is held to `expect(text, check)` where it acts, not where it starts: a call that acts on the environment is refused when the program has checked nothing before it, and a program that does not act (reading pages, keeping code, setting nodes) needs none. What a check itself does in the environment is reading; a reflex's program is held to nothing. The message the model gets while its program still runs now says the two things to do then: follow the program, and prepare what comes after it with what needs no acting on the environment. `after(unit)` waits until a unit has ended, however it ended: a program sent while another still runs begins with it, then checks with `expect`, then acts.
<!-- zh -->
`expect(text, check)` 的要求从"程序启动时"改到"动手的那一刻"：程序此前没有检查过任何东西时，对环境的动作调用会被拒绝；不动手的程序（读说明页、保存代码、设置节点）不需要它。检查函数自己在环境里做的事算作读取；反射节点的程序不受此限制。程序还在运行、模型被问到时收到的消息，现在写明此时要做的两件事：跟住这个程序，并用不需要对环境动手的事为之后做准备。`after(unit)` 等到某个单元结束（不论怎样结束）：在另一个程序还在运行时发出的程序以它开头，然后用 `expect` 检查，再动手。
