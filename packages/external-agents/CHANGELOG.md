# Changelog

## 0.3.1

- Attached POSIX hosted terminals receive the local window size and resize with it. They start with usable dimensions before a client attaches; older hosts and other transports retain their existing behavior.
- Package removal retains shared immutable cache files for other projects and independently configured data directories, and updates choose compatible versions while keeping your declared ranges. Explicit updates refresh published versions, including in a running app. A project install paused for trust refuses changed declarations instead of overwriting them. Preparing path, Git or URL sources and waiting for trust leave other package commands available. If another package change is already publishing files or records, a new request stops promptly and asks you to retry after it finishes. Broken environment caches rebuild on first use; installation errors show their cause and retry only transient network failures, and the terminal uses its declared dependency pins. Browser depends on computer 0.8, and current browser, computer and external-agents packages require Harness 0.82 or newer. The core refuses older computer packages with an upgrade command instead of running an incompatible managed-workspace protocol. Project updates change the lock without turning indirect dependencies into declarations; outside a project, `--update --project` refuses to touch user packages. Installing from a project's declarations preserves its source references and ranges, including legacy local-path records. Named dependency updates respect retained parent packages' constraints; jointly updated or replaced parents use their new dependencies. Local sources stay local and resolve relative to the project root; older URL records remain usable. Manifest installs retain compatible registry locks. Dependency changes, including local replacements, respect retained parents and recorded ranges; incompatible existing records are refused before writes. The old computer/browser pair has one joint-upgrade command, and obsolete project lock conflicts explain explicit removal. Cache reuse checks source identity and compatibility, including identical-version switches from development copies or another registry. Cleanup refuses the working directory, its ancestors, the home directory and filesystem roots. Registry mirrors are recognized by identical archive checksums; implicit lock restore refuses different or missing content until you explicitly update or select a source. Source selection updates project declarations and dependencies together. Automatic installation respects development/disabled choices and pinned ranges; updates preserve enabled state and select versions compatible with the current platform. Capability recovery refreshes an already installed provider and restores missing selected cache files without dropping owner settings. Recovery commands retain saved ranges; unnamed development dependencies and unavailable project locks refuse before writes, and missing-cache lock restoration checks its archive checksum. Automatic recovery validates existing registry content in every scope, while explicit updates keep their selection authority. Dependency recovery names compatible joint commands, registry read failures preserve their real cause, and ready installed capabilities remain available before installation-policy gates without repeated change notifications. Recovery commands stay limited to the related installed packages, including with obsolete lock entries or a stray lock. First-use installation of a new provider applies the same protection to already selected shared dependencies.

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
