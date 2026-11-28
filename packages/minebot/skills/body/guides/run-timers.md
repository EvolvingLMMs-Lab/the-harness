guide("run-timers"): sleep and the timer functions code on the body is given.

sleep(ms) -> Promise
  Also h.sleep. Starts a timeout of ms milliseconds, then passes the gate:
  - the run is running (not paused) when the time is over: resolves with undefined;
  - the run is paused when the time is over: stays pending and resolves when the run is
    resumed;
  - the run is told to stop, before or after the time is over: rejects at once with the
    error 'stopped';
  - the run has ended (the call is made by code that was left running): rejects at once
    with 'this code has ended: it no longer has the body'.
  A sleep that is pending when the run ends by itself stays pending; its timeout is
  cleared.
  The time is counted by the process clock (Node's setTimeout), not in game ticks.

setTimeout(fn, ms, ...values), setInterval(fn, ms, ...values), setImmediate(fn, ...values)
  Node's functions of these names, called with the same arguments; each returns Node's
  own timer object. Called after the run has ended, each throws 'this code has ended: it
  no longer has the body' and sets no timer. The body keeps every timer made this way in
  the run's list. A
  timeout or an immediate leaves the list when it fires; an interval stays until it is
  cleared.
  The callback is called by Node with no gate: it runs while the run is paused and after
  the run was told to stop. What the callback calls on `bot` follows guide("run-bot").
  An error thrown in a callback is an uncaught exception of the body's process: the event
  uncaught {message}; the run goes on.

clearTimeout(t), clearInterval(t), clearImmediate(t)
  Take the timer from the run's list and clear it with Node's function of that name.

When the run ends.
  Every timer still in the list is cleared, and the timeouts of pending sleeps too. The
  report's cleared.timers is the number of timers that were in the list (sleeps are not
  counted).

Other timers.
  globalThis.setTimeout, globalThis.setInterval and globalThis.setImmediate are Node's
  plain functions: timers made with them are in no list and are not cleared when the run
  ends. They end when the body's process is started again.

Routines.
  A routine called through `skills` gets the timer functions and the sleep of the run
  that called it: its timers are in that run's list.

In a sense.
  A sense's `h.sleep(ms)` is a plain timeout promise with no gate, and a sense has no
  timer names of its own; it sees Node's globals (guide("run-senses")).
