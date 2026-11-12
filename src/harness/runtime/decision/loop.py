"""Decision protocol and dispatch tables.

TaskRun coordinates these decisions with task lifecycle and the model's units.
"""


# Seconds between two model_text records of a streamed reply.
STREAMED_SECONDS = 0.3


# Added to the system prompt of an interactive conversation.
INTERACTIVE_PROMPT = (
    "\n\nA user is with you in this conversation. Their messages reach you as \"Message from the user: ...\". "
    "A reply in plain text, without a block, is your answer to them: what you did or found, or a question you "
    "need answered. It ends this turn, and the conversation goes on with their next message: you keep what you "
    "have (your programs' variables, the rules, the facts, the environment)."
)


# Sent back for a reply that only announces what the model will do, at most ANNOUNCED_TIMES
# in a row (replayed: it then wrote its program in 32 of 33 calls).
ANNOUNCED_TIMES = 2


ANNOUNCED = ("Nothing ran: your reply says what you will do, but it has no {block} block. Do it now: reply with "
             "the {block} block itself, starting with its opening tag. If you meant only to tell {who} "
             "something, reply with that in plain text again.")


# An empty reply (reasoning only, not cut off: the provider's text never came) is asked
# again at once, without a format error, at most this many times in a row.
EMPTY_RETRIES = 2


# runtime.turn_grace_seconds: how long a program may hold the model's turn. One that is
# over by then gives the turn back with its result; a longer one goes on as a unit, and
# the turn comes back with its handle.
TURN_GRACE_SECONDS = 2.0


# runtime.longest_wait_seconds: the longest a <wait> lasts; one that names no time lasts
# this long, so no wait is endless.
LONGEST_WAIT_SECONDS = 60.0


# What the model is told when its wait ended: why (WAIT_ENDS), and after how long; the units
# that run follow, each with how long it has run and when it last printed (messages.unit_text).
WAIT_ENDED = "Wait ended after {seconds:.1f} s: {why}."
WAIT_ENDS = {"unit": "a unit you started ended", "message": "a message reached you", "event": "an event reached you",
             "time": "its time is over"}


# What the model is told, with its next prompt, when its conversation goes on in a new
# process (`units`: those that still ran when the old one was last heard of).
CONTINUED = ("Note from the harness: this conversation was continued in a new process. Its messages and facts "
             "are restored. What lived in the old process is gone: the variables and functions your programs "
             "defined, the rules you set, and the units that still ran{units}. Set up again what you still need.")


# What the model is told when its turn comes back while its program still runs.
RUNNING = "Program {number} is still running, as unit {unit}."


# Added to the feedback of a program that ended.
PROGRAM_ENDED = ("\nThe program ended. If the task is done, answer in plain text; otherwise write a program "
                 "for the rest of the task.")


# runtime.thinking: a level bounds the reasoning effort (a model set lower keeps its own)
# and the reply's tokens; "model" leaves them. (Replayed: nine in ten replies under 500.)
THINKING = {"model": (None, None), "none": ("none", 2000), "low": ("low", 2000), "medium": ("medium", 8000),
            "high": ("high", None)}


EFFORTS = ("none", "low", "medium", "high")


# Added to the system prompt at "none" and "low".
THINK_BRIEFLY = ("\n\nThink briefly: a sentence or two, then the block. Time goes on while you think, and a long "
                 "reply is cut off with nothing run.")


def _model_of(chat) -> dict:
    """The model a call goes to and its reasoning effort, as a record says them (none for a
    scripted model)."""
    model = getattr(chat, "model", None)
    if not isinstance(model, str):
        return {}
    effort = getattr(chat, "reasoning_effort", None)
    return {"model": model, **({"reasoning_effort": effort} if effort else {})}


def _thinking(main: dict, level: str) -> dict:
    """The main model's role with its effort and reply length bounded by `level`."""
    effort, tokens = THINKING[level]
    main = dict(main)
    if effort is not None:
        own = main.get("reasoning_effort")
        if own not in EFFORTS or EFFORTS.index(own) > EFFORTS.index(effort):
            main["reasoning_effort"] = effort
    if tokens is not None:
        main["max_output_tokens"] = min(int(main.get("max_output_tokens") or tokens), tokens)
    return main


# Why the model is called (a model_request's reason): a pending message or unresolved event
# (the method that says whether one is pending) comes before what happened last.
TRIGGERS = {"user": "_pending_message", "escalation": "_unresolved",
            "start": None, "program_end": None, "program_running": None, "unit_end": None, "wait_end": None,
            "error": None,
            "rejected": None, "finish_refused": None, "verify": None, "empty": None, "format": None}


# The trigger of a role's request: explicit requests share the transport of decisions.
REQUESTS = {"verifier": "request", "observer": "request", "vlm": "request", "pointer": "request",
            "reflection": "reflect", "compaction": "compact"}


# Compaction (runtime/task/run.py _compact_if_due). When the context a call read reaches
# runtime.compact_at_tokens, the model is asked for a summary of the conversation (COMPACT,
# after its last message), and the summary (COMPACTED) stands in the first message in
# place of every message before the last KEPT_MESSAGES.
KEPT_MESSAGES = 4
COMPACT = (
    "You have written a partial transcript for the initial task above. Please write a summary of the transcript. "
    "The purpose of this summary is to provide continuity so you can continue to make progress towards solving "
    "the task in a future context, where the raw history above may not be accessible and will be replaced with "
    "this summary. Write down anything that would be helpful, including the state, next steps, learnings etc. "
    "Give it these sections:\n"
    "1. Primary request and intent: what was asked, in full.\n"
    "2. Key facts: what you found out about the environment and how it behaves.\n"
    "3. What exists: what your programs defined that is still needed, what the library holds, the reflexes "
    "you set and the units that run, each with what it is for.\n"
    "4. Errors and fixes: what went wrong and how it was repaired.\n"
    "5. Problem solving: what is solved and what is still being worked out.\n"
    "6. All messages of the user that are not results of programs.\n"
    "7. Pending tasks.\n"
    "8. Current work: precisely what you were doing just before this summary.\n"
    "9. Next step: the step that follows directly from the current work.\n"
    "Reply with the summary only, no program. You must wrap your summary in a <summary></summary> block.")
COMPACTED = (
    "This conversation is being continued from an earlier part of it that ran out of context. The summary below "
    "covers the earlier portion. The messages after this one are the most recent messages from before the "
    "compaction, kept verbatim. The kernel with what your programs defined, the library, the tree of reflexes "
    "and the units that run are as they were.\n\nSummary:\n{summary}")


# What a reply of the model does: the method of TaskRun for each output. A reply that is
# text (message) and a <finish> block are the same answer.
OUTPUTS = {"program": "_out_program", "verify": "_out_verify", "finish": "_out_answer", "wait": "_out_wait",
           "message": "_out_answer", "invalid": "_out_invalid", "empty": "_out_empty"}


# How a turn ends (the reason of its turn_result record and of the IDLE state after it), and
# the status the summary keeps for it (what a benchmark's caller reads). Model calls and
# wall time are the turn's and begin anew with the next one; cost is the conversation's.
TURN_ENDS = {"answer": "finished", "budget": "budget_exhausted", "wall_time": "wall_time_exhausted",
             "cost": "cost_exhausted", "error": "error", "interrupted": "interrupted",
             "episode_ended": "episode_ended"}
# The ends after which only a new message starts a turn: what reached the model before
# them is kept in its history and starts none.
TURN_STOPS = ("cost", "error", "interrupted")


# The summary's count of each role's requests.
COUNTS = {"verifier": "verifier_calls", "reflection": "reflection_calls", "observer": "vision_calls",
          "vlm": "vision_calls", "pointer": "vision_calls", "compaction": "compaction_calls"}
