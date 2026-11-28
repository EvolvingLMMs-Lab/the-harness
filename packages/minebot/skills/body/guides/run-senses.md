guide("run-senses"): what a sense's code is given, when it runs, how code reads senses.

How a sense is compiled.
  The text is the body of a plain function (not async) with three parameters: bot, Vec3,
  h. It is made in the global scope of the body's process, like a run's code
  (guide("run-scope")): no require; Node's globals are there.
  A sense's name follows the rule of a routine's name: a lower-case letter, then up to
  60 lower-case letters, digits or _.

What it is given.
  bot     the Mineflayer bot itself: no proxy, no gate. Every call acts at once.
  Vec3    the Vec3 class
  h       {Vec3, skills, sleep, registry, note}. There is no h.priority, no h.atomic and no
          h.channels: a sense uses no channel.
          h.skills are the saved routines called with the Mineflayer bot itself, a plain
          sleep, Node's own timers, a log that drops its lines, and a signal that is
          {stopped: false}. h.sleep(ms) is a plain timeout promise. h.note is the one of
          guide("run-helpers"). A new h object is made for every computation.
  A sense belongs to no run: nothing it starts is cleared when a run ends, and nothing it
  does is counted in a run's `did` unless a running job holds that channel at that
  moment (guide("run-channels")).

When it runs.
  Once when it is defined (when the body is in the world): the answer to the definition
  holds that value, or the error.
  Then with every state the body builds: every 50 ms, while the body is in the world and
  has its entity, all senses one after the other, in the order they were defined, on the
  process's single thread between other work.
  And whenever code calls senses.NAME().

The value.
  What the function returns, converted as a run's result is (guide("run-result")), is
  the state's sensed[NAME].
  The function throws: the value is null and sense_errors[NAME] is the error's message,
  its first 200 characters.
  The function returns a promise: the value is null and the error is 'it returned a
  promise: a sense does not wait'. A rejection of that promise is ignored.
  A sense with no error has no entry in sense_errors.

The time limit.
  Each computation for the state is timed. One that takes more than 10 ms adds one to
  the sense's count of slow runs; one within 10 ms sets the count to 0. At 3 the sense
  is no longer computed for the state: its value is null and its error is 'it took N ms,
  more than the 10 ms a sense has, 3 times running: it is not computed until it is
  defined again'. Defining the sense again, with the same text or another, starts it
  anew. The computation at the definition and those of senses.NAME() are not timed.

senses (in a run's code)
  An object: one function per sense defined on the body. The same object is given to
  every run and routine.
  senses.NAME() computes the sense at that moment and returns the function's value as it
  is, not converted. It throws what the function throws, and throws 'it returned a
  promise: a sense does not wait' for a promise. It computes also a sense that is no
  longer computed for the state.
  senses.NAME is undefined when no sense of that name is defined.
  A sense defined again while code runs is the one senses.NAME() computes from then on.

Where senses live.
  As files on disk, one per name, like routines. Every body process compiles all of them
  when it starts; one that does not compile is noted as sense_load_error {name, message}.
  Defining writes the file, then asks the body: the answer is {name, defined, value,
  error}. error is 'syntax: ...' when the text does not compile (nothing is saved), 'the
  body is not in the world' when the body has not spawned (the sense is saved and
  defined), 'the body did not answer' when the body's process says nothing for 3 seconds.
  Removing deletes the file and the sense on the body; the states after that have no
  entry for it.
