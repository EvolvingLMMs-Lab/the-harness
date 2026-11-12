"""Decision protocol and dispatch tables.

TaskRun coordinates these decisions with task lifecycle and the model's units.
"""


# Seconds between two model_text records of a streamed reply.
STREAMED_SECONDS = 0.3


# Added to the system prompt of an interactive conversation.
INTERACTIVE_PROMPT = (
    "\n\nA user is with you in this episode. Their messages reach you as \"Message from the user: ...\". "
    "To ask for information needed by this task, reply in plain text without a block; the task waits "
    "for the answer. Use <finish> for the completed task and your final answer. That ends this run; "
    "it does not open a new conversation turn."
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


# What the model is told when its wait ended: why (WAIT_ENDS), and after how long.
WAIT_ENDED = "Wait ended after {seconds:.1f} s: {why}."
WAIT_ENDS = {"unit": "a unit you started ended", "message": "a message reached you", "event": "an event reached you",
             "time": "its time is over"}


# What the model is told, with its next prompt, when its conversation goes on in a new
# process (`units`: those that still ran when the old one was last heard of).
CONTINUED = ("Note from the harness: this conversation was continued in a new process. Its messages and facts "
             "are restored. What lived in the old process is gone: the variables and functions your programs "
             "defined, the rules you set, and the units that still ran{units}. Set up again what you still need.")


# What the model is told when its turn comes back while its program still runs.
RUNNING = ("Program {number} is still running, as unit {unit}. Your turn is your own meanwhile; its result "
           "reaches you when it ends.")


# Added to the feedback of a program that ended without ending the task.
NOT_FINISHED = ("\nThe program ended without calling finish(). If the task is done, finish; otherwise "
                "write a program for the rest of the task.")


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
            "reflection": "reflect"}


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
          "vlm": "vision_calls", "pointer": "vision_calls"}
