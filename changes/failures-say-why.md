---
core: minor
app: patch
---
When something fails, every frontend now says what went wrong, what to do about it and where the log is, instead of a log path alone: a session host that does not start names the exception and the package that raised it; a package whose host code does not fit this harness, or whose background service does not start, is left out and listed by `harness list` while the host goes on. A data folder last used by a newer harness is refused with what to do. A release starts the `harness` range of each package it releases at that release's core version.
<!-- zh -->
出错时，每个前端都直接说明原因、怎么修、日志在哪，不再只给一个日志路径：后台服务起不来时会指出异常和出问题的扩展包；与当前版本不匹配、或后台服务启动失败的扩展包会被单独跳过并在 `harness list` 里标出，后台照常运行。数据目录如果被更新的版本用过，会给出明确提示和处理办法。发布时，随核心一起发布的扩展包的 `harness` 范围从该核心版本起算。
