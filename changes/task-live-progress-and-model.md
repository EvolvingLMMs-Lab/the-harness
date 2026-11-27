---
agent: minor
app: minor
external-agents: patch
---

Live task sub-step progress in chat, chat effort propagation to background tasks, and lean Antigravity CLI (`agy acp`) pure-text mode:

- Stream Task Engine sub-steps (`state` status, `model_request` step turns, executed `cell` commands & durations, `skill` completions, and `error` messages) from `Life.task_rows()` as `task_step` chat records, and render a live compact sub-step feed directly under running `任务` rows in `chat.js` (collapsing cleanly into the expandable details drawer once finished).
- Propagate the active chat's selected model and `reasoning_effort` into `Tasks` (`Tasks.submit` → `host.task(..., reasoning_effort=...)`), including delegated `place` tasks in `_tasks_in()`, so lowering reasoning effort or switching models in a chat takes effect inside the Task Engine as well.
- Pass `--include-default-customizations=false` when `AcpModel` runs `agy acp` as a pure-text LLM backend so Antigravity's built-in skills/plugins are not loaded into every task step prompt.

### 中文

- 打通后台任务引擎实时进度流：`Life.task_rows()` 将任务子步骤（工作区状态、每步模型思考、执行的脚本与耗时、技能与报错）实时推送到聊天记录，前端在运行中的「任务」下方直接展示实时子步骤流，完成后自动折叠进详情面板，告别黑盒干等。
- 修复后台任务未继承对话思考深度（`reasoning_effort`）与委派项目模型的问题：在对话里切换模型或调低深度后，任务引擎每一步同步生效。
- `AcpModel` 调用 `agy acp` 作为纯文本模型后端时自动附加 `--include-default-customizations=false`，避免每次任务步骤都加载全量默认技能/规则拖慢响应速度。
