---
core: minor
computer: patch
workspace: patch
local-models: patch
eval: patch
---
What the model is given has a limit everywhere, and says so where it leaves something out.

- A conversation is compacted instead of cut: when the context a call read reaches `runtime.compact_at_tokens` (default 150000), the model writes a summary, which replaces the conversation before its last messages. `runtime.max_history_turns` is gone (a configuration that sets it is refused): set `compact_at_tokens` instead. The trace records `compaction`; `context_shortened` is gone.
- What a unit printed or returned is told whole up to 30,000 characters (it was cut to 8,000 and 2,000); more is saved to a file a program can read, and the model is told the file and the first 2,000 characters. `output_of` reads up to 30,000 characters.
- Every turn tells how many nodes act in the tree of reflexes and which changed since the model was last told (at most 10), not the whole tree. `reflexes()` gives the nodes at the top and `reflexes("name")` those under a node, at most 50 at a time; a node's `under` is now the names of the nodes under it.
- The system prompt stays the same from call to call: what an active run has learned is told with a program's result, whole when it changed. The library's skills are listed within 8,000 characters (past that by name only) and its notes within 200 lines or 25,000 characters.
<!-- zh -->
给模型的内容处处有上限，有省略的地方会明说。

- 对话改为压缩而不是截断：一次调用读到的上下文达到 `runtime.compact_at_tokens`（默认 150000）时，模型写一份摘要，替换掉最近几条消息之前的对话。`runtime.max_history_turns` 已移除（仍设置它的配置会被拒绝），改用 `compact_at_tokens`。trace 记录 `compaction`，不再有 `context_shortened`。
- 单元打印或返回的内容在 30,000 字符以内完整告知（原来截到 8,000 和 2,000）；超过时存成程序可读的文件，模型看到文件位置和开头 2,000 字符。`output_of` 最多读 30,000 字符。
- 每一轮只告诉模型反射树里有多少个会行动的节点、上次告知以来哪些有变化（最多 10 个），不再发整棵树。`reflexes()` 给出顶层节点，`reflexes("name")` 给出某节点下面的节点，一次最多 50 个；节点的 `under` 现在是它下面节点的名字。
- 系统提示词在各次调用之间保持不变：主动学习的运行学到了什么，随程序结果告知，有变化时才完整给出。库里的技能列表不超过 8,000 字符（超出部分只列名字），笔记不超过 200 行或 25,000 字符。
