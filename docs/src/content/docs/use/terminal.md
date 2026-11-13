---
title: "Use the terminal"
description: "Use terminal chat, workspaces, approvals, sessions and the timeline."
---

```bash
harness
```

`harness` opens a terminal chat, including over SSH. Configure your model on first use ([Install](/docs/getting-started/install/#connect-a-model)). Your first message starts a task.

## The conversation

Chat stays in terminal scrollback. Below it are the input and status: activity, model, workspace and session. Send another message while the agent works to steer its next step ([Interrupt and take over](/docs/use/interrupt/)).

Each new conversation asks where to work: no environment, a project folder, background browser or applications, desktop, or separate display. Enter confirms the highlighted choice; projects also ask for a folder. `/environment` chooses for the next conversation. Set `session.environment` to `last` or a fixed kind to stop asking, or pass `--workspace KIND` for this conversation.

Desktop/application tasks also ask about physical input, other-window information and recording. Cancel leaves the task unstarted. Saved preferences can be changed in `/settings`; `--physical` and `--window-details` override one task only. API calls return `choice_required` for missing decisions; sub-agents must satisfy the same choices. Project tasks omit unrelated desktop questions. See [CLI workspaces](/docs/use/cli/).

Messages and Markdown answers appear alongside dimmed thinking and compact program summaries: `▸ Program 3 · ok · 2.1 s`. **Ctrl+O** opens full code and output; press it again or Esc to return. Details do not enter chat scrollback, and new chat output waits until they close. Sub-agent output is labelled.

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
| `/new`, `/clear` | a new conversation with nothing of this one; the one shown goes on in the session host, and `/resume` comes back to it |
| `/resume` | pick an earlier conversation and go on with it in its own session (one that ended starts again with its messages and facts) |
| `/sessions` | the sessions that run, with their sub-agents; switch to one |
| `/host`, `/host stop` | the session host: its address, process, version and open sessions; `stop` ends it and what runs in it |
| `/environment` | where this conversation works, and the choice for the next one |
| `/agents` | switch sub-agents on: for this conversation, or for the next one before it starts |
| `/model` | pick an enabled model for new conversations; use `/models` to edit the list |
| `/effort LEVEL` | change the current conversation's reasoning effort from its next call |
| `/experiment NAME [TASK [SEED]] [-- instruction]` | start an interactive task on an experiment's worker |
| `/settings` | terminal and agent settings, including installed packages; Enter changes one |
| `/packages` | the installed packages and the registry's; Enter on one shows what it provides and installs, updates, turns it off or removes it (asked first) |
| `/library` | what the agent learned: each library's entries by kind with their evidence; Enter reads one and its history |
| `/pause`, `/continue` | stop at the next step, go on |
| `/cancel` | end the turn that runs; the conversation waits for your next message |
| `/approve [app \| session \| always]`, `/reject [why]` | answer what the agent waits for |
| `/end` | end the conversation (`/resume` can still go on with it) |
| `/timeline` | the timeline (Ctrl+T) |
| `/detach`, `/exit` | leave; the conversation goes on |

`/resume`, `/sessions`, `/model`, `/settings`, `/packages`, `/library` and the timeline
open over the whole terminal and close back to the chat (Esc). A selected row shows its explanation; F2 opens the complete text. Long text readers support arrows, PageUp/PageDown and Home/End. Browser-only appearance settings are kept out of the terminal settings list.

## Files and shell commands

- `@` and a path attaches a file to the message (Tab completes the path): the agent gets
  its text, or the picture itself for an image, or the names in a folder.
- `!command` runs the command here, in this directory, shows its output and sends it to the conversation that started it, even if you switch conversations while it runs.
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
whole run; arrows, PageUp/PageDown and Home/End scroll through lanes. Esc closes it. When the model's row and a program's row have blocks at once,
the agent thinks while it acts. [Watch and replay a run](/docs/use/replay/) has more.

## Leave it running

The **session host** keeps conversations running after `/exit`, terminal closure or SSH disconnection. Reopen `harness` and select `/resume` or `/sessions`. `/host` shows the background process; `/host stop` ends it and its conversations.

`harness --continue` opens the conversation you last messaged or resumed; `harness --resume ID` selects one explicitly. Ended sessions restore their messages and facts with a new kernel ([Sessions](/docs/use/sessions/)). For one scripted task, use `harness run "task"` ([CLI](/docs/use/cli/)).

`/models` opens `EDITOR` (default vi on macOS/Linux). Save and close to return; vi uses `Esc`, `:wq`, Enter to save, or `:q!` to discard. Invalid JSON can be reopened for repair. Empty or mismatched model lists still let you open the terminal to repair them; new tasks wait for a valid selection. Model changes apply to new conversations. Newly installed package environments appear immediately; updates/removals of loaded packages apply after their sessions end and the host reconnects.
