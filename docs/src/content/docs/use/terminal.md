---
title: "Use the terminal"
description: "The terminal chat: typing and sending, what it shows while it works, approvals, every keyboard shortcut and command, your own key bindings, and what each terminal needs."
---

```bash
harness
```

`harness` opens a chat in your terminal, including over SSH. If you have used Claude Code, you already know how to use it: the keys, the commands and their names are the same wherever The Harness has the same thing. The first run asks which model to use ([Install](/docs/getting-started/install/#connect-a-model)); after that the chat opens with the version, the model and the directory above the input box, and nothing starts until you send a message.

## Type and send

| To | Press |
|---|---|
| send the message | Enter |
| start a new line | Shift+Enter, Ctrl+J, Alt+Enter, or `\` then Enter |
| paste several lines | paste: a paste never sends. More than three lines or 800 characters show as `[Pasted text #1 +120 lines]` and are sent whole |
| attach an image from the clipboard | Alt+V on Windows, Ctrl+V elsewhere: it shows as `[Image #1]` |
| attach a file | `@` and its path (Tab completes it) |
| run a command here and give its output to the agent | `!command` (`!!command` only runs it) |
| run a command of the chat | `/` and its name: the list filters as you type, Tab or Enter takes one |
| see the keys | `?` on an empty input |

Ctrl+J and `\` then Enter start a new line in every terminal. Shift+Enter depends on the terminal: see [Terminals](#terminals).

The input box edits like a shell's line: Ctrl+A and Ctrl+E go to the start and end of the line, Ctrl+K and Ctrl+U delete to its end and start, Ctrl+W deletes back to the previous whitespace, Ctrl+Y pastes what one of those deleted and Alt+Y cycles through earlier deletions, Alt+B and Alt+F move a word, Alt+D and Alt+Backspace (or Ctrl+Backspace) delete one, and Ctrl+_ undoes. A word is a run of letters and digits, so in `src/utils/foo.ts` Alt+B stops at `ts`, `foo`, `utils` and `src`; Ctrl+W takes the whole path. These editing keys are not rebindable.

Up and Down move between the rows of a draft first. From its first or last row they walk the messages you sent before in this directory, earlier sessions included; the same message twice in a row is kept once. A draft you cleared with Ctrl+C or Esc Esc comes back with Up. Ctrl+R searches the messages of every directory: type to match, Ctrl+R again for an older match, Tab or Esc to keep the match and go on editing, Enter to send it, Ctrl+C to go back to what you had typed.

## While it works

A line over the input box says that it works, for how long, and how to stop it. Its reply appears as it is written.

- **Esc** stops the turn. What it did so far is kept.
- **A message you send meanwhile is queued.** Queued messages are listed over the input box and sent in order when the turn ends, also after Esc. **Up** on the first row of the input takes them back into the input box to change them. **Ctrl+Enter** stops the turn and sends what is queued now.
- **Ctrl+C** stops the turn; when nothing runs it clears the input, and a second press leaves. **Ctrl+D** deletes the character after the cursor when there is text; on an empty input a second press leaves.
- **Ctrl+O** opens the transcript: every step in full, with its time, the model of each call and its tokens, a program's code and whole output. It opens on the last turns; Ctrl+E shows them all. `q`, Esc, Ctrl+C or Ctrl+O closes it.
- **Ctrl+T** opens the timeline: a row for each part that works on its own under an axis of the time. `+` and `-` zoom, `0` shows the whole run.
- **Shift+Tab** goes through the approval levels (`approvals.programs`: ask each time, ask once per conversation, allow, never). The level in use is under the input box.
- **Alt+P** switches the model without clearing what you typed.

Leaving the chat does not stop the agent. It says so when you leave, with how to come back (`harness`) and how to stop it (`harness host stop`).

Under the input box: a hint at the left, and at the right the identity with what it spent today, and the model. The line below has the approval level and how much of the model's context the conversation uses. A step of the agent is one line (`▸ Program 3 · ok · 2.1 s`); the transcript has the rest.

## Approvals

When a step waits for you, the chat asks above the input box: what it is about to do, why that waits for you, and the answers.

```text
● Approval needed
  git push origin main
  It waits for you because it is a step of the kind "send" · A7 · cancelled in 30 min if nobody answers

  Do you want to proceed?
  ❯ 1. Yes
    2. No
  Enter to answer · esc to decline · tab to add a note
```

Move with Up and Down and press Enter, or press the number. Esc declines. Tab opens a line for a note that goes with your answer, whichever it is; Tab again closes it. What you were typing is put aside while the question has the keys, and comes back once it is answered. `/approve` and `/deny` answer by command. [Permissions](/docs/configure/permissions/#approvals) says what waits for you.

## Keyboard shortcuts

| Shortcut | What it does |
|---|---|
| Enter | send |
| Shift+Enter, Ctrl+J, Alt+Enter, `\` Enter | a new line |
| Up, Down (Ctrl+P, Ctrl+N) | move in the draft; then the history; Up takes queued messages back |
| Ctrl+R | search the history |
| Tab | take a suggestion; on an approval, a note |
| Esc | stop the turn; close a list or the keys; on an approval, decline |
| Esc Esc | clear the input (Up brings it back) |
| Ctrl+C | stop the turn; clear the input; twice: leave |
| Ctrl+D | delete forward; on an empty input, twice: leave |
| Ctrl+Enter, Ctrl+X Ctrl+S | stop the turn and send what is queued now |
| Ctrl+L | draw the terminal again |
| Ctrl+O | the transcript |
| Ctrl+T | the timeline |
| Shift+Tab | the next approval level |
| Alt+P | switch the model |
| Ctrl+S | put the input aside; on an empty input, bring it back (it also comes back after you send) |
| Ctrl+G, Ctrl+X Ctrl+E | edit the input in your editor (`VISUAL`, `EDITOR`) |
| Alt+V (Windows), Ctrl+V | attach the image on the clipboard |
| Ctrl+Z | suspend to the shell (not on Windows) |
| Ctrl+A, Ctrl+E, Ctrl+K, Ctrl+U, Ctrl+W, Ctrl+Y, Alt+Y, Alt+B, Alt+F, Alt+D, Ctrl+_ | edit the line |
| `?` on an empty input | the keys |

On macOS the Alt shortcuts need "Use Option as Meta Key" (Terminal) or Option set to "Esc+" (iTerm2).

The lists that open over the whole terminal (`/model`, `/resume`, `/config`, `/sessions`, `/library` and the others) all move with the same keys: Up and Down (Ctrl+P, Ctrl+N), PageUp and PageDown, Home and End, Enter to take a row, Esc to close; typing filters a picker, and `?` shows the keys of that view.

## Commands

| Command | What it does |
|---|---|
| `/help` | what it is, the shortcuts, the commands and the skills |
| `/clear [name]` (`/reset`, `/new`) | a new conversation with nothing of this one; this one goes on, called `name` if you give one |
| `/resume [conversation]` (`/continue`) | go on with an earlier conversation: the one named, or pick one |
| `/sessions` | the sessions that run, or an identity's chats: switch to one |
| `/rename [name]` | rename this conversation; without a name, by what it began with |
| `/project [folder]` (`/where`) | where this chat works: a project folder (`.` is this terminal's), a git project's isolated copy, or wherever it decides; from the main conversation, a new chat is opened on the project |
| `/model [model]` (`/models`) | switch to the model named (by its name or id), or pick one; under the models, a row for each source opens every other model that source offers, then one adds a source and the last edits the model list |
| `/effort [level]` | the reasoning effort, from the levels the model in use has |
| `/login`, `/logout` | add or remove a source of models: an agent signed in on this computer, a provider's key, a local model |
| `/status [stop]` (`/host`) | version, model, identity, whether the provider and the session host answer; `stop` ends the session host |
| `/usage [week \| month \| raise DOLLARS]` (`/cost`, `/stats`) | what the identity spent: today, 7 days, 30 days; `raise` lifts today's limit |
| `/context` | how much of the model's context the conversation uses |
| `/compact [instructions]` | free context: the earlier part of the conversation becomes a summary; the instructions say what it must keep |
| `/config [key=value ...]` (`/settings`) | the settings, or set one directly: `/config terminal.editor_mode=vim` |
| `/permissions` (`/allowed-tools`) | the approval rules |
| `/keybindings` | open your keyboard shortcuts file |
| `/terminal-setup` | make Shift+Enter a new line in VS Code, Cursor, Windsurf, Alacritty or Zed |
| `/memory [N]` (`/instructions`) | the instruction files (`AGENTS.md`) and what it remembers; `N` opens that file |
| `/skills [sources]` | the skills it has; each skill is also a command, `/name`; `sources`: where skills come from |
| `/mcp`, `/acp` (`/external-agents`) | the MCP servers and the external agents: list, add, test, remove |
| `/agent` (`/profile`) | the identities: use, new, rename, delete |
| `/library` | what it learned: skills, its tree of reactions, memory |
| `/agents [on]` | the sub-agents of this conversation: open one, stop one; `on` lets it start them |
| `/init` | have the agent write the project's `AGENTS.md` |
| `/diff` | the changes of a coding session |
| `/copy [N]` | copy the last response (the Nth latest); with code blocks, pick one |
| `/export [file]` | the conversation as plain text: to the file, or copy or save from a choice |
| `/doctor` | check this installation |
| `/update`, `/version` | whether a newer version is out; the version in use |
| `/stop` (`/pause`, `/cancel`) | stop the turn, as Esc does |
| `/queue [text \| list \| edit N text \| rm N \| clear]` (`/q`) | queue a message; list, change or drop what is queued |
| `/bg <prompt>` (`/background`) | have it do something in a chat of its own while this one stays free |
| `/approve [app \| session \| always]`, `/deny [why]` (`/reject`) | answer what waits for you |
| `/calendar`, `/channels` (`/platforms`), `/timeline`, `/transcript` | the identity's calendar, its channels, the timeline, the transcript |
| `/environment`, `/packages` (`/plugin`), `/learn`, `/import`, `/end` | where a conversation works, the packages, a conversation that learns this environment, another agent's transcript, ending a conversation of the app's agent |
| `/steer`, `/terminal`, `/answer`, `/merge`, `/handoff` | in a session with another agent only |
| `/experiment` | with the eval package only |
| `/exit` (`/quit`, `/detach`) | leave; what runs goes on |

A name that is no command is answered `Unknown command: /name`, with the nearest command when there is one. `/learn` and `/handoff` keep The Harness's meaning, which is not that of Hermes's commands of the same names: `/learn` starts a conversation that gets to know this environment, `/handoff` starts another agent with the context you give.

## The views

Each of these opens over the whole terminal, shows the same data as the app's page and the command line, and moves with the keys above; `?` lists the keys of the view, and a view with nothing in it says so.

| View | What it does |
|---|---|
| `/calendar` | The identity's calendar: who did each thing (you, it on its own, its tree of reactions), how it ended, what the safety layer refused, when it was asleep. `d` `w` `m` show a day, a week, a month; `t` today; `n` and `p` the next stretch and the one before; `c` creates; Enter opens an entry, `e` edits it; `x` or Delete removes it; `z` undoes; `/` searches titles and notes; `o` pauses and resumes what it does on its own. An entry put at a time already past is marked `◌ missed`: it was never due, so it is not run. |
| `/usage` | What the identity spent: `t` today, `w` the last 7 days, `m` the last 30, by day, chat, task and model. A call under your own plan is counted as a call, not as dollars. `r` raises today's limit. |
| `/channels`, `/mcp`, `/acp`, `/skills sources` | One list of what it is connected to, in four groups: channels, MCP servers, external agents, skill sources. `a` adds to the group the cursor is in, `t` tests, `x` removes, Enter opens a row. A channel comes from a channel package: the kinds offered, each question and every word are what the package declares. With none installed, the list says where channels come from. |
| `/library`, `/skills`, `/memory` | What it learned: skills with their evidence, uses and origin (Enter: diff, undo, approve, restore, delete), the tree of reactions browsed like folders (Enter into a branch, ← up, `m` move, `x` disable, `u` remove), memory (Enter reads, `x` forgets), and the shared libraries, read only. |
| `/config`, `/permissions` | Every setting by its name, under the page the app has it on, its value in words; typing searches; Enter changes one. The settings few people need come last on their page, under "Advanced". A setting of an identity (its limits, its learning) is changed for the identity the chat runs as. |
| `/model` | The enabled models, each with the source it comes from and its effort levels; **More models of …** asks a source for every model it offers and keeps the one you pick; **Add a source** takes one from what is on this computer (an agent signed in, a key, a local model): it is tried with one call that keeps nothing, kept only when you say so, and an agent then asks which of its models. |
| `/agent` | The identities: Enter makes one current and opens it here, `n` makes a new one, `r` renames, `x` deletes after listing its conversations, channels and spending. |

## Customize the keys

`/keybindings` opens `keybindings.json` in your data folder (`~/.harness`), made with the defaults when there is none. It has the format of Claude Code's keybindings file: a `bindings` array of blocks, each with a `context` and a map of keystrokes to actions; `null` unbinds. What you save applies at once, without a restart.

```json
{
  "bindings": [
    {
      "context": "Chat",
      "bindings": {
        "ctrl+k": "chat:newline",
        "ctrl+s": null,
        "ctrl+x ctrl+k": "command:clear"
      }
    }
  ]
}
```

| Context | Actions |
|---|---|
| `Global` | `app:interrupt` (Ctrl+C), `app:exit` (Ctrl+D), `app:toggleTranscript`, `app:toggleTimeline`, `app:redraw` |
| `Chat` | `chat:submit`, `chat:newline`, `chat:cancel`, `chat:sendNow`, `chat:clearInput`, `chat:cycleMode`, `chat:modelPicker`, `chat:undo`, `chat:externalEditor`, `chat:stash`, `chat:imagePaste`, `history:search`, `history:previous`, `history:next`, and `command:<name>` for any command |
| `Autocomplete` | `autocomplete:accept`, `autocomplete:dismiss`, `autocomplete:previous`, `autocomplete:next` |
| `Confirmation` | `confirm:yes`, `confirm:no`, `confirm:previous`, `confirm:next`, `confirm:addNote` |
| `HistorySearch` | `historySearch:next`, `historySearch:accept`, `historySearch:cancel`, `historySearch:execute` |
| `Transcript` | `transcript:exit`, `transcript:toggleShowAll` |
| `Help` | `help:dismiss` |
| `Select` | `select:next`, `select:previous`, `select:pageUp`, `select:pageDown`, `select:first`, `select:last`, `select:accept`, `select:cancel` |

A keystroke is modifiers joined with `+` (`ctrl`, `shift`, `alt` or `meta`, `cmd`) and a key: a character, or `escape`, `enter`, `tab`, `space`, `up`, `down`, `left`, `right`, `pageup`, `pagedown`, `home`, `end`, `backspace`, `delete`, `f1` to `f12`. A chord is keystrokes separated by spaces. Ctrl+C and Ctrl+D cannot be rebound, nor can Ctrl+M, Ctrl+I, Ctrl+[ and Ctrl+H, which a terminal sends as Enter, Tab, Escape and Backspace. A mistake in the file (JSON that does not read, a misspelled modifier, an unknown context or action) is said in the chat; the bindings that read still apply.

For Vim keys in the input box, set `terminal.editor_mode` to `vim` in `/config`: Esc goes to NORMAL mode, Enter still sends.

## Terminals

Whether Shift+Enter reaches the chat depends on the terminal. Ctrl+J and `\` then Enter always work.

| Terminal | Shift+Enter |
|---|---|
| Windows Terminal, the Windows console | works |
| iTerm2, WezTerm, Ghostty, Kitty, Warp, foot, Alacritty 0.16 or later, xterm | works: the chat asks the terminal to report modified keys when it starts, and puts it back when it ends |
| VS Code, Cursor, Windsurf, Zed, Alacritty before 0.16 | run `/terminal-setup` once: it adds a Shift+Enter binding to the terminal's own configuration (the file is backed up first; an existing binding is left as it is) |
| tmux | add `set -s extended-keys on` and `set -as terminal-features 'xterm*:extkeys'` to `~/.tmux.conf`, in a terminal of the rows above |
| GNOME Terminal, Apple Terminal, JetBrains IDEs | not available: use Ctrl+J, `\` then Enter, or Option+Enter in Apple Terminal with "Use Option as Meta Key" |

## Leave it running

The **session host** keeps conversations running after `/exit`, terminal closure or SSH disconnection. Reopen `harness` and select `/resume` or `/sessions`. `/status` shows the background process; `/status stop` ends it and its conversations.

`harness --continue` opens the conversation you last messaged or resumed; `harness --resume ID` selects one explicitly. Ended sessions restore their messages and facts with a new kernel ([Sessions](/docs/use/sessions/)). For one scripted task, use `harness run "task"` ([CLI](/docs/use/cli/)).

A conversation of the app's agent asks where to work when it opens: no environment, a project folder, background browser or applications, desktop, or a separate display. Enter confirms the highlighted choice; `/environment` chooses for the next conversation, `session.environment` in `/config` stops the question, and `--workspace KIND` answers it for one conversation ([CLI workspaces](/docs/use/cli/)).
