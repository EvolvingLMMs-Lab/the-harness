---
core: minor
---
A program can keep the environment: after `uninterruptible()` no rule's program and no other unit takes the environment from it until it ends, whatever their priority. A rule whose condition comes to hold meanwhile does not act; it is judged again when the program has ended and acts if its condition still holds, and the model is told once that it was held back (the event `HELD_BACK`). Cancelling the program, the time of its calls, a rule that ends executions and the end of the episode still end it. `rules_set()` lists the rules that exist with their priority, highest first. Numeric priorities are unchanged.
<!-- zh -->
程序可以一直持有环境：调用 `uninterruptible()` 之后，直到它结束，不管优先级多少，任何规则的程序和其他单元都不会从它手里接管环境。期间条件成立的规则不会行动；程序结束后重新判断，条件仍然成立才行动，模型会被告知一次该规则被挡住（事件 `HELD_BACK`）。取消这个程序、它的调用到时限、结束执行的规则以及 episode 结束，仍然会结束它。`rules_set()` 按优先级从高到低列出现有的规则及其优先级。数字优先级不变。
