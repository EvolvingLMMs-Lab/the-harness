---
title: "Permissions and privacy"
description: "When the agent may use your real mouse and keyboard, what it learns about your windows, what it sends to the model provider, and where your data is kept."
---

An agent that works on your own computer can reach your apps, accounts and files. The
settings on this page decide how far it goes. Each is graded: a level for everything,
and rules that set another level for one app, window, kind of action, session or agent.
They are kept in `~/.harness/config.toml`; the app has them under **Settings → Mouse
and keyboard** and **Settings → Permissions and limits**.

Before the first desktop or background-application task, choose the mouse/keyboard and
other-window information levels explicitly. There is no accepted-by-default answer;
cancelling leaves the task unstarted. Existing saved choices and explicit per-task flags
are respected. Screen recording is off by default and is not a first-use question. Enable it explicitly when recording a demo for replay.

## Mouse and keyboard

In **desktop** mode, the agent observes screenshots and uses your real mouse and keyboard.
It has no background window, element, or browser tools. The input policy below still applies.

In **apps** mode, a step reaches a window in one of three ways, tried in order:

1. **Semantic**: through the window's accessibility tree, such as pressing a button or
   setting a field's value.
2. **Targeted**: input sent to that window only, or to a browser it launched.
3. **Physical**: your real mouse and keyboard.

The first two leave your mouse, keyboard and focus alone. The **physical-input level**
decides when the third may be used. A background browser and a display of its own
never need it.

| Level | In the app | |
|---|---|---|
| `never` | Don't | a step that needs it is refused, and the agent is told why |
| `ask_each` | Ask me every time | ask before every step |
| `ask_once_app` | Ask me the first time in each app | ask the first time in each app, in this session |
| `ask_once_session` | Ask me once per chat | ask the first time in this session |
| `when_idle` | Only while I'm away | only after you left the computer alone for a moment, and stop the moment you touch it |
| `allow` | Go ahead | allowed, still in turn with other agents and still giving way to you |

### Rules

A rule sets the level for part of the computer, by app (its process name, a glob works),
window title, kind of action (`pointer`, `drag`, `keyboard`, `clipboard`, `foreground`),
session or agent. The most specific rule that matches wins.

```toml
# ~/.harness/config.toml
[physical]
level = "ask_once_app"

[[physical.rules]]
level = "never"
app = "wechat"

[[physical.rules]]
level = "never"
app = "bank*"

[[physical.rules]]
level = "when_idle"
app = "figma"
action = "drag"
idle_seconds = 10

[[physical.rules]]
level = "ask_each"
action = "clipboard"
```

When the level asks, the step waits and the session asks you: the app, the window and
what the agent wants to do there. Your answer can be kept for this step, this app in
this session, every app in this session, or always (a rule in your settings).

### Change it

`/settings` in `harness`, **Settings → Mouse and keyboard** in the app, or
`config.toml` by hand: the workers read the level and the rules each time they change.
An experiment of the eval package takes them for one run (`harness run EXPERIMENT
--physical LEVEL`, with `--allow-app`, `--ask-app` and `--deny-app` adding rules after
yours).

### You come first

| Setting | Default | |
|---|---|---|
| `physical.yield_on_user_input` | on | a step waits while you use the computer |
| `physical.idle_seconds` | 2 | how long you leave the computer alone before `when_idle` acts |
| `physical.max_hold_seconds` | 3 | how long one agent keeps the mouse and keyboard before the next in line |
| `physical.corner_stop` | on | pushing the pointer into a corner of the screen stops the agent |

## Another environment

A conversation starts in the environment you chose. When a step cannot be done there,
the agent may ask to take another one into the same conversation: a project task that
must see how its page renders takes the browser or your desktop; a desktop task that
must run a command takes a project folder. It says why, and the question shows that
reason:

```text
it wants to do something that waits for you (another environment): use Your desktop
    why: to check how the changed page renders
```

`environments.attach` is the level for every kind, and a rule sets another level for
one kind:

| Level | |
|---|---|
| `never` | refused; the agent goes on in its own environment and says what it could not confirm |
| `ask_each` | ask every time |
| `ask_once_session` (default) | ask the first time for each kind in a conversation |
| `allow` | taken without asking |

```toml
[environments]
attach = "ask_once_session"

[[environments.rules]]
level = "never"
kind = "desktop"
```

- If you skip confirmations (`physical.level = "allow"`, in your settings or for one
  run with `--physical allow`), it does not ask. A `never` level still refuses.
- Whether it asked or not, each attachment, its reason and how it was allowed are shown
  in the conversation, drawn on the timeline and written to the trace.
- Where nobody can be asked (a script, the Python API) and the level asks, the request
  is refused with the reason. It never waits and is never allowed silently.
- Taking your desktop does not grant your mouse and keyboard: each step with them is
  still decided by the physical-input level above.
- An attached environment counts against the same workspace limits and is given back
  when the agent releases it or the conversation ends.

## What it learns about your windows

To find its way, the model may be told about windows the agent did not open itself. The
**window details** level decides how much:

| Level | The model learns |
|---|---|
| `none` | nothing about your windows |
| `presence` | that other windows are there |
| `apps` | which apps they belong to |
| `titles` | their titles |

```toml
[privacy]
level = "apps"

[[privacy.rules]]
level = "none"
app = "bank*"
```

`/settings` in `harness` or **Settings** in the app changes the level and its rules.

## Approvals

Workers and tool adapters flag sensitive operations involving credentials, payment,
sending, deletion or another irreversible effect. A browser page's address alone does
not make navigation sensitive. The user can approve one request when the host owns the
operation. A sensitive refusal from an ordinary worker ends that step. Unattended runs
refuse sensitive operations.

With `approvals.ask = "programs"`, programs also require approval. **Ask before acting**
next to the app's chat input sets that policy for one conversation. A rejected operation
does not run, and the agent reads your reason.

Claude Code and Codex sub-agents can work with files in their own workspace. Their file
operations use the parent conversation's approval policy. Shells and external connectors
are unavailable to those sub-agents.

## Limits

**Settings → Permissions and limits** caps what a conversation may spend: steps per task,
minutes per conversation, and how many levels of sub-agents it may start. There is no
dollar limit: only OpenRouter reports what a call cost.
Sub-agents spend from their parent's budget ([sessions](/docs/use/sessions/#budgets)).

## What leaves your computer

Every screenshot the agent takes goes to the model provider with its request, so
anything on the screen is seen by the provider. Close what a task does not need, or give
the agent a background browser or a display of its own. Nothing else is sent anywhere:
conversations, screenshots, settings and keys stay on this computer.

| Where | What |
|---|---|
| `~/.harness/conversations/` | each conversation: its trace, screenshots and title |
| `~/.harness/config.toml` | your model, keys, settings and rules, readable by you only |
| `~/.harness/host/` | the session host's address and key, readable by you only |

**Settings → Data** shows the size of your conversations, exports one, deletes those
older than some days, or deletes all.

## Programs run in isolation

The agent's programs run in a separate process that reads only Python and The Harness
itself, writes only a fresh working folder, starts no processes and connects only to the
services its skills use; your home folder is out of its reach. These checks keep
programs away from your data; they are not a sandbox against deliberate escape. A skill or a package you
install runs with your access, which is why The Harness asks before installing one from
outside the official registry ([Packages](/docs/configure/packages/#trust)).

### Isolated workspaces

Use `--managed-workspace` in the terminal or the App's isolated workspace option on an unprivileged Linux host with system Python, Bubblewrap, and libseccomp. This mode uses a dedicated display or browser, has no external network access, and exposes a limited set of synchronous skill calls. If startup or the worker handshake fails, the conversation reports the failure. A sensitive refusal from a regular external worker stays terminal.

A deployment may set `HARNESS_BWRAP` to an absolute path outside the system installation. The executable and its parent directories must be owned by root or the host account and writable only by their owner. The existing `HARNESS_CHROME_PATH` and `HARNESS_XVFB` overrides select the workspace browser and display server.

After a lost receipt the host only queries the original result. If it cannot recover it, the outcome stays unknown.
