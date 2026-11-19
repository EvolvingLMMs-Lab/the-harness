guide("units"): how units run, what you are told of them, and how they share the environment.

Units.
- Your work runs as units. A program is a unit: it runs alongside the others, with its
  own output and result.
- A program that is over within a moment gives you its result at once. A longer one
  keeps running: you are asked again at once, with its name, and you get its result when
  it ends.
- While it runs you can start another program, cancel one, or wait.
- A program that is to act when the running one is over begins with after(unit): it
  returns when that unit has ended, however it ended, with {"ended", "done"}. Put the
  expect after it, so that it checks what the earlier program left. Without after(unit),
  each call that acts waits only for the call that has the environment at that moment:
  two programs that each act several times take the environment in turn, call by call.
- A wait ends when a unit you started ends, when a message or an event reaches you, or
  when its time is over. You are told which.
- What a program starts (units, reflexes) keeps running after the program and after your
  turn. When a unit ends or an event arrives, your next turn starts. Cancel what should
  not keep running.

What you are told, and in what order.
- Each time you are asked, you are told, in this order: what your last reply led to;
  then what reached you by itself since (a unit ending, an event, a message), the most
  urgent first; last, how things stand now: the state, the units that run, and what
  changed in the tree of reflexes. While a program of yours runs, how things stand ends
  with the same words each time, whatever woke you: what that program asks of you.
- What cannot wait reaches you first: what the environment tells, a unit that ended
  with an error, and an event (one from a node of the tree comes when that node's tell
  says). It ends a wait at once. The reply you are writing when it comes is still used:
  its program runs and checks with expect what it relies on, and you are told the news
  with the next call. A message of the user drops the reply you were writing, and you
  are asked again. Everything else is told the next time you are asked.
- Something that happened before comes with its count: which one of its kind it is in
  this run, and when the earlier ones happened.
- Everything you were told and everything you replied in this run is kept, in order, in
  one file that a program can read. The summary that stands in for an earlier part of
  the conversation gives its name. To say something about the run as a whole, count from
  that file; do not rely on what you remember.

How a unit ends.
- Every unit ends with the same report, whoever started it: how it ended (by itself, an
  error, an event, cancelled, its time limit), whether its result is there (done: yes or
  no), and what it returned.
- A unit that ended by itself is not thereby done. Read done.
- A program states its result with until(condition): a function of the view that is true
  when the work is done. It is checked when the program ends.
- A program that only reads says until(None).
- A program that says neither is not started. You are told, and you send it again with
  its result stated.
- A program checks what it relies on with expect(text, check), before it acts on the
  environment. An action with no expect before it in the program is refused, and the
  program ends there. When a check does not return True, a program that acts ends there,
  with what the check found; a program that only reads (until(None)) goes on. What a
  check itself does in the environment is reading. A reflex's program is held to none of
  this.
- The report lists every expect with what its check showed. When all of them held and
  done is no, the program relied on something it did not check, or its until does not
  say the result.
- until(condition, report=None, interrupted="tell") takes two more settings.
  report: the message you read whenever you are told of this program: when a reflex
  takes the environment from it, when it ends, and its text also in the line of running
  units. Write it for this program: put in it what you will need at that moment to judge
  how far its work is and whether it still gets there.
  It is a function, called at the moment you are told as report(view): view is the
  state then.
  A message is text, plain data, a picture, a file, or a list of these in the order you
  want them: a picture is what look(...) or get_observation() returns, or an image you
  made; a file is a pathlib.Path (an image file is shown, a folder is listed, any other
  file is given as its text). At most 2000 characters of text, 4 pictures and 4 files.
  interrupted: what happens when a reflex takes the environment from the program.
  "tell" (the default): the program goes on, and you are told, in one message with what
  the reflex says. You are told so of one program 3 times; the times after that are
  counted and told with its end. When you are told, do not wait on as before: compare
  what the program reports with what it is for, find out why the reflex had to act during
  it, and decide: the program goes on as it is, the program is changed or ended, or the
  node is changed.
  "stop": the program ends there, and you are told at once.
  "never": the program goes on, and you are not told.

While something runs.
- What you leave running is yours to follow. You are told when it ends without its
  result.
- When you are asked while it runs, compare what it has done so far with its result,
  from its output and from what the environment shows.
- If it is not getting there, find out why before you change it, let it go on or end it.
- Know how long it has to run, and do not wait for its end to learn that it failed:
  that costs all the time it ran. Wait much shorter than its run and look; have its
  report show the numbers that tell how far it is (until(report=)); set a node of the
  tree that tells you when what it relies on is gone.
- When it is getting there, prepare what comes after it, with what needs no acting on
  the environment: read the pages the next goal needs, write and keep the code it needs,
  set the nodes for where the agent goes next, bring the plan up to date.

Units of your own.
- spawn(fn, name=None, priority=None, restart=False, until=None): run fn as a unit of
  its own and go on (until: what it is for, as until(condition) says for a program). Its
  handle: .wait(timeout=None) returns what fn returned, .cancel() ends it,
  .send(message) gives it a message that receive(timeout=None) reads inside fn, .status.
  entries(): the handles of the units that run, your programs among them, each with its
  .id (the name you are told).
  output_of(unit, chars=2000): what a unit (its id or its handle) has printed so far, the
  last chars characters (at most 30000); its result still has all of it when it ends.
  What you are told has a limit, and says so where it left something out: what a unit
  printed or returned is told whole up to 30000 characters; more is saved to a file, and
  you are told the file, which a program can read, and its first 2000 characters. Of a
  unit that failed you are told the first and last 5000 characters.
  Where the environment has channels (CHANNELS), units act at the same time, each on the
  channels it took: spawn(..., claims=[...]) or claim(*channels) takes them,
  unclaim(*channels) lets them go, channels() says who has each. Reaching for a channel
  another unit has is a CHANNEL_CONFLICT event.

Who has the environment.
- A unit of higher priority (a reflex's program) takes the environment from a lower one
  and holds it until it ends. What you start meanwhile waits for the higher unit to end.
  Units of equal priority take turns.
- What becomes of the lower call depends on the environment. Your instructions say which
  of the two it is.
- Where it is paused: the lower call is suspended where it is and goes on by itself when
  the higher unit has ended. Its program does not end, and you are not asked.
- Where it is ended: the lower call ends there with the event PREEMPTED and what it had
  done, and you are told at once: which reflex took the environment, from which program,
  and the state. You decide what goes on: the same again, or something else. Only a unit
  started with restart=True has its call started again by itself (its result counts it:
  .restarts).
- Your programs have priority 0, so every reflex takes the environment from them.
- An action of a program that must not be broken off: put `with at_priority(n):` around
  that action, and no more than that action. During the block a reflex whose own
  priority is n or more still takes the environment; a reflex below n waits. It is
  judged again when the block ends, and you are told once that it was held back (the
  event HELD_BACK).
- While a block holds a place, nothing below it answers what happens to the agent. A
  program that holds one for its whole length has taken the tree's work on itself and
  must do all of it.
- at_priority is for rare cases. Before you use it, ask whether the tree is wrong: when
  a node breaks off your work, look at that node first. A node that takes the
  environment when it should not is changed in the tree (guide("tree"), section 5).
  Use at_priority only when the node is right and this one action still must not be
  broken off.
- Code that runs for long in the environment itself asks for a place the same way, where
  the environment's page says how.
