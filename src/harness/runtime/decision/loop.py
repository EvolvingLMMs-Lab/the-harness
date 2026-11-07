"""Decision protocol, dispatch tables and speculative-reply rules.

TaskRun coordinates these decisions with task lifecycle and program execution.
"""
import ast
import re
from harness.runtime.decision.protocol import AHEAD_KINDS, ProtocolError, looks_like_action, parse_reply


# Seconds between two model_text records of a streamed reply.
STREAMED_SECONDS = 0.3


# Added to the system prompt of an interactive conversation.
INTERACTIVE_PROMPT = (
    "\n\nA user is with you in this episode. Their messages reach you as \"Message from the user: ...\". "
    "To ask for information needed by this task, reply in plain text without a block; the task waits "
    "for the answer. Use <finish> for the completed task and your final answer. That ends this run; "
    "it does not open a new conversation turn."
)


# Added to an interactive conversation's prompt (a sub-agent's too): a message while a program runs.
MESSAGE_PROMPT = (
    " A message that comes while a program runs reaches you at once: reply <wait> to let the program go on "
    "(you are asked again with its result), a block that moves nothing to run it beside the program, or what "
    "should run instead, which stops the program at its next step."
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


# Old profiles can still disable speculation; the other values share one policy.
THINK_WHILE_ACTING = ("off", "on", "on_events", "periodic")


AHEAD_SECONDS = 3.0


_ASSUME = re.compile(r"<assume>(.*?)</assume>", re.DOTALL)


_ASSUME_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is,
    ast.IsNot, ast.In, ast.NotIn, ast.Name, ast.Load, ast.Constant, ast.Subscript,
    ast.Slice, ast.Tuple, ast.List,
)


AHEAD_RUNNING = (
    "Program {number} is running now. Prepare what comes after it. State a check on its result in "
    "<assume>...</assume> before the next block. The check can read result (the final "
    "execution receipt), output (stdout) and state (the latest observation). "
    "Reply <wait> if you need to see the result first."
)


LOOK_RUNNING = (
    "Program {number} is still running. Reply <wait> to let it continue, a Python block that "
    "can run alongside it, or <stop>reason</stop> and the replacement block."
)


_STOP = re.compile(r"<stop>(.*?)</stop>", re.DOTALL)


# The end of the message of a call made when a message for the model comes while program
# N runs (A6's demo 3: a budget typed during a 17 s page load sat unread until it ended).
MESSAGE_RUNNING = ("Program {number} is still running. Reply <wait> to let it finish: you are asked again with its "
                   "result. Or reply with what should run instead: the program stops at its next step, and your "
                   "block runs then.")


# What a reply may do beside the running program at once, instead of stopping it: tell or
# start agents and entries, update the plan, note places, plain Python.
_BESIDE_CALLS = {"send_agent", "cancel_agent", "delegate", "spawn", "plan", "step_done", "recall", "read_skill",
                 "remember", "forget", "things", "thing", "forget_thing",
                 "print", "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple", "range",
                 "enumerate", "zip", "sorted", "min", "max", "sum", "any", "all", "isinstance", "round", "abs",
                 "repr", "format"}


_BESIDE_METHODS = {"append", "extend", "get", "items", "keys", "values", "format", "join", "strip", "split",
                   "lower", "upper", "replace", "startswith", "endswith", "update", "pop", "copy", "count",
                   "index"}


def _beside(program: str) -> bool:
    """Whether `program` needs no body: it calls only _BESIDE_CALLS, _BESIDE_METHODS and
    functions it defines itself, so it may run beside a running program. What it hands to
    spawn() runs as an entry of its own, whose channels the tick keeps apart
    (CHANNEL_CONFLICT), so it may do anything."""
    try:
        tree = ast.parse(program)
    except SyntaxError:
        return False
    own = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    spawned = {id(inner) for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "spawn"
               for argument in [*node.args, *(keyword.value for keyword in node.keywords)]
               for inner in ast.walk(argument)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and id(node) not in spawned:
            func = node.func
            if not (isinstance(func, ast.Name) and (func.id in _BESIDE_CALLS or func.id in own)
                    or isinstance(func, ast.Attribute) and func.attr in _BESIDE_METHODS):
                return False
    return True


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


# Pending events take priority over the event that brought the loop to a decision.
# Explicit requests have a trigger per role and share the same transport as decisions.
TRIGGERS = {
    "running": {"message": "_pending_message", "escalation": "_pending_escalation",
                "ahead": "_pending_ahead"},
    "between": {"user": "_pending_message", "escalation": "_unresolved",
                "start": None, "program_end": None, "error": None, "rejected": None,
                "finish_refused": None, "verify": None, "empty": None, "format": None},
    "request": {"verifier": "request", "observer": "request", "vlm": "request",
                "pointer": "request", "reflection": "reflect"},
}


OUTPUTS = {
    "between": {"program": "_out_program", "verify": "_out_verify", "finish": "_out_finish",
                "message": "_out_message", "invalid": "_out_invalid", "empty": "_out_empty"},
    "running": {"wait": None, "message": "_say_beside", "parallel": "_run_beside",
                "replace": "_interrupt"},
    "request": {"verifier": "verifier_calls", "reflection": "reflection_calls",
                "observer": "vision_calls", "vlm": "vision_calls", "pointer": "vision_calls"},
}


def _running_reply(text, kinds):
    """Parse one running-program reply and distinguish ordinary prose from malformed blocks."""
    try:
        return parse_reply(text, (*kinds, *AHEAD_KINDS)), False
    except ProtocolError:
        return None, bool(text.strip()) and not looks_like_action(text)
