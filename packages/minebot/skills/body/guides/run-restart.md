guide("run-restart"): when the body's process is ended and started again; the effects.

The two processes.
  The bot and all code given to it run in one Node process, the body. A second process,
  the bridge, starts the body, keeps the jobs, the events, the saved routines and senses
  on disk, and answers for the body from the state the body sends it every 50 ms.

When the body's process is ended.
  The bridge checks every 500 ms and ends the process (kill) in these cases; the text is
  the `why` of the event and the start of the error of every job that ran:
  - "the code kept the body's process busy without a pause for 5 s": the process sent
    nothing for 5000 ms. It sends its state every 50 ms from a timer, so this is code
    that runs 5 seconds without reaching an await that lets timers run.
  - "the body's physics did not tick for 8 s": the body is in the world, its state has
    dead: false, and its count of physics ticks did not change for 8000 ms. Mineflayer
    emits no physics tick while bot.physicsEnabled is false, while it is mounted on an
    entity, from a respawn packet until the next position packet of the game, while the
    block at its position is not loaded, and while its position is not a finite number.
  - "the body was not in the world 60 s after its process started".
  - "the code did not return 3 s after it was told to stop (CAUSE)", CAUSE being stop,
    another job or death (guide("run-ending")).
  The process also ends by itself:
  - 50 ms after the bot's 'end' event (the connection to the game closed, a kick
    included; the event end {reason} is noted first): "the body's process ended (3)".
  - when the bridge is gone.

What the bridge does then.
  - When the body was in the world: the restarts count goes up by one and the event
    body_restarted {why} is noted. Otherwise the event is body_gone {why}; a body_gone
    with the same why as the last event is not added again: that event's `times` goes up.
  - Every job, all running ones and all paused ones, ends with status
    'stopped' and the error WHY + ": the body was started again, where it stood;
    listeners, timers and variables the code had left are gone, saved routines are
    kept". Its report's `ended` is "the body was started again", or the cause it was
    told to stop with before. `cleared` is None; `did` is the last count the body sent.
  - A new body process is started: at once when the body was in the world, 3 seconds
    later when it was not.

What the new process has.
  - A new Mineflayer bot, made as guide("run-differences") says, logging in with the
    same name.
  - Every saved routine and every saved sense, read from disk and compiled again. A
    file that does not compile is noted: skill_load_error or sense_load_error {name,
    message}.
  - Nothing else from before: no context, no listener, no timer, no value on globalThis
    or on the bot, no pending promise. The count `ticks` starts at 0.
  - The priority asked with h.priority or h.atomic is gone with the context.
  It is in the world at the bot's first 'spawn' event: the event joined {dimension} is
  noted, and runs can start. Mineflayer emits that first 'spawn' at the first health
  packet whose health is above 0. A body that logs in dead (it had died and was not
  respawned when its process ended) is in the world at the first health packet too: its
  state has dead: true, no death is counted again, and respawn() reaches it.
  A run that is started while the body is away waits up to 15 seconds for it; a stop
  that led to the restart answers when the body is in the world again, or 60 seconds
  later.

What stays in the bridge.
  The events (the last 2000), the jobs with their logs and reports (the last 200), the
  counts deaths and restarts, the game window's connection.

While the body is away.
  The state's `connected` is false. get_state() keeps the body's last reading beside it.
