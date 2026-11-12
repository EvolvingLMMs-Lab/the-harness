---
title: "Use the Python API"
description: "Start and steer sessions, read their traces as they are written, manage packages, and run an episode in your own process."
---

Everything the app and the CLI do is available from Python. There are three entry
points:

| Module | For |
|---|---|
| `harness.host` | sessions of the session host, shared with every other frontend |
| `harness.packages` | installing and listing packages |
| `harness.sdk` | the interface packages build on: skills, `ClosedLoop`, events, workers |

## Sessions

```python
from harness.host import Host

host = Host.connect()                        # starts the session host when it does not run
conversation = host.start(
    experiment="computer",
    workspace="browser",
    instruction="Find the opening hours of the city library.",
)

for record in conversation.records():        # the trace's records, as they are written
    if record["event"] == "agent_message":
        print("agent:", record["text"])
    if record["event"] == "turn_result":     # the turn is over: an answer, a limit or an error
        break

conversation.send_message("And on Sundays?")   # the same conversation goes on
conversation.close()
```

`host.start` takes `experiment`, `task`, `seed`,
`model`, `workspace`, `instruction`, `confirmation` (ask before each program), `sets`
(`--set` items) and `title`. It returns a conversation with:

| Method | |
|---|---|
| `send_message(text)` | a message for the agent, which gets it at once; after a turn it starts the next one |
| `pause()`, `resume()` | stop at the next step, go on |
| `cancel()` | end the turn that runs; the conversation waits for the next message |
| `confirm(accept, reason="", remember=None)` | answer what it waits for: a program, or the mouse and keyboard (`remember`: `once`, `app`, `session`, `always`) |
| `close()` | end the conversation |
| `records()` | the trace's records, old ones first, then new ones as they come |
| `describe()` | its session: status, what it waits for, its agents |
| `memory()` | what it remembers: this run's entries (what it saw and where) and its library's, in one format |

The host lists and steers every session, whichever frontend started it:

```python
for session in host.sessions():
    print(session.id, session.status, [agent["id"] for agent in session.agents()])

host.approve("3f9a")                          # what an agent of the session waits for
host.stop_session("3f9a")
host.conversation("3f9a/a1").send_message("Use the other account.")   # one of its agents
```

Each record is a dictionary with `seq`, `time`, `event` and the fields of its kind;
[Events and traces](/docs/reference/traces/) lists them all.

## Packages

```python
from harness import packages

packages.install(["workspace"])          # and what it depends on
packages.installed()                     # [{name, version, source, provides, ...}]
packages.search("robot")
packages.info("browser")
packages.update()
packages.remove(["workspace"])
```

The same as `harness install`, `harness list` and the other package commands
([Packages](/docs/configure/packages/)).

## An episode in your own process

To embed the agent in a program of your own, without the session host, run a
conversation in your process:

```python
from pathlib import Path

from harness.runtime.task.run import TaskRun
from harness_eval.run import load_task_config

config = load_task_config("my-experiment.toml", task="play", seeds=[0])
conversation = TaskRun(config, 0, Path("runs/mine/seed-0"), interactive=True)
conversation.trace.subscribe(print)      # every record as it is written
conversation.start()                     # the episode runs on a thread of its own
conversation.send_message("Collect the coins first.")
conversation.close()
```

The episode ends with your process.

## For packages: harness.sdk

Code inside a package imports The Harness only through `harness.sdk`: the session and
skill conventions, `ClosedLoop`, events and traces, embodiments and benches, service
clients, settings and paths. It changes incompatibly only with a new major version.
[Write a skill](/docs/extend/skills/) and [Write a package](/docs/extend/packages/) show
it in use, and the [Python API reference](/docs/reference/api/) documents every module.
