---
core: patch
external-agents: patch
---
A reflex whose condition is slow for a moment no longer costs the tree its nodes. The nodes a period had no time for, because one before them used its budget up, are judged in the next period instead of being removed, and a condition that takes longer than the budget counts as a fault only when it does so three times in a row. Before, one condition 0.6 ms over its budget removed every node of a tree.

With a model that is a session of an agent (the `acp` backend), a compacted conversation now starts a new session that holds the summary and the recent messages. It used to go on in the old session, which still held everything: the context did not shrink and the conversation was compacted again before every call.
<!-- zh -->
反射的条件偶尔慢一下，不再让树失去节点。某个周期里因为前面的节点把预算用完而没轮到判断的节点，改为下一个周期再判断，不再被移除；条件超过预算要连续三次才算故障。此前，一个条件超出预算 0.6 毫秒就移除了整棵树的全部节点。

模型是某个 agent 的会话时（`acp` 后端），压缩后的对话现在会开一个新会话，只带摘要和最近的消息。此前它会在旧会话里继续，而旧会话仍保留着全部内容：上下文没有变小，于是每次调用前都再压缩一次。
