guide("run-routines"): how a routine is saved, versioned, and called from code.

save_routine(name, code)
  name: a lower-case letter, then up to 60 lower-case letters, digits or _. Any other
  name: nothing is saved, error 'name: lower case letters, digits, _'.
  code: a function body with the 15 names of guide("run-scope"). The bridge compiles it
  once to test it; when it does not compile nothing is saved, error 'syntax: ' + the
  parser's message. Either error makes the Python call raise ValueError.
  When a routine of that name exists with a different text, that text is first copied
  as a version. Saving the same text again makes no version.
  The text is written to disk and the body compiles it at once. The code is not run by
  saving. Returns {saved: name, versions: [...]}.

Versions.
  A version's name is the time it was replaced, in UTC, as 2026-01-31T12-00-00-000Z.
  routine_versions(name) lists them, oldest first. read_routine(name) gives the text now
  saved; read_routine(name, version) the text of that version; both raise KeyError when
  there is none.

Where routines live.
  As files on disk, one per name. Every body process compiles all of them when it starts
  (guide("run-restart")). On the body they are one table, name -> compiled function,
  shared by all runs and senses.

skills
  An object with one entry per saved routine. Also h.skills.
  skills.NAME, skills['NAME']     a function when a routine of that name is saved,
                                  undefined otherwise (calling it then throws a TypeError)
  'NAME' in skills                true when saved
  Object.keys(skills)             the names saved
  The table is read each time skills.NAME is read: a routine saved while code runs is
  the one found from then on. A call already under way keeps the function it began with.

skills.NAME(args = {}, log = the run's log, signal = the run's signal) -> Promise
  Calls the routine's function with: the run's bot, h, skills, sleep and timer
  functions; Vec3 and senses as every code gets them; and the three arguments as its
  `args`, `log` and `signal`. The routine acts on the run's channels: a call on a channel
  the run does not use fails as it does in the run (guide("run-channels")).
  Resolves with the routine's return value as it is: not converted, not copied. Rejects
  with what the routine throws.
  It starts no job and makes no context: the routine runs inside the calling run. Its
  gated calls wait when that run is paused and fail with 'stopped' when that run is told
  to stop; its timers and listeners are in that run's lists and are cleared when that run
  ends, not when the routine returns; what it does is counted in that run's `did`; its
  log lines are in that run's logs.
  A routine called without `await` runs alongside the code that called it, in the same
  context.
  A routine can call routines, itself included, in the same way. There is no limit on
  depth but the process's own stack and memory.
  A different `log` or `signal` passed as second or third argument is what the routine
  gets under those names; the gate does not read them: it follows the run.

routine(name, args=None, seconds=60)
  Starts a run whose code is: return await skills["name"](args, log, signal). It is a
  run like any run_js (guide("run-gate")); with no routine of that name it ends with a
  TypeError ("... is not a function") as its error.

In a sense.
  A sense's h.skills calls the same routines with the Mineflayer bot itself (no gate), a
  plain sleep, Node's own timers, a log that drops its lines and a signal {stopped:
  false} (guide("run-senses")).
