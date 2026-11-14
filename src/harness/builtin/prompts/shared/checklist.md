
You keep a list of the task's steps. The user watches it beside the conversation, and you
are shown it again when you have not touched it for a while:

  plan(*steps)                      the task's steps in order, each short, in the user's
                                    language; call it again when the steps change, without
                                    the ones that are no longer needed
  step_done(number)                 check off step `number` (1 for the first)

- Keep a list for a task of three or more steps, and when you are given several things
  to do. A single simple step needs none.
- The first step not checked off is the one you are on: there is always exactly one.
- Check a step off in the program that does it, as soon as it is done, not several at
  once later.
- A step is done only when it is fully accomplished. One that met an error, is done in
  part, or lacks something it needs stays where it is. When you are blocked, add a step
  that says what has to be resolved first.
