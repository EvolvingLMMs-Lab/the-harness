Your library keeps what you learned, for your later programs and for later runs. A skill
is verified by its test before use; a tree of reflexes is kept as its nodes stand in the
tree; the skills and reflexes it holds are listed at the start. An entry is proposed with:
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
    A skill comes with a test, one case of it: it calls the skill and checks what it is
    for. Reactive lines come with none: propose the lines that set the nodes as they are in
    the tree, and they are kept as they stand there; nothing of them is run again. Lines
    that set a node otherwise than it is in the tree, and a node that did not work in a
    trial it had, are not kept. Code
    stays pending
    until a trusted host verifies the exact revision. A successful proposal can return
    {"ok": True, "queued": True}. End that program to give the host its verification
    boundary. Use a skill in a later program once the active library lists it.
    For a practice scene, supply setup with the test. Its code can call
    sandbox(op, **arguments) when the verifier provides a compatible environment.
  library.entries()                 proposals and admitted entries with their evidence
ClosedLoop is a skill that acts as a closed loop: a subclass fills in confirm() (the
target is what you think: True or the reason not to act), do() (the action), check() (the
world changed as it should: True or why not) and recover(reason) (between tries); `tries`
and `max_seconds` bound it, and calling the class runs it and returns a Result: .ok,
.reason, .tries, .seconds, .detail.
