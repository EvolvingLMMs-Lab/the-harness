---
core: patch
external-agents: patch
---
Attached POSIX hosted terminals receive the local window size and resize with it. They start with usable dimensions before a client attaches; older hosts and other transports retain their existing behavior.
<!-- zh -->
连接 POSIX 托管终端后会同步本地窗口尺寸，并在窗口变化时更新；客户端连接前也有有效的初始尺寸。旧 host 和其他终端后端保留原有行为。
