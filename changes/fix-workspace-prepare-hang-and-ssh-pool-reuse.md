---
core: patch
workspace: patch
agent: patch
---
Fix permanent task hang when workspace preparation fails (write final `summary.json`, end `/api/stream` on terminal `ERROR`/`FINISHED` states, and exit `Tasks.observe()` cleanly), and run SSH workspace workers in-process over the shared host `ssh.POOL` bridge instead of opening a redundant second SSH connection per worker subprocess.
<!-- zh -->
修复准备工作区失败时任务永久卡在“进行中”的死锁（落盘终态 `summary.json`、`/api/stream` 在终态自动结束流、`Tasks.observe()` 收到 `ERROR`/`FINISHED` 立即退出），并让 SSH workspace worker 直接在宿主进程内复用共享的 `ssh.POOL` 持久桥，避免每个 worker 子进程二次建立 SSH 连接导致超时。
