# The Harness app

The `app` package is the window onto an agent's life: a page the session host serves at `/`,
with every identity's chats, its calendar and its settings. The page reads and writes only the
host's API; the agent's life runs in the host, so closing the page (or never opening it) changes
nothing about what the agent does.

```sh
harness app                 # the host (started when none runs) and the page's address
harness app --no-window     # only the address, even with the desktop shell installed
```

`harness app` never opens a web browser. It prints the address (with the session key); when the
desktop shell (`shell/`, a Tauri window) is installed, it opens the shell's window on it.

## Screens

| Screen | What it shows |
| --- | --- |
| Left column | New chat, Calendar, the chats (main conversation first, each connected place a chat of its own; marked when something new happened there, busy while it works, waiting for the desktop or for you), Settings and the identity at the bottom |
| Chat | Title bar with its state and today's spending; the record: what was said, events of the place, the tree's reactions, actions with their outcome (done ✓, refused ⊘, failed ✕, cancelled ■, unknown ?), what it learned, approval cards, the morning summary; the composer (with the place to work in for the main conversation and new chats) |
| Timeline | Below the chat (⧉ in the title bar): when the model, the place's actions and its tasks were busy; a task's own lanes come from the core (`/api/lanes`) |
| Tools rail | Context, Terminal, Browser, Files and Changes of the chat, as tabs of a side panel |
| Calendar | A week view like Google Calendar's: what it did and when, who did it (the tree, on its own, the owner), how it ended, what the safety layer refused, when it was asleep; Create puts an entry on it |
| Settings | General, Model, Usage, Permissions and limits, Packages, What it learned (skills with their evidence, source and undo; the tree of reactions one level at a time like a file manager; memory), Connectors, Computer, Personalization, Data, About |
| Identity menu | Switch, create (display name, fixed id, clone persona, skills and reactions, never memory), import |
| First run | The model: keys found on this computer, one test call, a working key saved to the credentials file, an OpenClaw or Hermes agent offered to bring over; then the main conversation, where the agent asks for its name |

The desktop shell raises system notifications from `/api/agent/notifications` (approvals, the
limit reached, failed or unknown actions, an expired channel login).

## Design

The archive design's working version: its tokens and typefaces (Space Grotesk, Inter, JetBrains
Mono; SIL OFL 1.1) are copied into `ui/static/archive/` unchanged, square corners, solid
surfaces, light or dark as the system is (or `general.theme`). The semantic colours and symbols
of actions, outcomes, events and records are local tokens in `ui/static/tokens.css`, named as
they are proposed for the archive design, so the terminal uses the same names.

## What it adds to the host

`/` (the page), and `/api/app/found`, `onboard`, `elsewhere`, `persona`, `skill`,
`place` and `about` beside the core's own `/api/app/...` routes (`harness_app/host.py`).
