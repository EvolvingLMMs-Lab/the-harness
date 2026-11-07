---
title: "Learn while it works"
description: "The agent keeps learning during ordinary runs: what it proposes, how entries are tested and admitted, and how to freeze a library for evaluation."
---

An agent with learning on does not stop learning when the task starts. While it works,
the model can propose an entry for its library (a note, a memory, a skill with a test,
a reactive rule). At useful decision points the model can reflect on observed program
results and propose an addition. This is
**passive** learning. It uses the same library and the same rules of evidence as an
[active run](/docs/learn/learn-an-environment/); only the trigger differs.

## Turn it on

```toml
[overrides.agent.runtime.library]
path = "$HARNESS_HOME/libraries/my-app"   # or a path relative to this file
learn = "on"            # "off" (the default): read one frozen version, learn nothing
trigger = "passive"     # "active": a run whose goal is to learn
evidence = "test"       # accept trusted test evidence
load = "proposed"       # the lowest evidence an entry needs to be loaded
reflect = true          # reflection after each episode proposes one entry
```

For core tasks, bind a library with `--library` and explicitly enable writes with
`--learn-while-working`. A frozen run reads one library snapshot. Inspect it with
`harness library show PATH`.

## How an entry gets in

1. **Proposed.** The model proposes an entry from a program, with its test for code:

   ```python
   library.propose("note", "save_shortcut", "Ctrl+S saves without a dialog in this editor.")
   library.propose("skill", "open_inventory", code, test)
   ```

2. **Verified.** Executable proposals stay pending until a trusted host verifies their
   exact source, test, attachments and declared dependencies. The result records the
   conditions of the verification.
3. **Activated.** The runtime loads the admitted revision before the first request or
   between programs at a safe boundary. The run records which revision it actually
   enabled. A failed load leaves the previous active revision in place. A later independent
   check of the same revision can earn `replayed`. A paired development comparison
   that confirms the revision was active and improved scores can earn `validated`.

## Skills written as closed loops

A skill the agent writes is usually a **closed loop**: confirm the target, act, check
that the world changed, retry or give the reason. The agent subclasses `ClosedLoop`:

```python
class open_inventory(ClosedLoop):
    """Open the inventory."""
    tries = 2

    def confirm(self):
        return "open already" if inventory_open() else True

    def do(self):
        press("e")

    def check(self):
        return True if inventory_open() else "no inventory after E"
```

Calling `open_inventory()` returns a result with `ok`, `reason`, `tries` and `seconds`.
Each try's end is news for the model, which can look again while the skill runs.
[Write a skill](/docs/extend/skills/) has the full interface.

## Memory

One interface holds what this run saw and where (working memory) and what earlier runs
kept (the library):

```python
remember("window", "the totals are in the last column", where="Quarterly report.xlsx")
remember("tree", where=(12, 64, -30))              # a position: seen again near it, the same tree
remember("door", "the code is 4711", name="side_door", keep=True)   # also a library entry
recall("totals column")                            # this run's notes and the library's entries
recall(kind="tree", near=(0, 64, 0))               # nearest first
```

Every entry has the same fields: `scope` (`run` or `library`), `kind`, `name`, `text`,
`where`, `evidence`, `source`, `version`. A run's entry has the evidence `seen`; a library
entry its grade. The run's memory is shared with its sub-agents, every change is a
`world` record of the trace (and so is what each `recall()` found), and after each program
the model is told, under "Memory:", its notes without a place and then the nearest places.
The run reads the library memory captured at startup. Writable runs can also read
later changes in the same library if they meet the run's evidence and scope settings.
Use `near` for distance ordering and `radius` to restrict results to positioned entries.
Without `near` or `radius`, reporting a position does not change which entries are searched.
`keep=True` saves the same ID and its observation fields in a writable library.
`forget(id)` removes the visible entry from its scope, including persisted memory when
the run has write access. `harness library show RUN`, `/library`, **Memory** in a conversation's menu in the
app and `conversation.memory()` show a run's memory beside the library entries it started
with. Older traces may have only the names and version from their manifest.

## Uses

A run records each library result under the revision that executed it. The library
groups results by revision and keeps validation evidence separately. Updating a use
count leaves the code revision unchanged. Imported results whose revision is unknown
appear separately in the library view. `uses = "learn"` (the
default) counts them in a run that learns, `"on"` also with a frozen library (practice),
`"off"` never.

## Freeze it for evaluation

A result is only comparable when the agent did not change during it. Leave `learn` off
(the default) to evaluate: the run then reads one frozen version of the library and
learns nothing. The run refuses to start an episode if the library changed after the
configuration was loaded.

To keep only what helps, set `evidence = "validated"`: entries learned during runs wait
as candidates, and an entry is admitted only when the library scores better with it on
held-out tasks than without it.

## On disk

```text
<library>/
├── notes/*.md  memory/*.md  skills/*.py  reactive/*.py
├── .revisions/             immutable content and tests by revision
├── tests/<name>.py          editable copy of a code entry's test
├── skills/<name>.files/     a skill's attachments, such as a small model it trained
├── candidates/              entries waiting for held-out validation
└── index.json               evidence, origin, tests, uses and history of every entry
```

A library is a plain folder: copy it to reuse what an agent learned on another
computer, or point `path` of several experiments at the same one.
