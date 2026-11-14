"""Reflection: turn a development episode into one candidate library entry.

The model reads a compact trajectory (programs, events, outcome on the dev
seed) and the current library, and may propose one entry:

    <note name="...">one or two sentences</note>             -> notes/<name>.md
    <memory name="...">situation and what worked</memory>   -> memory/<name>.md
    <skill name="...">def f(...): ...</skill>                -> skills/<name>.py
    <none/>

(The nodes of a tree of reflexes are not proposed here: they are kept from the tree the
agent set, library.propose "reactive".)

The reply gives its kind, name and text; the learner checks them as every candidate
(runtime/learning/learner.py candidate()). A candidate only enters the library after it improves
the score on held-out development seeds (harness self-improve).
"""

import ast
import json
from pathlib import Path
import re

from harness.core.episodes import new_name, read_records
from harness.paths import ROOT
from harness.runtime.learning.learner import KINDS, MEMORY_MAX_CHARS, NOTE_MAX_CHARS
from harness.runtime.learning.library import Library, eligible, executable


# The request: the same whatever the agent acts in (the pack's markers name the run's skills).
PACK = ROOT / "prompts" / "reflect"


def system_prompt(names=()) -> str:
    """The reflection request for a run whose embodiment kind, bench and enabled skills
    are `names` (prompts/reflect): a note, a memory entry or a skill."""
    from harness.runtime.decision.prompts import assemble_prompt

    text = assemble_prompt(PACK, list(names), features=())
    request = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return request.replace("{note_max_chars}", str(NOTE_MAX_CHARS)).replace(
        "{memory_max_chars}", str(MEMORY_MAX_CHARS))


_ENTRY = re.compile(rf'<({"|".join(KINDS)})\s+name="([^"]*)">(.*?)</\1>', re.DOTALL)
# An outcome's keys every worker reports; the rest is what an evaluator measured besides.
OUTCOME_KEYS = {"success", "reward", "process_score", "terminated", "truncated", "steps", "unscorable"}


def summarize_episode(run: Path, max_chars: int = 12000, *, since=0) -> str:
    lines = []
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8")) if (run / "summary.json").exists() else {}
    # A trace cut off mid-line (a crash) is read up to its last whole record.
    program = 0
    for event in read_records(run):
        kind = event["event"]
        if kind == "reset":
            lines.append(f"Instruction: {event['observation']['instruction']}")
        elif kind == "model_reply" and program >= since and event.get("ahead", "used") == "used":
            lines.append(f"[turn {event['call']}] {event['text'].strip()[:1500]}")
        elif kind == "cell":
            program += 1
            if program <= since:
                continue
            result = event["result"]
            text = f"  -> {result['status']}"
            if result.get("escalation"):
                ev = result["escalation"]["event"]
                text += f" {ev['kind']} from {ev['source']}: {json.dumps(ev['detail'])[:300]}"
            if result.get("error"):
                text += " " + result["error"].strip().splitlines()[-1][:300]
            if result.get("stdout"):
                text += " | out: " + result["stdout"].strip().replace("\n", " / ")[:300]
            lines.append(text)
        elif kind == "skill_step" and program >= since and event.get("library_revision"):
            lines.append(f"Used {event.get('library_key')} at {event['library_revision']}: "
                         f"{event.get('what')}, ok={event.get('ok')}")
        elif kind == "verify" and program >= since:
            lines.append(f"  verify {event['claim'][:200]!r}: {event['answer'][:200]}")
        elif kind == "outcome" and set(event.get("outcome") or {}) - OUTCOME_KEYS:
            # What the evaluator measured besides the score (a practice segment's time, deaths).
            extra = {key: value for key, value in event["outcome"].items() if key not in OUTCOME_KEYS}
            lines.append(f"Measured: {json.dumps(extra, default=str)[:600]}")
    if summary:
        lines.append(f"Outcome: success={summary.get('success')} "
                     f"score={summary.get('reward')} status={summary.get('status')}"
                     + (f" guards fired={summary['guard_triggers']}" if summary.get("guard_triggers") else ""))
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars // 2] + "\n...\n" + text[-max_chars // 2:]
    return text


def library_text(library, holdings=None):
    if isinstance(library, (str, Path)):
        library = Library(library)
    captured = library.capture()
    index = captured.index
    entries = {item.key: item for item in captured.entries
               if not executable(item.key) or holdings is None and eligible(
                   item, index.get(item.key) or {}, captured.layers, captured.load)}
    if holdings is not None:
        entries.update({key: item for key, (item, _) in holdings.items()})
    lines = []
    for key, item in entries.items():
        row = index.get(key) or {}
        uses = (row.get("uses_by_revision") or {}).get(item.revision) or {}
        lines.append(f"--- {key} ({item.revision}, {uses.get('ok', 0)} successes, "
                     f"{uses.get('failed', 0)} failures)\n{item.source.decode('utf-8').strip()[:1200]}")
    return "\n".join(lines)[:8000] or "(empty)"


def propose(chat, run: Path, library, embodiment=(), *, since=0, holdings=None):
    """Use the same reflection request for online and offline learning."""
    names = [embodiment] if isinstance(embodiment, str) else list(embodiment)
    prompt = (f"Current library:\n{library_text(library, holdings)}\n\n"
              f"Episode:\n{summarize_episode(run, since=since)}\n\nPropose at most one addition.")
    from harness.core.trace import Trace
    from harness.runtime.decision.thoughts import think
    from harness.runtime.events import EVENTS

    trace = None if getattr(chat, "thinks", False) else Trace(run / "reflection" / new_name(), EVENTS)
    reply = think(chat, system_prompt(names), [{"role": "user", "content": prompt}], trace=trace)
    return parse_candidate(reply.text), reply.text


def parse_candidate(text: str, *, require_test=True):
    """The entry a reply proposes, (kind, name, text), or None: none, empty, or code that
    is not the one public function with a docstring the request asks for."""
    match = _ENTRY.search(text or "")
    if not match:
        return None
    kind, name, body = match.group(1), match.group(2), match.group(3).strip()
    test = None
    if kind in ("skill", "reactive"):  # code; a note and a memory entry are text
        check = re.search(r"<test>(.*?)</test>", text[match.end():], re.DOTALL)
        if check:
            test = re.sub(r"^```[a-z]*\n|\n```$", "", check.group(1).strip())
        if require_test and not test:
            return None
        body = re.sub(r"^```[a-z]*\n|\n```$", "", body).strip()
        try:
            tree = ast.parse(body)
        except SyntaxError:
            return None
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")]
        if len(functions) != 1 or not ast.get_docstring(functions[0]):
            return None
    if not body:
        return None
    entry = kind, name, body + "\n"
    return (*entry, test) if test else entry
