---
agent: minor
app: minor
---

Local Markdown plan/spec artifacts (`write_artifact`) and elimination of ghost `folder.changed` project placeholder chats:

- Suppress unread increments for workspace filesystem events (`folder` / `ssh` places) in `Chats.record(..., quiet=...)` / `Life._event()`, and stop showing backend `kind="place"` placeholder rows under sidebar projects on unread spikes.
- Add a zero-latency `write_artifact` action to the dialogue agent that atomically writes local Markdown plans/specs into `sessions/<chat>/artifacts/<name>.md` (without polluting the project repository), records an `artifact` card in chat, and integrates with `Plan` mode.
- Add `/api/app/artifacts` and `/api/app/artifact` endpoints, interactive Artifact cards in `chat.js` (View plan / Open local `.md` / Approve & Proceed), and rendered Markdown artifact preview inside the right `Context` panel.

### 中文

- 彻底消除项目下因 `folder.changed` 反复闪现的幽灵占位对话：工作区（`folder` / `ssh`）文件系统事件不再递增聊天未读数，侧边栏永久过滤后端自动创建的 `place` 占位行。
- 新增轻量本地 `.md` 方案/产物机制（`write_artifact`）：无需启动重量级后台任务即可直接将方案落盘到 `sessions/<chat>/artifacts/<name>.md`（不污染项目 Git 状态），在 `Plan` 模式下自动引导先落盘评审再执行。
- 聊天流渲染紧凑文档卡片（支持「查看方案」右侧 Markdown 渲染预览、「打开本地文件」及「批准并执行」一键切回 Auto 并开始实施），并在右侧上下文面板列出当前对话的全部方案文档。
