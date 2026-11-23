guide("run-pause"): what the body does on a code's channels when that code is paused and resumed.

Who is paused.
  A unit of higher priority that takes channels pauses the running jobs that share one
  of those channels with it (none named: every running job); running jobs on other
  channels go on (guide("run-channels")). A job that was already told to stop is not
  paused. Each job paused goes through the steps below on its own. A job in a step that
  must not be interrupted (h.atomic, guide("run-helpers")) goes through them when that
  step is over, or when it has taken longer than its seconds; whoever paused hears that
  it is paused only then.

At a pause.
  In this order:
  1. The job leaves the running jobs and joins the paused jobs. The clock of its time
     (`seconds`) stops. The bridge notes the event job_paused {job, by}: `by` is the name
     given by whoever paused (null when none).
  2. On the body the context is marked paused. An entry {by, seconds: null} is added
     to signal.pauses.
  3. The name of the item in the hand is recorded (null for an empty hand).
  4. The context no longer holds its channels. From here nothing is counted into its
     `did`.
  5. Gated calls of the kind that is done again (dig, lookAt, look, consume, fish,
     waitForTicks) stop waiting for their call under way.
  6. The body lets go of the job's own channels, and of no other:
       move   bot.clearControlStates(): every key up
       use    bot.stopDigging(), then bot.deactivateItem()
       look   nothing
     Errors of these are ignored.
  The game goes on with the body as it then is. Jobs on other channels go on acting.

While paused.
  The code keeps running wherever it does not touch the gate: its own computing, reads,
  the bot's own functions, its listeners and its timers' callbacks all run.
  A gated call that waits (guide("run-bot")) and sleep(ms) stay pending.
  A call that happens at once does nothing and returns undefined; setControlState and
  clearControlStates still change the keys recorded for the run.
  A call on a channel the code did not say it uses still fails at once with the channel
  error.
  A gated call that was under way and is not of the done-again kind (placeBlock, equip,
  craft, an open call, clickWindow, ...) goes on in the library and settles as it does.
  Code that returns or throws while paused ends as usual.
  A paused job that is told to stop ends on the spot: guide("run-ending").

At a resume.
  1. Every running job that shares a channel with this one is told to stop first (cause
     'another job') and the resume waits until they are over.
  2. The clock of the job's time goes on with what was left. The bridge notes job_resumed
     {job, paused_seconds}: all the seconds this job was paused so far.
  3. use: when an item name was recorded and the hand holds no item of that name, the
     first inventory item of that name is equipped to the hand (bot.equip(item, 'hand');
     an error is ignored; with no such item nothing is equipped).
  4. The context is no longer paused and holds its channels again. The last entry of
     signal.pauses gets its `seconds` (two decimals).
  5. move: each key recorded as true is pressed: bot.setControlState(key, true). Errors
     are ignored.
  6. Everything that waited at the gate goes on: pending sleeps resolve, waiting calls
     start, calls of the done-again kind are made again with their arguments.
  The head is not turned back: a job on look that was paused finds it where the code
  that held look meanwhile left it.

signal.pauses
  An array, a new copy at each read, one entry per pause of this run, oldest first:
  {by, seconds} for a pause that is over, {by, seconds: null} for the one that lasts.
  A routine called with the run's signal reads the same.

In the report.
  paused_seconds is the sum of the job's pauses. `seconds` counts from the start to the
  end of the job, pauses included.
