# Persistent agent

The optional agent package owns identities: an agent that lasts, with a name, a persona,
private memory, conversations and a learning library of its own. The Harness core
independently performs natural-language tasks, benchmark episodes and learning; it never
imports this package.

```sh
harness agent new work --name "工作助手"
harness agent use work
harness agent say "Remember that PRs must be in English"
harness agent say "Continue our discussion" --session SESSION_ID --json
harness agent --folder ./project
harness agent list -v
harness agent about
harness agent rename "小林"
harness agent memory
harness agent delete work
harness --identity work
```

## Identities

An identity has a fixed `id` (letters, digits, `_` and `-`; its folder name; the first one
is `default`) and a display name in `IDENTITY.md`, in any language, changed with
`rename`. Its folder `$HARNESS_HOME/agents/<id>/` holds `SOUL.md` (persona, read every
turn), `USER.md` (its owner, read every turn), `MEMORY.md` and `memory/` (one Markdown
file per entry, at most 1200 characters, scoped private), `library/`, `sessions/` and
`identity.json` (format, public key, model choice). Its Ed25519 key pair is made on
creation; the private key is kept in `agents/.keys/<id>.json`, readable by the user only,
and never shared; `about -v` and `list -v` show the fingerprint.

`new ID --from OTHER` clones persona, skills and reactions, never memory. `new ID --card
FILE` reads a Character Card (V3, V2, V1; PNG or JSON): name into `IDENTITY.md`;
description, personality and system prompt into `SOUL.md`; a PNG card is the avatar.

Every command acts on `--identity`, else the current identity (`use`), else the only one.
With several identities and none chosen, a terminal asks and a script fails; nothing is
guessed. `harness agent "TEXT"` is the earlier form of `say` and works for one release
with a notice. `harness`, the core terminal chat, runs as the identity this package
resolves (`identity` in its host module) and records it with each conversation.

One identity lives in one host at a time: the process that runs it holds
`agents/<id>/.life.lock` and names itself in `life.json`. A process of the same data
directory attaches to that life; one of another data directory is refused until the
holder ends. The system releases the lock of a process that died.

## Upgrading earlier identities

The first opening migrates an identity of schema 1: `instructions` into `SOUL.md`, each
`memory.json` entry into `memory/` (private, same revision), and for `default` the
Personalization settings not yet imported into `USER.md` and `SOUL.md`. Nothing is
removed: `identity.json` keeps schema 1 and its `instructions` (the original bytes are
copied to `identity.v1.json`), `memory.json` and
`sessions/` stay, and the earlier version still opens them. Global libraries stay where
they are; use `--library PATH` in a task to bind one explicitly.

## Dialogue and tasks

The agent handles ordinary dialogue itself and submits complete tasks through `Host.task`.
Tasks keep their own program/controller loop, budget, evidence and resource cleanup, and
carry the identity they belong to. A finished task is not automatically a verified
success. Learning writes the identity's library only when explicitly enabled;
remembering a preference does not activate executable code. A session stores raw
dialogue events plus a bounded working context and explicit summary; new sessions keep
memory but do not concatenate earlier conversations; history search is an explicit
action.

The host extension exposes `POST /api/agent/dialogue` with `text`, optional `identity`,
`session`, `model`, `workspace` and `folder`; `/api/agent/identities` lists the identities and
`/api/agent/identity` creates, chooses, renames or deletes one. `/api/tasks`
remains the bounded task endpoint. Concurrent writers to the same dialogue are refused.
Memory updates use revision checks; an uncertain task submission is preserved and never
blindly retried. User approvals are answered through the task interface, not by the
dialogue model. `harness.sdk.Agent` gives the same in Python: `Agent(id)`, `Agent.new`,
`Agent.list`, `Agent.use`, `say`, `memory`, `chats`, `rename`, `delete`.

Session schemas are checked on opening; incompatible data is not silently reinterpreted.
Credentials are not stored in identity data.
