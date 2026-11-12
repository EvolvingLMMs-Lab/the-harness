---
title: "Interrupt and take over"
description: "Change the agent's mind while it works, pause or stop it, approve its steps, and take the computer back."
---

You never have to wait for the agent to finish. A message reaches it at once, you can
stop it at its next step, and you can take the computer back at any moment. Every
frontend does the same; the table gives the app's controls and the terminal's.

| To | In `harness` | In the app |
|---|---|---|
| tell it something | type a message | type a message |
| pause | **Esc** (or **Ctrl+C**) | **Stop** or **Esc** |
| go on | `/continue` | **Continue** |
| end its turn | `/cancel` | |
| approve or reject a step | the choices above the input (a digit, or ↑ ↓ and Enter) | the card's buttons |
| use the computer yourself | | **Take over**, then **Hand back** |
| end the conversation | `/end` | start a new one (the old one stays in the list) |

## Tell it something while it works

A message is news for the model, and it gets it at once:

- **While the model writes a reply**, the reply is set aside and the model is asked
  again with your message.
- **While a program runs**, the program goes on and the model is asked at once, with
  your message: a program never holds the model's turn. Its answer decides what happens:
  it lets the program go on and waits for it, starts another program beside it, or
  cancels it and does something else.
- **Tasks and sub-agents it started** go on until the agent tells or stops them.

So "use the cheaper flight" changes the plan without throwing away the page the agent
is reading, while "stop, wrong account" stops it at its next step.

## When the model is called

Each call of the model is one **thought**, started by one of these:

| When | |
|---|---|
| the conversation starts | |
| you send a message | at once, whatever runs |
| a program ends | with its result |
| a program is still running after a moment | the model's turn comes back while the program goes on |
| another unit it started ends (a sub-agent, code a program started) | with what it ended with |
| an event or an error nobody handled goes up to the model | |
| a wait it chose is over | it is told why: a unit ended, a message, an event, or its time |
| a reply could not be used | |
| the episode ends | a short reflection, which may propose what was learned |

Every program the model writes runs as a unit beside the others. One that is over within
a moment (`runtime.turn_grace_seconds`, 2 s by default) gives the model its result with
its turn; a longer one goes on, and the turn comes back at once. The model may then start
another program, cancel one, or reply `<wait>`: no call is made while it waits, and the
wait ends when a unit it started ended, a message or an event reached it, or its time is
over (`runtime.longest_wait_seconds`, 60 s by default, is the longest). Something that
reaches the model while a call is out sets that call's reply aside, and the model is
asked again. Between calls, [rules](/docs/extend/reactive-rules/) act without the model.

What the model leaves running is its own to supervise. It can read what a unit has
printed so far while the unit runs: `output_of("e3")` with the unit's name, or `.output()`
on its handle from `entries()`, gives the last characters (2000 by default, at most 4000)
and takes nothing from the result, which still has the whole output when the unit ends.
When a wait is over, the model is told which units run, for how long, and how long ago
each last printed, so it can check on its work before it waits again and cancel a program
that is not doing what it expected. A rule that raises an event wakes it for a condition
without checking. A program in an isolated workspace gives its output only when it ends.

## Pause and stop

**Esc** in `harness` (or **Stop** in the app) stops every running program at its next
step, and rules are held: nothing more moves, and the model is not called again until you
type `/continue` (**Continue**) or send a message. A message sent during a pause replaces a program that had not started yet.

`/cancel` ends the turn that runs: the model's call is set aside, its programs are
cancelled, and the conversation waits for your next message with everything it has.

**End** ends the conversation. In a run of a benchmark, the environment then scores the
episode.

## Turns

The model's answer, a reply in plain text, ends its turn, not the conversation. The
conversation then waits with its messages, the variables of its programs, its rules, its
facts and the environment. What the model left running goes on, and the end of a unit or
an event starts its next turn without a message from you. A turn also ends when it has
used its model calls or its time (both begin anew with the next turn), when the
conversation's cost limit is reached, on an error, and when you cancel it; the terminal
says which.

## Approve each step

A sensitive step always waits for you: one whose target names credentials, a payment,
sending, deleting or something that cannot be undone. You allow it or reject it, for
that step only. With `ask = "programs"` under `[approvals]` (**Ask before acting** in the
app), every program waits too: the agent shows it before it runs, and you approve it or
reject it with a reason, which the model reads. A rejected step does not run
([Permissions](/docs/configure/permissions/#approvals)).

## Take over

When the agent works on your own desktop:

- **Take over** pauses it while you use the computer. **Hand back** gives it back, and
  the agent looks at the screen again before it goes on.
- **Your hands come first.** While you use the mouse or keyboard, its steps wait until
  you stop, and then it looks again. If you bring a window of yours to the front, it
  stops as after **Take over** and does not take the screen back until you hand it
  back.
- **To stop it at once**, push the pointer into a corner of the screen.

A background browser, apps in the background and a display of its own never use your
mouse and keyboard, so there is nothing to take back: the agent keeps working while you
use the computer.

## When it may use your mouse and keyboard

Whether an agent may use the real mouse and keyboard at all, in which apps, and whether
it asks first is a setting with several levels, from never to always, with rules for
apps, windows and kinds of action. [Permissions and privacy](/docs/configure/permissions/)
describes them; `/settings` in `harness` and the app's **Settings** change them.

## On the timeline

Your messages are marked `●` on the timeline, the agent's `○`, a pause `‖` and the end
`■`. A model call whose reply was set aside or not used is drawn faint, so you can see
what your message changed.
