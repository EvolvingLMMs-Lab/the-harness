---
title: "Run from the CLI"
description: "Do one task from a script with harness run, read its answer or its events as JSON, and drive conversations from another program with harness run rpc."
---

`harness` is for talking with the agent. To use it from a script or another program,
two commands do the same without a conversation on screen.

## One task: harness run

```bash
harness run "Rename the photos in ~/Pictures/trip by the date they were taken."
```

`harness run "task"` gives the agent the task, prints the conversation as it goes, and
ends with the agent's turn: once it has answered, or a limit or an error ended the turn.
Its exit status is 0 when it answered, 1 when it
ended in an error or without an answer, 2 on a usage error (including no model set up
and no terminal to ask in), and 130 on Ctrl-C.

| Option | |
|---|---|
| `-p`, `--print` | print only the agent's answer |
| `--json` | print every record of the run's trace as a JSON line, as it is written |
| `--continue`, `--session ID` | the task is one more turn of the most recent session, or of the one named, with its messages and facts ([Turns, and going on later](/docs/use/sessions/#turns-and-going-on-later)) |
| `--workspace none\|project\|browser\|desktop\|apps\|display` | where it works: `none` is conversation only (the model and your connected tools, nothing started); `project` works in `--folder`. Without it and without `--folder`, the setting `session.environment` decides: in a terminal it asks on stderr, with your last choice highlighted, also when the answer goes to a pipe (`answer=$(harness run "task" -p)`); without a terminal, or with `--json`, `ask` is an error that names this option, and nothing is chosen for you |
| `--folder PATH` | the folder of a project task |
| `--agents` | sub-agents on for this conversation (they are off unless `session.agents` is `on`) |

```bash
version=$(harness run "What is the newest stable Python release? Answer with the version only." -p)
harness run "Summarize the open issues of github.com/EvolvingLMMs-Lab/the-harness." --json > events.jsonl
```

Each JSON line is a trace record, with `seq`, `time`, `event` and the fields of its kind:
the model's requests and replies, each program and its result, each skill call, the
agent's messages, the state changes. [Events and traces](/docs/reference/traces/) lists
them all. The run is kept like any conversation, under `~/.harness/conversations/`, so
`harness replay` can show it again.

When a step waits for you (a sensitive step, your mouse and keyboard, or every program
under `approvals.ask = "programs"`), `harness run` asks in the terminal, `Allow it?
[y/N]`; without a terminal it declines, with the reason, and the agent reads it.

The model must be set up first: run `harness` once in a terminal, or export the
provider's key.

## A conversation from another program: harness run rpc

```bash
harness run rpc
```

`harness run rpc` runs one conversation driven by JSON lines on its standard input, and
writes its records as JSON lines on its standard output. It ends when its input closes
or the conversation ends.

| In (one JSON object a line) | |
|---|---|
| `{"type": "prompt", "text": "...", "files": ["..."]}` | the first starts the conversation; later ones are messages to it (after a turn's `turn_result` record, a message starts its next turn); `files` (optional): paths it attaches |
| `{"type": "message", "text": "...", "files": ["..."]}` | a message for the agent, which gets it at once |
| `{"type": "pause"}`, `{"type": "continue"}` | stop at the next step, go on |
| `{"type": "approve", "remember": "app"}` | approve what it waits for; for your mouse and keyboard, `remember` (optional) keeps the answer: `once`, `app`, `session` or `always` |
| `{"type": "reject", "reason": "..."}` | reject it, saying why (optional) |
| `{"type": "confirm", "accept": true, "reason": "", "remember": "app"}` | approve or reject, as above |
| `{"type": "end"}`, `{"type": "stop"}` | end the conversation |

These are the commands of the terminal chat (`/pause`, `/continue`, `/approve [app | session | always]`,
`/reject [why]`, `/end`), and do the same.

A sub-agent approval includes an `agent` and a `request_id`. Copy both fields into its `approve`, `reject` or `confirm` reply. A main-agent reply can also carry the request ID from its waiting state record.

| Out | |
|---|---|
| `{"type": "started", "run": "..."}` | the conversation started |
| `{"type": "waiting", "agent": "a1", "what": "...", "request_id": "..."}` | a sub-agent waits for approval |
| `{"type": "record", "record": {...}}` | a record of its trace |
| `{"type": "error", "message": "..."}` | a line it could not take |

A small driver in Python:

```python
import json
import subprocess

agent = subprocess.Popen(["harness", "run", "rpc"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
agent.stdin.write(json.dumps({"type": "prompt", "text": "Find the opening hours of the city library."}) + "\n")
agent.stdin.flush()
for line in agent.stdout:
    message = json.loads(line)
    record = message.get("record", {})
    if record.get("event") == "agent_message":
        print(record["text"])
    if record.get("event") == "turn_result":      # the turn is over; another prompt would go on
        break
agent.stdin.write(json.dumps({"type": "stop"}) + "\n")
agent.stdin.close()
```

To start and steer several sessions, or follow conversations the app and the terminal
started, use [the Python API](/docs/extend/python-api/).

## Benchmarks and sets of tasks

Running the agent over the tasks and seeds of a benchmark, resuming such a run and
scoring it come with the benchmark's package: install a compatible evaluation package, and its README on the [package directory](https://harness.lmms-lab.com/packages/)
describes its commands.
