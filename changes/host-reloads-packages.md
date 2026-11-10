---
core: patch
---
Packages installed, removed or updated with `harness install` or `harness remove` reach the
next conversation: the session host restarts by itself once no session is open, instead of
waiting for `/host stop`.
<!-- zh -->
用 `harness install` 或 `harness remove` 安装、删除或更新的包，下一个对话就能用上：session
host 会在没有打开的会话时自动重启，不再需要手动 `/host stop`。
