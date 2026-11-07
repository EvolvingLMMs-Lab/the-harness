# Changelog

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
