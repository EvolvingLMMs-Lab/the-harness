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

## The resident life and its chats

The agent is a resident service, not an app: the session host runs every identity's life
(this package's `background` service, `life.py`), and its `keep_alive()` holds the host up
while one is alive. `harness` in a terminal, the command line, `harness.sdk`, the app and chat
channels attach to the same life.

- **Chats.** The main conversation is the owner's private chat with it; the owner's private
  chat in QQ or another channel is the same conversation, each message labelled with its
  channel, and the answer goes back there. Every connected place (`places.json`: a space
  such as a QQ account, a project folder, a browser, the desktop) is a chat of its own, one
  per group inside a channel; its events, reactions, actions and outcomes are recorded there
  and new ones mark it in the list. "New chat" makes a chat for one piece of work.
- **One queue.** Input from every frontend (`POST /api/agent/say`) joins one queue in
  arrival order. Chats run their turns in parallel; within one chat the next waits. The
  desktop has one body: other chats wait for it, shown as `waiting: desktop`.
- **Events.** What a place pushes goes into its chat's record first; an event aimed at it,
  or an outcome failed or unknown, wakes the model for that chat. Its own messages trigger
  nothing.
- **Pause and quit.** Paused, the model is not woken and nothing runs; places stay
  connected, events are recorded and handled after resuming. When the host quits, actions in
  progress end as cancelled where they can be cancelled and unknown where not.
- **Restarts.** What was queued and not done is kept in `life-state.json` and done after a
  restart; every chat continues from its record. On waking, events older than
  `agent.stale_hours` (6) reach the model as one summary and it judges what still deserves an
  answer.

The host API: `/api/agent/life`, `/api/agent/chats`, `/api/agent/chat?chat=&after=` (the
record after a number), `/api/agent/say`, `/api/agent/opened`, `/api/agent/new_chat`,
`/api/agent/pause`, `/api/agent/resume`, `/api/agent/places`.

## Always working: the tree of reactions and waking the model

Each identity has one tree of reactions (`reactions.json`, `reactions.py`), judged by its
life from the root whenever the world changes or a time comes, whether or not anything runs,
anyone asks or budget is left. The core's behaviour tree (`Reflexes.select`) judges it: the
nodes at a place in order, the first whose condition holds is gone into, narrower nodes
first, so position is priority and an earlier node interrupts what a later one does.

- A node is a condition (an event of a place and its fields, an outcome, a fact of the
  moment such as `battery` or `working_in`, and all/any/not of these; a situation also says
  when it is over), an answer (call a skill, wake the model, stop, remind the owner, or
  nothing; stopping may come with a reminder), and a position (the node it hangs under and
  its place there). A situation's own answer comes when it comes; events are answered by
  the nodes for events, inside the situations that hold.
- Three nodes ship and can be disabled, not deleted: named or aimed at it → wake it; an
  action ended failed or unknown → wake it; needs approval → remind the owner.
- What the owner says becomes a node at once (`added by owner`) when it is an objective
  reaction needed even when the agent is passive; the model picks the branch it fits best.
  Anything else is a preference, kept as a memory.
- The model is woken on objective conditions only: what happens to it that needs
  understanding (the owner speaks, it is named, an action is refused or fails, something the
  tree cannot answer), and what it wants to do itself coming due: an intention it left (at a
  time, after some minutes, or once an event happens; `intentions.json`), the calendar,
  practice, events piling up in a place (20, or 4 hours old). Awake it decides whether to do
  something and what, and leaves intentions before it ends. Otherwise the model does not run.
- `agent.reserve` ($0.50) of the daily budget is kept for the owner's matters; its own work
  spends the rest, paced over the money and hours left today. When that is gone it is asleep:
  the tree still runs, events are recorded, the owner can still wake it, and the rest waits
  for 0:00, whose reset wakes it for what piled up. `agent.proactive` (on, learn_only, off)
  and "pause on its own" (`/api/agent/own`) stop only what it wants to do itself.

`/api/agent/tree?path=a/b` lists one level of the tree like a folder (each node with its
evidence, uses, how many nodes it holds and whether it is on the path of the node that last
took over); POST adds, moves, enables, disables or removes a node.

## Who can direct it: the safety layer, approvals and notifications

Every action passes a safety layer of fixed rules (`safety.py`) before it runs; it is not
the agent's judgement and cannot be unlearned, and a refusal reaches the agent as the
outcome "refused" with the reason; what to do after it is the agent's own judgement.

- Its input on the desktop is refused while the owner is using it (the computer package
  tells the owner's input from the agent's; it is on for every desktop task of an identity).
- Sending, publishing, paying, deleting and steps that cannot be undone run only with the
  owner's approval; logging in is left to the owner. What counts as sending is declared by
  the environment's vocabulary (a verb's `effect`, and for a project folder the `[sending]`
  command lines of its space declaration: `git push`, `gh pr create`, publishing): replying
  in the chat where it was asked is not sending.
- Authority comes from the source of a turn, never the prompt: the owner (bound channel
  accounts, local frontends), its own initiative (one level less: only where the place's
  `spaces.<place>.proactive` is `do`, only in the chat's own place) and everyone else (only
  within the chat they are in; never the owner's computer, files or accounts; no
  approvals). A turn has the lowest authority of its sources; results go back only to the
  chat that asked.

An approval request (`approvals.py`) gets a short code: a card in the main conversation and
in its chat, a system notification, and a message in the owner's private chat of a bound
channel, where "A7 approve" or "A7 reject" answers it (parsed on the channel side, never by
the model). The first answer wins; unanswered for `approvals.timeout_minutes` (30) it ends as
cancelled, never as done. System notifications are only for approvals, the spending limit
reached, actions that failed or ended unknown, and an expired channel login
(`general.notifications` switches them): `/api/agent/approvals`, `/api/agent/notifications`.

## The calendar and the morning summary

An ordinary calendar per identity (`calendar.py`): the owner and it both put things on it
(goals, tasks, reminders, what it arranged for itself; once, daily or weekly), and it shows
when it did what: every turn (begun by the owner, or by it on its own), each reaction of the
tree, how they ended, what the safety layer refused, and when it was asleep. A planned entry
coming due wakes it (the owner's on the reserve); one missed while the computer was off is
taken up once after startup, for its latest time only. When the owner moves or removes
something it planned, or says "don't do this kind of thing", it becomes a private memory that
shapes later decisions. Every morning (after 6:00) the summary of the stretch, what it did,
learned and spent and what waits for approval, goes into the main conversation and
`DREAMS.md`. `agent.proactive`, "pause on its own" and `spaces.<place>.proactive` (off,
learn, do; by default do for folders and browsers, learn for the desktop, off for chat
groups unless the owner gave it a goal there) say where it may act on its own.
`/api/agent/calendar`, `/api/agent/summary`, `/api/agent/settings`.

## Skills and learning

Learning is on by default and needs no switch (`learning.py`). A skill is a folder compatible
with agentskills.io's `SKILL.md` (a name, a one-line description, a body) that also holds our
program and its test (`skills/<name>/SKILL.md`, `program.py`, `test.py`); a learned skill's
code and its versions live in the identity's learning library. Someone else's `SKILL.md`
installs as a skill with instructions and no program, at evidence "proposed". Context holds
only names and descriptions; `read_skill` reads the whole text when used.

- Evidence: proposed, own test passed, replay passed, effective. "Effective" is a better
  score on development seeds where an environment is scored per episode; elsewhere 5 uses
  with at least 80% done. The library's demotion rule stays (3 uses under 25%: proposed).
- Admission by the environment: where actions have outside consequences a new skill is
  called only by the model by hand, and the tree calls it only once it is effective.
- When a turn ends and no event comes for 10 minutes, a background review proposes at most
  one thing: a skill (its own test runs first), a reaction (hung under the branch it fits),
  a memory, or practice, which it may choose to do on its own with budget left. Every day at
  0:30 dreaming merges duplicates, archives what went unused for 30 days (restorable), turns
  what it did by hand several times into a skill, and writes the day into `DREAMS.md`.
  Review and dreaming may use `learning.review_model` and count toward the daily limit.
- `learning.mode` per identity: on (takes effect at once and can be undone), review_first
  (waits for the owner), frozen (use without learning), off (nothing learned or loaded);
  replay_always stays an advanced option. Undo goes back to the previous version, or, with
  none, the skill is no longer loaded. `/api/agent/learned`.

## Spending

Each identity has a spending account (`usage/` in its folder, `harness.sdk.spending`):
the setting `agent.daily_budget` (default $2) and `agent.daily_calls` (default 500 calls
without a price), per identity with `harness usage --budget/--calls`, reset at 0:00 local
time. Every model call it makes is checked first: its dialogue's, and those of the tasks
it starts and their sub-agents (the run key `account`). Cost is OpenRouter's reported
cost, else an estimate from the model entry's `prices`; a local model costs $0 and counts
against the call cap, as does a provider with no prices. A call already made finishes; at
the limit the dialogue refuses with exit status 3 and a task's turn ends while its
programs go on. `harness usage [--week] [--raise-today DOLLARS]`, `/usage` and the status
line of `harness`, and `Agent.usage()`, `raise_today()`, `set_budget()` show and change it.

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
action. Memory entries have a scope: `private` entries appear only where the owner and it
are alone (the main conversation, new chats, the places the owner connected); `chat` entries
only in the chat they were written in. What other people say can only become `chat` memory.

The host extension exposes `POST /api/agent/dialogue` with `text`, optional `identity`,
`session`, `model`, `workspace` and `folder`; `/api/agent/identities` lists the identities and
`/api/agent/identity` creates, chooses, renames or deletes one. `/api/tasks`
remains the bounded task endpoint. With the host running, every writer to a chat joins its life's
one queue.
Memory updates use revision checks; an uncertain task submission is preserved and never
blindly retried. User approvals are answered through the task interface, not by the
dialogue model. `harness.sdk.Agent` gives the same in Python: `Agent(id)`, `Agent.new`,
`Agent.list`, `Agent.use`, `say`, `memory`, `chats`, `rename`, `delete`.

Session schemas are checked on opening; incompatible data is not silently reinterpreted.
Credentials are not stored in identity data.
