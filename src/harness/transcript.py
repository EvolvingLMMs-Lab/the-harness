"""A trace as people read it, for every frontend: items() gives a record's items {kind, role,
text, keys}, which the host sends as its `view`; presentation() is the only reading of a reply."""

from collections import defaultdict
import json
import os
import re

from .core import format as formats
from harness.runtime.safety.approval import WORDS, say
from .core.format import clip_lines
from .core.lanes import Lanes
from .runtime.status import ENDED
from harness.runtime.decision.protocol import DIRECT_KINDS, KINDS, ProtocolError, parse_reply

LOOK_TAGS = re.compile(r"</?(?:wait|assume|stop)>")  # what a look's reply marks its parts with
_ASSUME = re.compile(r"<assume>.*?</assume>", re.DOTALL)
_MARKUP = re.compile(r"<\s*/?\s*(python|verify|finish|action|plan|step_done|search_web|navigate|read_page|tools)\b"
                     r"|｜{1,2}DSML｜{1,2}", re.IGNORECASE)
# Records said in one item from their own fields: (kind, role, words[, only with `timeline`]).
SAID = {
    "program_stopped": ("program_stopped", "note", "program {program} stops at its next step: {why}"),
    "verify": ("verifier", "verifier", "{answer}"),
    "confirmation_request": ("approval_request", "note", "the program waits for your approval"),
    "stuck": ("stuck", "note", "the same {repeated} three times in a row"),
    "agent_sent": ("agent_sent", "note", "to sub-agent {agent}: {text}"),
    "agent_cancelled": ("agent_cancelled", "note", "stopped sub-agent {agent}"),
    "environment_released": ("environment", "note", "gave {label} back"),
    "error": ("error", "error", "{message}"), "kernel_died": ("error", "error", "{message}"),
    "model_request": ("call", "call", "model call {call}: {reason}", True),
    "finish": ("finished", "end", "finished ({source}): {text}", True),
    "interrupted": ("interrupted", "error", "interrupted", True),
    "resumed": ("resumed", "note", "continued in a new process: {messages} messages restored"),
    "cleanup_error": ("cleanup_error", "error", "cleanup error: {message}", True),
    "context_shortened": ("context_shortened", "call", "history shortened to {history_turns} turns", True),
    "malformed_dropped": ("malformed_dropped", "call", "{messages} malformed messages left the history", True),
}


# How a turn that ended without an answer is said (the reason of the IDLE state after it:
# runtime/decision/loop.py TURN_ENDS).
TURN_STOPPED = {"budget": "out of model calls for this turn (a message goes on)",
                "wall_time": "out of time for this turn (a message goes on)",
                "cost": "the conversation's cost limit is reached", "error": "it ended in an error",
                "interrupted": "interrupted", "episode_ended": "the environment's episode ended"}


def presentation(record: dict) -> dict:
    """A model_reply as {kind, thought, body}; one without `presentation` (older) read from its text."""
    shown = record.get("presentation")
    if not isinstance(shown, dict):
        text = str(record.get("text") or "")
        try:
            reply = parse_reply(text, tuple(dict.fromkeys(KINDS + DIRECT_KINDS)))
        except ProtocolError:
            return {"kind": "invalid", "body": ""} if _MARKUP.search(text) else {"kind": "message", "body": text.strip()}
        shown = {"kind": reply.kind, "thought": reply.thought, "body": reply.body}
    return {**shown, "thought": _ASSUME.sub("", shown.get("thought") or "").strip()}  # <assume> before 1.47.6


def answer_of(record: dict) -> str | None:
    """The agent's answer when `record` is the reply that ends its turn (harness run -p), else None."""
    if record.get("event") in ("finish", "agent_message") and record.get("text"):
        return str(record["text"])
    reply = presentation(record) if record.get("event") == "model_reply" and record.get("ahead", "used") == "used" else {}
    return str(reply.get("body") or "") if reply.get("kind") == "finish" else None


def physical(request: dict) -> tuple[str, str]:
    """A physical-input request's doing.* key and app: its window title's end, else its process."""
    actions = request.get("actions") or ["pointer"]
    doing = "doing." + ("clipboard" if "clipboard" in actions else actions[0])
    parts = [part.strip() for part in re.split(r" [-–—] ", str(request.get("window") or "")) if part.strip()]
    app = (parts[-1] if len(parts) > 1 else request["app"][:1].upper() + request["app"][1:] if request.get("app")
           else request.get("window") or say("label.this_window"))
    return (doing if doing in WORDS else "doing.other"), app


def _item(kind: str, role: str, text="", **keys) -> dict:
    return {"kind": kind, "role": role, "text": "" if text is None else str(text), "keys": keys}


def items(record: dict, names: dict, timeline: bool = False) -> list[dict]:
    """A record's items; `names` (filled in here) names the spans and entries started so far,
    `timeline` adds the model calls and how the episode ended."""
    kind, get = record.get("event") or "", record.get
    said = SAID.get(kind)
    if said and (timeline or len(said) == 3) and get("reason") != "think":
        fields = defaultdict(str, {"source": "model", **{key: value for key, value in record.items() if value is not None}})
        return [_item(said[0], said[1], said[2].format_map(fields))]
    took, reason = formats.duration(get("seconds") or 0), f": {get('reason')}" if get("reason") else ""
    if kind == "reset":
        return [_item("task", "task", get("instruction") or (get("observation") or {}).get("instruction", ""))]
    if kind == "user_message":
        files, text = get("files") or [], get("text") or ""
        named = [f"@{path}" for path in files if os.path.basename(path) not in text]  # not named in its text
        return [_item("from_parent" if get("sender") == "parent" else "user", "you", " ".join([text] + named).strip(),
                      files=files)]
    if kind == "agent_message":
        # A plain reply's notification refers to the model_reply that owns its display.
        # Independent messages (including replies during a program) still own theirs.
        if get("reply_call") is not None:
            return []
        return [_item("message", "agent", get("text"))]
    if kind == "terminal_output":
        # Exclude control bytes from transcript consumers, including the local terminal.
        text = "".join(char for char in str(get("text") or "") if char in "\t\n" or char.isprintable())
        return [_item("terminal_output", "output", text)]
    if kind == "external_artifacts":
        links = [str(row.get("url") or "") for row in get("artifacts") or []]
        return [_item("external_artifacts", "note", "\n".join(url for url in links if url.startswith("https://")))]
    if kind == "external_question":
        return [_item("external_question", "note", get("text"), schema=get("schema"))]
    if kind == "agent_delegated":
        shared = ", its windows handed over" if get("windows") else ""
        return [_item("agent_started", "note", f"started sub-agent {get('agent')} ({get('kind')}{shared}): {get('task')}")]
    if kind == "agent_waited":
        states = ", ".join(f"{agent} {status}" for agent, status in (get("states") or {}).items())
        return [_item(kind, "note", f"waited {took} for sub-agents: {states}")]
    if kind == "agent_report":
        report = str(get("result") or get("error") or "")
        return [_item(kind, "error" if get("status") == "error" else "outcome", f"sub-agent {get('agent')} {get('status')} ("
                      f"{get('model_calls')} calls, {took})"
                      + (f": {report}" if report.strip() else ""))]
    if kind == "model_request" and get("reason") == "think":  # a look again while a program runs, and why
        why = "news" if get("why") == "news" else "a while without a call"
        return [_item("look", "call", f"model looks again while program {get('program')} runs ({why})", news=get("news") or [])]
    if kind == "model_reply" and get("ahead", "used") != "used":  # written while a program ran: set aside
        return ([_item("while_acting", "agent", LOOK_TAGS.sub("", get("text") or "").strip())] if get("think") else []) + (
            [_item("call_set_aside", "call", f"model call {get('call')}: made while a program ran, {get('ahead')}")]
            if timeline else [])
    if kind == "model_reply":
        reply = presentation(record)
        shown, body, thought = reply.get("kind"), reply.get("body") or "", reply.get("thought") or ""
        out = [_item("reasoning", "thinking", get("reasoning"))] if timeline and get("reasoning") else []
        if shown in ("invalid", "message"):
            out.append(_item(shown, "agent", (get("text") or "") if shown == "invalid" else body))
        else:
            out += [_item("thought", "agent", thought)] if thought else []
            out.append(_item("program", "code", body, reply=shown, thought=thought) if shown in ("python", "action")
                       else _item("verify_ask" if shown == "verify" else "finish", "agent", body))
        usage = get("usage") or {}
        # Tokens, no dollars: only OpenRouter reports a cost (the record keeps it).
        return out + ([_item("usage", "call", f"{took}, {usage.get('input_tokens')} in / {usage.get('output_tokens')} "
                                              f"out tokens")] if timeline else [])
    if kind == "skill_step":
        number, after = f"{get('step')}" + (f"/{get('of')}" if get("of") else ""), f" after {took}" if get("seconds") is not None else ""
        return [_item(kind, "skill" if get("ok") else "error",
                      f"{get('skill')} step {number}, {get('what')}: {'done' if get('ok') else 'failed'}{after}{reason}")]
    if kind == "span_start" and get("lane") in ("skill", "service"):
        names[get("id")] = get("name")
        parameters = ", ".join(f"{key}={value if isinstance(value, str) else json.dumps(value)}"
                               for key, value in (get("parameters") or {}).items())
        return [_item("skill", "skill", f"{get('name')}({parameters})")] if get("lane") == "skill" else []
    names.update({get("id"): get("name") or get("id")} if kind == "entry_start" else {})
    name, claims = names.get(get("id"), get("id")), ", ".join(map(str, get("claims") or []))
    if kind == "entry_start":
        return [_item(kind, "entry", f"{name} ({get('kind', 'program')}" + (f", claims {claims})" if get("claims") else ")"))]
    if kind == "entry_claims":
        return [_item(kind, "entry", f"{name} claims {claims or 'nothing'}")]
    if kind == "entry_end":
        why = get("error") or get("event_kind")
        return [_item(kind, "error" if get("status") == "failed" else "entry", f"{name}: {get('status')}" + (f" ({why})" if why else ""))]
    if kind == "span_end" and get("id") in names and get("event_kind") not in (None, "", "COMPLETED", "PREDICATE_SATISFIED"):
        return [_item("skill_failed", "error", f"{name}: {get('event_kind')}")]
    if kind == "cell":
        result = get("result") or {}
        escalation = result.get("escalation") or {}
        return [_item("result", "result", f"{result.get('status')} after {formats.duration(result.get('seconds') or 0)}"),
                *([_item("output", "output", result["stdout"])] if result.get("stdout") else []),
                *([_item("cell_error", "error", result["error"])] if result.get("error") else []),
                *([_item("unhandled", "error", f"unhandled {(escalation.get('event') or {}).get('kind')} in "
                                               f"{escalation.get('skill')}")] if escalation else [])]
    if kind == "protocol_error":
        return [_item("announced", "note", "it said what it would do, without a program; asked to do it now") if get("announced")
                else _item("format_error", "note", f"format error, nothing ran: {get('message')}")]
    if kind == "confirmation":
        return [_item("approved", "note", "approved") if get("accepted") else _item("rejected", "note", f"rejected{reason}")]
    if kind == "environment_attached":
        how = "you allowed it" if get("asked") else ("confirmations are skipped" if get("skipped_confirmation")
                                                     else "your settings allow it")
        where = f" in {get('folder')}" if get("folder") else ""
        return [_item("environment", "note", f"took {get('label') or get('kind')}{where} into this conversation "
                                             f"({how}): {get('why')}", environment=get("kind"), why=get("why"))]
    if kind == "environment_refused":
        return [_item("environment", "note", f"did not take {get('kind')}: {get('reason')}", environment=get("kind"))]
    if kind == "agents_enabled":
        return [_item("environment", "note", "sub-agents are on for this conversation" if get("enabled")
                      else "sub-agents stay off")]
    if kind == "physical_request" and get("sensitive"):
        names.update({f"physical:{get('id')}": say("label.that_app")} if get("id") else {})
        return [_item(kind, "note", say("sensitive", kind=say(f"sensitive.{get('sensitive')}"), target=get("target")),
                      sensitive=get("sensitive"), why=get("why"))]
    if kind == "physical_request":
        doing, app = physical(record)
        names.update({f"physical:{get('id')}": app} if get("id") else {})
        window = f" ({get('window')})" if get("window") and get("window") != app else ""
        return [_item(kind, "note", say("request", doing=say(doing), app=app, window=window), app=app, doing=doing, why=get("why"))]
    if kind == "worker_approval_result" and get("outcome") == "unknown":
        return [_item("delivery_unknown", "note", "Action outcome unknown. It was not resent.")]
    if kind == "physical_answer":
        remember = get("remember") if f"allowed.{get('remember')}" in WORDS else "once"
        app = names.get(f"physical:{get('id')}") or say("label.that_app")
        return [_item("allowed", "note", say(f"allowed.{remember}", app=app), remember=remember, app=app) if get("accepted")
                else _item("refused", "note", say("refused", reason=reason))]
    if kind == "state":
        if get("status") == "IDLE" and get("reason") in TURN_STOPPED:
            # The turn ended without an answer: why, before the user's turn.
            return [_item("state", "turn", f"turn over: {TURN_STOPPED[get('reason')]}"), _item("state", "turn", "your turn")]
        words = {"IDLE": "your turn", "PAUSED": "paused"}.get(get("status")) or get("status") in ENDED and f"conversation over: {get('reason')}"
        return [_item("state", "turn", words)] if words else []
    if kind == "outcome":
        outcome = get("outcome") or {}
        return [_item("outcome", "outcome", f"evaluator: success {outcome.get('success')}, reward {outcome.get('reward')}, "
                                            f"process score {outcome.get('process_score')}, steps {outcome.get('steps')}")]
    if timeline and kind in ("policy_to_end", "wrap_up"):
        return [_item(kind, "end", f"{kind.replace('_', ' ')}: {get('status')}" + (f": {get('error')}" if get("error") else ""))]
    if kind == "library" and get("action") in ("admitted", "rejected", "promoted"):
        # What the agent learned (runtime/learning/learner.py): an entry kept, waiting for its test, refused, or re-graded.
        if get("action") == "admitted":
            text = (f"learned {get('section')}/{get('name')} ({get('evidence')}, {get('origin')})" if get("admitted")
                    else f"proposed {get('section')}/{get('name')}: waits for its test ({get('origin')})")
        elif get("action") == "rejected":
            text = f"not learned {get('kind')} {get('name')}: {str(get('reason'))[:200]}"
        else:
            text = f"{get('key')}: {get('evidence')}"
        return [_item("learned", "note", text)]
    if timeline and kind in ("library", "library_loaded") and (get("action") or "loaded") == "loaded":
        return [_item("library_loaded", "end", f"library {str(get('version'))[:12]} loaded: {get('status')}")]
    return []


# A transcript item's line around its text, by kind; with a number, its lines one by one,
# at most that many (with True, the blank ones left out). Other kinds: the text as it is.
FORMS = {
    "task": ("task: {}",), "user": ("you: {}",), "from_parent": ("from the agent that started it: {}",),
    "while_acting": ("agent, while it acts: {}", 6, True), "reasoning": ("thinking: {}", 12, True),
    "thought": ("agent: {}", 40), "message": ("agent: {}", 40), "invalid": ("agent: {}", 40),
    "program": ("  | {}", 60), "verify_ask": ("agent asks the verifier: {}",),
    "finish": ("agent finished: {}",), "usage": ("  ({})",), "skill_step": ("    · {}",),
    "program_stopped": ("({})",), "skill": ("  > {}",), "entry_start": ("+ {}",), "entry_claims": ("~ {}",),
    "entry_end": ("- {}",), "skill_failed": ("  ! {}",), "result": ("  = {}",), "output": ("    {}", 20),
    "cell_error": ("    {}", 8), "unhandled": ("    {}",), "verifier": ("verifier: {}",), "announced": ("({})",),
    "format_error": ("({})",), "approval_request": ("the program waits for you: /approve, or /reject [why]",),
    "approved": ("({})",), "rejected": ("({})",), "allowed": ("({})",), "refused": ("({})",), "stuck": ("({})",),
    "state": ("-- {} --",), "error": ("error: {}",), "learned": ("  * {}",), "environment": ("({})",),
}


def approval_options(item: dict) -> list[tuple[str | None, str]]:
    """The approval scopes and labels offered for a transcript request."""
    from harness.runtime.safety.input import REMEMBER

    keys = item.get("keys") or {}
    scopes = REMEMBER if item["kind"] == "physical_request" and not keys.get("sensitive") else ("once",)
    return [(scope, say(f"answer.{scope}", app=keys.get("app"))) for scope in scopes] + [
        (None, say("answer.no"))]


def item_lines(item: dict) -> list[tuple[str, str]]:
    """The plain-text lines of one transcript item, each with its role."""
    kind, role, text, keys = item["kind"], item["role"], item["text"], item.get("keys") or {}
    if kind == "look":
        news = keys.get("news") or []
        return ([(role, text)] + [(role, f"  - {line}") for line in news[:6]]
                + ([(role, f"  - and {len(news) - 6} more")] if len(news) > 6 else []))
    if kind == "agent_report":
        cut = text.find("): ") + 1 or len(text)
        rows = clip_lines(text[cut + 2:], 12)
        return [(role, text[:cut] + (": " + rows[0] if rows else ""))] + [("output", "    " + row) for row in rows[1:]]
    if kind == "physical_request":
        why = f"\n    why: {keys['why']}" if keys.get("why") else ""
        answers = [(("/reject [why]" if scope is None else "/approve" if scope == "once" else f"/approve {scope}"),
                    words) for scope, words in approval_options(item)]
        return [(role, text + why + "".join(f"\n    {command:<20}{words}" for command, words in answers))]
    if kind == "state" and text == "paused":
        return [(role, "-- paused: /continue, or send a message --")]
    form = FORMS.get(kind, ("{}",))
    if len(form) == 1:
        return [(role, form[0].format(text))]
    return [(role, form[0].format(line)) for line in clip_lines(text, form[1])
            if not (len(form) > 2 and form[2]) or line.strip()]


def record_lines(record, names, timeline=False) -> list[tuple[str, str]]:
    """The lines of one record, each with its role. Names and timeline are passed to items()."""
    return [line for found in items(record, names, timeline) for line in item_lines(found)]


class TextTranscript:
    """Lines for the records of one conversation, in order, each after the path of its
    lane (blank for the conversation's own: the user's messages, its status); with
    `timeline`, the lines a finished episode's record shows too (record_lines)."""

    def __init__(self, timeline=False):
        self.names = {}
        self.lanes = Lanes()
        self.timeline = timeline
        self.width = len("model")

    def parts(self, record) -> list[tuple[str, str, str]]:
        """The lines of `record` as (kind, lane path, text)."""
        lines = record_lines(record, self.names, timeline=self.timeline)
        path = self.lanes.add(record) or ""
        self.width = max(self.width, len(path))
        return [(kind, path, text) for kind, text in lines]

    def lines(self, record) -> list[str]:
        return [f"{path:<{self.width}}  {text}" for _, path, text in self.parts(record)]
