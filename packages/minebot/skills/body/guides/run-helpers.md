guide("run-helpers"): the object `h` code on the body is given.

h.Vec3               the same class as the name Vec3
h.skills             the same object as the name skills (guide("run-routines"))
h.sleep(ms)          the same function as the name sleep (guide("run-timers"))
h.registry           bot.registry as it was when the body first spawned: the minecraft-data
                     of the game version (blocksByName, itemsByName, ...)
h.channels           the channels this run's code uses, an array of 'move', 'look',
                     'use': the ones its program unit claims, all three when it claims
                     none (guide("run-channels")). A routine called through `skills` reads
                     the run's.
h.go(goal, options), h.path(goal, options)
                     walking the body and searching a route (guide("nav-go")).
h.avoid(name, args), h.unavoid(name), h.rules()
                     a hazard or route rule in force for as long as this run lasts, and
                     what is defined and in force (guide("nav-hazards")).
h.hold()             a promise that resolves when the run is told to stop: for code that
                     only keeps a rule in force.

h.priority(node, fn) -> Promise; h.priority(fn) -> Promise
  Runs fn while the run asks to hold the body with the place of the node `node` of the
  tree of reflexes (its name): that node and the nodes before it still take the body,
  the nodes after it wait. Without a name, every node waits.
  1. Remembers what the run asks for now (nothing at the start of a run).
  2. Sets it to the node's name, or to true when no name was given.
  3. Waits as sleep(200) does: 200 ms, longer while the run is paused; rejects with
     'stopped' when the run is told to stop, and fn is then not called.
  4. Calls fn() with no arguments and awaits it.
  5. Puts back what was remembered, also when fn throws or step 3 rejects.
  Resolves with what fn returns; rejects with what fn throws.
  What is asked is in the state the body reports, as `priority` (guide("run-state")): the
  body sends its state every 50 ms, and the 200 ms of step 3 are there for the run to have
  read it. The body itself does nothing else with it: the run that reads the state holds
  back the nodes that come after the named node. A name that is no node of the tree asks
  for nothing.
  Calls can be nested: each puts back what was asked for before it.
  The priority belongs to the run's context: a routine called through `skills` sets and
  reads the same one.

h.atomic(fn, seconds = 5) -> Promise
  Wrap a step that must not be interrupted in it, and only that step, as small as it can
  be. While fn runs no node of the tree takes the body, and a pause is made only when fn
  is over.
  1. Within another h.atomic: calls fn() and returns what it returns (the same step).
  2. Otherwise as h.priority(fn): asks to hold the body above every node, waits 200 ms,
     then calls fn().
  3. A pause asked while fn runs is kept and made when fn is over (guide("run-pause")).
  4. When fn has not settled `seconds` after it was called, rejects with 'atomic: the
     step took longer than N s'; fn goes on as far as it can without the body, and a
     pause asked meanwhile is made then.
  5. Puts back what h.priority asked before, as h.priority does.
  Resolves with what fn returns; rejects with what fn throws.

h.expect(text, check) -> Promise
  Checks, where it is called, something the code relies on.
  1. Calls check() with no arguments and awaits it. check reads the game as the body
     has it (blocks, entities, the inventory) and returns true, or what it found instead.
  2. When it returned true: logs 'expected "TEXT": it held' and resolves with true.
  3. Otherwise rejects with an Error whose message is 'Nothing further ran: you expected
     "TEXT". It does not hold: FOUND': FOUND is the value as text (a string as it is,
     anything else as JSON, at most 2000 characters). A check that throws counts as one
     that found 'the check threw MESSAGE'; one that throws 'stopped' rejects with that.
  Code that does not catch the rejection ends there with status 'error', and that
  message is the report's error. Every call is in the report's `expected`: {text, held,
  found}. It is not gated: it runs while the run is paused too.

h.note(kind, data = {})
  Notes an event of the kind 'user:' + kind. The fields of `data` are copied onto the
  event, beside those every event has (seq, t, age: guide("run-events")). A field of
  `data` named kind, ev, seq or t takes the place of the event's own; a field named age
  is replaced by the world's age. `data` passes through structured cloning and then JSON:
  with a function in it the event cannot be sent, and nothing is noted and nothing thrown.
  Returns undefined. It is not gated: it notes whether the run is paused, told to stop
  or ended.

In a sense.
  A sense's `h` has Vec3, skills, sleep, registry and note, and no priority, no expect
  and no channels. Its skills and sleep are not those of a run (guide("run-senses")).
