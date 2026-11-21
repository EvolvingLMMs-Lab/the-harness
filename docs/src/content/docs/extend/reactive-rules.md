---
title: "Write reflexes"
description: "The reactive layer is one tree: a behaviour tree whose nodes say when they act, what they do and when the situation is over, set with one call; facts, senses, order."
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
set_reflex(name, when, do=None, *, over=None, under=None, before=None, every=None, ends=False,
           tell=None, tell_failed="now", about=None, report=None, test=None, covers=None, claims=None)
```

A node says **when** the agent comes into its situation, what it **does** then, and when
the situation is **over**. Any node may have nodes under it. The tree is judged as a
behaviour tree: from its top, in order, each time it is judged. These statements are the
whole of it:

1. A node is a sequence: its condition, then its action. The condition decides only
   whether the action begins. Once begun, the action runs until it has a result, whatever
   the condition does meanwhile.
2. The result is success when the situation is past: `over` holds (the program is then
   ended there, its work done), or, for a node without `over`, its program returned and
   `when` no longer holds. It is failure when the program returned or raised and the
   situation is not past.
3. A node with nodes under it is a selector: the nodes under it in order, then what the
   node does itself. A node under another is judged only while the upper node is in its
   situation, and it goes first. What the upper node does itself answers what is in its
   situation and in none of those under it, and gives way when one of them begins.
4. Among the nodes at one place the earlier takes the environment from the later, and
   gives it back when it has its result. The order is the order the nodes were set in,
   unless a node says `before`. There are no priorities and no times.
5. A node that failed is not tried again in that occurrence of its situation, and nothing
   is tried again because time passed. What comes after it acts: a later node at that
   place that is in its situation, then what the node above does itself; when that fails
   too, the node above has failed. When a node at the top failed, the model is told
   (`REFLEX_FAILED`), once. A failed node may act again when its situation was past and
   has come anew (`over` held, or for a node without `over` its condition stopped holding;
   for a node under another, also when the upper node's situation was past), or when the
   node is set again.
6. A node that tells the model has its turn like any other: it tells when neither a node
   before it at its place nor one under it is acting, once for each occurrence.
7. Nothing of the tree is judged while the agent cannot act, and none of its programs
   begins then. The session's `can_act(state)` says whether it can (always, unless the
   environment says otherwise).

```python
def step_back(): ...
def refill(): ...

set_reflex("too_close", lambda view: view["distance"] < 0.2, step_back,
           over=lambda view: view["distance"] > 0.5)
set_reflex("refill", lambda view: view["level"] < 0.2, refill,
           over=lambda view: view["level"] > 0.8)
```

`too_close` was set first, so it comes first and takes the environment from `refill`.
`step_back` begins when the distance falls below 0.2 and is ended, its work done, when the
distance is above 0.5; if it returns before that, it has failed.

- **when** is a function of the view: the agent comes into the node's situation when it
  holds, and the node's action begins as soon as it holds and the node's turn has come. It
  decides only whether the action begins. Or it is the name of an event: the node answers
  that event when it happens, and the model is not told of it then.
- **do** is what the node does:
  - a program (a function): started as a unit when the node's turn comes. Once begun it
    runs until it has a result: it returns, it raises, or `over` comes to hold. It is not
    started again in that occurrence of the situation. A program that answers an event
    gets the event when it takes an argument.
  - the name of an event: the model is told it, once for each occurrence, when its
    condition holds and no node under it or before it at its place is acting. So a
    node that tells, tells what nothing answered, and no more.
  - `"stop"`, or another action the environment names: what runs is ended. Such a node is
    judged at every step of an execution.
  A node set by the model with nothing to do is refused. A node that answers a situation
  has a program, and so has a node above others: its program is the fallback of its whole
  situation, for what is in none of the narrower ones and for when one of them acted and
  failed. The name of an event is for a node that watches what a program is for; it is
  not an answer to a situation.
- **over** is a function of the view that holds when the situation is past. It is
  another question than `when`: `when` says when the action begins, `over` when its work
  is done (something that came too near is not past the moment it is one step further
  off). While the program runs and `over` comes to hold, the program is ended there, its
  work done, and gives the environment back at once. A program that returns while `over`
  does not hold has failed. The action does not begin while `over` holds. Without `over`,
  the work is done when the program returned and `when` no longer holds (nor the condition
  of a node it is under): give `over` wherever the action itself changes what `when` reads.
- **under** makes the node a narrower situation within another. A node may be put under
  any node whose `when` is a condition, whatever that node does itself, and that node is
  not set again: the tree grows by adding.
- **before** is the name of a node at the same place (under the same node, or at the
  top): this node comes just before it. Without it a node comes after those set there
  earlier. Of two nodes in their situations the earlier has the environment, and a node's
  place is what a program's `at_priority("name")` refers to.
- **ends** says what becomes of the unit the node's program takes the environment from.
  `False` (the default): it is resumed where it stopped when the program is over. `True`:
  it is ended there, and the model is told at once which node took the environment, from
  which unit, and the state. A node that only adds to the agent's condition leaves what
  it interrupted able to go on; one that changes what that relied on ends it. A node that
  tells (`do="EVENT"`) may say `ends=True` too: what runs then ends with that event, which
  is how the model is told. The tree is there to act in time: telling the model is for
  what no action is known for, since its reply takes seconds.
- **tell** says what the model hears when the node's program has done its work, which
  each node decides for itself. `"never"`: nothing; the tree's line counts it. `"first"`
  (the default): the first time only, with the model's next call. `"later"`, `"next"` or
  `"now"`: every time, as a notice at that place in the model's queue; only `"now"` sets
  the reply the model is writing aside. For a node that tells an event, `tell` is the
  place of that event in the queue (`"now"` by default). The event of a program that did
  its work is `REFLEX_ACTED`.
- **tell_failed** says what the model hears when the node's program did not do its work
  and nothing else took the situation (a later node at its place, then the node above
  with its own program): `"now"` by default, or `"next"`, `"later"`, `"never"`. The
  event is `REFLEX_FAILED`.
- **about** and **report** are what the model reads when it is told of the node, written
  by the model when it sets the node. `about` is one sentence: the situation the node
  answers. `report` is the message the model reads when it is told of the node, written
  for that node's situation: what it will need then to judge whether the situation is over
  and to decide what to do next. It is a function, called as `report(view, returned)`, that
  returns text, plain data, a picture (what `look(...)` returned, or an image), a file (a
  `pathlib.Path`), or a list of these. A node that tells the model anything (every
  node but one with `tell="never"` and `tell_failed="never"`) needs both and is refused
  without them. The message is in words: the node with its sentence and how its program
  ended, which program it took the environment from (how often, for how long), the node's
  report, and that program's own report.
- A program says the same of itself: `until(condition, report=..., interrupted=...)`.
  `report` is a function of the view; what it returns is told whenever the model hears of
  the program (while it runs, when a reflex takes the environment from it, at its end).
  `interrupted` says what happens then: `"tell"` (the default: the program goes on and the
  model is told, in the same message as the node's; three times for one program, the rest
  counted and told with its end), `"stop"` (the program ends there and the model is told at
  once) or `"never"`.
- **test** is a trial of the node, where the model wants one; none is required. A
  function that brings the node's situation about is run at once, with the node already
  in the tree, and `set_reflex` returns what it showed: whether the node had its turn,
  how long that took, and for a node with a program whether the situation was then over,
  which the node's own condition says. The trial checks the node's goal in one ordinary
  case, and a node that reached it has passed.
- A node has to be able to run: when the model sets one, its condition is judged once on
  the state as it is (a node under others: while the conditions above it hold), and a
  condition that raises is refused. Before the first node of a run the model reads the
  page on how a tree is designed and set (`guide("tree")`, which also has every setting of a node; the core
  prompt has one line for each call and leaves the details to such pages), and `set_reflex` is
  refused until it has; after a summary of the conversation the page is named, and read again with
  `guide("tree")`.
  `runtime.reflex_method = "optional"` turns these three off (the page, a node that does
  nothing, the judging of a condition when it is set).
- **every** is the seconds between judgements of its condition. Without it the condition
  is judged when the state or the facts change (the state is read every period, whether a
  program runs or not).
- **covers** names the lines of `situations(...)` this node answers, each by its text or
  by its number (1 for the first). `situations(*lines)` is where the model lists what can
  happen to the agent during the whole task; it returns the lines no node answers yet.
- **claims** names the channels the node's program uses, where the environment pauses and
  declares channels: the program takes only those, and what runs on the other channels
  goes on beside it. Without it the program takes the whole environment.

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
set_reflex("gas", lambda view: view["sensed"]["gas"], leave, under="underground")
set_reflex("dark", lambda view: view["light"] < 3, light_up, under="underground")           # after gas
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

A node's program runs as a unit, and the unit's priority is the node's place in the tree:
the earlier the node, the higher. Every node is above the model's own programs: a reflex
takes the environment from them. What the model pursues is the model's own program, not a node.

When a unit of higher priority needs the environment, what happens to the call of the
lower one depends on the environment:

- **An environment that pauses** (`"pauses": True` in its worker's profile, with the
  methods `pause` and `resume`: `core/worker.py`) holds the lower call where it is, and is
  told who takes it, so that what it holds can know when it goes on. The
  higher unit acts, and the call goes on when that unit has ended, in the same program and
  without a question to the model. The trace records `call_paused` and `call_resumed`.
  Where such an environment also declares channels, a node that says `claims` takes only
  those channels: calls on the other channels are not held.
- **Elsewhere** the lower call ends where it is with the event `PREEMPTED`. When it was a
  node's program, the node acts again when its turn comes. When it was a
  program of the model, the model is told at once and decides what goes on; a unit
  started with `spawn(fn, restart=True)` has its call made anew by itself.

The embodiment's kind lists `pauses` in `prompt_features`, so the prompt says which of the
two holds. Where an environment divides its input into channels, units act at the same
time on the channels they took.

### A program's place among the reflexes

The model's programs come after every node of the tree: every reflex takes the
environment from them. An action of a program that must not be broken off takes a place
among the reflexes for as long as it lasts, and no longer:

```python
with at_priority("too_close"):   # the place of the node too_close
    close_the_gate()             # only this action
watch_the_road()                 # after every node again: every reflex has its turn
```

`at_priority(node=None)` takes the name of a node, or nothing. During the block the
program holds the environment with that node's place: that node and the nodes before it
in the tree still take the environment from the program; the nodes after it do not act
meanwhile. Each of those is judged again when the block ends and acts if it is still in
its situation, and the model is told once that it was held back (the event `HELD_BACK`).
Without a name the program holds the environment above every node. A name that is no node
of the tree is refused.
The place is the action's, not the program's or a stage's: while it is held nothing after
it answers what happens to the agent, so a program that holds one for its whole length
has taken the tree's work on itself. Outside a `with`, `at_priority(...)` holds nothing and
says so in the program's output. What still ends the program: cancelling it, the time of
its calls, a node that ends what runs, the end of the episode.

A step that must not be interrupted is wrapped in `atomic(seconds=5)`, and only that
step, as small as it can be:

```python
with atomic():                   # no node takes the environment during it
    swap_the_parts()             # the step, and no more
```

It is `at_priority()` without a name (above every node) for `seconds` at most: past them
the nodes may take the environment again, and the program's output says so when the
block ends. Code that runs in the environment may have its own atomic for a step inside
it, where its page says how.

Code that runs for long in the environment itself (a routine the agent saved there) asks
for a place the same way: its worker reports `"priority"` with its state for as long as
that code asks for one (the name of a node, or `True` for above every node), and the unit
whose call runs holds the environment with it (`core/worker.py`).

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

A node's program needs none: what it is for is that the node's situation is past (`over`,
or without it that `when` no longer holds).
An execution has its own (`until=` of a controller).

The report goes to who started the unit. The model's programs report to the model. A
node's program reports to the tree, which acts on `done` alone.

## What the model is told

The tree's own programs are its own business: their ends are recorded (`unit_end`, the
`rule` record when one begins), and one that has done its work starts no call of the
model. The model is told:

- the event a node raises (`do="NAME"`);
- that a node's program returned with its situation not past, or raised, and neither a
  later node at its place nor the node above took the situation (the event `REFLEX_FAILED`
  with the program's report, once until that node has done its work again). The failed
  node is not started again in that occurrence of its situation;
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
what it was until the next period. A fault never removes a node. A condition that raises
or breaks the restrictions does not hold that once, and its node is judged again the next
time. One that is too slow three times in a row is set aside, because it would use up
every period the nodes after it share: its node stays in the tree and is not judged, nor
are the nodes under it, until the node is set again. Either way the model is told what
went wrong, once for each reason (a `REACTIVE_FAULT` event), and the node's line says how
often. A node's program is ordinary code and has no such limits.

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
the functions they use): they are run when a session starts. An agent that proposes one
gives no test with it: the entry is kept on the trials its nodes had when they were set
in the tree, nothing of it is run again, and lines that set a node otherwise than it is
in the tree are not kept. With `knowledge = "learned"`, the agent starts without a package's handwritten
reflexes and learns its own ([Let it learn an environment](/docs/learn/learn-an-environment/#games-learned-or-handwritten)).
