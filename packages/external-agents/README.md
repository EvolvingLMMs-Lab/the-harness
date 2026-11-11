# external-agents

The `external-agents` package adds ACP, terminal and cloud coding sessions to the
Harness session host. It also provides bounded Claude Code and Codex delegates.

## Install

```bash
harness install external-agents
```

It also needs the CLI of the agent you use, installed and signed in once:

- Claude Code: `npm install -g @anthropic-ai/claude-code`, then `claude`
- Codex: `npm install -g @openai/codex`, then `codex`

A task that delegates to one of them installs this package on first use (as
`packages.auto_install` says). A CLI that is missing is an error that says how to install it.

## External conversations

Run `harness agents update` and `harness agents ls` to inspect the saved ACP Registry.
Choose an ID and explicitly install it with `harness agents install ID`. Use
`harness agents add NAME -- COMMAND ARGS` to register a trusted local ACP server or
`harness agents add --terminal NAME -- COMMAND ARGS` for a terminal CLI. The corresponding
IDs are `acp:custom/NAME` and `terminal:NAME`. The app shows configured agents
alongside Harness. Start the terminal chat with `harness --agent ID --folder .`.

To observe a selected transcript, use `harness sessions import PROVIDER FILE --follow`.
For opt-in terminal notifications and approvals, enable the exact project directory
with `harness agents hooks enable PROVIDER DIRECTORY`. Configure the native client's
`PermissionRequest`, `Notification` or `Stop` hooks to run
`harness agents hooks dispatch PROVIDER` as appropriate. The bridge only answers a
matching, actively observed session. If its request expires it yields to the native
client. The command changes Harness's forwarding allowlist. Configure the native
client's own hook files separately.

Cloud settings contain an `account_scope` label and optionally the name of a
`credential` variable. Pass the settings file to
`harness agents configure-cloud PROVIDER SETTINGS.json`.

| Provider ID | Required settings | Default credential variable |
| --- | --- | --- |
| `claude` | `agent_id`, `environment_id` | `ANTHROPIC_API_KEY` |
| `openai` | `model`, `environment` with type `openai_hosted` or `none` | `OPENAI_API_KEY` |
| `copilot` | `repository` as owner/name, `ref` | `GITHUB_TOKEN` |
| `jules` | `source` as the native source resource, `ref` | `JULES_API_KEY` |
| `cursor` | repository URL in `repository`, `ref` | `CURSOR_API_KEY` |
| `devin` | `organization` | `DEVIN_API_KEY` |
| `qoder` | `agent_id`, `environment_id` | `QODER_ACCESS_TOKEN` |

Closing a cloud session in Harness detaches the observer. Use the separate cancel
operation when the provider supports it. Jules plan approval stays in Jules so a
stale Harness request cannot approve the wrong plan. Provider support is experimental
pending review against real accounts.

## As the model

An ACP agent can be the model of the Harness agent. Add an entry with the provider
`acp:ID` to `~/.harness/models.json` and select it like any model:

```json
[{ "provider": "acp:ID", "model": "MODEL", "enabled": true, "efforts": ["low", "high"] }]
```

Each call is one turn of a session of the agent in an empty directory, and its text is
the reply. The agent gets no client capabilities and no built-in tools where it accepts
that, its requests for permission are refused, and a turn in which it starts a tool of
its own fails. `--agent acp:ID` remains the agent's own conversation in a folder.

## Use

In a program, as with any sub-agent:

```python
a1 = delegate("write a script that renames the photos in ./photos by date", agent="claude-code")
wait_agents([a1])
```

For an explicitly multi-turn delegation, pass `multi_turn=True`. After a
`ready` report, send more work with `send_agent(a1, "...")`. Finish the delegated
session with `cancel_agent(a1)` or let the parent close it.

`agent` is `"claude-code"` or `"codex"`; `budget` (`calls`, `cost`, `seconds`) and `model`
work as for the harness's own sub-agents. The sub-agent works in a directory of its own
(under its parent's run), and what it makes there is its result's `files`.

- Claude Code uses its bounded `Read` tool. A `PreToolUse` hook checks each target
  in the delegated workspace. Codex runs a turn without a local execution environment and
  can list, read, write and delete workspace files through Harness tools. Both adapters
  disable shell, browser, MCP and other external tools.
- The gate refuses files outside the workspace and aliases such as symbolic links. Known
  credential files, whole-file replacement and deletion wait for one approval per operation.
  With `approvals.ask = "programs"`, every workspace operation waits. Unattended sensitive
  operations are refused. Claude Code native tools are limited to non-credential reads.
- The sub-agent's text, file operations and answer appear in its trace. Claude Code reports
  cost at the end of its turn. Codex reports calls and tokens.
- `HARNESS_CLAUDE_CODE_COMMAND` and `HARNESS_CODEX_COMMAND` select another copy of the CLI.
