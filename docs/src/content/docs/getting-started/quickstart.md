---
title: "Quickstart"
description: "From install to a finished task on your own computer: connect a model, give a task, add a message while it works, and replay it."
---

This page takes you from a fresh install to a finished task. The agent works in a
background browser of its own, which you choose when the conversation starts, and never
touches your mouse, keyboard or windows. You need Python 3.11 or newer, Google Chrome, and a model: Claude Code, Codex, Gemini CLI, Grok or another agent signed in
on this computer (it runs under your own plan, no key), a key for a model provider, or a
model on this computer. [Models and providers](/docs/configure/models/) lists them all.

## 1. Install and connect a model

```bash
npm install -g @lmmslab/harness   # or: pip install the-harness
harness
```

The first run looks at what is on this computer and lists what can be the model:

```text
Welcome to The Harness

Which model should it use?
> 1. Claude Code    signed in · uses your Claude plan, no key needed
  2. OpenRouter     key found in the environment (OPENROUTER_API_KEY)
  3. Codex          not installed · npm install -g @openai/codex, then run codex login
  4. Gemini CLI     not installed · npm install -g @google/gemini-cli, then run gemini and sign in with Google
  5. Grok           not installed · npm install -g @xai-official/grok, then run grok and sign in
  6. More agents…   GitHub Copilot, Cursor, Qwen Code, OpenCode and the others of the ACP Registry
  7. Enter a key for a provider…
  ↑ ↓ to move · Enter to choose · Esc to leave
```

Press Enter on one that was found, choose **More agents…** for any other agent of the ACP
Registry, or choose **Enter a key for a provider…** and paste a key. An agent that is not on
this computer is listed with how to install and sign in to it. The Harness asks the source for one word, keeps it only when it answers, and says
what went wrong when it does not. An agent then asks which of its models to use (Enter keeps the one it is set to);
`/model` changes the model later and `/effort` how hard it thinks. A key that works is kept in `~/.harness/config.toml`,
also when it was found in your shell's environment, so that the agent can use it when it
starts with the computer. Everything else keeps its default; `harness setup` runs this
again and `harness model` changes the model only.

Then the conversation opens. The task below is on a web page, which the agent reads as
text and looks at when it needs to; a model that reads images can do both.

## 2. Give it a task

Type:

```text
Go to python.org and find the newest stable Python release. Tell me its version
and the date it was released.
```

Every new conversation first asks where it should work: no environment (conversation
only), a project folder, a background browser, your applications in the background, your
desktop or a separate display. Choose **Background browser**. Your last choice is
highlighted the next time, so Enter takes it. The first time, The Harness installs the
`browser` package and its environment, which takes a moment; later tasks start at once.

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
**Esc**: the turn stops, what it did so far stands, and your next message goes on from
there. To change the task, just say so.
[Interrupt and take over](/docs/use/interrupt/) has the details.

When it is done, it answers. The answer ends its turn, not the conversation: it waits for
your next message and keeps what it has. Type another task, or press **Ctrl+C** twice to
leave; the conversation stays in the session host until you end it with `/end`, and
`harness --continue` comes back to it later.

## 4. One task, from a script

```bash
harness run "What is the newest stable Python release? Answer with its version only." -p --workspace browser
```

`harness run` does one task and ends; a script names where it works with `--workspace`
(nobody is there to ask); `-p` prints only the answer, and `--json` prints
every event as a JSON line. [Run from the CLI](/docs/use/cli/) has more.

## 5. Replay the run

Use `harness replay RUN` for terminal records or add `--json` for original events.

## Next

- [Use the terminal](/docs/use/terminal/): keys, sessions and sub-agents in the terminal.
- [Let it learn an environment](/docs/learn/learn-an-environment/): have the agent learn
  an app or a game before it works in it.
- [Permissions and privacy](/docs/configure/permissions/): before you let the agent use
  your own desktop.
