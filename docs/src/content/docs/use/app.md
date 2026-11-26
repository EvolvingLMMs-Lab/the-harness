---
title: "The app"
description: "The app's window: the chats on the left, the chat with its composer, queue and status bar, the tools on the right, and every keyboard shortcut."
---

The app is a window on the agent that lives in the session host. It opens from the
[desktop app](/docs/getting-started/desktop-app/) or, with a pip install, from `harness app`,
which prints an address to open in a browser. Closing the window does not stop the agent;
the terminal chat (`harness`) shows the same chats.

## First open

The first time, a welcome lies over the window. It lists what on this computer can be the
model: an agent signed in here (it runs under your own plan, no key needed), a provider's
key found in the environment, a model on this computer, or a key you type. Choose one with
the mouse or the arrow keys and press **Try it** (or Enter): it is asked for one word and
kept only when it answers. **Choose a model later** lets you look around first; the composer
then says that a model is still to be chosen.

An empty chat offers a few things to say. Click one, or type your own.

## The window

| Where | What |
|---|---|
| Left | **New chat**, **Calendar**, the list of chats, **Settings**, and the identity in use at the bottom (click it to switch) |
| Middle | The chat: its title and state on top, the transcript, the timeline when it is switched on, the composer, and the status bar |
| Right | The tools rail: Context, Terminal, Browser, Files and Changes of the open chat, each opening as a tab of a side panel |

Every icon has a name: hold the pointer over it, or move to it with Tab.

## Chat

- **The reply appears as it is written.** While the agent uses tools, each action shows as
  it happens with how it ended; afterwards they fold into one line (how many, how they
  ended, how long) that opens to the actions, and each action opens to what it was given
  and what came back.
- **Thinking** shows above the reply while the model thinks.
  **Settings › General › Show thinking** hides it.
- **Enter** sends and **Shift+Enter** starts a new line. While you compose with an input
  method, Enter belongs to it.
- **Stop** (the square button, or Esc) stops the turn. What was already done stays.
- **The queue.** What you send while it works waits in a queue shown above the composer.
  Each waiting message can be edited, deleted or sent now. Stop with messages waiting holds
  the queue and opens it; **Resume** lets it go on. The queue is kept by the host: it
  survives a restart and is the same in every window and in the terminal.
- **Drafts.** What you typed and did not send stays with its chat when you look at another
  one or restart the app.
- **Reading position.** Coming back to a chat returns to where you were reading. A chat you
  left at the bottom keeps following new output; **Jump to latest** takes you back there.
- **Attachments.** Drop files anywhere on the chat, paste an image, or use **+**. They go
  with your next message.
- **Sent messages.** In an empty composer, Up and Down bring back what you sent in this chat.
- **Find.** Ctrl+F searches the transcript; Enter and Shift+Enter step through the matches,
  Esc closes.

### When it asks you

Before paying, sending, deleting and other steps you must decide, a card in the chat asks:
*Do you want to proceed?* Press **1** for *Yes*, **2** for *No, and tell it what to do
differently* (a line opens for what to do instead), or **Esc** to decline. A request nobody
answers in time is cancelled, never taken as done. The bell at the top of the left column
takes you to a chat that waits for you.

### When a turn fails

A card says what went wrong and what to do about it, with **Retry** (says the turn's message
again), **Switch model** (for this chat), **Open logs** (the end of the host's log) and
**Copy error**.

## The model of a chat

The model picker is beside the composer. It lists the models set up here in one list (agents
signed in on this computer, provider keys, local models) and changes the model of **this
chat only**; in the middle of a chat it asks first, because the new model reads the whole
conversation again. **Settings › Model** changes the default that new chats start with.

## Status bar

Under the composer: what the agent asks you about first (click to change it; it is the same
for every chat), how much the last model call read, where the chat works, its model, and
what was spent today of the daily limit.

## The list of chats

- **Search** (the magnifier, or Ctrl+Shift+F) looks in the titles and in what was said.
- **Pin** keeps a chat at the top. **Archive** takes it out of the list; **Archived**, above
  the list, shows the archived ones, where they can be read and unarchived.
- **Rename** and **Delete** (it asks first).

Each is in the menu on a chat's row (the button that appears on it, or the right mouse
button). The main conversation is neither archived nor deleted.

## Keyboard

On macOS, use Cmd where Ctrl is written.

| Key | What it does |
|---|---|
| Ctrl+K or Ctrl+P | The command palette: any action, settings page or chat by name |
| Ctrl+/ | The list of shortcuts |
| Ctrl+, | Settings |
| Ctrl+N | New chat |
| Ctrl+B | Hide or show the left sidebar |
| Ctrl+J | Open or close the tools panel |
| Ctrl+F | Find in this chat |
| Ctrl+Shift+F | Search chats |
| Esc | Close or cancel what is open; with nothing open, stop the turn |
| Enter, Shift+Enter | Send; a new line |
| Up, Down | In an empty composer, the messages you sent |
| 1, 2 | On an approval card, choose that option |
| Shift+F10, F2, Delete | On a chat in the list: its menu, rename, delete |

Dialogs take Enter for their main button and Esc to cancel, and Tab moves through every
control. Opened in a browser tab instead of the desktop app, the browser keeps a few keys
for itself (Ctrl+N, Ctrl+P).
