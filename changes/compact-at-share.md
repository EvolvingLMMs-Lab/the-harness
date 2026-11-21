---
core: minor
---
`runtime.compact_at_share`: where the model says how many tokens it can read at most (an ACP agent does, in its usage updates), the conversation is compacted at this share of them instead of at the fixed `compact_at_tokens`, as Claude Code compacts at about 83% of the window. The summary is still asked for ahead at 70% of that limit. A model that says nothing keeps `compact_at_tokens`.
<!-- zh -->
`runtime.compact_at_share`：模型说了自己最多能读多少 token 时（ACP agent 会在用量更新里说），对话在它的这个比例处压缩，不再用固定的 `compact_at_tokens`，和 Claude Code 在窗口约 83% 处压缩一样。摘要仍在这个上限的 70% 处提前写。模型没说窗口时照旧用 `compact_at_tokens`。
