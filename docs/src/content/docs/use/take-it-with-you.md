---
title: "Take an identity with you"
description: "Share an agent identity as a package or a character card, adopt one someone shared, back it up with a passphrase, move it to another computer, and bring an agent over from OpenClaw or Hermes."
---

An identity is a folder ([Keep agent identities](/docs/use/identities/)), so it can travel.
Five commands cover it, each with the same meaning in the app (Settings › Data) and in
Python (`harness.sdk.Agent`):

| Command | What it does | Its key and credentials |
|---|---|---|
| `harness agent share ID --to PLACE` | shares persona, avatar, skills and reactions | never go |
| `harness agent adopt SOURCE` | makes a new identity from a shared one | a new key |
| `harness agent backup ID` | a full backup, encrypted with a passphrase | go, encrypted |
| `harness agent restore FILE` | restores a backup on this computer | come back |
| `harness agent retire ID` | stops it on this computer after it moved | stay, unused |

## Share an identity

```sh
harness agent share default --to github:you/yu-agent
```

The package carries the persona (`SOUL.md`, `IDENTITY.md`), the avatar, the skills with their
programs and tests, and the reactions you or it added. Memory and `USER.md` (what it knows
about you) stay unless you add `--with-memory`. The private key, channel credentials, model
keys, conversations, calendar and spending never go.

Before anything is sent, the command prints every text that will become public, file by
file, and asks `Publish? [y/N]`. Places of this computer become names (your home folder
becomes `~`), and the groups its reactions name become placeholders such as `<group>`. If a
model key or a channel token appears in any of it, the share stops and says which file holds
it. A script that has checked the output gives `--yes`.

`--to` takes what [`harness share`](/docs/learn/while-working/) takes:

- `github:OWNER/REPO` or `github:OWNER/REPO#FOLDER`: a repository it creates is **private**
  unless you give `--public`.
- `git:URL#FOLDER`: any git remote.
- `USER@HOST:FOLDER`: an archive copied with scp.
- a folder or `.tar.gz` file on this computer.

The package's `package.toml` declares `[provides] identity`, and its README holds the line
that adopts it.

### A character card

```sh
harness agent share default --card --to yu.png
harness agent share default --card --to yu.json
```

`--card` writes a Character Card V3 with only the name and the persona: as JSON, or inside
the avatar PNG (which needs `avatar.png` in the identity folder). Skills, reactions and memory
are not in a card.

## Adopt an identity

```sh
harness agent adopt github:friend/study-buddy
harness agent adopt ./study-buddy.tar.gz --id buddy
harness agent adopt card.png
```

Adopting gives a **new identity**: a new id (from its name, or `--id`), a new key pair, and
`adopted.json` in its folder saying where it came from. Someone else's skills are programs you
do not know yet, so every adopted skill starts as *proposed* and its program is not used until
its own test passes on your computer:

```sh
harness agent adopt --test --identity buddy
```

A skill whose test passes is *own test passed* and is used from then on; one that fails or has
no test stays proposed. Adopted reactions start **disabled**; enable them one by one in
Settings › What it learned or with `harness library`. A character card gives a name, a persona
(`SOUL.md`) and, for a PNG card, the avatar; its other fields are ignored.

## Back up and restore

```sh
harness agent backup default -o yu.harness-backup
```

The backup holds the whole identity: persona, memory, conversations, learning library,
reactions, calendar, spending record, its private key and this identity's channel credentials.
The model keys are shared by all identities and go only with `--with-keys`. It asks for a
passphrase twice; a script sets `HARNESS_BACKUP_PASSPHRASE`. Keep the file private: anyone
with it and the passphrase can be this identity.

The file is encrypted with the standard library only: scrypt derives two keys from the
passphrase and a random salt, HMAC-SHA256 in counter mode encrypts, and an HMAC-SHA256 tag
over the whole file is checked before anything is decrypted. A wrong passphrase or a changed
file is refused as a whole and nothing is written.

```sh
harness agent restore yu.harness-backup
```

Restoring asks for the passphrase, puts the identity back with the same id and the same key,
adds model keys it holds that this computer does not have yet, and lists the channels to log
in to again. An identity of the same id already here is refused unless you give `--replace`;
the one that was there is kept aside in `agents/.ID.before-restore-TIME`.

## Move to another computer

Two computers have no coordinator, so moving is explicit:

1. On the old computer: `harness agent backup default -o yu.harness-backup`.
2. On the new computer: `harness agent restore yu.harness-backup`, then log in to its
   channels again. QQ and similar channels allow an account online in one place, so the old
   computer's connection drops.
3. On the old computer: `harness agent retire default`.

Retiring writes `retired.json` in the identity folder. The resident service no longer starts
it, a running host pauses it, and opening it there afterwards (`harness agent`, `harness
--identity`, the app, `Agent("default")`) says it has moved. Its files stay. Restoring a
backup on that computer brings it back.

To change the model instead, pick another one for the identity in Settings › Model, or tell it;
`/model` changes the model of one chat only. Persona, memory, skills and reactions stay.

## Bring an agent over from OpenClaw or Hermes

```sh
harness agent import openclaw
harness agent import hermes ~/.hermes/profiles/coder
```

Without a folder it reads where each keeps its agent: OpenClaw's workspace
(`OPENCLAW_WORKSPACE_DIR`, else `~/.openclaw/workspace`) and the Hermes profile (`HERMES_HOME`,
else `~/.hermes`). The first opening of the app offers the same as "bring it over".

| From | Persona | Memory | Skills |
|---|---|---|---|
| OpenClaw | `SOUL.md`, `IDENTITY.md` (name), `AGENTS.md` (as instructions in `SOUL.md`), `USER.md` | `MEMORY.md` and `memory/*.md` | `skills/*/SKILL.md` |
| Hermes | `SOUL.md`, `profile.yaml` (display name), `memories/USER.md` | `memories/MEMORY.md` | `skills/**/SKILL.md` |

Memory becomes entries in `memory/`, private, at most 1200 characters each. Skills come as
*proposed*. Configuration, `.env`, `auth.json`, OpenClaw's `credentials/` and Hermes's platform
state are never read, so no channel token or key comes along and one token is never used by
two agents at once. Afterwards it suggests stopping the original agent (`openclaw gateway
stop`, `hermes gateway stop`) before you connect its channels to the new identity.

## In Python

```python
from harness.sdk import Agent

yu = Agent("default")
yu.share("./shared", confirm=lambda preview: True)
yu.backup("yu.harness-backup", "a long passphrase")
buddy = Agent.adopt("github:friend/study-buddy", test=True)
Agent.restore("yu.harness-backup", "a long passphrase")
```

`share` sends nothing unless `confirm(preview)` returns true; the preview lists every public
text under `texts`.

## Data from earlier versions

The first time this version opens your data it keeps every original file, so going back to the
earlier version still works:

| Earlier data | Where it goes |
|---|---|
| instructions in `agents/ID/identity.json` | `SOUL.md`; `identity.json` keeps what the earlier version reads |
| `agents/ID/memory.json` | one file per entry in `memory/`, private, indexed in `MEMORY.md` |
| `agents/ID/library/` | this identity's learning library, as it is |
| global libraries in `$HARNESS_HOME/libraries` | stay global, shown as shared libraries, read only |
| conversations of the terminal chat and the app | listed under `default` as earlier chats: read only, continued as a new chat |
| `agents/ID/sessions` | this identity's earlier conversations |
| `personal.about` and `personal.instructions` | `USER.md` and `SOUL.md` of `default` |
| `harness agent "TEXT"` | `harness agent say "TEXT"`; the old form works for one release |
