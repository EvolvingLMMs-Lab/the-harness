---
core: minor
---
A skill can bring its own pages of instructions. Its `skill.toml` names them (`[guides.<name>]` with `file`, a path from the skill's folder), and the model reads one with `guide("<name>")`, as it reads the core's `tree` and `units`. A page may name the skill's functions that wait for it (`before`): such a function is refused until the page was read, and the refusal names the page. A page that was read is given again after a summary of the conversation.
<!-- zh -->
skill 可以带自己的说明页。在 `skill.toml` 里声明（`[guides.<名字>]`，`file` 是相对 skill 目录的路径），模型用 `guide("<名字>")` 读，和读核心的 `tree`、`units` 一样。一页可以指明要等它读过才能调用的函数（`before`）：这一页读过之前调用这些函数会被拒绝，拒绝信息里写明该读哪一页。读过的页在对话被摘要之后会重新给一遍。
