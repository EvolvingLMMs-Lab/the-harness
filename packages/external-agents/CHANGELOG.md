# Changelog

## 0.3.0

- An ACP agent (Claude Code, Codex and the others of the ACP Registry) can be the model of the Harness agent: a `models.json` entry with the provider `acp:ID` now gives the Harness agent that model, with programs, workspaces, learning and libraries, where it used to start the agent's own session. For the agent's own session in a folder, name it with `--agent acp:ID`; `--library` with `--agent` is now an error instead of being ignored. `harness agents update` no longer fails with HTTP 403.
- An ACP agent used as the model keeps its session across a run: a call that only drops an old picture, leaves out a reply that was not kept, or changes part of the system prompt goes on in the same session instead of sending the whole conversation again. The agent's process ends when the conversation ends or the model is changed. A model or reasoning effort the agent cannot set is now an error instead of being ignored: write `"default"` to take the agent's own.
- A reflex whose condition is slow for a moment no longer costs the tree its nodes. The nodes a period had no time for, because one before them used its budget up, are judged in the next period instead of being removed, and a condition that takes longer than the budget counts as a fault only when it does so three times in a row. Before, one condition 0.6 ms over its budget removed every node of a tree. With a model that is a session of an agent (the `acp` backend), a compacted conversation now starts a new session that holds the summary and the recent messages. It used to go on in the old session, which still held everything: the context did not shrink and the conversation was compacted again before every call.

## 0.2.0

- Start ACP, terminal and cloud coding sessions in the session host. The host keeps their
  project, external ID, trace, available controls and handoff links.
- Discover and install pinned ACP Registry distributions, configure trusted local commands,
  and explicitly observe or recover a selected native session.
- Claude Code and Codex delegates can opt into follow-up turns inside the original S7
  tool and budget boundaries.

## Unreleased (S7)

- Claude Code and Codex run in a fresh delegated workspace with only bounded file
  operations. Every operation passes the harness gate; sensitive overwrites, credential
  files and deletes wait once for the user, and unattended runs use the run's recorded
  approval policy. Native shells, MCP servers, browser/computer tools and permission
  widening are unavailable.

## 0.1.0

- Claude Code (`claude -p`) and Codex (`codex app-server`) as sub-agents: `delegate(task, agent="claude-code")`.
- Every tool call they ask about passes the harness's gate (the shield, the user for sensitive
  steps, the `approvals.ask` setting); no `acceptEdits`, no `--full-auto`.
