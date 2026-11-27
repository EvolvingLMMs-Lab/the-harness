---
core: patch
agent: patch
---

Fix permanent chat hang and unstoppable turns after an unexpected reboot or host crash:

- End `/api/stream` cleanly in `src/harness/host/http.py` when a conversation under `conversations_dir` is orphaned (no longer running in `server.conversations` and has no `summary.json`) instead of streaming `: keep-alive` indefinitely.
- Pass `stop=cancellation.event` from `Session._observe()` into `Tasks.observe()` → `RemoteConversation.records(after=..., stop=...)` so clicking Stop always breaks out of an active task stream immediately.
- Recover orphaned `pending.run` tasks cleanly both on `Life.start()` (`_recover_interrupted`) and in `Session.turn()`, marking dangling tasks as cancelled instead of deadlocking or emitting `? unknown`, and avoid re-submitting already-started `life-state.json` jobs as duplicate user messages after a hard shutdown.

### 中文

- 修复电脑重启或异常中断后会话永久卡死、无法停止且无法发消息的问题：
  - 宿主 `/api/stream` 检测到孤儿任务（已不在当前运行会话中且未写完 `summary.json`）时立即结束流，不再无限发送 keep-alive 挂死监听线程。
  - `Session._observe()` 向 `Tasks.observe()` 传入取消信号 `stop`，点击停止按钮必定能立即打断任务等待。
  - 在 `Life.start()` 与 `Session.turn()` 启动恢复阶段自动清理异常断电/重启残留的孤儿 `pending` 任务并补写 `cancelled` 终态，同时不再把已开始执行但被强行中断的消息重复发送一遍。
