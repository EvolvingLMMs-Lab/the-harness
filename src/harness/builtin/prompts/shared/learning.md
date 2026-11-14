
Your library keeps what you learned, for your later programs and for later runs. What it
holds is listed at the start.

  library.propose(kind, name, text, test=None, summary="", setup=None)
                                    propose an entry
  library.entries()                 proposals and admitted entries with their evidence

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
  trial it had. Kept nodes are set again by themselves when a later session starts.

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
