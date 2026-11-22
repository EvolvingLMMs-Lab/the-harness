"""The high-level reply format: a short thought and exactly one action block."""

from dataclasses import dataclass
import json
import re


# <wait> (optionally with a number of seconds, and with the <check> it runs when it ends):
# the model waits by choice until something reaches it (runtime/task/run.py). <answer>: the
# model's answer to the question a program of its own asked with decide().
KINDS = ("python", "verify", "finish", "wait", "answer")
DIRECT_KINDS = ("action", "finish", "wait")
_SECONDS = re.compile(r"\d+(?:\.\d+)?")


_CHECK = re.compile(r"<check>(.*?)</check>", re.DOTALL)


def wait_check(body: str) -> str | None:
    """The program in a <wait> block's <check> (what the model looks at when the wait ends),
    None when it has none."""
    found = _CHECK.search(body or "")
    if not found:
        return None
    program = found.group(1).strip("\n")
    fenced = _FENCE.match(program)
    return (fenced.group(1) if fenced else program) if program.strip() else None


def wait_seconds(body: str) -> float | None:
    """The seconds a <wait> block asks for at most (its first number outside its <check>),
    None when it names none."""
    found = _SECONDS.search(_CHECK.sub("", body or ""))
    return float(found.group(0)) if found else None
_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n(.*?)\n\s*```\s*$", re.DOTALL)
# DeepSeek models sometimes end a block with their own tool-call markup instead of its
# closing tag ("</\uff5cDSML\uff5c parameter>", "</\uff5cDSML\uff5c invoke>", ...): 50 of
# agent 1.4.0's 677 development replies, each a call that ran nothing. Lines of it are
# dropped, and a block it left open is closed at the end of the reply.
_MARK = r"\uff5c{1,2}DSML\uff5c{1,2}"
_LEAKED = re.compile(rf"^\s*</?\s*{_MARK}[^>\n]*>\s*$", re.MULTILINE)
# Or the whole block is their tool call: <\uff5cDSML\uff5c invoke name="python"> with the
# program as its one parameter (an app conversation on DeepSeek V4.1 Flash wrote every
# program so). It is read as the block it names.
_INVOKE = re.compile(rf"<\s*{_MARK}\s*invoke\s+name=\"(\w+)\"\s*>(.*?)(?:<\s*/\s*{_MARK}\s*invoke\s*>|$)",
                     re.DOTALL)
_PARAMETER = re.compile(rf"<\s*{_MARK}\s*parameter\b[^>]*>(.*?)(?:<\s*/\s*{_MARK}\s*parameter\s*>|$)",
                        re.DOTALL)
_CALLS = re.compile(rf"<\s*/?\s*{_MARK}\s*(?:function_)?calls\s*>")
_TOOL_MARKUP = re.compile(r"<\s*/?\s*(?:python|verify|finish|action|wait|plan|step_done|search_web|navigate|read_page|tools)\b",
                          re.IGNORECASE)


def looks_like_action(text: str) -> bool:
    """Action-shaped replies must be corrected, not treated as ordinary chat."""
    return bool(_TOOL_MARKUP.search(text or "") or re.search(_MARK, text or ""))


class ProtocolError(ValueError):
    pass


@dataclass
class Reply:
    thought: str
    kind: str
    body: str


def _invoked(text: str, kinds) -> str | None:
    """A reply whose block is a DeepSeek tool call (one invoke of a kind, one parameter)
    as that block, the text before it as the thought; else None."""
    if any(f"<{kind}>" in text for kind in kinds):
        return None
    invokes = list(_INVOKE.finditer(text))
    # Count *all* invokes, including unknown tools. Never silently execute a subset.
    openings = re.findall(rf"<\s*{_MARK}\s*invoke\b", text)
    if len(invokes) != 1 or len(openings) != 1 or invokes[0].group(1) not in kinds:
        raise ProtocolError("Expected one supported DSML invoke; use a single <python> or <verify> block")
    invoke = invokes[0]
    kind, inner = invoke.group(1), invoke.group(2)
    parameters = _PARAMETER.findall(inner)
    if len(parameters) == 1:
        body = parameters[0]
        remaining = _PARAMETER.sub("", inner)
    elif not parameters and not re.search(rf"<\s*{_MARK}\s*parameter\b", inner):
        # Observed Flash variant: a named invoke contains the program directly,
        # sometimes followed by a stray closing parameter tag. Require the invoke's
        # closing tag before accepting this form.
        if not re.search(rf"</\s*{_MARK}\s*invoke\s*>$", invoke.group(0)):
            raise ProtocolError("Unclosed DSML invoke; resend the complete <python> block")
        body = re.sub(rf"</\s*{_MARK}\s*parameter\s*>\s*$", "", inner)
        remaining = ""
    else:
        raise ProtocolError("A DSML invoke needs exactly one program, not multiple parameters")
    tail = _CALLS.sub("", text[invoke.end():]).strip()
    thought = _CALLS.sub("", text[:invoke.start()]).strip()
    if remaining.strip() or tail or re.search(_MARK, body + thought):
        raise ProtocolError("Ambiguous DSML content; resend one complete action block")
    return f"{thought}\n<{kind}>\n{body.strip(chr(10))}\n</{kind}>"


def _without_leaked_markup(text: str, kinds) -> str:
    if not re.search(_MARK, text):
        return text
    if re.search(rf"<\s*{_MARK}\s*invoke\b", text):
        if any(f"<{kind}>" in text for kind in kinds):
            raise ProtocolError("Mixed action blocks and DSML invokes; resend just one block")
        return _invoked(text, kinds)
    text = _LEAKED.sub("", text).rstrip()
    for kind in kinds:
        if text.count(f"<{kind}>") == 1 and f"</{kind}>" not in text:
            return text + f"\n</{kind}>"
    return text


def parse_reply(text: str, kinds=KINDS) -> Reply:
    text = _without_leaked_markup(text or "", kinds)
    pattern = re.compile(r"<(%s)>(.*?)</\1>" % "|".join(kinds), re.DOTALL)
    blocks = pattern.findall(text)
    if len(blocks) > 1 and all(kind == "python" for kind, _ in blocks):
        # Several <python> blocks and nothing else (plan() in one, the program in the
        # next: A6's demo runs showed it as a format error) are one program, in order.
        bodies = []
        for _, body in blocks:
            body = body.strip("\n")
            fenced = _FENCE.match(body)
            bodies.append(fenced.group(1) if fenced else body)
        blocks = [("python", "\n".join(body for body in bodies if body.strip()))]
    if len(blocks) != 1:
        names = ", ".join(f"<{kind}>" for kind in kinds)
        raise ProtocolError(f"Reply must contain exactly one of {names}; found {len(blocks)}")
    kind, body = blocks[0]
    thought = text[:text.index(f"<{kind}>")].strip()
    # Stray plan/tool tags before a valid block are not user-facing prose or extra
    # actions. The caller retains the original reply verbatim in the trace.
    if looks_like_action(thought):
        thought = ""
    body = body.strip("\n")
    if kind in ("python", "action"):
        fenced = _FENCE.match(body)
        if fenced:
            body = fenced.group(1)
        if not body.strip():
            raise ProtocolError(f"<{kind}> block is empty")
    return Reply(thought=thought, kind=kind, body=body if kind == "python" else body.strip())


def json_list(text) -> list:
    """The JSON list in a model's reply (the first "[" to the last "]"), or [] when there is
    none or it does not parse."""
    match = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not match:
        return []
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []
