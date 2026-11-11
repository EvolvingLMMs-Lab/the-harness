---
core: patch
---
The terminal chat shows the agent's text that looks like HTML as it was written instead of
leaving it out: `Vec<String>` no longer reads `Vec`, and a line that starts with a tag such
as `<div>` no longer hides itself and the lines after it. `<br>` breaks the line
and `<kbd>` keeps its style.
<!-- zh -->
终端聊天会按原样显示 agent 回答里像 HTML 的文字，不再把它丢掉：`Vec<String>` 不会再只剩
`Vec`，以 `<div>` 等标签开头的一行也不会再连同后面几行一起消失。`<br>` 显示为换行，`<kbd>` 保留按键样式。
