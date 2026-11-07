---
name: act-with-the-harness
description: Do a task on this computer's desktop and applications, in a web browser, or in a game through The Harness, which sees the screen and acts with its own agent. Use when the user asks to operate an application or a website, fill a form, click through a GUI, or play or test a game, and not for editing code in this repository.
---

# Act with The Harness

The Harness is an agent that acts: it sees a screen and controls a desktop, a browser or a
game, thinking while it acts. Its MCP server (`harness`) gives you its sessions as tools.

## Do a task

1. Call `run_task` with the task in plain words, as the user would say it, plus what to
   report back. Name a `workspace` only when the task needs one: `browser` (a background
   browser), `desktop`, `apps` or `display`. Otherwise The Harness chooses.
2. `run_task` waits at most `wait_seconds` (up to 120). A short task comes back with its
   `answer`. A longer one comes back with its `session` and progress; poll it with
   `get_session` every half minute or so, and look at it with `observe_screen` when its
   progress is unclear.
3. To change course, use `send_message` with the session and what to do instead. To give
   up, use `stop_session`.
4. Report the answer to the user, and say where the files are if it made any.

## Approvals

The Harness asks before it uses the user's real mouse and keyboard, before a step that
touches credentials, a payment, sending, deleting or cannot be undone, or before each program
when the user set "ask before acting". When `get_session` says a session waits for
approval, tell the user to approve it in The Harness: in its app, or with /approve in its
terminal chat (`harness`; /sessions picks the session). Never approve it yourself; there is
no tool for it.

## When it is not there

If the `harness` tools are missing, the user needs The Harness and its MCP server package:
`pip install the-harness`, `harness install mcp-server`, and a model set up once by
running `harness`.
