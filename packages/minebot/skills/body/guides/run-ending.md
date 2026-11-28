guide("run-ending"): every way a run ends, what signal shows, what is cleared.

signal
  signal.stopped   false until the run is told to stop, true from then on
  signal.pauses    the pauses of the run so far (guide("run-pause"))
  Both are read-only views of the run's context. A routine called through `skills`
  without a third argument gets the run's signal.

1. The code returns or throws (ended "by itself", or "an error").
  signal.stopped stays false. The end is reported with the value or the error
  (guide("run-result")), then the clearing below is done.

2. The run is told to stop.
  Causes, with the report's `ended` when the code then returns without an error:
    stop_routines(), or the run's call was ended or cancelled      "stopped"
    another run was started on a channel this one uses            "other code took the body"
    a run that shares a channel was resumed                        "other code took the body"
    the body died (every running job and every paused job)        "the body died"
  A run that is running (not paused), in this order:
  - signal.stopped turns true.
  - Every gated call and every sleep that is pending rejects with the error 'stopped'.
    Each gated waiting call and each sleep made afterwards rejects with 'stopped' too.
  - The body lets go of the run's own channels once: move: bot.clearControlStates();
    use: bot.stopDigging() and bot.deactivateItem(); look: nothing.
  - Calls that happen at once (setControlState, attack, chat, ...) still act until the
    code ends, and so does everything that is not gated.
  - The code has 3 seconds to return or throw. When it returns, the run ends with status
    'done' and its return value. When it throws (the error 'stopped' it let pass, or any
    other), the run ends with status 'stopped', result None and the error 'stopped'. In
    both cases `ended` is the cause in the list above.
  - When it has not ended after 3 seconds, the body's process is ended and started again
    (guide("run-restart")): status 'stopped', `ended` as in the list above, error "the
    code did not return 3 s after it was told to stop (CAUSE): the body was started
    again, where it stood; listeners, timers and variables the code had left are gone,
    saved routines are kept".
  A run that is paused ends on the spot: status 'stopped', result None, error 'stopped
  while it was paused', and the clearing below. Its code is not run further by the body:
  what waited at the gate rejects with 'stopped'.

3. The body's process is ended for another reason (ended "the body was started again").
  Every job, running or paused, ends with status 'stopped' and the reason as its error
  (guide("run-restart")). Nothing of the code is left in memory.

The time given with `seconds` ends nothing: guide("run-gate").

What is cleared when a run ends (cases 1 and 2).
  - Every timer in the run's list is cleared; the timeouts of pending sleeps are cleared.
  - Each listener the run put on the bot through bot.on, once, addListener,
    prependListener or prependOnceListener, and that is still on it, is taken off.
  - The report's `cleared` is {timers, listeners}: how many of each there were.
  - Calls that waited at the gate are rejected with 'stopped'.
  - When the run was not paused, the body lets go of its own channels, and of no other:
    move: bot.clearControlStates(), every key up; use: bot.stopDigging(), then
    bot.deactivateItem(), no dig under way and no item in use; look: nothing, the head
    stays where it is. Errors of these are ignored. What other running jobs hold on
    their channels is not touched.
  - The context leaves the running jobs and no longer holds its channels.
  Not cleared: listeners on other objects than the bot, timers from globalThis, values
  written on the bot or on globalThis.

Code that is still running after its run ended.
  A promise chain that was not awaited, or a callback kept elsewhere, goes on in the
  process. For it, each of these throws or rejects with 'this code has ended: it no
  longer has the body': the gated calls of `bot` and bot.creative (the ones that wait
  and the ones that happen at once: guide("run-bot")); sleep; setTimeout, setInterval and
  setImmediate. Every other function of `bot` (the ones that read: blockAt, findBlocks,
  nearestEntity, recipesFor) and every property still answer: an object the code made
  with its bot and left for later goes on reading through it. The methods of
  the bot's own objects (bot.inventory, bot._client, a window that a call returned) and
  globalThis's timers are Node's and the library's own and still run.
  Only the first end of a run is reported.
