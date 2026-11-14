---
title: "Write reflexes"
description: "The reactive layer is one tree: a node says when it has its turn and what it does, set with one call; facts, senses, priority."
---

An agent does two kinds of things. It answers what happens to it and around it, and is
then where it was. And it sets out to make something the case that is not. The first is
the **reactive layer**: a tree of reflexes that acts by itself, all the time, without the
model. The second is the model's, done by its programs and over when it is done. The tree
never sets out for anything.

What decides which kind a behaviour is, is how it begins, not what comes of it: a reflex
begins because a condition came to hold by itself (the agent is hurt, something it needs
is within reach). A way of doing something that the agent has learned is kept as a skill
the model calls, however often it is used: it is not a node.

A run is one model and the **units** it starts. A program the model writes is a unit, and
so is code a program starts with `spawn` and the program of a reflex. Units run beside
each other, each with its own output and result. Nothing runs on time unless a reflex asks
for it: a task that sets none has no clock at all.

## One tree

What acts without the model is one tree, empty at first. There is one call, and it puts a
node into the tree:

```python
set_reflex(name, when, do=None, under=None, priority=0, every=None, again_seconds=0, ends=False)
```

A node says **when** it has its turn and what it **does** then. Any node may have nodes
under it. Four statements are the whole of it:

1. A node under another has its turn only while that one's condition holds, and before
   it: while a node under it is answering, the node itself does not act. What the node
   does itself answers what is in its situation and in none of those under it, and gives
   way when one of them begins.
2. Among the nodes at one place the earlier takes the environment from the later, and
   gives it back when it is done.
3. A node has done its work when the situation it answers is over. When its program ends
   and the situation is not over, or the program fails, what comes after it has the
   environment: a later node at that place whose condition holds, then what the node
   above does itself. When nothing has, the model is told what the program did.
4. A node that tells the model has its turn like any other: it tells when neither a node
   before it at its place nor one under it is answering.

```python
def step_back(): ...
def refill(): ...

set_reflex("too_close", lambda view: view["distance"] < 0.2, step_back, priority=2)
set_reflex("refill", lambda view: view["level"] < 0.2, refill, priority=1, again_seconds=10)
```

- **when** is a function of the view: the node has its turn while it holds. Or it is the
  name of an event: the node answers that event when it happens, and the model is not told
  of it then.
- **do** is what the node does:
  - a program (a function): started as a unit when the node's turn comes. What it is for
    is that the node's condition no longer holds. It begins again while the turn lasts,
    not before `again_seconds` after it ended. A program that answers an event gets the
    event when it takes an argument.
  - the name of an event: the model is told it, once each time its turn comes: its
    condition holds and no node under it or before it at its place is answering. So a
    node that tells, tells what nothing answered, and no more.
  - `"stop"`, or another action the environment names: what runs is ended. Such a node is
    judged at every step of an execution.
  - nothing: only the nodes under it answer.
- **under** makes the node a narrower situation within another. A node may be put under
  any node whose `when` is a condition, whatever that node does itself, and that node is
  not set again: the tree grows by adding.
- **priority** (a whole number, 0 or more) is the node's own, wherever it is in the tree.
  Of two nodes whose turn it is the higher has the environment, among equals the earlier
  in the tree; and it is the number a program's `at_priority(n)` is compared with.
- **ends** says what becomes of the unit the node's program takes the environment from.
  `False` (the default): it is resumed where it stopped when the program is over. `True`:
  it is ended there, and the model is told at once which node took the environment, from
  which unit, and the state. A node that only adds to the agent's condition leaves what
  it interrupted able to go on; one that changes what that relied on ends it.
- **every** is the seconds between judgements of its condition. Without it the condition
  is judged when the state or the facts change.

`reflexes()` gives the tree as it stands, each node with whether its condition holds,
whether its program runs, how often it began and the report of its last run. `drop_reflex(names=None)` removes nodes with the nodes under
them. Setting a node of a name that exists puts the new one in its place.

## Designing the tree

The tree is designed as a whole, not grown from what went wrong last. While the model is
not looking, the tree is all that answers for the agent, so what it does not cover has
nobody. Before relying on it, the model names every kind of thing that can happen to the
agent where it is going to be (to its condition, to where it stands, from what is around
it, to what it is doing). The tree divides all of that. A node is a situation: its
condition says when the agent is in it, by what is happening to the agent, not by what
causes it. What the node does is its answer to the situation as such: something that fits
whatever the cause, or telling the model (`do="NAME"`). The nodes under it are the
narrower situations within it that the model knows a better answer for, each by its cause
or circumstance. While one of them answers, the node itself does not act; what is in the
situation and in none of them gets the node's own answer. So a node is complete from the
moment it is set, and what it learns later goes under it without changing it: the model
writes every node so. This holds at every depth, and how far a situation is divided
follows from how much the model knows of it. Design it from the top down. Begin with the
widest situations, each a respect in which something can be wrong for the agent, and give
each its node; then divide each into the narrower ones the model already knows. What
several conditions have in common is judged once, in the node above them, and each of them
says only what distinguishes it there. Prefer a deep tree to a wide one: a node under
another is judged only while that one's condition holds, so the narrow costs nothing while
the wide is quiet; and a wide node still answers the case the model did not list, where a
row of cases has no node for it. A new node goes under the narrowest node whose situation
it falls in, and to the top only when it falls in none. The unexpected has two forms, and
the tree tells the model of both. Something happens that no node answers. Or what should
happen does not: the agent goes on acting and what the action is for does not come; the
thing it should change stays as it was while time and supplies go. The second is as much a
situation of the agent as the first, and it is the one that passes unnoticed, because
nothing arrives. So for whatever is set going, a node watches what it is for, and tells
the model when that stays away longer than it would if things were as the model assumed.
Neither form may pass with no answer and without the model's hearing of it. What happens
to the agent whatever it is doing belongs in the tree, also when the model met it inside
one program: answered there, it is answered nowhere else.

Every turn the model is told how the tree stands, within a limit that does not grow with
the tree: how many nodes act in it and, of those that changed since it was last told, how
often each one's program began, did its work and did not (at most 10; an empty tree is
told as empty). `reflexes()` gives the nodes at the top, `reflexes("name")` the nodes
under one, at most 50 at a time.

## What several nodes share

Said once, in the place that fits:

```python
set_reflex("underground", lambda view: view["depth"] > 0, "UNDERGROUND")     # what none under it answers is told
set_reflex("gas", lambda view: view["sensed"]["gas"], leave, under="underground", priority=2)
set_reflex("dark", lambda view: view["light"] < 3, light_up, under="underground", priority=1)
```

- **A condition** that several nodes have in common is the node above them: it is judged
  once, they have their turn only while it holds, and what that node does itself answers
  whatever is underground and is neither gas nor darkness.
- **An action** shared by several nodes is a function they call: reuse is ordinary code.
  A function that sets a part of the tree under a given node puts the same part in
  several places.
- **What they see** beyond the reported state is a [sense](#senses), defined once and read
  by conditions and programs alike.
- **What they know** is in the [facts](#facts).

## Where a node stands to the model's programs

A node's program runs as a unit, and its priority is the node's own. Every
node is above the model's own programs (priority 0): a reflex takes the
environment from them. What the model pursues is the model's own program, not a node.

When a unit of higher priority needs the environment, what happens to the call of the
lower one depends on the environment:

- **An environment that pauses** (`"pauses": True` in its worker's profile, with the
  methods `pause` and `resume`: `core/worker.py`) holds the lower call where it is, and is
  told who takes it, so that what it holds can know when it goes on. The
  higher unit acts, and the call goes on when that unit has ended, in the same program and
  without a question to the model. The trace records `call_paused` and `call_resumed`.
- **Elsewhere** the lower call ends where it is with the event `PREEMPTED`. When it was a
  node's program, the node begins again by itself when its turn comes. When it was a
  program of the model, the model is told at once and decides what goes on; a unit
  started with `spawn(fn, restart=True)` has its call made anew by itself.

The embodiment's kind lists `pauses` in `prompt_features`, so the prompt says which of the
two holds. Where an environment divides its input into channels, units act at the same
time on the channels they took.

### A program's place among the reflexes

The model's programs have priority 0: every reflex takes the environment from them. An
action of a program that must not be broken off takes a place among the reflexes for as
long as it lasts, and no longer:

```python
with at_priority(70):    # above the reflexes of priority below 70, below the rest
    close_the_gate()     # only this action
watch_the_road()         # priority 0 again: every reflex has its turn
```

During the block the program holds the environment with that priority. A reflex whose
own priority is 70 or more still takes the environment from the program, wherever the
node is in the tree: the number is compared with the node that runs, not with the node
it is under. One below does not act meanwhile: it is judged again when
the block ends, and the model is told once that it was held back (the event `HELD_BACK`).
The place is the action's, not the program's or a stage's: while it is held nothing below
it answers what happens to the agent, so a program that holds one for its whole length
has taken the tree's work on itself. Outside a `with`, `at_priority(n)` holds nothing and
says so in the program's output. What still ends the program: cancelling it, the time of
its calls, a node that ends what runs, the end of the episode.

Code that runs for long in the environment itself (a routine the agent saved there) asks
for a place the same way: its worker reports `"priority"` with its state for as long as
that code asks for one, and the unit whose call runs holds the environment with it
(`core/worker.py`).

### What a condition sees

A condition reads the view: the state as it is, the facts (`view["facts"]`), the senses
(`view["sensed"]`), and what a state alone does not show:

| | |
|---|---|
| `view["was"][key]` | what that part of the state was before it last changed (the senses under `["sensed"]`) |
| `view["unchanged"][key]` | for how many seconds it has not changed |
| `view["units"]` | the units that run, each `{"name", "kind", "reflex", "priority", "seconds"}` |

With these a node can say that something is changing for the worse, or that what should
change does not while a program runs.

## How a unit ends

Every unit ends with the same report, whoever started it: a program of the model, code it
spawned, a node's program.

| Field | What it says |
| --- | --- |
| `ended` | How it ended: by itself, an error, an event, cancelled, its time limit. |
| `done` | Whether what it was for is the case, judged on the view when it ended. Nothing where it stated no condition. |
| `returned`, `error`, `seconds` | What it gave back, or why it failed. |

How it ended and whether it is done are two things: a unit that ended by itself has not
done its work when what it was for is not the case. What a unit is for is its
**completion condition**, a function of the view:

```python
until(lambda view: view["door"] == "open")     # in a program: what this program is for
spawn(fill, until=lambda view: view["level"] > 0.8)
```

A node's program needs none: what it is for is that the node's condition no longer holds.
An execution has its own (`until=` of a controller).

The report goes to who started the unit. The model's programs report to the model. A
node's program reports to the tree, which acts on `done` alone.

## What the model is told

The tree's own programs are its own business: their ends are recorded (`unit_end`, the
`rule` record when one begins), and one that has done its work starts no call of the
model. The model is told:

- the event a node raises (`do="NAME"`);
- that a node's program ended with its situation not over, or failed, and no later node at
  its place took the environment (the event `REFLEX_FAILED` with the program's report,
  once until that node has done its work again). A node whose program failed does not
  begin again for 2 seconds;
- that a node was held back by a program that is not interrupted;
- an event no node answers.

## Facts

`facts` is what the run knows, shared: a small store of named values that programs read
and write and that conditions read as `view["facts"]`.

```python
facts.set("door", "open")
facts.get("door", "closed")
facts.drop("door")
```

Values are plain data (numbers, text, lists, dicts). Keep progress in facts: a program
that was ended and started again then goes on from what was done, not from nothing.

## Senses

A condition reads the view and makes no calls, so it sees only what the environment
reports. Where the environment can run code where it is (a game's bot, a page's script),
the model defines what else it reports: a sense is a named piece of code in the
environment's own language, computed by the environment each time it reports its state.

```python
sense("edge_ahead", "...code in the environment's language...")   # {"value": ..., "error": ...}
set_reflex("edge", lambda view: view["sensed"]["edge_ahead"], step_back)
get_state()["sensed"]["edge_ahead"]                                # the same value, in a program
senses()                                                           # those defined, with code and values
drop_sense("edge_ahead")
```

One definition serves conditions and programs alike, and the judgement stays as fast as
it was: the value is in the state when the condition is judged.

A worker offers senses by saying `"senses": True` in its profile and serving `sense`,
`senses` and `drop_sense` (`core/worker.py`); its state then carries `"sensed"`. The
embodiment's kind lists `senses` in `prompt_features`, and its prompt says which language
the code is in and what it has in scope.

## Controllers

`run_controller(fn, until=None, max_seconds=None)` applies the command `fn(view)` returns
for each step, for visual servoing and other fast loops. It is a bounded execution: a
node that ends what runs applies to it, and it ends with an event.

## The limits of a condition

Conditions and controllers must be fast and may not open files, use the network, start
processes, sleep or call a model. They share one budget per period,
`runtime.reactive_budget_ms` (5 ms by default). A node the period had no time for, because
the ones before it used the budget up, is no fault: it keeps what it was and is judged in
the next period. A condition that takes longer than the budget once is a moment of the
machine: its answer counts, and one that had to be ended (at four times the budget) keeps
what it was until the next period. One that does so three times in a row, or that raises or breaks
the restrictions, produces a `REACTIVE_FAULT` event, and its node is removed with the nodes
under it. A node's program is ordinary code and has no such limits.

Every command still goes through the environment's own checks, which reject commands
that are malformed or out of range, whoever wrote them. A delayed command can be vetoed
before it is sent. Once sent, its receipt belongs to the execution that sent it. A lost
receipt does not cause an automatic retry.

## In a skill and in a library

A skill puts nodes into the session's tree, `self.reactive`, with the same call:

```python
class Footing:
    def keep_footing(self):
        """End whatever moves when the ground ahead is gone."""
        self.reactive.set("no_gap", lambda view: view["ground_ahead"] is False, "stop")
```

A reactive entry of a library is the lines that set its nodes (`set_reflex(...)`, with
the functions they use): they are run when a session starts, once the entry's test has
passed. With `knowledge = "learned"`, the agent starts without a package's handwritten
reflexes and learns its own ([Let it learn an environment](/docs/learn/learn-an-environment/#games-learned-or-handwritten)).
