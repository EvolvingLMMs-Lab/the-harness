---
core: minor
---
A reaction tells the model when it begins. When a rule's program (a unit of higher priority) takes the environment from a call that runs, the model is told at once, as with every event that reaches it: which rule took the environment, from which program, and the state; a wait ends and a call that is out is asked again. The interrupted call ends there with the event `PREEMPTED` and what it had done, and the model decides what goes on. The unit that took the environment holds it until it ends: what the model starts meanwhile waits behind it and goes on then.

What breaks: an interrupted call is no longer started again by itself. `spawn(fn, restart=True)` asks for that (the default was `restart=True`, it is `restart=False` now); a program whose call is interrupted ends with `PREEMPTED` unless a handler answers it (`on("PREEMPTED", ...)`). The `preempted` record also names the rule, the units and the execution.
<!-- zh -->
反应在开始时就告诉模型。规则的程序（优先级更高的单元）从一次正在进行的调用手里接管环境时，模型会立即得知，和每个到达它的事件一样：哪条规则接管了环境、从哪个程序手里、以及当时的状态；等待结束，正在进行的模型调用被重新发起。被打断的调用在当前位置以事件 `PREEMPTED` 结束，并带着它已经做了的事，接下来做什么由模型决定。接管环境的单元持有环境直到自己结束：模型在此期间启动的东西排在它之后，等它结束再继续。

不再兼容的部分：被打断的调用不再自动重新启动。需要时用 `spawn(fn, restart=True)` 要求（默认值原来是 `restart=True`，现在是 `restart=False`）；调用被打断的程序会以 `PREEMPTED` 结束，除非有 handler 处理它（`on("PREEMPTED", ...)`）。`preempted` 记录还会写出规则、单元和执行的名字。
