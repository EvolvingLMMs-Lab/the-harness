---
agent: minor
---
A turn that fails says why and what to do in the words of the first run (the key was refused, no credit, no such model, no connection, the agent is not signed in), and a turn that the daily limit stopped says how to raise it. A chat's context can be compacted on request (`harness agent compact ["what to keep"]`, `Agent.compact`, `POST /api/agent/compact`), and a chat says how full its context is (`Agent.context`, `context` in `GET /api/agent/chat`: the tokens of its last model call and the model's window where it reports one). A turn that was stopped keeps what it had written of its reply in the record.
<!-- zh -->
失败的回合会用和首次引导一样的话说明原因和修法（key 被拒绝、没有余额、没有这个模型、连不上、agent 没登录）；被每日额度拦下的回合会说明怎么提高额度。对话的上下文可以手动压缩（`harness agent compact ["保留什么"]`、`Agent.compact`、`POST /api/agent/compact`），也能看到上下文用了多少（`Agent.context`、`GET /api/agent/chat` 里的 `context`：最近一次模型调用的 token 数，以及模型报告的窗口大小）。被停下的回合会把已经写出来的回复文字留在记录里。
