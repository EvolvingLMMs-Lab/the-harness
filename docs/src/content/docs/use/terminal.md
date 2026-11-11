---
title: "Use the terminal"
description: "Talk with the agent in the terminal with harness: the conversation, the keys, the commands, files and shell commands, approvals, sessions and the timeline."
---

```bash
harness
```

`harness` opens a chat with the agent in your terminal, as coding agents' terminals do. It
works over SSH too. The first run asks for the model and its key
([Install](/docs/getting-started/install/#connect-a-model)); nothing starts until you send
your first message.

## The conversation

The conversation is printed into the terminal itself, so it stays in its scrollback, you
can select and copy it, and it is still there after you leave. Under it are the input box
and one status line: what the agent is doing, the model, its workspace and the session.

Type a task and press Enter. Every new conversation first asks where it should work: no
environment (conversation only), a project folder, a background browser, background
applications, your desktop, or a separate display. Your last choice is highlighted and
Enter takes it; a project then asks for its folder, with the current directory filled in
inside a repository. `/environment` shows where the conversation works and chooses for
the next one; `session.environment` in `/settings` can stop the question (`last`, or one
kind). The first desktop/application task also asks about real mouse and keyboard input
and other-window information; computer tasks ask whether to save screen video. Cancel
leaves the task unstarted. Those choices are saved and can be changed with `/settings`.
Project-folder tasks do not ask unrelated desktop questions. `harness --workspace desktop`
(or `none`, `project`, `browser`, `apps`, `display`) names it for this conversation
([CLI workspaces](/docs/use/cli/) describes them).

`--physical` and `--window-details` are explicit choices for one task and do not change
saved preferences. Noninteractive/API calls return `choice_required` when a decision is
missing instead of choosing silently; configure that setting and submit the task again.
Sub-agents cannot enter a computer workspace with unresolved choices.

The conversation shows your messages, the agent's answers (Markdown), its thinking
(dimmed), and each program it ran as one line, `▸ Program 3 · ok · 2.1 s`; **Ctrl+O**
opens the current or latest program's code and output in a temporary details view;
**Ctrl+O** again (or Esc) closes it and restores the compact chat. Details are not appended
permanently to chat history. New chat output received while it is open appears after closing it. A sub-agent's lines
start with its name, in its colour.

A message you send while the agent works reaches it at once; it takes it into account at
its next step ([Interrupt and take over](/docs/use/interrupt/)).

## Keys

| Key | |
|---|---|
| Enter | send |
| Shift+Enter, Ctrl+J | a new line (`\` then Enter too) |
| ↑ ↓ | the messages you sent before |
| Ctrl+R | search them |
| Tab | complete a command or a file |
| Esc | interrupt the agent: it stops at its next step and keeps what it did |
| Esc Esc | clear the input (it stays in the history) |
| Ctrl+C | interrupt the agent; when it is not working, clear the input; twice, leave |
| Ctrl+D twice | leave |
| Ctrl+O | open program details; press again to return to compact chat |
| Ctrl+T | the timeline |
| ? | the keys (on an empty input) |

## Commands

Type `/` and the commands are listed as you type; Tab or Enter takes one.

| Command | |
|---|---|
| `/help` | the commands and keys |
| `/new` | a new conversation; the one shown goes on in the session host |
| `/resume` | pick an earlier conversation and go on with it (one that ended shows what it did; a message starts a new one) |
| `/sessions` | the sessions that run, with their sub-agents; switch to one |
| `/host`, `/host stop` | the session host: its address, process, version and open sessions; `stop` ends it and what runs in it |
| `/environment` | where this conversation works, and the choice for the next one |
| `/agents` | switch sub-agents on: for this conversation, or for the next one before it starts |
| `/model` | the model of the conversation shown (from its next call) and of new ones; type another model id of the provider to use it |
| `/effort LEVEL` | change the current conversation's reasoning effort from its next call |
| `/experiment NAME [TASK [SEED]] [-- instruction]` | start an interactive task on an experiment's worker |
| `/settings` | every setting, those packages add too; Enter changes one |
| `/packages` | the installed packages and the registry's; Enter on one shows what it provides and installs, updates, turns it off or removes it (asked first) |
| `/library` | what the agent learned: each library's entries by kind with their evidence; Enter reads one and its history |
| `/pause`, `/continue` | stop at the next step, go on |
| `/approve [app \| session \| always]`, `/reject [why]` | answer what the agent waits for |
| `/end` | end the conversation |
| `/timeline` | the timeline (Ctrl+T) |
| `/detach`, `/exit` | leave; the conversation goes on |

`/resume`, `/sessions`, `/model`, `/settings`, `/packages`, `/library` and the timeline
open over the whole terminal and close back to the chat (Esc).

## Files and shell commands

- `@` and a path attaches a file to the message (Tab completes the path): the agent gets
  its text, or the picture itself for an image, or the names in a folder.
- `!command` runs the command here, in this directory, shows its output and gives the
  command and its output to the agent.
- `!!command` only runs it.

## Approvals

When a step waits for you (a sensitive step, your mouse and keyboard, or with
`approvals.ask = "programs"` any program: [Permissions](/docs/configure/permissions/#approvals)),
the choices appear above the input box, under what it asks and why:

```text
it wants to click in Scratch (notes.txt - Scratch) with your mouse and keyboard
  why: click the Save button
❯ 1. allow this time
  2. Scratch is fine for this chat
  3. anything is fine for this chat
  4. always allow Scratch
  5. don't allow
```

Press the number, or move with ↑ ↓ and press Enter. "Don't allow" asks for a reason (it
sees it; Enter without one is fine). "Always" adds a rule to your settings
([Permissions](/docs/configure/permissions/)). For a sensitive step, allowing covers that one
step only, whichever choice you pick.

## The timeline

**Ctrl+T** shows the timeline full screen: a row for each part that works on its own (the
model, each of its programs and the other units it started, and the environment) under an axis of the run's time. `+` and `-` zoom, `0` shows the
whole run, Esc closes it. When the model's row and a program's row have blocks at once,
the agent thinks while it acts. [Watch and replay a run](/docs/use/replay/) has more.

## Leave it running

Every conversation is a session of the **session host**, a background process that the
terminal, the app and Python share. Leaving (Ctrl+C twice, `/exit`), closing the
terminal or losing the SSH connection leaves the conversation running. Open `harness`
again and come back to it with `/resume` or `/sessions`. The first conversation starts
the host by itself; `/host` shows it and `/host stop` ends it.

Several conversations can work at once, each in a workspace of its own, and an agent can
split its task between sub-agents
([Work with sessions and sub-agents](/docs/use/sessions/)).

For a task from a script, without the chat, use `harness run "task"`
([Run from scripts](/docs/use/cli/)). The first time, the chat installs prompt_toolkit
and rich into an environment of their own; they are not dependencies of the core.
