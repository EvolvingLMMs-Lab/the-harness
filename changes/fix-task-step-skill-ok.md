---
agent: patch
---

Fix false red `×` badges on successful task sub-steps and suppress noisy `output`/`status` polling rows:

- Derive `task_step` skill `ok` status from `execution.event.kind` (`COMPLETED` / `PREDICATE_SATISFIED`) when `execution` omits an explicit `"ok"` boolean (as emitted by `entries.py:record_event`).
- Suppress internal successful `output` and `status` polling events from the live chat sub-step feed so shell runs stay clean and readable.

### 中文

- 修复任务引擎实时子步骤把成功执行的 `run` / `read` 误标成红叉 `×` 的问题（改为按 `execution.event.kind` 是否为 `COMPLETED` / `PREDICATE_SATISFIED` 判断）。
- 过滤掉成功时的内部 stdout 分片轮询事件（`output` / `status`），避免刷屏。
