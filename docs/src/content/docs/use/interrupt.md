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
| approve or reject a step | the choices above the input (a digit, or ↑ ↓ and Enter) | the card's buttons |
| use the computer yourself | | **Take over**, then **Hand back** |
| end the conversation | `/end` | start a new one (the old one stays in the list) |

## Tell it something while it works

A message is news for the model, and it gets it at once:

- **While the model writes a reply**, the reply is set aside and the model is asked
  again with your message.
- **While a program runs**, the program goes on and the model is asked at once, with
  your message. Its answer decides what happens to the program:
  - it lets the program finish, and is asked again with the program's result;
  - it runs something beside it that does not need the screen or the controls (telling
    a sub-agent, updating the plan, a calculation), and the program goes on;
  - or it stops the program at its next step and does something else.
- **Tasks and sub-agents it started** go on until the agent tells or stops them.

So "use the cheaper flight" changes the plan without throwing away the page the agent
is reading, while "stop, wrong account" stops it at its next step.

## When the model is called

Each call of the model is one **thought**, started by one of these:

| When | Between programs | While a program runs |
|---|---|---|
| the conversation starts | yes | |
| you send a message | yes | yes, at once |
| an event or an error goes up to the model | yes | |
| a program ends, or a reply could not be used | yes | |
| a program starts (`think_while_acting = "on"`) | | yes: it plans the next step |
| something new comes in (`"on_events"`, the default) | | yes |
| some seconds pass without a call (`"periodic"`) | | yes |
| the episode ends | a short reflection, which may propose what was learned | |

While a program runs, at most one thought is out at a time and new triggers wait for
it; your message voids a reply that was not used yet. A reply may run a program, run
something beside the program that needs neither screen nor controls, start or tell a
sub-agent, stop the program, remember something, propose a library entry, answer you,
wait for the program's result, or finish. `think_while_acting` under `[model]` in
`config.toml` sets how often the agent thinks while it acts.

## Pause and stop

**Esc** in `harness` (or **Stop** in the app) stops a running program at its next step:
nothing more moves, and the model is not called again until you type `/continue`
(**Continue**) or send a message. A message sent during a pause replaces a program that had not started yet.

**End** ends the conversation. In a run of a benchmark, the environment then scores the
episode.

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
