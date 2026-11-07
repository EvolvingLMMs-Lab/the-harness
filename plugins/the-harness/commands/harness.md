---
description: Do a task on this computer, in a browser or in a game with The Harness
argument-hint: <task in plain words>
---

Do this task with The Harness, following the act-with-the-harness skill: $ARGUMENTS

Call the harness MCP tool `run_task` with the task. If it returns before the answer, poll
`get_session` until the session has answered or ended, then report the answer (and any
files) to the user. If it waits for approval, tell the user to approve it in The Harness.
