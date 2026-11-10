---
title: "在应用、编辑器和 agent 里使用 The Harness"
description: "The Harness 作为 MCP 服务器和 ACP agent，Claude Code 和 Codex 作为它的子 agent，以及一个 Claude Code 插件。"
---

应用、编辑器和别的 agent 可以驱动 The Harness，The Harness 也可以把工作交给它们。

| 从哪里 | 怎么做 | 包 |
|---|---|---|
| 任何 MCP 客户端：Cursor、ChatGPT、Claude 等应用，Claude Code、Codex、OpenCode、Pi 等 agent | `harness mcp`，一个 MCP 服务器 | `mcp-server` |
| Zed 和其他 ACP 编辑器 | `harness acp`，一个 Agent Client Protocol 的 agent | `acp` |
| Claude Code，作为插件 | MCP 服务器、两个 skill 和两个命令 | 本仓库的 `plugins/the-harness` |
| The Harness 自己的 agent | Claude Code 或 Codex 作为子 agent | `external-agents` |

每种方式都在会话宿主里开会话，所以它们和其他会话一样出现在 app 和终端对话的 `/sessions` 里。

## MCP 服务器

```bash
harness install mcp-server
```

然后加到你的客户端里：

- Claude Code：`claude mcp add harness -- harness mcp`
- Codex，在 `~/.codex/config.toml` 里：

  ```toml
  [mcp_servers.harness]
  command = "harness"
  args = ["mcp"]
  ```

- Cursor，在 `.cursor/mcp.json` 里：

  ```json
  {"mcpServers": {"harness": {"command": "harness", "args": ["mcp"]}}}
  ```

`harness mcp` 走 stdio。`harness mcp --http` 在 `http://127.0.0.1:8790/mcp` 提供 streamable HTTP（用 `--port` 换端口），只对本机开放；例如 `claude mcp add --transport http harness http://127.0.0.1:8790/mcp`。

| 工具 | 做什么 |
|---|---|
| `run_task` | 为一个任务开会话，最多等 `wait_seconds`（不超过 120）：拿到回答，或者拿到会话和进度 |
| `list_sessions`、`start_session`、`send_message`、`stop_session` | 管理会话 |
| `get_session` | 一个会话的状态、回答和最近的进度 |
| `observe_screen` | 一个会话此刻的画面，作为图片 |
| `read_events` | 一个会话的时间线，作为记录 |
| `list_packages`、`install_package` | 包（官方包，按名字安装） |
| `list_library` | agent 学到的东西 |

长任务从不阻塞客户端：它返回会话，客户端用 `get_session` 跟进。会话在等批准时（敏感步骤、用户真实的鼠标键盘，或者 `approvals.ask = "programs"` 下的每个程序：见[权限设置](/docs/zh-cn/configure/permissions/#审批)），工具会说明，由用户在 The Harness 里批准：在 app 里，或者在终端对话里（`/sessions`，然后 `/approve`）。没有哪个工具能批准它。

## ACP agent

```bash
harness install acp
```

在 Zed 的 `settings.json` 里：

```json
{"agent_servers": {"The Harness": {"command": "harness", "args": ["acp"]}}}
```

每个对话线程是一个会话。编辑器会显示 agent 的消息，把它运行的每个程序显示成一次工具调用，agent 等批准时会问你。

## Claude Code 插件

```text
/plugin marketplace add EvolvingLMMs-Lab/the-harness
/plugin install the-harness@the-harness
```

它带来 MCP 服务器、`act-with-the-harness` 和 `follow-harness-sessions` 两个 skill，以及 `/harness <task>` 和 `/harness-sessions` 两个命令。先装好 The Harness 和 `mcp-server` 包。

## Claude Code 和 Codex 作为子 agent

```bash
harness install external-agents
```

agent 的程序可以把一个任务交给另一个 agent 的 CLI，它在本机自己的目录里无头运行：

```python
a1 = delegate("write a script that renames the photos by date", agent="claude-code")
wait_agents([a1])
```

`agent` 是 `"claude-code"`（`claude -p`）或 `"codex"`（`codex app-server`）。它们的消息和工具调用在时间线上显示为这个子 agent 的泳道，花费和 The Harness 自己的子 agent 一样计入预算，到预算就停。CLI 必须装好并登录过；没有的话，子 agent 会失败并说明怎么安装。

Codex 的工作区文件操作由宿主处理。替换现有文件、删除和读取凭据路径要单独批准。Claude Code 的原生工具限于工作区内非凭据路径的读取，并经过 PreToolUse。Shell、原生写入和未授权的工具通道保持关闭。无人值守时拒绝敏感操作。
