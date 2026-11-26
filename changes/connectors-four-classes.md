---
core: minor
agent: minor
external-agents: minor
mcp-server: patch
---
Everything the agent is connected to is managed the same way: listed, added, removed and tested. MCP servers: `harness mcp list | add | get | remove | enable | disable | test` (`harness mcp add NAME URL`, or `harness mcp add NAME -- COMMAND ARGS`; `test` connects once and lists the tools), `/api/app/mcp`, `harness.sdk.connectors`. The Harness as an MCP server is `harness mcp serve`; `harness mcp` alone still does that. External agents: `harness agents list [--registry] | add | get | remove | test` (`test` asks the agent for one word), `/api/app/acp`; `harness agents ls` now prints a table (`--json` for JSON). Skill sources, new: `harness skills sources | add SOURCE | test | update | remove` takes skills from a folder, a `SKILL.md`, a repository or an archive into an identity, each as proposed (`/api/agent/skill_sources`, `Agent.skill_source_add`). `harness channels test ACCOUNT` says whether a channel account works. A `SKILL.md` whose description is a YAML block (`description: >`) is read whole.
<!-- zh -->
agent 接入的每一样东西都用同一种方式管理：列出、添加、删除、测试。MCP 服务：`harness mcp list | add | get | remove | enable | disable | test`（`harness mcp add 名字 地址`，或 `harness mcp add 名字 -- 命令 参数`；`test` 连接一次并列出工具）、`/api/app/mcp`、`harness.sdk.connectors`。把 The Harness 当成 MCP 服务是 `harness mcp serve`；单独的 `harness mcp` 仍然是它。外部 agent：`harness agents list [--registry] | add | get | remove | test`（`test` 让它回答一个词）、`/api/app/acp`；`harness agents ls` 现在打印表格（`--json` 输出 JSON）。新增技能来源：`harness skills sources | add 来源 | test | update | remove` 从文件夹、`SKILL.md`、仓库或压缩包把技能装进一个身份，每个都记为“提议”（`/api/agent/skill_sources`、`Agent.skill_source_add`）。`harness channels test 账号` 说明一个渠道账号现在能不能用。描述写成 YAML 块（`description: >`）的 `SKILL.md` 现在能完整读出。
