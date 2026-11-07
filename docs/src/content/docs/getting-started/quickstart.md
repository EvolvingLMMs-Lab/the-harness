---
title: "Quickstart"
description: "From pip install to a finished task on your own computer: connect a model, give a task, add a message while it works, and replay it."
---

This page takes you from a fresh install to a finished task. The agent works in a
background browser of its own, the default workspace, and never touches your mouse,
keyboard or windows. You need Python 3.11 or newer, Google Chrome, and a key for a model
provider. The examples use [OpenRouter](https://openrouter.ai/), where one key reaches
most models; any provider in [Models and providers](/docs/configure/models/) works the
same way.

## 1. Install and connect a model

```bash
pip install the-harness
harness
```

The first run asks three things:

```text
Which model should the agent use? (the key stays in ~/.harness/config.toml, readable by you only)
   1. OpenRouter  (one key for most models)
   ...
Provider [1-11, default 1 OpenRouter]:
Model [deepseek/deepseek-v4.1-flash]:
OPENROUTER_API_KEY:
```

Press Enter to keep the suggestions and paste your key. The Harness checks the key with
the provider, keeps the answers, and opens the conversation. The model must accept
images, since the agent sees the page through screenshots.

## 2. Give it a task

Type:

```text
Go to python.org and find the newest stable Python release. Tell me its version
and the date it was released.
```

A conversation works in a background browser unless you choose another workspace. The first time, The Harness
installs the `browser` package and its environment, which takes a moment; later tasks
start at once.

The conversation fills in as it works. Each line starts with the part of the agent it
comes from: `model` for the model's words and the programs it writes, `e0` for those
programs as they run, `env` for the browser. Press **ctrl+t** to show the timeline above
it: a row for the model and a row for its programs. The model's row has a block for each
call and is empty between calls; when both rows have blocks at once, the model is
thinking about the next step while a program runs.

## 3. Add a message while it works

Before it answers, type:

```text
Also give me the link to the release notes.
```

Your message reaches the model at once. A program that is running goes on, and the
agent takes your message into account in its next step. To stop it instead, press
**Esc** (it pauses at its next step) and type `/continue` to go on; to change the task,
just say so.
[Interrupt and take over](/docs/use/interrupt/) has the details.

When it is done, it answers and waits for your next message. Type another task, or press
**Ctrl+C** twice to leave; the conversation stays in the session host until you end it
with `/end`.

## 4. One task, from a script

```bash
harness run "What is the newest stable Python release? Answer with its version only." -p
```

`harness run` does one task and ends; `-p` prints only the answer, and `--json` prints
every event as a JSON line. [Run from the CLI](/docs/use/cli/) has more.

## 5. Replay the run

Use `harness replay RUN` for terminal records or add `--json` for original events.

## Next

- [Use the terminal](/docs/use/terminal/): keys, sessions and sub-agents in the terminal.
- [Let it learn an environment](/docs/learn/learn-an-environment/): have the agent learn
  an app or a game before it works in it.
- [Permissions and privacy](/docs/configure/permissions/): before you let the agent use
  your own desktop.
