---
title: "Run from the CLI"
description: "The harness command: a first message, print mode, status, doctor, config, sessions and logs; one task with harness run; conversations driven by another program with harness run rpc."
---

`harness` is for talking with the agent, and the same command looks after it: what it is
connected to, its settings, its chats, its logs. To use the task engine from a script or
another program, `harness run` and `harness run rpc` work without a conversation on screen.

## The everyday commands

```bash
harness                              # the chat
harness "explain this folder"        # the chat, started with that message
harness -p "what changed today?"     # answer and exit
git diff | harness -p "review this"  # what is piped in goes with the question
harness -c                           # go on with the most recent chat
harness -r "trip notes"              # go on with a chat, by its id or title; -r alone lists them
```

A word that is no command is the chat's first message. One word that is close to a command
is taken for a slip: `harness udpate` prints `Did you mean harness update?` and ends with
status 2, starting nothing. `harness --help` lists the commands on one screen, and
`harness COMMAND --help` describes one.

`-p` (`--print`) answers without the chat on screen: the agent identity takes the question
in a chat of its own (`-c`: in its most recent chat, `-r CHAT`: in that one), and the
command ends when its turn is over, with status 0 when it answered. `--output-format` is
`text` (the answer), `json` (one object: `result`, `is_error`, `session_id`, `identity`) or
`stream-json` (every record of the turn as a line, then that object). `--model ENTRY` uses
another model of the model list for that chat. Ctrl+C stops the turn.

| Command | |
|---|---|
| `harness status` | version, model, identity, session host and what is connected, on one screen (`--json`) |
| `harness doctor` | what is missing on this computer, each line with its fix: Python, the model and its key or sign-in, whether the session host starts, packages that were left out, which `harness` this terminal runs. Exit status 0 when nothing is missing, 1 otherwise (`--json`) |
| `harness setup`, `harness model` | the first run again; the model only |
| `harness config show \| get KEY \| set KEY VALUE \| unset KEY \| edit \| path` | the settings, each named `section.key` ([Settings](/docs/reference/settings/)); `--identity ID` reads and writes an agent identity's own value; a provider's key is set by its variable's name (`harness config set OPENROUTER_API_KEY ...`) and kept with the credentials |
| `harness sessions` | the identity's chats: `list` (`-q TEXT`, `--archived`), `new`, `rename CHAT TITLE`, `pin`, `archive`, `delete`; and the sessions of tasks (`ls`, `show`, `stop`, `resume`, ...) |
| `harness logs [NAME] [-n N] [-f]` | the last lines of a log (default: the session host's); `harness logs list` shows the logs there are |
| `harness host [status \| start \| stop \| restart \| install \| uninstall]` | the session host: how it runs, start or stop it, start it at login |
| `harness usage`, `harness calendar`, `harness agent`, `harness library` | an identity's spending, calendar, the identities themselves and what one learned ([Identities](/docs/use/identities/), [Spending](/docs/use/spending/)) |
| `harness channels`, `harness mcp`, `harness agents`, `harness skills` | what it is connected to; each takes `list`, `add`, `remove` and `test` ([Connect MCP servers and Agent Skills](/docs/extend/mcp/)) |
| `harness update` | update The Harness and the installed packages |
| `harness completion bash \| zsh \| fish` | print a completion script: `harness completion bash >> ~/.bashrc` |

Two commands of packages share a name with these: `harness config EXPERIMENT` is the
evaluation package's (an experiment's resolved configuration), and `harness status` with
service names or `--deploy` is the `local-models` package's (the services of a deploy).

Put options after their command: `harness run "task" --model MODEL`. A continuation, in either the terminal or `harness run`, keeps its saved model, workspace and run settings; omit new-conversation options such as `--model`, `--effort` and `--folder`. In an open terminal, `/effort LEVEL` changes that conversation; `/model` selects only new ones. Restarting an ended session requires its saved model entry to remain enabled. The terminal's `--agent` also rejects `--model` and `--effort`; an external agent task can use `harness run "task" --agent NAME --effort LEVEL`.

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
| `--continue`, `--session ID` | the task is one more turn of the session you last messaged or resumed, or of the one named, with its messages and facts ([Turns, and going on later](/docs/use/sessions/#turns-and-going-on-later)) |
| `--workspace none\|project\|browser\|desktop\|apps\|display` | where it works: `none` is conversation only (the model and your connected tools, nothing started); `project` works in `--folder`. Without it and without `--folder`, the setting `session.environment` decides: in a terminal it asks on stderr, with your last choice highlighted, also when the answer goes to a pipe (`answer=$(harness run "task" -p)`); without a terminal, or with `--json`, `ask` is an error that names this option, and nothing is chosen for you |
| `--folder PATH` | the folder of a project task |
| `--space ADDRESS` | work in the space at this address (a `ws://` or `http://` URL of any space that speaks the Agent Space Protocol; `--workspace space`): the agent acts through its vocabulary ([Spaces](/docs/concepts/spaces/)) |
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

The model must be set up first: run `harness` once in a terminal (or `harness setup`).

## A conversation from another program: harness run rpc

RPC starts a new conversation and rejects `--continue` and `--session`; use the single-task `harness run` form to continue an existing one. Background events do not change the implicit continuation target; scripts can select it explicitly with `--session ID`.

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
