---
title: "Write reactive rules"
description: "Rules: a condition, a priority and a program, started without asking the model; facts; event handlers."
---

The model is called when there is something to decide, which takes seconds. Some things
cannot wait that long. **Rules** handle them: a rule is judged without the model, from
what the agent sees, and acts at once.

A run is one model and the **units** it starts. A program the model writes is a unit, and
so is code a program starts with `spawn` and the program of a rule. Units run beside each
other, each with its own output and result. Nothing runs on time unless a rule asks for
it: a task that sets no rule on time has no clock at all.

Programs set rules, the agent can learn them ([Learn while it works](/docs/learn/while-working/)),
and a package can ship them. Programs call `rule`, `when`, `watch`, `on`, `clear_rules`,
`facts` and `run_controller` through the core program API.

## A rule

```python
def refill():
    open_valve()
    facts.set("refills", facts.get("refills", 0) + 1)

rule(lambda view: view["level"] < 0.2, refill,
     ends=lambda view: view["level"] > 0.8,
     priority=5, name="refill", min_seconds=2, again_seconds=10)
```

`rule(begins, program=None, ends=None, priority=0, name=None, reads=None, every=None,
min_seconds=0, again_seconds=0, while_holds=False, raises=None)`:

- **begins**: when `begins(view)` comes to hold, the rule begins.
- **program**: what it starts then, as a unit of the rule's **priority**. A unit of higher
  priority takes the environment from units of lower priority ([below](#priority)).
- **ends**: when `ends(view)` comes to hold, the rule's own program is ended. With
  `while_holds=True` and no `ends`, the program is ended when `begins(view)` no longer
  holds. Without either, the program runs to its own end.
- **min_seconds** is the shortest time the program keeps going once begun, and
  **again_seconds** the time before the rule may begin again after its program ended.
  With separate conditions for beginning and ending, they keep a rule from switching back
  and forth at a boundary.
- The rules a rule's program sets live while that program does. A few rules at the top,
  each program with the rules that matter only while it runs: the units at run time are
  the decision tree. Order and branching are the program's own code.

That is the whole vocabulary. There are no node types and no planner: the model plans,
and the rules carry it out.

### When a rule is judged

A rule says what it reads, and is judged when that changes:

```python
rule(lambda view: view["facts"].get("door") == "open", go_through, reads="facts.door")
rule(lambda view: view["pressure"] > 3, vent, every=0.5)
```

- `reads` names the parts of the view the rule reads, as dotted keys. Without it, the
  rule is judged at every change of the state or the facts.
- `every` judges the rule on time instead, every that many seconds (`True`: at the
  environment's own rate). The environment gives the default and the shortest period.

### Rules without a program

A rule may only raise an event or end something, as guards do:

```python
when(lambda view: view["level"] > 0.95, "stop", name="no_overflow")
watch("battery.charge", low=0.1, event="LOW_BATTERY", stops=False)
rule(lambda view: view["jammed"], raises="JAMMED")
clear_rules("no_overflow")           # or clear_rules() for all rules
```

- `when(predicate, action, name=None, stops=True)`: when `predicate(view)` holds, the
  executions that run are ended. `action` is `stop`, `hold`, an environment's own action,
  or the name of an event to raise. With `stops=False` it only raises its event, and
  everything goes on.
- `watch(signal, low=None, high=None, event=None, name=None, stops=True)` does the same
  when a number (a dotted key of the view, or a function of it) leaves a range. The event
  defaults to `<SIGNAL>_OUT_OF_RANGE`.
- `rule(begins, raises="NAME")` raises that event when it begins. `begins` may also return
  an `Event` to raise, or `{"stop_entry": unit.id}` to end that unit.

A rule that ends executions is judged at every step of an execution.

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

## Priority

Every unit has a priority. A program of the model has 0, a rule's program has the rule's,
and code started with `spawn(fn, priority=...)` has its own or that of the unit that
started it.

When a unit of higher priority needs the environment, the execution of a lower unit ends
where it is, with the event `PREEMPTED` and what it had done, and the higher unit holds
the environment until it ends. The model is told at once, as with every event that
reaches it (a wait ends, a call that is out is asked again): which rule took the
environment, from which program, and the state. It decides what goes on: the same call
again, or something else. What it starts meanwhile waits behind the higher unit and goes
on when that is over.

The harness starts the interrupted call again by itself only for a unit that asked for
it: `spawn(fn, restart=True)`. Its call is made anew when the higher unit is over, and
its result says how often: `result.restarts`. Units of equal priority take turns, the
oldest first. Where an environment divides its input into channels, units act at the
same time on the channels they took.

### A program that is not interrupted

A program of the model has priority 0, so a rule of higher priority takes the environment
from it. A program whose action must not be cut short says so first:

```python
uninterruptible()
leave_the_danger()
```

From that call to the program's end no rule's program and no other unit takes the
environment from it, whatever their priority. A rule whose condition comes to hold
meanwhile does not act: it is judged again when the program has ended and acts if its
condition still holds, and the model is told once that it was held back (the event
`HELD_BACK`), so it may cancel the program to let the rule act. What still ends the
program: cancelling it, the time of its calls, a rule that ends executions, the end of the
episode. Two such programs take turns.

`rules_set()` lists the rules that exist with their priority, highest first.

## Handlers

```python
covered = []

def remember_cover(trace):
    if trace.event.detail.get("reason") == "covered":
        covered.append(trace.event.kind)
        return True
    return False

on("SKILL_ERROR", remember_cover)
```

`on(event, handler)` calls `handler(trace)` when an execution ends with that event.
Returning `True` (or nothing) resolves it; `False` passes it on to the model. Handlers
share the rule budget and restrictions. The program can act on the state a handler
records.

## Controllers

`run_controller(fn, until=None, max_seconds=None)` applies the command `fn(view)` returns
for each step, for visual servoing and other fast loops. It is a bounded execution: rules
apply to it, and it ends with an event.

## The rules for rules

Conditions and controllers must be fast and may not open files, use the network, start
processes, sleep or call a model. They share one budget per period,
`runtime.reactive_budget_ms` (5 ms by default). One that breaks these rules produces a
`REACTIVE_FAULT` event and the rule is removed. A rule's program is ordinary code and has
no such limits.

Every command still goes through the environment's own checks, which reject commands
that are malformed or out of range, whoever wrote them. A delayed command can be vetoed
before it is sent. Once sent, its receipt belongs to the execution that sent it. A lost
receipt does not cause an automatic retry.

## In a skill

A skill registers rules on the session's reactive layer, `self.reactive`, with the same
`rule`, `when`, `watch` and `on`:

```python
class Footing:
    def keep_footing(self):
        """End whatever moves when the ground ahead is gone."""
        self.reactive.when(lambda view: view["ground_ahead"] is False, "stop", name="no_gap")
```

## In a package

A package can ship rules for its environment as a skill whose functions set them when
the session starts, or as reactive entries of a library. With `knowledge = "learned"`,
the agent starts without a package's handwritten rules and learns its own ([Let it learn an environment](/docs/learn/learn-an-environment/#games-learned-or-handwritten)).
