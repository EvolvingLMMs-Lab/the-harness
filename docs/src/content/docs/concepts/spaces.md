---
title: "Spaces"
description: "Every place the agent works in is a space, reached through the Agent Space Protocol: how the core enters one, what an outcome tells, how events reach the reflexes, and how a space is chosen."
---

Every place the agent works in is a **space**: a project folder, this computer's desktop, a
background browser, a benchmark, a QQ group. A space has a state, laws that decide what each
action leads to, and participants (the agent, people, other agents). The Harness reaches every
space through one open protocol, the [Agent Space Protocol](https://github.com/agent-space-protocol/agentspaceprotocol)
(ASP), with its Python SDK, the core's one dependency (standard library only, like the core).

The four layers keep their places: the language model and the programs and learned policies act
through the space's verbs, the reactive layer answers the events the space pushes, and the safety
layer stays at the environment's boundary (the worker's shield, or the laws of a space that speaks
the protocol itself). The tick still coordinates them.

## What the protocol promises

A space keeps three properties, which a participant can check through the protocol alone
(`agent-space check`):

- **Consistent**: what an observation shows makes sense and says when it was confirmed.
- **Complete**: every action with an ID ends with exactly one final outcome, and sending the same
  ID again never acts twice.
- **Recorded**: actions, outcomes and events are appended to a record by sequence number.

An outcome is one of five, and the agent decides from it whether to wait, try again or do
something else:

| Outcome | Means |
|---|---|
| done | it happened; the result is given |
| refused | nothing happened (no permission, bad arguments, a stale basis, the shield stopped it) |
| failed | it was tried and did not succeed; the effects that did happen are listed |
| cancelled | it stopped when asked; the effects before are listed |
| unknown | it may or may not have happened: what is known and what is not confirmed are given |

A program gets a done action's result; any other outcome raises `ActionFailed`, whose
`outcome.end` and `outcome.reason.code` say which and why.

## How the core enters a space

| The space | How it is entered |
|---|---|
| a worker (workspace, computer, browser, a benchmark) | the **translation layer** serves the worker, unchanged, as a space beside it; the conversation enters as its owner, its programs as members |
| a space that speaks the protocol (a QQ channel, the inspector's test space, a room) | by its address: `--workspace space --space ws://...` |

The translation layer (`python -m harness.space.translate`) maps the worker protocol onto the
space: a step the shield passes is done, one it stops is refused with its reasons, a step whose
input may have reached the environment when the worker failed is unknown; a step based on an
observation that is past is refused as stale; the outcome is read by the evaluator role only;
what a worker tells by itself becomes an event. A package says what its worker's space offers in
`spaces/<name>.toml` ([Environments](/docs/extend/environments/#a-space-of-its-own)): verbs, their
effect class (read, change, send, spend, irreversible), and verbs made of steps, such as the
project folder's `run`, which lasts until the command ends.

## Events and reactions

What a space pushes reaches the agent's side first and the model last:

1. **Record.** Every event becomes a `space_event` record of the conversation's trace, with the
   protocol's version and the space's sequence number ([Traces](/docs/reference/traces/)).
2. **Reflexes.** An event kind is a reflex's condition:
   `set_reflex("greet", "qq.message", program)` runs `program(event)` when one arrives. Events of
   the agent's own presences trigger nothing.
3. **The model.** What no reflex answers stays in the record, unless one of the three reactions
   the agent has from the start wakes the model:

| Reaction (`runtime.reactions`) | When |
|---|---|
| `addressed` | an event addressed to the agent (it names or mentions it, a reply to it, what an environment tells) |
| `failed` | an action whose outcome is failed or unknown, which no program of the model waits for (a reflex's) |
| `approval` | an action waits for consent: the owner is reminded |

Each can be switched off (`runtime.reactions = {addressed = "off"}`); none is removed.

## Acting from the vocabulary

A space without skills of its own is used through its vocabulary alone, as a model is given an
MCP server's tools: each verb is a function `namespace.verb(object, **args)` of the programs,
and the model's context gets one line per verb (its parameters, effect class and summary), the
kinds of things and the events. `observe()` gives the structure, and `space_page(name)` a page of
the vocabulary when a program needs it. A space with skills of its own (a desktop, a project
folder) keeps them, found by the vocabulary's namespace.

## Choosing a space

```bash
harness run "turn the lamp on" --space ws://127.0.0.1:7777
harness --workspace space --space ws://127.0.0.1:7900
```

In Python, `Host.task(text, space="ws://...")`. A package may serve a space of its own:
`python -m harness.space.serve NAME` runs it (the [qq](https://github.com/EvolvingLMMs-Lab/the-harness/tree/main/packages/qq)
package serves a QQ account over OneBot 11), and the inspector's `agent-space tui ADDRESS` lets a
person enter the same space and act.
