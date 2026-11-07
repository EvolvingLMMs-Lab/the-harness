---
name: follow-harness-sessions
description: Look at, steer or stop what The Harness is doing in its sessions, read a session's timeline, or see what it learned. Use when the user asks what The Harness is doing, how a task it runs is going, or what its library holds.
---

# Follow The Harness's sessions

- `list_sessions` lists the sessions that run, or with `all` those that ended too. Each
  has its status, what it waits for, and its agents (sub-agents included).
- `get_session` gives one session's status, its answer if it has one, and its last
  progress lines. `observe_screen` shows its screen now.
- `read_events` gives its timeline as records: the model's replies, the programs it ran,
  skills' steps, guards and reflexes, sub-agents. Page with `after` and `next_after`.
  Summarize for the user; don't paste records.
- `send_message` tells a session something: a correction, an answer to its question, more
  to do. `stop_session` ends it.
- `list_library` lists what The Harness learned (notes, memory, skills and reactive rules,
  each with its evidence). `list_packages` and `install_package` show and add what it can
  do (official packages by name).

When a session waits for approval, the user approves it in The Harness itself (its app, or
/approve in its terminal chat, where /sessions picks the session), never through these tools.
