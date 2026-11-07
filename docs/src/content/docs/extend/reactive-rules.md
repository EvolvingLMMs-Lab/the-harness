---
title: "Write reactive rules"
description: "Guards, reflexes and event handlers: rules that react within a control period, without asking the model."
---

The model is called when there is something to decide, which takes seconds. Some things
cannot wait that long: a robot arm about to hit the table, a monster in a game, a dialog
that pops up in the middle of a click. **Reactive rules** handle them. A rule runs every
control period (a few dozen times a second) without the model, decides from what the
agent sees, and acts at once.

There are three kinds:

| Kind | Does | Set with |
|---|---|---|
| **guard** | watches, and stops or raises an event when something holds | `when`, `watch` |
| **reflex** | acts: takes over or adds to the input of some channels | `reflex` |
| **handler** | answers an event of the running program | `on` |

Programs set them, the agent can learn them ([Learn while it works](/docs/learn/while-working/)),
and a package can ship them. A rule set inside a task the program started belongs to
that task. Programs can call `when`, `watch`, `on`, `rule`, `clear_rules` and
`run_controller` through the core program API.

## Guards

```python
when(lambda view: view["see"].get("lava"), "stop", name="no_lava")
watch("hud.health", low=6, event="LOW_HEALTH", stops=False)
clear_rules("no_lava")           # or clear_rules() for all guards and observation rules
```

- `when(predicate, action, name=None, stops=True)` fires when `predicate(view)` is true.
  `action` is `stop`, `hold`, an embodiment's own action (`open_gripper` on a robot,
  `back_off` in a game), or the name of an event to raise.
- `watch(signal, low=None, high=None, event=None, name=None, stops=True)` fires when a
  signal (a dotted key of the view, or a function of it) leaves a range. The event
  defaults to `<SIGNAL>_OUT_OF_RANGE`.
- A guard that stops ends the execution it fires in and lets go of the keys it held. With
  `stops=False` it only raises its event, and everything goes on.

## Reflexes

A reflex acts instead of only watching. It is a function of the view that returns
nothing, or the input for this period:

```python
def jump_gaps(view):
    if view["see"].get("gap_ahead"):
        return {"keys": ["space"]}          # adds a jump to whatever is moving
    return None

def flee(view):
    if view["see"].get("creeper_near"):
        return {"keys": ["s"], "take": ["move"]}   # takes the move channel
    return None

reflex(jump_gaps, priority="assist")
reflex(flee, priority="hazard")
remove_reflex("flee")
reflex_state()                              # which reflexes run, and which act now
```

An act is `{"keys", "buttons", "dx", "dy", "take"}` for one period. With `take`, it
replaces what the running tasks do on those channels for as long as it acts; their keys
come back the period it stops. Without `take`, its keys are added to what goes out.
Priorities, highest first: `hazard`, `combat`, `survival` (the default), `assist`. A
reflex that acts shows on the timeline as a lane of its own while it acts.

Reflexes run on embodiments whose input is divided into **channels**, such as a game's
movement, look, hands and items.

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

`on(event, handler)` calls `handler(trace)` when an execution of the program ends with
that event. Returning `True` (or nothing) resolves it; `False` lets it escalate. Inside a
task the program started, the handler sees that task's events and those of the tasks it
started, and ends with it. Handlers share the rule budget and restrictions. The program
can act on the state a handler records.

## Robots: controllers

On a robot, `run_controller(fn, until=None, max_seconds=None, region=None, hz=None,
cameras=None)` runs `fn(observation)` at a fixed rate and sends the joint, end-effector
or gripper targets it returns, for visual servoing and other fast loops. It is a bounded
execution: guards apply to it, and it ends with an event.

## The rules for rules

Callbacks on the control loop must be fast and may not open files, use the network,
start processes, sleep or call a model. They share one budget per control period,
`runtime.reactive_budget_ms` (5 ms by default). A callback that breaks these rules
produces a `REACTIVE_FAULT` event. A handler called in response to an event outside the
control loop runs in the scope of the task that registered it.

Every command a rule produces still goes through the environment's own checks, which
reject commands that are malformed or out of range, whoever wrote them. A delayed
command can be vetoed before it is sent. Once sent, its receipt belongs to the
execution that sent it. A lost receipt does not cause an automatic retry.

## In a skill

A skill registers rules on the session's reactive layer, `self.reactive`:

```python
class Footing:
    def keep_footing(self):
        """Stop whatever moves when the ground ahead is gone."""
        self.reactive.rule(lambda view, state: view["see"].get("gap_ahead"), "stop",
                           name="no_gap", priority=400)
```

`rule(decide, does, name=None, priority=0, action=None, on=None)` adds one rule.
`decide(view, state)` returns a falsy value to do nothing, or what the rule does:

| `does` | |
|---|---|
| `"stop"` | stop the executions it watches (with `action`: `stop`, `hold` or the embodiment's own) |
| `"event"` | raise the event `action` to the task that set it |
| `"act"` | return this period's input, as a reflex does |
| `"answer"` | answer an event of kind `on`, as a handler does |

The named priorities are `hazard` 400, `combat` 300, `survival` 200, `assist` 100 and
`guard` 0.

## In a package

A package can ship rules for its environment as a skill whose functions set them when
the session starts, or as reactive entries of a library. With `knowledge = "learned"`,
the agent starts without a package's handwritten rules and learns its own ([Let it learn an environment](/docs/learn/learn-an-environment/#games-learned-or-handwritten)).
