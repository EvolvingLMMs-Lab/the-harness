guide("run-scope"): how the code given to run_js or save_routine is compiled, and its names.

How the code is compiled.
  The text is the body of an async function. The body's process makes it with the
  AsyncFunction constructor, with 15 parameters in this order: bot, h, Vec3, skills,
  sleep, log, signal, args, senses, setTimeout, setInterval, setImmediate, clearTimeout,
  clearInterval, clearImmediate. There is no goals and no Movements: no plugin that
  walks is loaded.
  `await` works at the top level of the text. `return value` ends the code with that
  value; code that reaches its end without `return` has the value undefined.
  The function is in sloppy mode; a text that begins with 'use strict' is in strict mode.
  A `let`, `const` or `class` at the top level of the text with one of the 15 names does
  not compile. The run ends at once with the error 'syntax: ' followed by the parser's
  message (for `const h = 1`: "syntax: Identifier 'h' has already been declared"). Every
  other syntax error ends the run the same way, before any line of it runs.
  The same declaration inside a nested block or a nested function compiles and hides the
  name there. `var` with one of the names compiles and keeps the value the name has.
  The function is made in the global scope of the body's process. require, module,
  exports, __dirname and __filename are not defined there: reading one throws a
  ReferenceError. Node's globals are defined (process, Buffer, console, performance,
  globalThis). What console.log writes is in no report.
  Every run and every routine is compiled and run in the one body process, one after the
  other on its single thread. A value stored on globalThis or on the bot stays for later
  runs until the body's process is started again (guide("run-restart")).

The names.
bot                  the Mineflayer bot behind the gate: guide("run-bot")
h                    an object of helpers: guide("run-helpers")
Vec3                 the Vec3 class of the vec3 package
skills               the saved routines, callable: guide("run-routines")
sleep(ms)            a wait the body can end: guide("run-timers")
log(...values)       adds a line to the run's logs: guide("run-result")
signal               signal.stopped and signal.pauses: guide("run-ending")
args                 the value given as `args`: see below
senses               the senses as functions, senses.NAME(): guide("run-senses")
setTimeout, setInterval, setImmediate, clearTimeout, clearInterval, clearImmediate
                     timers that end with the run: guide("run-timers")

args.
  For run_js(code, args) and routine(name, args): the object given, after a passage
  through JSON; {} when none was given (None, or any empty value).
  For a routine called as skills.NAME(args) from other code: the very object passed, not
  copied; {} when the call passes none.

Other pages on running code.
  guide("run-gate")         which codes run at once, how a run starts
  guide("run-channels")     the channels move, look, use: what code says it uses
  guide("run-pause")        what a pause and a resume do
  guide("run-ending")       every way a run ends, and what is cleared
  guide("run-result")       log, the return value, a thrown error, how values are converted
  guide("run-report")       the report of a run: its fields and the `did` counters
  guide("run-restart")      when the body's process is ended and started again
  guide("run-death")        what the body does at death and for a respawn
  guide("run-events")       the events the body notes
  guide("run-state")        the state the body reports
  guide("run-differences")  what this bot has that a plain Mineflayer bot does not
