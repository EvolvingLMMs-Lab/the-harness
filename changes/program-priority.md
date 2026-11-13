---
core: minor
---
A program takes its place among the reflexes with `at_priority(n)`: from that call to its end it holds the environment with priority n. Reflexes of priority n or more still take the environment from it; those below wait and are judged again when it has ended, and the model is told once of each that was held back. `uninterruptible()` is gone: it shut every reflex out, the ones that answer a danger the program has nothing to do with as well. A program that must not be cut short by anything calls `at_priority` with a number above its highest reflex.
<!-- zh -->
程序用 `at_priority(n)` 在反射中间取得自己的位置：从这个调用到程序结束，它以优先级 n 持有环境。优先级为 n 或更高的反射仍然能从它手里接管环境；低于它的等待，程序结束后重新判断，每个被挡住的反射会告知模型一次。`uninterruptible()` 已移除：它把所有反射都挡在外面，包括那些应对与程序无关的危险的反射。确实不能被任何东西打断的程序，用一个高于最高反射的数调用 `at_priority`。
