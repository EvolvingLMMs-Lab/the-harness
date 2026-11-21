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


# An empty reply (reasoning only, not cut off: the provider's text never came) is asked
# again at once, without a format error, at most this many times in a row.
EMPTY_RETRIES = 2


# runtime.turn_grace_seconds: how long a program may hold the model's turn. One that is
# over by then gives the turn back with its result; a longer one goes on as a unit, and
# the turn comes back with its handle.
TURN_GRACE_SECONDS = 2.0


# runtime.tell_budget: whether the model is told, with every call, what the run has left
# (model calls, environment steps, live time). "never": the limits are the host's to keep
# and the model is not told them; "always": told with every call (a benchmark whose
# episodes are a few dozen calls, where the model must plan its end).
TELL_BUDGET = ("never", "always")
# Whether the model's nodes of the tree of reflexes follow the method: the page on how a tree
# is made is read first, every node does something, and its condition can be judged
# (runtime.reflex_method; runtime/execution/session.py).
REFLEX_METHOD = ("required", "optional")
# A page of instructions the model asked for (guide(name)), given whole with the result of
# the unit that asked: from here on it is read (as Claude Code's Read returns a file).
GUIDE_PAGE = "guide(\"{name}\"), the page you asked for:\n\n{page}"
# The pages read before a summary are named after it, and not given again (as Claude Code notes a
# file read before the conversation was summarized whose contents it does not include): what
# stands after a summary stays small, so that the next summary is far off.
GUIDES_READ = ("Note: you read these pages before this summary: {names}. Their text is not included here; "
               "call guide(name) to read one again.")


# Whether a program has to say what it is for (runtime.purpose). "required": one that calls
# neither until(condition) nor until(None) is not started and the model is told NO_PURPOSE, as
# Claude Code refuses a call that leaves out what it is for.
PURPOSES = ("required", "optional")
NO_PURPOSE = ("Nothing ran: this program does not say what it is for. Call until(condition) in it, with a "
              "function of the view that holds when the program's work is done; a program that only reads "
              "says until(None). Send the program again with it.")


# What the model is told with a program's end when all it expected held and what it was for
# is not the case.
ALL_HELD = ("Every expectation held and the result is not there: the program relied on something it did not "
            "check, or its until does not say the result.")


def calls(program: str, name: str) -> bool:
    """Whether the program calls name(...). One that does not parse says nothing either way:
    it is started, and its error is the answer."""
    import ast

    try:
        tree = ast.parse(program)
    except (SyntaxError, ValueError):
        return True
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
               for node in ast.walk(tree))


def says_purpose(program: str) -> bool:
    """Whether the program calls until(...)."""
    return calls(program, "until")




# runtime.longest_wait_seconds: the longest a <wait> lasts; one that names no time lasts
# this long, so no wait is endless.
LONGEST_WAIT_SECONDS = 60.0


# What the model is told when its wait ended: why (WAIT_ENDS: the kind of the notice that
# ended it, runtime/decision/notices.py, or its time), and after how long.
WAIT_ENDED = "Wait ended after {seconds:.1f} s: {why}."
WAIT_ENDS = {"unit": "a unit you started ended", "message": "a message reached you", "event": "an event reached you",
             "note": "the harness told you something", "time": "its time is over"}


# How the model reads an event that reached it; what the event's record holds follows.
# The plan (the checklist skill) is shown to the model again when it has made PLAN_STALE_CALLS
# calls without touching it, as Claude Code reminds of a task list that was not used recently.
PLAN_STALE_CALLS = 10
PLAN_STALE = ("Your plan has not been touched for {calls} calls. As it stands:\n{steps}\n"
              "Check off what is done, and call plan() again if it no longer matches what you are doing. "
              "This is only a reminder: ignore it if it does not apply.")


# The part of the state the environment calls the agent's situation (its profile: "situation")
# took a value it has not had in this run.
SITUATION_NEW = ("The state's {key} is now {now}, for the first time in this run (it was {before}). "
                 "The tree of reflexes has {nodes}, set before that. Before a program acts here, go through what "
                 "can happen to the agent here and give situations(...) the lines for it.{hint}")


EVENT = "Event {kind} from {source}"
# An event of a kind the model was told before in this run: its count, and how long ago the
# last EARLIER_TOLD of the earlier ones were told.
EVENT_AGAIN = " (the {count} of this kind in this run; the earlier ones {earlier} ago)"
EARLIER_TOLD = 5


def ordinal(number: int) -> str:
    """1st, 2nd, 3rd, 4th, 11th, 22nd."""
    if 10 <= number % 100 <= 20:
        return f"{number}th"
    return f"{number}" + {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")


# What the model is told, with its next prompt, when its conversation goes on in a new
# process (`units`: those that still ran when the old one was last heard of).
CONTINUED = ("Note from the harness: this conversation was continued in a new process. Its messages and facts "
             "are restored. What lived in the old process is gone: the variables and functions your programs "
             "defined, the rules you set, and the units that still ran{units}. Set up again what you still need.")


# What the model is told when its turn comes back while its program still runs: the fact.
# What a running program asks of the model is told with every call while one runs
# (WHILE_RUNNING), whatever the call is for.
RUNNING = "Program {number} is still running, as unit {unit}."
# Told with how things stand, at every call while a program of the model runs: when it has
# just been started, when a wait ended, when another program ended, when an event came. One
# text for all of them: they are the same moment, the model looking in on work that runs.
WHILE_RUNNING = ("A program of yours runs ({units}). Write the program for what comes after it now, while "
                 "it runs, and send it: it begins with after(\"{unit}\"), which returns when that one has "
                 "ended, then checks with expect what it relies on, then acts. So the agent goes on at once "
                 "when this one ends, and nothing waits for your next reply. Work it out from what you know "
                 "now; what this one's end decides goes into the next program's expect and its branches. "
                 "Prepare with what needs no acting on the environment: read the pages it needs, write and "
                 "keep the code, set the nodes for where the agent goes next. When the next one is sent, look "
                 "in on this one well before it is due to end (a wait much shorter than what it has left), "
                 "with a report that shows how far it is (until(report=)): change or end it when it is "
                 "behind.")


# Added to the feedback of a program that ended, when no other program of the model runs.
# Told with how things stand at every call: the two figures the model sets its pace by
# (prompts/core: the agent acting and the model thinking at the same pace).
REPLY_PACE = "Your last reply took {took} s to write; for {still} s of them no program of yours ran."
REPLY_WAITED = " Since your last program you waited {times} times, {seconds} s in all, for programs of yours to end."


def reply_pace(pace, state, waited=(0, 0.0)) -> str | None:
    """The line on the pace of the last reply (`pace`: the seconds it took to write, and
    those of them in which no program of the model ran), and of the model's waits while a
    program of its own ran since its last program (`waited`: how many, their seconds in
    all), where it waited. None before the first reply, and while the environment says
    the agent cannot act (its state has can_act false): then nothing stands waiting for
    the model, and there is no pace to keep."""
    if pace is None or (state or {}).get("can_act") is False:
        return None
    took, still = pace
    times, seconds = waited
    return (REPLY_PACE.format(took=round(took), still=round(min(still, took)))
            + (REPLY_WAITED.format(times=times, seconds=round(seconds)) if times else ""))


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


# Why the model is called (a model_request's reason): a message or an event it was told and
# has not answered ("user", "escalation") comes before what happened last.
REASONS = ("user", "escalation", "start", "program_end", "program_running", "unit_end", "wait_end", "error",
           "rejected", "finish_refused", "verify", "empty", "format")


# The trigger of a role's request: explicit requests share the transport of decisions.
REQUESTS = {"verifier": "request", "observer": "request", "vlm": "request", "pointer": "request",
            "reflection": "reflect", "compaction": "compact", "search": "request"}


# Compaction (runtime/task/run.py _compact_if_due). When the context a call read reaches
# runtime.compact_at_tokens (runtime.compact_at_share of the tokens the model can read, where
# it says), the model is asked for a summary of the conversation (COMPACT,
# after its last message), and the summary (COMPACTED) stands in the first message in
# place of every message before the recent ones, which stay as they are: from the end
# back until they hold KEEP_MIN_TOKENS and KEEP_MIN_MESSAGES, or KEEP_MAX_TOKENS
# (messages.recent_start).
KEEP_MIN_TOKENS, KEEP_MIN_MESSAGES, KEEP_MAX_TOKENS = 10_000, 5, 40_000
# The summary is asked for ahead, in the background, at this share of the limit
# (runtime.compact_arm_tokens, when set, instead), and put in at the limit.
COMPACT_ARM_SHARE = 0.7
# Old results. A call made after the provider's cache of the conversation has gone cold
# (runtime.clear_results_after_minutes since the model's last reply) reads everything
# anew: before it, the results of all programs but the last KEPT_RESULTS are replaced
# by CLEARED (messages.clear_results).
KEPT_RESULTS = 5
CLEARED = "[Old tool result content cleared]"
COMPACT = (
    "You have written a partial transcript for the initial task above. Please write a summary of the transcript. "
    "The purpose of this summary is to provide continuity so you can continue to make progress towards solving "
    "the task in a future context, where the raw history above may not be accessible and will be replaced with "
    "this summary. Write down anything that would be helpful, including the state, next steps, learnings etc. "
    "Before the summary, go through the conversation in order in an <analysis></analysis> block, so that "
    "nothing is missed. Give the summary these sections:\n"
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
    "This session is being continued from a previous conversation that ran out of context. The summary below "
    "covers the earlier portion of the conversation. Recent messages are preserved verbatim. The kernel with "
    "what your programs defined, the library, the tree of reflexes and the units that run are as they were."
    "\n\nSummary:\n{summary}"
    "\n\nIf you need specific details from before this summary (what you were told, what a program printed, "
    "what you replied), read the full record at: {record}\nIt has one JSON line for each message, in order: "
    "time, role, text.")


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
          "vlm": "vision_calls", "pointer": "vision_calls", "compaction": "compaction_calls",
          "search": "search_calls"}
