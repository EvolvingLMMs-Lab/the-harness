---
core: minor
---
The list of what can happen to the agent (`situations(...)`) counts for the values the environment's situation had when the list was given: once the state shows another, a program that acts is refused until the list is given again, and the refusal says to think the place through first. An environment can add a sentence of its own to every message that asks for the list (its profile: `situations_hint`), for example where its own description is to be read. The refusal of an action without an `expect` says that what holds for every action is not one; the message about expectations that all held names a wrong `until` as the other cause; the message for a program that still runs says to look at its result first when the next program depends on it.
<!-- zh -->
“会发生什么”的清单（`situations(...)`）只对列清单时环境的情况值有效：状态显示情况变成了别的值之后，要动手的程序会被拒绝，直到重新给出清单；拒绝里写明先把这个地方想清楚。环境可以给每一条要求列清单的消息加上自己的一句话（profile 里的 `situations_hint`），例如先去读它自己的说明。没有 `expect` 就动手时的拒绝写明：对每个动作都成立的事不算预期；“预期全部成立但结果没到”的消息把 `until` 写错列为另一种原因；程序还在运行时的消息写明：下一个程序依赖它的结果时，先看结果。
