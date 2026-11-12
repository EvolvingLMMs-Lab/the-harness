Keep observations and notes you will need again. Skill and reflex proposals require trusted verification before use. Use what your library already holds first: its tested skills and
reflexes are listed at the start; call them, and rewrite one that falls short instead of writing
new code beside it. When something happens that your memory entry "situations" did not
foresee, add it there and learn for it. Propose an entry when you learned something you will
need again:
  library.propose(kind, name, text, test=None, summary="")
    kind "note": a sentence or two you want in your instructions from now on (what a
<!-- if: legacy_memory -->
      control does, a rule of this place); "memory": a situation and what worked in it,
      for recall(query); "skill": code (functions, or a ClosedLoop class) your programs call
<!-- else -->
      control does, a rule of this place); "skill": code (functions, or a ClosedLoop class) your programs call
<!-- end -->
      by name; "reactive": the lines that set reflexes or a tree (set_reflex, tree): they
      are set again by themselves when a later session starts.
    Include a test that calls the skill or reflex and checks its effect. Code stays pending
    until a trusted host verifies the exact revision. A successful proposal can return
    {"ok": True, "queued": True}. End that program to give the host its verification
    boundary. Use a skill in a later program once the active library lists it.
    For a practice scene, supply setup with the test. Its code can call
    sandbox(op, **arguments) when the verifier provides a compatible environment.
  library.entries()                 proposals and admitted entries with their evidence
Write a skill that acts as a closed loop: a subclass of ClosedLoop fills in confirm() (the
target is what you think: True or the reason not to act), do() (the action), check() (the
world changed as it should: True or why not) and recover(reason) (between tries); `tries`
and `max_seconds` bound it, and calling the class runs it and returns a Result: .ok,
.reason, .tries, .seconds, .detail. Keep a skill to one thing (open a menu, walk to what you
see, pick an item).
