---
core: minor
---
The call that sets a rule that acts by itself is `set_reflex(name, when, do=None, ...)`; `reflexes()` lists them and `drop_reflex(names=None)` removes them. They replace `rule`, `rules_set` and `clear_rules`: programs and library entries that call those change the names (the name comes first, the condition is `when`, the program is `do`).

An environment that can hold what a call is doing and let it go on later says `"pauses": True` in its worker's profile and serves `pause` and `resume`. There a unit of higher priority no longer ends the call it takes the environment from: the call is paused, the higher unit acts, and the call goes on when that unit has ended, in the same program and without a question to the model. The trace records `call_paused` and `call_resumed`. Environments that do not pause behave as before (the call ends with PREEMPTED).

A reflex's program that ended well is recorded and no longer wakes the model; its failure does. A learned reactive entry may set trees as well as reflexes when it is loaded, and the body of a lambda in it counts as code that runs later, like a function's: an entry such as `set_reflex("low", lambda view: view["facts"].get("low"), refill)` loads, where it was refused before.
<!-- zh -->
设置自己行动的规则的调用改为 `set_reflex(name, when, do=None, ...)`；`reflexes()` 列出它们，`drop_reflex(names=None)` 移除它们。它们取代 `rule`、`rules_set` 和 `clear_rules`：调用旧名字的程序和库条目需要改名（名字在最前，条件是 `when`，程序是 `do`）。

环境如果能把一个调用正在做的事保持住、之后让它继续，就在 worker 的 profile 里声明 `"pauses": True` 并提供 `pause` 和 `resume`。在这样的环境里，优先级高的单元不再结束它所接管的调用：该调用被暂停，高优先级单元行动，等它结束后调用接着进行，仍在同一个程序里，也不询问模型。trace 记录 `call_paused` 和 `call_resumed`。不能暂停的环境行为不变（调用以 PREEMPTED 结束）。

反射的程序正常结束时只记录、不再唤醒模型；失败时仍会告知。学到的 reactive 条目在加载时除了反射也可以设置树；条目里 lambda 的函数体和函数一样算作之后才运行的代码：像 `set_reflex("low", lambda view: view["facts"].get("low"), refill)` 这样的条目现在可以加载，以前会被拒绝。
