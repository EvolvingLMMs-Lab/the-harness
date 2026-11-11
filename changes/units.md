---
core: minor
computer: minor
workspace: minor
eval: patch
---
A run is now one model and the units it starts. Every program the model writes runs as a unit beside the others, with its own output and result: the model's turn comes back at once (with the result when the program was over within `runtime.turn_grace_seconds`, 2 s by default, else while it still runs), and the model may start another program, cancel one, or reply `<wait>` until a unit ends, a message or an event reaches it, or its time is over (`runtime.longest_wait_seconds`). A rule is a condition, a priority and a program: `rule(begins, program, ends=..., priority=...)` starts the program as a unit when its condition comes to hold; `facts` is a store of named values that programs and rule conditions share. A unit of higher priority takes the environment from a lower one, whose call is started again afterwards. A sub-agent that ends wakes the model that started it.

What breaks: the look-ahead during a program (`<assume>`), `watch(every=seconds)`, the reflex rule (`reflex`, `remove_reflex`, the named priorities) and the `USER_MESSAGE` event are gone; `runtime.think_while_acting`, `model.think_while_acting` and `--think` are still accepted and have no effect. A worker's profile says how it is driven with `max_hz` and `step_seconds` instead of `clock` (an old `clock` is still read); an environment that needs a command every period while nothing runs now needs a rule on time. A pause stops every unit and holds until the conversation is continued. The traces lose `ahead`, `side_program`, `side_program_end` and `program_stopped` and gain `unit_end`, `wait`, `wait_end`, `rule`, `fact` and `preempted`.
<!-- zh -->
一次运行现在由一个模型和它启动的单元组成。模型写的每个程序都作为一个单元与其他单元并排运行，各有自己的输出和结果：模型的这一轮立刻回来（程序在 `runtime.turn_grace_seconds`（默认 2 秒）内结束时带着结果，否则程序仍在运行），模型可以再启动一个程序、取消一个，或者回复 `<wait>`，直到某个单元结束、有消息或事件到达、或时间到（`runtime.longest_wait_seconds`）。规则是一个条件、一个优先级和一个程序：`rule(begins, program, ends=..., priority=...)` 在条件变为成立时把程序作为单元启动；`facts` 是程序和规则条件共享的命名值存储。优先级高的单元从优先级低的单元手里接管环境，低优先级的那次调用之后被重新启动。子 agent 结束时会唤醒启动它的模型。

不再兼容的部分：程序运行期间的前瞻（`<assume>`）、`watch(every=秒数)`、反射规则（`reflex`、`remove_reflex`、命名优先级）和 `USER_MESSAGE` 事件已移除；`runtime.think_while_acting`、`model.think_while_acting` 和 `--think` 仍被接受，但不起作用。worker 的 profile 用 `max_hz` 和 `step_seconds` 说明它如何被驱动，不再用 `clock`（旧的 `clock` 仍可读取）；没有东西运行时每个周期也需要命令的环境，现在需要一条按时间判断的规则。暂停会停下每个单元，直到对话继续。trace 去掉了 `ahead`、`side_program`、`side_program_end` 和 `program_stopped`，新增 `unit_end`、`wait`、`wait_end`、`rule`、`fact` 和 `preempted`。
