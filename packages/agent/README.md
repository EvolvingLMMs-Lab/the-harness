# Persistent agent

The optional agent package owns identity, multi-turn dialogue, long-context compression,
private memory and conversation history. The Harness core independently performs
natural-language tasks, benchmark episodes and learning; it never imports this package.

```sh
harness run "Fix the parser and verify the regression" --folder ./project
harness agent --identity work --folder ./project
harness agent "Remember that PRs must be in English" --identity work --json
harness agent "Continue our discussion" --identity work --session SESSION_ID
harness agent --identity work --show-memory
```

`harness` without a command opens this optional agent. `harness run` never installs it.
Agent instances live under `$HARNESS_HOME/agents/<identity>`. Each contains an identity
configuration, private memory, sessions and a separate learning library. A session stores
raw dialogue events plus a bounded working context and explicit summary. New sessions
retain private memory but do not silently concatenate previous conversations; history
search is an explicit agent action. Independent identities share nothing by default.

The default identity imports legacy Personalization text once on first creation. Legacy
workspace libraries and historical run traces remain untouched; use `--library PATH` to
bind an old library explicitly. To edit persistent instructions, edit the identity's
`identity.json` while its sessions are idle. Package upgrades do not rewrite this data.

The agent handles ordinary dialogue itself and submits complete tasks through `Host.task`.
Tasks keep their own program/controller loop, budget, evidence and resource cleanup.
Agent dialogue calls and each task's usage are recorded separately. A finished task is
not automatically a verified success. Learning writes the separate library only when
explicitly enabled; remembering a preference does not activate executable code.

The host extension exposes `POST /api/agent/dialogue` with `text`, optional `identity`,
`session`, `model`, `workspace` and `folder`; it returns identity, session and answer.
This is the persistent-dialogue endpoint for frontends. `/api/tasks` remains the bounded
task endpoint. Concurrent writers to the same dialogue are refused. Memory updates use
revision checks; an uncertain task submission is preserved and never blindly retried.
User approvals must be answered through the task interface, not by the dialogue model.

Core run recovery and agent conversation recovery are distinct. Session schemas are
checked on opening; incompatible data is not silently reinterpreted. Summaries retain
raw source events and task references. Credentials are not stored in identity data.
