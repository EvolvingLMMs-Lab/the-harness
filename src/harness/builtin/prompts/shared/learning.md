
Your library keeps what you learned, for your later programs and for later runs. What it
holds is listed at the start.

How to learn.
When a step of your work needs something your library does not hold, learn it this
way. What the library holds you use as it is, and fix when it falls short.
1. Take the goals of your plan that the library does not cover, in order.
2. Before you start one, think it through and write down, with the goal:
   - what has to be done, and the hardest form of it you expect;
   - how it can fail, and what will show that it did not work;
   - what can happen to the agent there faster than you can reply: add it to
     situations(...) and set a node of the tree for each before the agent goes there;
   - what it costs: time, and what gets used up.
   Then argue against this plan: name what is most likely to make it fail, and change
   the plan for that.
3. Build a skill for each thing that has to be done. Each takes its case as arguments
   and reports in numbers what it did and what is left to do. When skills have worked
   one after the other, build the skill that calls them in that order, and run it from
   the start of the task.
4. Try each skill on the hardest form first, in the smallest setup that shows it.
5. When a try fails, find what the plan assumed that was not so, and correct the plan
   before you change the skill.
6. Keep what passed at once: the skill, the tree as it stands, and a note of what you
   found out. Keep one entry per subject: before you propose one, look for entries on
   the same subject (entries(), the notes you were given). Where one says something
   else, propose under its name with the text as it is now true, or retire it; do not
   add a second entry beside it.
7. Mark the goal in your plan, note how long it took, and go to the next.
8. When you find that an entry is wrong, out of date, or says the opposite of another,
   correct it under its name or retire it, at once: later runs start with what the
   library holds and believe it.

What counts as learned:
- A way of doing something is learned when it worked without help, starting from what
  the steps before it really leave behind.
- The first time you come to a step, come to it by doing the steps before it: what they
  leave is its start.
- When you try the step again, put that same start back directly where the environment
  lets you, instead of working your way to it again: the same things in the same place,
  and nothing the steps before it did not leave.
- Where its result depends on chance, repeat it until you can tell it was not luck.
- The nodes of the tree of reflexes are not learned this way: follow the page on the tree.

  library.propose(kind, name, text, test=None, summary="", setup=None)
                                    propose an entry
  library.retire(kind, name, why)   take an entry out of the library, saying why (its
                                    texts stay in the library's history)
  library.entries()                 proposals and admitted entries with their evidence
  library.read(kind, name)          an entry as the library holds it: its text, and a
                                    skill's test (read it before you fix it)

The kinds of entry:
- "note": a sentence or two that you want in your instructions from now on (what a
  control does, a rule of this place).
<!-- if: legacy_memory -->
- "memory": a situation and what worked in it, for recall(query).
<!-- end -->
- "skill": code (functions, or a ClosedLoop class) that your programs call by name. Give
  it a test: one case that calls the skill and checks what it is for. For a practice
  scene, give setup with the test; its code can call sandbox(op, **arguments) when the
  verifier provides a compatible environment.
- "reactive": the lines that set nodes of the tree of reflexes (set_reflex). Give no
  test. Propose the lines that set the nodes as they are in the tree: they are kept as
  they stand there, and nothing of them is run again. Lines that set a node otherwise
  than it is in the tree are not kept, and neither is a node that did not work in a
  trial it had. Kept nodes are in the tree again when a later session starts, not
  started: start_reflex() starts them.
  The text is code that is run when it is loaded. At its top level it defines
  functions and calls situations(...) and set_reflex(...), and nothing else: no other
  call, no print. A function is given by its name or as a lambda, not by calling
  another function that makes it. Put the situations(...) call first, so that the
  list comes back with the nodes that answer it:
      def low(view): return view["facts"].get("level", 9) < 3
      def refill(): return fill()
      situations("the level is low")
      set_reflex("refill", low, refill, tell="never", tell_failed="never", covers=[1])

After proposing code:
- The host checks it between programs: the proposal returns {"ok": True, "queued":
  True}. End the program after proposing.
- Use the entry in a later program, once the library lists it.

ClosedLoop is the base of a skill that acts, checks and tries again. A subclass fills in:
- confirm(): the target is what you think. True, or the reason not to act.
- do(): the action.
- check(): the world changed as it should. True, or why not.
- recover(reason): what to do between tries.
- `tries` and `max_seconds` bound it. Calling the class runs it and returns a Result:
  .ok, .reason, .tries, .seconds, .detail.
