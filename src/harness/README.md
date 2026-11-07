# Source map

The runtime implements the [agentic-control concept](../../docs/src/content/docs/concepts/harness.mdx):
the model writes a controller at decision points; programs, learned policies and reactive
rules act without a model call on every step. A worker checks commands at the environment
boundary. The controller's Python process and the task's target environment are separate.

## The four control layers

| Concept | Source | Responsibility |
|---|---|---|
| Model decisions | `runtime/decision/` | Model transport, requests and cancellation, messages, prompts, reply protocol and speculative-reply rules |
| Programs and learned policies | `runtime/execution/` | Controller process, session bootstrap, bounded executions, skills and control API |
| Reactive control | `runtime/reactive/` | Guards, reflexes and event handlers evaluated during execution |
| Fixed safety | `runtime/safety/` | Shield mechanism, input ownership, approval contracts and controller isolation |

These are control responsibilities, not four sequential RPC services. The shared
`runtime/tick.py` scheduler advances executions and rules. It is not a fifth layer.
Environment-specific commands, observations and safety decisions stay in their packages
and workers; putting generic shield code here does not move the target environment here.

## Task coordination and learning

`runtime/task/run.py` owns a bounded task's lifecycle: setup, decision/program transitions,
steering, budgets, approvals, learning activation boundaries, termination and cleanup.
It coordinates the four layers. Its state stays on `TaskRun`; this organization adds no
shared-state container, forwarding properties, component registry or callback framework.
`runtime/task/delegation.py` manages bounded child executions, not persistent agents.

`runtime/learning/` is cross-layer: an explicitly bound library can supply notes, memories,
skills, policies and reactive rules. Its learner, fixtures and activation machinery retain
their existing admission contracts. Learning is available without an agent package.

Three kinds of data have different owners:

| Data | Owner |
|---|---|
| Working state of this task | `runtime/task/context.py` |
| Captured library entries and their evidence | `runtime/learning/library.py`, `views.py`, `usage.py` |
| Historical projection for frontends and replay | `core/memory.py`, `core/episodes.py` |

Persistent identity, personal memory and multi-turn conversations belong to the optional
agent package. A CLI task and a benchmark episode use the same task engine without it.

## Where to start reading

- Task starts, stops, waits or exhausts its budget: `runtime/task/run.py`.
- A model request is sent, cancelled or settled: `runtime/decision/thoughts.py`.
- A reply is classified or speculation is interpreted: `runtime/decision/loop.py` and `protocol.py`.
- A program starts or returns a receipt: `runtime/execution/kernel.py` and `results.py`.
- Controller API and environment session setup: `runtime/execution/session.py`.
- Bounded actions and interruptions: `runtime/execution/entries.py` and `runtime/tick.py`.
- A guard, reflex or handler runs: `runtime/reactive/rules.py`.
- A command is refused or needs approval: `runtime/safety/shield.py`, `approval.py` and the package's worker.
- A proposal is tested or admitted: `runtime/learning/learner.py` and `fixtures.py`.
- Library contents become runnable: `runtime/learning/active.py` and the task's activation boundary.
- A frontend reads recorded memory: `core/memory.py`.

## Other core directories

- `host/`: task hosting, worker leases, workspace ownership and HTTP access.
- `core/`: shared I/O, traces, records, transport and worker infrastructure.
- `config/`: resolve and validate configuration.
- `packages/`: install and activate capabilities owned by external packages.
- `services/`: service lifecycle and clients.
- `sdk/`: the package-facing Python API; consumers should use it instead of internal paths.
- `builtin/`: shipped generic configuration, prompts, skills and services.
- `tui/` and `cli.py`: terminal interfaces.

Runtime implementations import their actual owners. Old flat runtime modules are removed;
there are no alias tables or fallback imports. Internal bootstrap strings and all tracked
callers move together. This is a source organization change, not a new execution protocol.
