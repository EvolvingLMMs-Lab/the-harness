---
title: "Write a skill"
description: "Use the skills the agent has, then write your own: a manifest, a few lines of Python, and a closed loop that checks its own result."
---

A **skill** is a set of functions the agent's programs can call, such as `click`,
`press`, `read_page` or `probe_inputs`, with the text that tells the model how to use
them. Skills come with the core and with packages; you can turn them on and off, and
write your own.

## Use skills

Every skill is listed in the [skills reference](/docs/reference/skills/) with its
functions and what the model reads about them. A skill can be off because the
configuration leaves it out, or because it needs a service this computer does not run;
a run's `manifest.json` lists the skills it had and why the others were off. To change
the skills of a run:

```toml
[overrides.agent.skills]
enable = ["agents", "checklist"]
disable = ["verify"]
```

In the app, **Settings → Packages** turns a package's skills on and off for new
conversations.

The agent calls skills from its programs. Most functions run as **bounded executions**:
they act for a limited time, under the guards and reactive rules that are set, and end
with an event (`COMPLETED`, or what stopped them) that the program can handle or let go
up to the model.

## A skill of your own

This skill saves a document with Ctrl+S and checks that it was saved, on the `desktop`
embodiment (your computer). A skill is a folder:

```text
savefile/
├── skill.toml
├── __init__.py
└── prompt.md
```

`skill.toml` says what it is:

```toml
name = "savefile"
summary = "Save a document with Ctrl+S and check that it was saved."
layer = "base"
mixin = "skills.savefile:SaveFile"
exports = ["save_file"]
embodiments = ["desktop"]
```

`__init__.py` holds the functions, as methods of a class that is mixed into the
agent's session, so they can call the other skills' functions on `self`. Here the
function hands the session to a closed loop (below), whose keyword arguments become its
attributes:

```python
from harness.sdk import ClosedLoop

class Save(ClosedLoop):
    def unsaved(self):
        return any(row["id"] == self.window and "*" in row["title"]
                   for row in self.session.windows())

    def confirm(self):
        return self.unsaved() or "nothing to save"

    def do(self):
        self.session.press("ctrl", "s", window=self.window)
        self.session.wait(0.5)

    def check(self):
        return not self.unsaved() or "the title still shows unsaved changes"

class SaveFile:
    def save_file(self, window):
        return Save(session=self, window=window)
```

`prompt.md` is what the model reads about it, added to the system prompt while the
skill is on:

```markdown
save_file(window) -> result   save the document in a window (an id of windows()) and
                              check that it was saved; result.ok, result.reason
```

## Closed loops

`ClosedLoop` is how a skill does something and makes sure it happened, in any
environment. Subclass it and fill in the steps:

| Step | |
|---|---|
| `confirm()` | before each try: `True` when the target is what you expect, else the reason not to act |
| `do()` | the action |
| `check()` | after it: `True` when the world changed as it should, else the reason |
| `recover(reason)` | between tries after a failed check: look again, step back |

Each step returns `True` or a reason; raising `Stop(reason)` ends the loop at once.
`tries` (default 3) and `max_seconds` (default 30) bound it. Calling the class runs the
loop and returns a result with `ok`, `reason`, `tries`, `seconds` and `detail`. Each
try's end is news for the model, which can look again while the skill runs. The skills
the agent writes for itself while it learns are closed loops too
([Learn while it works](/docs/learn/while-working/)).

## Try it

Put the folder in a package ([Write a package](/docs/extend/packages/)) and install it
from where it is, so your changes apply at once:

```bash
harness install ./my-package --link
harness list my-package       # what The Harness found in it: savefile
harness run "Write a line in Notepad and save it." --workspace apps
```

The [timeline](/docs/use/replay/#the-timeline) shows each `save_file` call on the
programs' lane, and the trace records each try.

## The manifest

| Key | |
|---|---|
| `name` | the skill's name |
| `summary` | one line, shown in listings |
| `layer` | `base` for a skill the agent uses directly; `reactive`, `handlers` and `learned` for the other kinds |
| `mixin` | `module:Class`, the class whose methods become functions |
| `exports` | the functions programs can call |
| `embodiments` | the kinds of environment it works on, or `["*"]` for every kind |
| `needs`, `needs_any` | the kinds of service it cannot run without (all, or one of them) |
| `requires` | other skills it uses |
| `requirements` | Python packages it needs, installed into its own folder |
| `order` | where it sits among the skills, in the session and in the prompt |
| `optional` | off unless a configuration turns it on |
| `guides` | pages of instructions the model reads on demand, and the functions that wait for one |

The [configuration keys reference](/docs/reference/configuration/) lists every key.

## Pages the model reads on demand

What the model needs for every reply belongs in the skill's prompt section. The rest (how each
function behaves, what it costs, what goes wrong) belongs in a page of its own, which the model
reads with `guide("name")` when it is about to use the skill:

```toml
[guides.crane]
file = "guides/crane.md"      # a path from the skill's folder
before = ["lift", "lower"]   # these functions are refused until the page was read

[guides.rigging]
file = "guides/rigging.md"    # a page nothing waits for
```

A function named in `before` answers a call made before the page was read with a refusal that
names the page; once the page was read it runs as usual. A page that was read is given to the
model again after a summary of the conversation. Name the pages in the skill's prompt section,
one line each, so that the model knows they exist. `tree` and `units` are pages of the core.

## A skill that needs a model

A skill that calls a model it runs itself, such as a segmenter, names the service kind
in `needs` and calls it through the session's clients. The skill stays plain Python;
the model's heavy dependencies belong to the service, which gets an environment of its
own the first time a run uses the skill ([Services](/docs/configure/services/)). When
the service is not available, the skill is turned off and its text leaves the prompt.

## Agent Skills

A folder with a `SKILL.md` (the Agent Skills format) needs no code: the agent sees its
name and description, and reads its instructions and files when a task needs them.
[Connect MCP servers and Agent Skills](/docs/extend/mcp/) describes them.
