---
title: "Skill"
sidebar:
  label: 概览
  order: 0
---

模型所写程序可调用的内容（这里是核心自带的 skill；各扩展包的 skill 在它的 [/packages](/packages/zh-cn/) 页面上）。agent 按接口层或名称启用 skill；缺少所需服务的 skill 会被移除，提示词中相应的文本也随之移除（[Skill 与 prompt pack](/docs/zh-cn/extend/skills/)）。

| Skill | 层 | 导出名称 | 所需服务 |
| --- | --- | --- | --- |
| [memory](/docs/zh-cn/reference/skills/memory/) | base | `remember`, `recall`, `forget` | – |
| [experience](/docs/zh-cn/reference/skills/experience/) | base | `hint`, `keep_hint`, `experience` | – |
| [learning](/docs/zh-cn/reference/skills/learning/) | base | `library`, `ClosedLoop`, `sandbox` | – |
| [verify](/docs/zh-cn/reference/skills/verify/) | base | `verify` | – |
| [checklist](/docs/zh-cn/reference/skills/checklist/) | base | `plan`, `step_done` | – |
| [instructions](/docs/zh-cn/reference/skills/instructions/) | base | `read_skill` | – |
| [agents](/docs/zh-cn/reference/skills/agents/) | base | `delegate`, `wait_agents`, `send_agent`, `cancel_agent` | – |
| [entries](/docs/zh-cn/reference/skills/entries/) | base | `spawn`, `receive`, `entries`, `output_of`, `claim`, `unclaim`, `channels` | – |
| [mcp](/docs/zh-cn/reference/skills/mcp/) | base | `mcp_tools`, `mcp_call` | mcp |
| [environments](/docs/zh-cn/reference/skills/environments/) | base | `use_environment`, `release_environment`, `request_agents` | – |
| [conversation](/docs/zh-cn/reference/skills/conversation/) | base | `finish`, `get_state`, `get_observation`, `show` | – |
