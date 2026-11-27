---
title: "The app"
description: "The app's window: the chats on the left, the chat with its composer, queue and status bar, the tools on the right, the calendar, the settings pages, and every keyboard shortcut."
---

The app is a window on the agent that lives in the session host. It opens from the
[desktop app](/docs/getting-started/desktop-app/) or, with a pip install, from `the-harness app`,
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
| Right | Collapsible **Overview** panel (~280 px, toggled from the top bar, overlay drawer below 1100 px) consolidating Changes/Review, Files, Terminal, Plugins/Customizations, active Browser, Background Tasks, Goals, Artifacts, and conditional Pull Requests |

Every icon has a name: hold the pointer over it, or move to it with Tab.

The parts have no fixed width: drag the edge between two of them (the chat list, the tools
panel, the list of the Settings page, the calendar's left column) to make one wider or
narrower. The window remembers it; a double-click on the edge puts it back, and with the
edge focused (Tab) the Left and Right keys move it. The chat always keeps room to read and
type.

## UI design standards and responsive layout

### Reference-product provenance

Every layout and interaction upgrade in the app follows an established desktop product pattern (zero ad-hoc invented tabs or chrome):

1. **Centered reading column and frameless prose** *(ChatGPT / Cursor)*: The outer transcript scroll container spans `100%` of the chat area so the scrollbar stays at the outer edge, while messages, queue/plan strips, timeline dock, and composer align inside a shared `--chat-max-width: 760px` column (`--chat-pad-x: 24px`). Assistant replies render frameless directly on the canvas; user messages render as right-aligned rounded bubbles inside the 760 px column.
2. **First-turn automatic conversation title** *(ChatGPT / Cursor)*: Each chat persists `title_source` (`"default" | "auto" | "user"`). Manual rename locks `"user"`. When `title_source == "default"` on the first turn (first user message, or first assistant reply if the first user message has no text), a background hook generates a concise title in the conversation's language (with clean quote/filler-stripped truncation fallback), never overwriting `"user"` titles, and pushes updates live over SSE to both sidebar and top bar.
3. **Persistent attachments and lightbox** *(ChatGPT)*: Composer attachments render as `56px` rounded image thumbnails (with remove/retry) or file chips. Sent messages persist descriptors (`{id, name, mime, size, url}`) served from a same-origin read-only endpoint (`/api/app/attachments/<id>`) with strict ID validation, directory containment, accurate `Content-Type`, and `X-Content-Type-Options: nosniff`. User messages show right-aligned rounded image thumbnails above the bubble (`object-fit: cover`, `loading="lazy"`, graceful error fallback) opening a native `<dialog>` lightbox with `Esc`/backdrop close and prev/next navigation.
4. **Markdown and offline KaTeX math pipeline** *(ChatGPT)*: One pure `renderMarkdown(raw)` pipeline skips fenced and inline code spans, extracts Pandoc-style `$...$`, `$$...$$`, `\(...\)`, and `\[...\]` math (protecting `$1.50`, `$0.50`, `$PATH`, and unclosed streaming delimiters), sanitizes HTML, renders math offline via vendored KaTeX (`throwOnError: false`, `trust: false`, zero runtime CDN requests), adds language headers + copy buttons to code blocks, and wraps wide tables and display math in horizontally scrollable containers.
5. **Collapsible right Overview panel** *(Antigravity / Cursor)*: Replaces the always-on right icon rail with a single collapsible right **Overview** panel (`~280px`, persisted in `localStorage`, toggled from the top bar) backed by `GET /api/app/overview`. It consolidates Review/Changes, Files, Terminal, Plugins/Customizations (plus Browser when active) with one-click back-to-Overview, alongside Background Tasks, Goals, Artifacts, and conditional Pull Requests, automatically hiding empty optional sections.

### Three-viewport rules

- **Wide (`>= 1100px`)**: Left sidebar can remain expanded and resizable; chat transcript scroll container is `100%` wide with the `760px` centered reading column (`24px` horizontal padding); right Overview panel docks beside the chat (~`280px` in Overview, expandable when inspecting tools) and disappears completely when collapsed.
- **Medium (`700-1099px`)**: Left sidebar stays toggleable; chat reading column centers within `min(100%, 760px)`; right Overview/Tools panel opens as an overlay drawer over the right edge (with backdrop/Esc close) instead of compressing the chat column.
- **Narrow (`< 700px`)**: Left sidebar and right Overview/Tools panel both open as overlay drawers; reading column padding tightens to `16px` and user bubbles adapt cleanly (`max-width: 92%`); wide tables and block math scroll horizontally within their own containers with zero page-level horizontal overflow.

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

## Where a chat works

Beside the composer, on the left, is where the chat works and on which project, as a session
of Claude Code or Codex is opened on a project. The menu lists your projects (folders),
**Open folder…** to add one, and the browser or the desktop when they are connected. A chat
you started works in the place you choose from then on, and the list on the left groups the
chats of a project under its name; a new chat opens on the project of the chat you were in.
For a project that is a git repository you can choose its **isolated copy** instead: the chat
works in a git worktree on a branch of its own, and the project itself changes only when
that branch is merged. With **It decides**, the agent picks the place for each task. The
main conversation is not tied to one place: what you choose there goes with your next
messages.

## The model of a chat

Three things are kept apart: the **source** is whose account it runs under (an agent signed
in on this computer runs under your own plan; a provider under its key; or this computer),
the **model** is one of those the source offers, and the **reasoning effort** is one of the
levels that model has.

The model picker is beside the composer. Its headings are the sources, and under each are
that source's models that are kept here; **More models of …** opens every other model the
source offers (an agent declares its own, a provider has a catalog). It changes the model
of **this chat only**; in the middle of a chat it asks first, because the new model reads
the whole conversation again. Next to it, the effort button offers the levels of the model
in use, and is not there for a model that has none. **Settings › Model** changes the
default model and effort that new chats start with.

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

## Calendar

**Calendar**, in the left column, shows what the agent did and what is planned: what you
asked for, what it did on its own, what it learned, the reactions that ran, and when it was
asleep. Each looks different, and each carries a mark for how it ended.

- **Views.** Day, Week, Month and Year, from the buttons at the top right or the keys below.
  A day's number opens that day; the small month on the left moves the view.
- **Create.** Click an empty slot, or drag over a stretch of time, and type a title in the
  small box; Enter saves. **More options** opens the whole form: kind (task, reminder or
  goal), all day, start, end, repeats, note. Clicking a day in the month view, or the row at
  the top of the week, makes an entry for the whole day. The agent is woken when an entry
  comes due.
- **Move and resize.** Drag an entry of yours to another time or day; drag its lower edge to
  change how long it is. Each change says **Saved** with **Undo**. An entry that repeats is
  changed in its form instead, because the change applies to every occurrence.
- **An entry's card.** Click an entry to see who put it there or did it, its kind, how it
  ended, and the chat it belongs to, with edit and delete for the entries you may change.
  What was done is a record and stays.
- **Missed.** An entry put at a time that has already passed was never due: it is kept as
  **missed**, drawn with a dotted outline and its title struck through, and nothing is done
  for it. Dragged to a time ahead, it comes due as usual.
- **Search** looks through the titles and notes of a year either side of today.
- **Shown**, on the left, hides and shows each kind of entry. **Let it act on its own**
  pauses what it starts by itself; what you ask for still runs. **Today's budget** shows what
  it used on its own and what is kept for you.

## Settings

**Settings** (Ctrl+,) opens over the window. A change is saved as you make it and says
**Saved**, or why it was not. With two or more identities, the pages that hold an identity's
own things have **Applies to** at the top: pick the identity the page is for. A setting that
belongs to the whole computer is marked **every identity**. The settings few people need are
under **Advanced** at the end of their page, closed until you open it. A setting that is a
list of rules (for single apps, windows or kinds of step) shows how many there are and opens
with **Edit…**, where rules are added and removed.

| Page | What is there |
|---|---|
| General | Language, theme, whether thinking is shown, notifications, starting with the computer |
| Model | The default model (listed under its source) and its reasoning effort (the levels that model has), and the identity's own model, applied with **Apply** after one test call; the saved models under their sources (enable, disable, remove, **More models of …**); the sources found on this computer that are not set up yet; **Add a source** |
| Usage | What was spent and how many calls were made, by day, by chat, by kind and by model, for today, 7 days or 30 days; today's limit with **Raise today's limit** (see [Limit what an identity spends](/docs/use/spending/)) |
| Permissions and limits | What waits for you, what it asks before doing, the daily limit and the part kept for you, pause, and how much it does on its own |
| Packages | Installed packages (switch, update, remove) and the registry to search and install from |
| What it learned | Skills, the tree of reactions and memory: what each is from, how often it was used, the change against the version before, undo, delete; shared libraries, read only |
| Connectors | Channels, MCP servers, external agents and skill sources, each with add, test and remove |
| Computer | The places it can work in and how much it does on its own in each; the real mouse and keyboard, what it learns of your other windows, where a new chat works, the background browser and a display of its own |
| Personalization | Its name, the files that describe who it is, and which instruction files a new chat reads |
| Data | Share, export a card, back up, restore from a backup file you pick (it asks before it replaces an identity that is already here), bring over from another product, retire, delete the identity (see [Take an identity with you](/docs/use/take-it-with-you/)) |
| About | Version, the identity's key fingerprint, updates, and which `harness` a terminal runs |

### Usage

Calls made under your own plan (an agent signed in on this computer) are counted as calls.
They cost nothing here; the list price is shown beside them for comparison and is never
added to what was spent.

### Connectors

- **Channels** come from channel packages. **Add a channel** first asks which kind, from the
  packages installed, then walks through what that package asks for: its fields, signing in,
  the groups to join, and binding you as the owner with a one-time code. With no channel
  package installed, the page says where to get one (**Settings › Packages**).
- **MCP servers** are added as a command on this computer or as an address. A server is
  connected once when added and its tools are listed; **Test** connects again.
- **External agents** are other agents on this computer that speak ACP. One that is signed in
  can be chosen as a model.
- **Skill sources** are folders, repositories or addresses that hold skills. **Look first**
  reads a source without installing anything.

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

In the calendar, single keys work while nothing is being typed:

| Key | What it does |
|---|---|
| D, W, M, Y (or 1, 2, 3) | Day, week, month, year view |
| T | Today |
| J or N, K or P | Next, previous day, week, month or year |
| G | Go to a date |
| C | Create an entry |
| Enter, E | On an entry: its card; edit it |
| Delete or Backspace | Delete the entry (can be undone) |
| Z | Undo the last change |
| / | Search the calendar |
| R | Refresh |

Dialogs take Enter for their main button and Esc to cancel, and Tab moves through every
control. Opened in a browser tab instead of the desktop app, the browser keeps a few keys
for itself (Ctrl+N, Ctrl+P).
