---
title: "Use The Harness from Claude Code, Codex, Cursor and editors"
description: "The Harness as an MCP server and an ACP agent, Claude Code and Codex as its sub-agents, and a Claude Code plugin."
---

Other agents and editors can drive The Harness, and The Harness can hand work to them.

| From | How | Package |
|---|---|---|
| Claude Code, Codex, Cursor, any MCP client | `harness mcp`, an MCP server | `mcp-server` |
| Zed and other ACP editors | `harness acp`, an agent of the Agent Client Protocol | `acp` |
| Claude Code, as a plugin | the MCP server, two skills and two commands | this repository's `plugins/the-harness` |
| The Harness's own agents | Claude Code or Codex as a sub-agent | `external-agents` |

Every way in starts sessions in the session host, so they show in the app and in
`/sessions` of the terminal chat like any other.

## The MCP server

```bash
harness install mcp-server
```

Then add it to your client:

- Claude Code: `claude mcp add harness -- harness mcp`
- Codex, in `~/.codex/config.toml`:

  ```toml
  [mcp_servers.harness]
  command = "harness"
  args = ["mcp"]
  ```

- Cursor, in `.cursor/mcp.json`:

  ```json
  {"mcpServers": {"harness": {"command": "harness", "args": ["mcp"]}}}
  ```

`harness mcp` speaks over stdio. `harness mcp --http` serves streamable HTTP at
`http://127.0.0.1:8790/mcp` (`--port` to change it), on this computer only; for example,
`claude mcp add --transport http harness http://127.0.0.1:8790/mcp`.

| Tool | Does |
|---|---|
| `run_task` | starts a session on a task and waits at most `wait_seconds` (up to 120): the answer, or the session and its progress |
| `list_sessions`, `start_session`, `send_message`, `stop_session` | the sessions |
| `get_session` | a session's status, answer and last progress |
| `observe_screen` | a session's screen now, as an image |
| `read_events` | a session's timeline, as records |
| `list_packages`, `install_package` | the packages (official ones, by name) |
| `list_library` | what the agent learned |

A long task never blocks the client: it returns the session, which the client follows
with `get_session`. When a session waits for an approval (a sensitive step, the user's real
mouse and keyboard, or every program under `approvals.ask = "programs"`: see
[the permissions](/docs/configure/permissions/#approvals)), the tools say so, and the
user approves it in The Harness: in the app, or in the terminal chat (`/sessions`, then
`/approve`). No tool approves it.

## The ACP agent

```bash
harness install acp
```

In Zed's `settings.json`:

```json
{"agent_servers": {"The Harness": {"command": "harness", "args": ["acp"]}}}
```

Each thread is a session. The editor shows the agent's messages, each program it runs as
a tool call, and asks you when the agent waits for an approval.

## The Claude Code plugin

```text
/plugin marketplace add EvolvingLMMs-Lab/the-harness
/plugin install the-harness@the-harness
```

It brings the MCP server, the skills `act-with-the-harness` and `follow-harness-sessions`,
and the commands `/harness <task>` and `/harness-sessions`. Install The Harness and the
`mcp-server` package first.

## Claude Code and Codex as sub-agents

```bash
harness install external-agents
```

An agent's program hands a task to another agent's CLI, which works headless on this
computer in a directory of its own:

```python
a1 = delegate("write a script that renames the photos by date", agent="claude-code")
wait_agents([a1])
```

`agent` is `"claude-code"` (`claude -p`) or `"codex"` (`codex app-server`). Their messages and
tool uses show on the timeline as the sub-agent's lane, what they spend counts against the
budget as for The Harness's own sub-agents, and they stop at their budget. The CLI must be
installed and signed in; when it is not, the sub-agent fails with how to install it.

Codex workspace file operations go through the host. Replacing or deleting a file and reading a credential path require a separate decision. Claude Code's native tools are limited to reading non-credential paths in its workspace and pass through PreToolUse. Shell, native writes, and unauthorized tool channels stay disabled. Unattended runs refuse sensitive calls.
