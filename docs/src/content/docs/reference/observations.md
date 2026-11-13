---
title: "Observations and views"
description: "What an environment reports with observe, what each part of the system reads, and the calls that put a view in front of the model."
---

This page is the reference for what the [Multimodal first](/docs/concepts/multimodal/)
principle looks like in the calls: what an observation holds, which part of the system
reads what, and how the model gets a view.

## An observation has several forms

Every environment answers the same call, `observe`, with several forms of input:

| Form | Examples |
|---|---|
| Text | the instruction, a terminal's output, the contents of a file, the outline of a window |
| Structure | the state: windows and their elements with roles, names and values; a robot's joints, gripper and poses |
| Images | screenshots, the frames a game draws, camera views with their calibration |

Each form arrives as the environment reports it: a screenshot as an image, a cell's
value as a value, a command's output as text.

## Each part uses what serves it

The parts of the system need different inputs, and each takes its own.

- **The model** reads text every turn: the instruction, the state, what its programs
  printed and what happened to each step. A picture reaches it when one of its programs
  looks. The model decides whether to look, how often, and how long a view stays in its
  sight.
- **Programs** work on text and structure directly: they read an element's value or
  parse a command's output. When a picture is the best evidence, a program asks a
  vision model about it or has it point at something, and continues from the answer.
- **Reactive rules** run on the observation at the control rate, on measurements, with
  no model call.
- **Learned policies** take camera views and robot state in their native form, through
  the environment's adapter.
- **The verifier** judges a claim on the same evidence the model can get: the state, the
  elements or page text the environment reports, and its views.

## The model looks when it needs to

Three calls, the same in every environment, give the model its views:

| Call | |
|---|---|
| `look(camera=None, region=None)` | put a view, or a part of one, in the next turn together with this program's result. Clicking and then looking is one model call |
| `watch(cameras=None)` | from now on the views come with every program's result, until `unwatch()` |
| `look(keep=3)`, `look(pin="before")`, `unpin("before")` | a view stays for the next reply only, unless the model keeps the views of its last few programs or pins one |

Reading a total from a spreadsheet needs no picture: the cell's value is in the window's
elements. Checking how a page renders does: the program looks once, after the change. A
game or a moving scene is seen rather than read, so the model turns `watch()` on there
itself. Structure and text are taken the same way, on request: `elements()`,
`read_page()`, a file.

A model that reads no images works wherever text and structure are enough. The model
list records whether a model reads them; one that does not is sent none, and when it
looks, a vision model you name describes the view for it
([Models and providers](/docs/configure/models/#models-that-read-no-images)).

An evaluation whose rules hand a policy a fixed observation declares that in its own
configuration: `runtime.cameras` names the views that come with every turn.

## The modality that fits the step

A total read from a spreadsheet cell, or the exit text of a command, is cheap and
exact. A drawing canvas, a game and a physical scene are known through images. The
model and the programs it writes choose step by step, and every form stays available
to them.

The same holds for where the work happens. A conversation starts in the environment you
choose, which may be none at all, and takes another one when a step needs it: a project
task that must see its page takes the browser, after asking you
([Environments](/docs/configure/configuration/#where-a-conversation-works)).

This is how one control loop serves environments that share little else. A
desktop, a website, a game and a robot differ in what they report, in their actions and
in their pace. Each one says what it reports once, in its
[environment](/docs/extend/environments/), and the agent's skills work on it unchanged.
