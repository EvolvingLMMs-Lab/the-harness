---
core: minor
external-agents: minor
---
An ACP agent (Claude Code, Codex and the others of the ACP Registry) can be the model of the Harness agent: a `models.json` entry with the provider `acp:ID` now gives the Harness agent that model, with programs, workspaces, learning and libraries, where it used to start the agent's own session. For the agent's own session in a folder, name it with `--agent acp:ID`; `--library` with `--agent` is now an error instead of being ignored. `harness agents update` no longer fails with HTTP 403.
<!-- zh -->
ACP agent（Claude Code、Codex 以及 ACP Registry 里的其他 agent）可以当作 Harness agent 的模型：`models.json` 里 provider 为 `acp:ID` 的条目现在让 Harness agent 用它做决策，程序、工作区、学习和 library 都可用；以前选这个条目会启动 agent 自己的会话。要启动 agent 自己在目录里的会话，用 `--agent acp:ID`；`--agent` 加 `--library` 现在会报错，不再被悄悄忽略。`harness agents update` 不再返回 HTTP 403。
