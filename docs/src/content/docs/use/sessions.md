---
title: "Work with sessions and sub-agents"
description: "Several conversations at once from every frontend, sub-agents that split a task, approvals from anywhere, and budgets that hold for the whole tree."
---

A **session** is one conversation with the agent: your task, its trace and its
workspace. Many run at once on one computer. Each session is a tree: its main agent and
the **sub-agents** an agent starts to work on parts of the task at the same time. Every
frontend (the terminal, the app, Python) starts, lists, joins, approves and ends the
same sessions.

## External coding sessions

Enable the `external-agents` package and configure a trusted adapter. A session you start
from the terminal or Python appears in the same project list and trace.

```sh
harness agents update
harness agents ls
harness agents install ACP_REGISTRY_ID
harness run "Inspect this repository" --agent acp:ACP_REGISTRY_ID --folder . --isolation worktree
harness sessions ls --all --kind acp --project .
```

Use `harness agents add NAME -- COMMAND ARGS` for a local ACP server and
`harness agents add --terminal NAME -- COMMAND ARGS` for a CLI with terminal input.
The Registry listing separates the saved catalog, platform support and local installation.
ACP operations depend on the agent's v1 handshake and configuration options. The agent's
own authentication and process permissions apply. An optional `--share-mcp-tool project_info`
or `--share-mcp-tool project_diff` grants that read-only tool to one ACP session for up to
30 minutes. A worktree separates changes in Git.

Use `harness sessions import claude-code PATH.jsonl` or
`harness sessions import codex PATH.jsonl` for a selected transcript. Add `--follow` to
observe appended records. `harness sessions reconnect ID --agent ACP_ADAPTER --released`
attempts to continue the original native ID after its previous controller exits. The
adapter must support the original session and directory. `harness sessions handoff ID AGENT
"context to send"` instead starts another conversation linked to the original. Review the
context you send, particularly when the destination runs in the cloud.
For ACP adapters that expose discovery, select an ID from `harness sessions discover
ACP_ADAPTER --folder .` and index it with `harness sessions observe ACP_ADAPTER
EXTERNAL_ID --folder .` before attempting recovery.

For a managed worktree, use `harness sessions diff ID` to review changes. Close the session
and commit its changes before using `harness sessions merge ID`. This fast-forwards the
original, clean branch. `harness sessions discard ID` removes the managed worktree,
including its uncommitted files.

Cloud adapters are configured with `harness agents configure-cloud PROVIDER SETTINGS.json`.
The account scope, repository and ref or environment live in the settings file. The
credential comes from the named environment variable or Harness credential store.
`harness sessions discover cloud:PROVIDER` lists accessible native IDs, and
`harness sessions observe cloud:PROVIDER EXTERNAL_ID` attaches in read-only mode.
Cloud operations vary by provider. The seven adapters are experimental pending live review.

## The session host

One background process per user, the **session host**, runs the sessions of every
frontend. The first frontend that needs it starts it by itself. It listens on this
computer only, with a new key each time, and exits once no session is open and nothing
has asked it for anything for 30 minutes. Closing a terminal or a browser tab does not
end a session.

In `harness`, `/host` shows whether the host runs, its address, process, version and
open sessions; `/host stop` makes it exit and ends the sessions open in it.

## See and steer sessions

In `harness`, `/sessions` lists the sessions that run, each agent under its session,
with its status and what it spent; pick one to switch to it and talk to it. There:

| Command | |
|---|---|
| `/approve`, `/reject [why]` | answer what its agent waits for |
| `/pause`, `/continue` | stop at the next step, go on |
| `/end` | end it |
| `/resume` | an earlier conversation; one that ended goes on in its own session |

The status of each agent is running, idle (its turn is over), paused, finished, or what
it waits for: your approval of a step, your approval of the mouse and keyboard, a
message, a free workspace or its turn at the mouse and keyboard. The spent column counts
each agent's model calls. The app's sidebar shows the same tree
([Use the terminal](/docs/use/terminal/)).

## Turns, and going on later

A conversation is made of turns. A turn starts with your message (or, without one, with
the end of something the agent left running, or an event) and ends with the agent's
answer. After it the conversation is idle and keeps everything: its messages, the
variables of its programs, its rules, its facts and the environment. Nothing but you (a
new conversation, `/end`, closing it) or the host stopping ends it.

A turn has limits of its own: the model calls and the time it may use begin anew with
every turn. A turn that reaches one ends with that reason, and your next message goes
on. Cost is counted for the whole conversation.

Sessions are kept on disk as they go. One that ended, because the host stopped, the
computer restarted or you ended it, is continued in its own session id:

```bash
harness --continue              # the last user message or resume, in the terminal chat
harness --resume 3f9a           # that session (harness sessions ls --all lists them)
harness run --continue "And on Sundays?"       # one more turn, then it ends
harness run --session 3f9a "And on Sundays?"
```

`/resume` in the chat and `harness sessions resume ID` do the same. The messages and the
facts are restored and a new kernel starts. What lived in the old process (the variables
of its programs, its rules, the programs that still ran) is gone; the agent is told so
with your next message and sets up again what it needs.

## Side by side

Each session works in a workspace of its own. `workspaces` under `[computer]` in
`config.toml` (or **Settings → Computer**) sets how many work at once, four by default,
and `displays` how many of them may be displays of their own, two by default. Beyond that, a new session parks the session that has waited longest for you
(its workspace is given up, and your next message to it continues it), or waits until one ends.

Background browsers and displays of their own never use your mouse and keyboard, so
they run side by side freely. Sessions that need the real mouse and keyboard take them
in turn, one step at a time, and give them up the moment you touch them. Each agent
works only in windows of its own: a window one agent works in is refused to the others.

## Approvals

What an agent waits for can be answered from any frontend: the card in the app, the
choices above the input in `harness` (or `/approve` after `/sessions`), or
`host.approve()` in Python. An agent waits for:

- **a sensitive step**, always: one that names credentials, a payment, sending, deleting
  or something that cannot be undone. The answer covers that step only;
- **a program**, when `approvals.ask` is `programs` (**Ask before acting** in the app);
- **the mouse and keyboard**, when your permissions ask first. The answer can be kept:
  this step, this app for this session, every app for this session, or always;
- **a message**, when the agent asked you something.

[Permissions](/docs/configure/permissions/#approvals) has the details.

A sub-agent's question goes to the agent that started it, which answers it or asks you.

## Sub-agents

An agent can hand parts of its task to sub-agents that work at the same time, each in a
workspace of its own, and wait for their results. Sub-agents are off by default: one
agent does the task and takes another environment itself when a step needs one. Switch
them on when a task splits into parts that can run at the same time:

- for every new conversation: `session.agents = "on"` in the settings;
- for one conversation: `--agents` on the command line, `/agents` in the terminal, the
  **Sub-agents** switch in the app's composer, `runtime={"agents": True}` in Python;
- when the agent asks: it may request them, saying why, and they load once you agree.

**Settings → Permissions and limits → Sub-agent levels** sets how deep they go once on:
0 none, 1 (the default) the conversation's agent starts sub-agents and they start
none, 2 theirs may start sub-agents too.

The agent does this from its programs:

| Call | |
|---|---|
| `delegate(task, workspace="new", budget=None, model=None)` | start a sub-agent with a task of its own; returns its id |
| `wait_agents(ids=None, timeout=None)` | wait until each has ended or asks something; returns each one's status, result, question and spending |
| `send_agent(id, text)` | answer its question, or give it more to do |
| `cancel_agent(id)` | stop it; returns its report |

- **Workspace**: `"new"` is a new workspace of the parent's kind, `"browser"` or
  `"desktop"` a new one of that kind, and `"share"` hands over the windows the parent
  holds while the parent waits.
- **Model**: another model of the same provider, for a cheaper or a stronger sub-agent.
- A sub-agent does not see its parent's conversation, only its own task. It ends when it
  finishes, runs out of budget or is cancelled, and reports its result.

## Budgets

A session has limits on model calls and minutes (**Settings → Permissions and limits**).
An experiment's `[budget]` can also cap dollars (`max_cost_usd`), counted only where the
provider reports a cost (OpenRouter). A sub-agent's budget, `{"calls", "cost",
"seconds"}`, is at most what its parent has left, and what it spends is charged to its
parent as it spends it, up the tree to the session. A session never spends more than its
limits, however many agents it has.

## From Python

```python
from harness.host import Host

host = Host.connect()                       # starts the host when it does not run
conversation = host.start(experiment="computer", workspace="display",
                          instruction="Find the cheapest train to Boston on Friday.")
for record in conversation.records():       # the trace's records as they are written
    print(record["event"])
    if record["event"] == "outcome":
        break
host.stop_session(conversation.session)
```

`conversation` has `send_message`, `pause`, `resume`, `confirm` and `close`;
`host.sessions()` lists the open sessions and `session.agents()` their agents.
[Use the Python API](/docs/extend/python-api/) has more.

## Where it is kept

| Where | What |
|---|---|
| `~/.harness/conversations/` | every conversation: trace, screenshots, one folder per sub-agent |
| `~/.harness/host/` | the running host's address and key (yours only), and the sessions that ended |
