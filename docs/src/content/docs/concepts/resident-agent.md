---
title: "The resident agent"
description: "How a Harness agent identity keeps working on its own: a resident service, a tree of reactions judged all the time, the model woken only when something calls for thinking, a calendar of what it did, a safety layer, approvals, learning, a daily budget and four frontends."
---

An agent identity ([Keep agent identities](/docs/use/identities/)) is not an app you open
and close. Once installed it keeps working: it watches the places you connected it to,
answers what happens there, does things of its own within its budget, and learns. The app,
the terminal and chat channels are ways to talk to it and look at it; closing them changes
nothing.

## Always working

The session host runs every identity's **life** as a resident service. A login item starts
the host when you sign in (`harness host install`), and the host stays up while a life is
alive. `harness` in a terminal, `harness agent`, the Python API, the app and chat channels
all attach to the same life.

Its conversations:

- **The main conversation** is your private chat with it. Your private chat in a chat channel or
  another channel is the same conversation; each message is labelled with its channel, and
  the answer goes back there.
- **Each connected place** is a chat of its own: a project folder, a browser, the desktop,
  a channel account, and one chat for each group inside a channel. What happens there, the
  reactions, actions and outcomes are recorded in it.
- **New chat** makes a chat for one piece of work.

Messages from every frontend join one queue in the order they arrive. Chats run their turns
side by side; within one chat the next turn waits. Only one chat at a time can use the desktop, so
other chats wait for it and show `waiting: desktop`. **Pause** stops the model and its work while places
stay connected and events are recorded; **quit** ends actions in progress as *cancelled*
where they can be cancelled and *unknown* where not. After a restart every chat continues
from its record, and events older than `agent.stale_hours` (6) reach the model as one summary
for it to judge what still deserves an answer.

## A tree of reactions, judged all the time

Each identity has one **tree of reactions** (`reactions.json` in its folder). Its life judges
the tree from the root whenever something changes or a time comes, whether or not a task
runs, anyone asks or budget is left. A node has three parts:

| Part | What it is |
|---|---|
| Condition | When it takes over: an event of a place and its fields, an outcome, a fact of the moment (`battery`, `owner_active`, `working_in`, `asleep`), or all / any / not of these. A situation also says when it is over. |
| Answer | One of five: call a skill, wake the model, stop, remind you, or nothing. |
| Position | The node it hangs under and its place there. An earlier node interrupts what a later one does. |

Three nodes come with every identity and can be disabled, not deleted: *named or aimed at
it → wake it*, *an action ended failed or unknown → wake it*, *needs approval → remind
you*. When you describe a reaction that must happen even while it is passive ("when the
battery is below 20%, stop"), it becomes a node at once, marked *added by owner*, under the
branch it fits best. Anything else you say is a preference and goes into memory. Goals, plans
and ways of doing things never go into the tree; ways of doing things are skills.

## Waking the model

The model is woken on objective conditions only:

- **What happens to it** that needs understanding: you speak, someone names it, an action is
  refused or fails, something the tree cannot answer.
- **What it wants to do coming due**: an intention it left (at a time, after some minutes, or
  once an event happens), an entry on the calendar, practice it chose, events piling up in a
  place (20 of them, or the oldest 4 hours old).

Awake, it decides whether to do something and what, and before it ends it leaves intentions
with the conditions that should wake it again. Otherwise the model does not run, so an
identity with nothing to think about costs nothing.

## The calendar

Each identity has an ordinary calendar. You and it both put things there: goals, tasks,
reminders, what it arranged for itself, once, daily or weekly. It also shows what happened:
every turn and who began it (you, or it on its own), each reaction of the tree, how they
ended, what the safety layer refused and when it was asleep. A planned entry coming due wakes
it. When you move or remove something it planned, or say "don't do this kind of thing", that
becomes a private memory that shapes later decisions. Every morning after 6:00 a summary of
what it did, learned and spent, and what waits for you, goes into the main conversation and
`DREAMS.md`.

Where it may act on its own is yours to set: `agent.proactive` (`on`, `learn_only`, `off`),
"pause on its own", and per place `spaces.<place>.proactive` (`off`, `learn`, `do`; by default
`do` for project folders and browsers, `learn` for the desktop, `off` for chat groups unless
you gave it a goal there).

## Who can direct it: the safety layer

Every action passes a **safety layer** of fixed rules before it runs. It is not the agent's
judgement and cannot be unlearned:

- Its input on the desktop is refused while you are using the desktop; it never fights you
  for the mouse.
- Sending, publishing, paying, deleting and steps that cannot be undone run only with your
  approval; logging in is left to you. What counts as sending is declared by the place
  (replying in the chat where it was asked is not sending).
- Authority comes from where a turn came from, never from what the prompt says: you (your
  bound channel accounts, local frontends), its own initiative (one level less, only where the
  place allows `do`), and everyone else (only within the chat they are in, never your
  computer, files or accounts). A turn has the lowest authority of its sources.

A refusal reaches the agent as the outcome *refused* with the reason; what to do next is its
own judgement, and the calendar records it.

## Approvals and notifications

An action that needs approval gets a short code such as `A7`: a card in the main conversation
and in its chat, a system notification, and a message in your private chat of a bound channel,
where you answer `A7 approve` or `A7 reject`. The first answer wins. Unanswered for
`approvals.timeout_minutes` (30) it ends as *cancelled*, never as done. System notifications
are only for four things: approvals, the spending limit reached, an action that failed or
ended unknown, and a channel login that expired.

## Learning

Learning is on by default. A skill is a folder compatible with `SKILL.md`
([agentskills.io](https://agentskills.io)) that also holds a program and its test. Each skill
has an evidence level: *proposed*, *own test passed*, *replay passed*, *effective* (5 uses
with at least 80% done, or a better score where an environment is scored). Where actions have
outside consequences, a new skill is called only by the model by hand, and the tree calls it
only once it is effective.

When a chat has been quiet for 10 minutes after a turn, a background review proposes at most
one thing: a skill (its own test runs first), a reaction, a memory, or practice. Every day at
0:30 it merges duplicates, archives what went unused for 30 days, turns what it did by hand
several times into a skill, and writes the day into `DREAMS.md`. `learning.mode` sets how:
`on` (takes effect at once and can be undone), `review_first` (waits for you), `frozen` (use
without learning), `off`.

## Spending

Each identity has a daily budget, `agent.daily_budget` ($2), reset at 0:00, and
`agent.reserve` ($0.50) of it is kept for your matters: your messages, mentions and work after
your approvals. Its own work spends the rest, paced over the money and hours left today. When
that is gone it is asleep: the tree still runs, events are recorded, you can still wake it,
and the rest waits for 0:00. See [Limit what an identity spends](/docs/use/spending/).

## Four frontends

Everything has an entry in every frontend:

| Task | App | Terminal (`harness`) | Command line | Python |
|---|---|---|---|---|
| Chats | the left column | `/sessions` | `harness sessions` | `Agent.chats()` |
| Identities | bottom of the left column | `--identity` | `harness agent new/use/list/rename/delete` | `Agent(id)` |
| Memory, reactions, what it learned | Settings › What it learned | `/library` | `harness library` | `Agent.memory()`, `Agent.reactions()` |
| Approvals | approval cards, notifications | `/approve`, `/reject` | `harness sessions approve` | session interface |
| Channels | Settings › Connectors | `/channels` | `harness channels` | `Agent.channels()` |
| Calendar | Calendar in the left column | `/calendar` | `harness calendar` | `Agent.calendar()` |
| Usage | title bar, Settings › Usage | `/usage` | `harness usage` | `Agent.usage()` |
| Resident service | tray menu | `/host` | `harness host install/uninstall/stop` | `Host` |
| Taking it with you | Settings › Data | — | `harness agent share/adopt/backup/restore/retire` | `Agent.share()` and others |

Moving an identity to another computer, sharing it and backing it up are described in
[Take an identity with you](/docs/use/take-it-with-you/).
