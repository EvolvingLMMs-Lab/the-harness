guide("run-gate"): which codes run at once, and what happens when a run is started.

Running on the body.
  Each run (one run_js or routine call) is a job with a context of its own on the body:
  its bot proxy, its sleep, its timers, its recorded listeners and keys, its channels, its
  `did` counters. A context is in one of these conditions:
    running    gated calls on its channels go through (guide("run-bot"))
    paused     gated calls wait or are left out (guide("run-pause"))
    told to stop   gated waits fail with 'stopped' (guide("run-ending"))
    ended      gated calls throw 'this code has ended: it no longer has the body'
  A routine called through `skills` is no job: it runs inside the context of the run that
  called it, on its channels.
  Reading is not gated in any condition: properties of bot, the bot's own objects, and
  every function outside the gated lists.

Channels.
  A job uses the channels its program unit claims, of move, look and use; none claimed:
  all three (guide("run-channels")). Two jobs share a channel when both use it. Running
  jobs never share a channel: jobs on channels of their own run at the same time, and at
  most one running job uses each channel.

Starting a run.
  1. Every running job that shares a channel with the new run is told to stop, with the
     cause 'another job' (its report: ended "other code took the body"). The new run
     waits until all of them are over: until their code returns, or, 3 seconds later,
     until the body's process was ended and a new one is in the world
     (guide("run-restart")). Running jobs on other channels go on. Paused jobs are left as
     they are: they stay paused, also when they share a channel with the new run.
  2. When the body is not in the world, the start waits up to 15 seconds for it. When it
     is still not there, nothing runs; the call's report has ended None and no error.
  3. The job gets the next id ('j1', 'j2', ...) and joins the running jobs, with its
     channels. The bridge keeps the last 200 jobs.
  4. The body's process is given the code, the args and the channels. It answers at once,
     with status 'error' and no line of the code run, in three cases:
       'the body is not in the world'            it has not spawned yet
       'the body is dead: no code runs on it until respawn()'   bot.isAlive is false
       'syntax: ' + the parser's message         the code does not compile
  5. Otherwise it makes the context and calls the function in a later microtask with the
     15 values of guide("run-scope").
  The start does not change the keys held down or a dig under way: what earlier code left
  set is still set, unless that code was ended in step 1 and let go of its channels.

The time given with `seconds`.
  run_js(code, args, seconds = 60) and routine(name, args, seconds = 60) pass `seconds`
  as the job's time. When the job has run that long, the bridge notes the event over_time
  {job, seconds} once, and the code goes on; nothing is stopped. The clock of this time
  stands still while the job is paused and goes on with what was left at a resume.
  seconds = 0 sets no such clock.

Several jobs.
  Any number of jobs can run, each on channels no other running job uses; any number can
  be paused, kept in the order they were paused. The state names them: jobs_running (the
  ids of every running job) and jobs_paused (guide("run-state")).
  Pausing and resuming are done from outside the body: the run pauses the jobs that share
  a channel with a unit of higher priority that takes those channels, and resumes them
  when that unit has ended (guide("run-pause")). A resumed job ends first every running
  job that shares a channel with it. Code on the body cannot pause or resume a job. It
  can ask for a priority for one action: h.priority, and keep a step from being
  interrupted: h.atomic (guide("run-helpers")).
