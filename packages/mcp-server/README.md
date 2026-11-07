# mcp-server

The `mcp-server` package makes The Harness an MCP server: `harness mcp`. A coding agent
such as Claude Code, Codex or Cursor then gives The Harness tasks on this computer (in a
browser, on the desktop, in its apps) and follows them. Each task is a session of the
user's session host, so the app and the terminal chat (/sessions) list and follow
it as well.

## Install

```bash
harness install mcp-server
```

It needs nothing outside Python.

## Use

`harness mcp` speaks MCP on stdin and stdout, which is what an MCP client starts.
`harness mcp --http [--port 8790]` serves streamable HTTP at `http://127.0.0.1:8790/mcp`
instead; it answers requests from this computer only.

Claude Code:

```bash
claude mcp add harness -- harness mcp
# or, with harness mcp --http running:
claude mcp add --transport http harness http://127.0.0.1:8790/mcp
```

Codex, in `~/.codex/config.toml`:

```toml
[mcp_servers.harness]
command = "harness"
args = ["mcp"]
```

Cursor, in `.cursor/mcp.json`:

```json
{"mcpServers": {"harness": {"command": "harness", "args": ["mcp"]}}}
```

## Tools

| Tool | Does |
| --- | --- |
| `run_task {task, workspace?, wait_seconds?}` | Starts a session on the task and waits at most `wait_seconds` (default 30, at most 120) for its answer; a longer task returns its session id and progress, to poll with `get_session`. |
| `start_session {task, workspace?}` | Starts a session and returns at once. |
| `list_sessions {all?}` | The sessions, newest first. |
| `get_session {session, lines?}` | Its status, what it waits for, its answer and its last lines of progress. |
| `send_message {session, text}` | A message for the session's agent. |
| `stop_session {session}` | Ends the session. |
| `observe_screen {session}` | The screen of its workspace now, as an image. |
| `read_events {session, after?, limit?}` | Its trace records, compact, with `next_after` for paging. |
| `list_packages {query?}` | The installed packages, or the registry's that match. |
| `install_package {name}` | Installs an official package by name. |
| `list_library {name?}` | The libraries of what the agent learned, or one library's entries. |

`workspace` is `auto` (the host takes what the task asks for), `browser`, `desktop`,
`apps` or `display`.

## Approvals

A session may wait for the user's approval: a program to confirm, or a step of physical
input that the physical-input policy holds. The tools report that it waits; the user
approves it in a harness frontend (the app, or /approve in the
terminal chat). There is no approve tool, so the agent that calls
the tools never approves its own input.
