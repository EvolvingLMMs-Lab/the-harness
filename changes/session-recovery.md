---
core: patch
---
Interrupted sessions recover safely when their last trace event was only partly written, and session history identifies conversations left open by a stopped host as interrupted. Continuing a session follows its latest user message or resume, unaffected by background agent events; metadata-only session details avoid loading the transcript, and dropped event streams retry with bounded backoff while remaining cancellable. The host uses the selected enabled model consistently and accepts custom endpoints without an API key.
Package management works before an environment is installed or selected, and installing an environment makes it available immediately.
RPC rejects task-continuation flags instead of silently starting a different conversation; use `harness run --continue` or `--session ID` to continue an existing one.

<!-- zh -->
日志最后一条事件未写完时，会话可以安全恢复；host 停止后仍未关闭的会话会标为已中断。续接会话以最近的用户消息或恢复操作为准，不受后台事件影响。只请求会话信息时不再加载整份对话记录，事件流中断后会逐步延长重试间隔，并允许取消。Host 一致使用选中的启用模型，并支持无需密钥的自定义端点。
尚未安装或选择环境时也能管理包；新安装的环境会立即可用。RPC 不再忽略续接参数后另起会话；续接现有会话请使用 `harness run --continue` 或 `--session ID`。
