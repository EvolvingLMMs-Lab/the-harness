---
title: "Keep agent identities"
description: "Give the agent a name and a persona that last, keep several identities apart, and choose which one a command or the terminal chat runs as."
---

An **identity** is an agent that lasts: its name, its persona, what it remembers about
you, its conversations and what it learned. Each identity is a folder you can open and
edit. Identities come with the optional `agent` package, which `harness agent` installs
the first time you use it.

## The first identity

The first identity has the id `default`. Talk to it:

```sh
harness agent say "Remember that pull requests are written in English"
harness agent
```

`harness agent say` is one turn; `harness agent` alone opens a chat in the terminal. The
earlier form `harness agent "TEXT"` still works for one release and tells you to use
`say`.

## An id and a name

Every identity has an **id** and a **display name**. The id uses letters, digits, `_`
and `-`, names its folder and never changes. The display name may be in any language
and changes whenever you like:

```sh
harness agent new work --name "工作助手"
harness agent rename "小林" --identity work
harness agent list
```

`harness agent new ID --from OTHER` copies another identity's persona, skills and
reactions, never its memory or conversations. `--card FILE` takes a character card
(Character Card V3, V2 or V1, as `.png` or `.json`): its name goes into `IDENTITY.md`, its
description, personality and system prompt into `SOUL.md`, and a PNG card becomes the
avatar. Other fields of the card are ignored.

## Which identity a command uses

Every command acts on one identity. `--identity ID` names it; without it the current
identity is used, which `harness agent use ID` chooses. When there is only one identity,
it is the one. With several and none chosen, nothing is guessed: in a terminal the
command asks which one, and in a script it fails with an error that says what to give.

```sh
harness agent use work
harness agent about
harness --identity work
```

`harness` (the terminal chat) runs as an identity too when the `agent` package is
installed: its status line shows the identity's name, and each conversation it starts is
recorded as that identity's.

## The identity folder

Each identity lives in `$HARNESS_HOME/agents/ID/` (`~/.cache/harness/agents/ID/`):

| File | What it holds |
|---|---|
| `IDENTITY.md` | the display name and the avatar |
| `SOUL.md` | personality, tone and limits, read at the start of every turn |
| `USER.md` | what it knows about you, read at the start of every turn |
| `MEMORY.md`, `memory/` | its memory: one file per entry and an index |
| `library/` | its own learning library |
| `sessions/` | its conversations |
| `identity.json` | machine data: its public key, model choice and format |

Edit `SOUL.md`, `USER.md` and the files in `memory/` with any editor; the next turn
reads them. A memory entry holds at most 1200 characters. Identities share nothing by
default: one never sees another's memory, conversations or library.

Each identity also has a key pair, which environments use to recognise it. The private
key is kept next to the folders, readable only by you, and never goes into a share. You
never manage it; `harness agent about -v` shows its fingerprint.

## One identity lives in one place

An identity runs in one session host at a time. A second terminal or the app on the same
computer and data directory joins the same identity; opening it from another data
directory while the first still runs is refused, with the process and directory that
hold it. When that process ends, even by a crash, the identity is free again.

## Identities from an earlier version

The first time this version opens an identity of an earlier one, it moves the
instructions into `SOUL.md` and each entry of `memory.json` into `memory/`, marked
private. Settings that the default identity had not imported yet (`personal.about` and
`personal.instructions`) go into `USER.md` and `SOUL.md`. Nothing is removed:
`identity.json` keeps what the earlier version reads (its original is copied to
`identity.v1.json`), `memory.json` and the conversations
stay as they were, and the earlier version still opens them. What it remembers after you
go back is what it remembered before the upgrade.

## Delete an identity

```sh
harness agent delete work
```

It lists the conversations and memory that go and asks you to type the id; a script gives
`--yes`. Deleting removes the folder and the key pair and cannot be undone.

## Its chats from the command line

What the terminal chat and the app do in an identity's chats, the command line does too,
on the same life in the session host:

```bash
harness agent say "Tidy the notes folder"       # into the main conversation; prints the answer
harness agent say "and then the photos" --no-wait   # only queue it
harness agent queue                              # what runs, and what waits behind it
harness agent queue edit 1 "and then the videos" # a message that waits, by its number or id
harness agent queue remove 1                     # also: clear, send-now ID, resume
harness agent stop                               # the turn in progress, as Esc does (--hold keeps the queue waiting)
harness agent compact "keep the decisions"       # compact the chat's context into a summary
harness sessions                                 # the chats; rename, pin, archive, delete
```

Stopping cuts the model call off and cancels the running task; what was done stands, and
the chat's record says `interrupted`. An identity's own settings are read and written with
`harness config ... --identity ID` ([Settings](/docs/reference/settings/#agent)).

## In Python

`harness.sdk.Agent` does the same as the commands:

```python
from harness.sdk import Agent

work = Agent.new("work", name="工作助手")
print(work.say("What do you remember about me?")["answer"])
Agent.use("work")
print(Agent().name, Agent.list())
```

`Agent()` with no id is the current identity; with several and none chosen it raises.

Everything the frontends do goes through the same methods:

```python
work = Agent("work")
work.say("and then the photos", wait=False)       # {"queued": id, "chat": "main"}
work.chat()["live"]                               # the reply while it is written: {text, reasoning, ...} or None
work.queue()                                      # {held, running, queued: [{id, text, ...}]}
work.queue_edit(id, "and then the videos"); work.send_now(id); work.queue_remove(id)
work.stop(hold=True); work.queue_resume()         # stop the turn; the queue waits until it is resumed
work.compact(instructions="keep the decisions"); work.context()
work.chats(q="ferry"); work.rename_chat(chat, "Trip"); work.pin_chat(chat); work.archive_chat(chat)
work.chat_model(chat, "openrouter/some-model", effort="high")
work.usage("week"); work.settings(); work.set("agent.daily_budget", 3)
work.calendar_add("Call Lin", "2026-12-01T15:00"); work.calendar_update(entry, until="2026-12-01T16:00")
work.calendar_remove(entry); work.calendar_restore()
Agent.channel_kinds(); work.channel_add("chat", dm="pairing"); work.channels()
work.skill_sources(); work.skill_source_add("github:OWNER/REPO")
```
