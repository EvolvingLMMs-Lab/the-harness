"""The active trigger of learning (runtime/learning/learner.py): a run whose goal is to get to know the
environment for a task, before the runs that do the task. It is an ordinary run of the
task's environment with `trigger = "active"`: its instruction says that it is practice and
what counts as learned (prompts/shared/learning-goal.md of the core; the task's own
instruction stays in it as what to learn for), not how to learn: that is the model's to
decide, by the principles of the core prompt. It is bounded by live time, not by the task's
budget. What it learns goes into the same library, through
the same learner, as what the task runs learn passively.

The schedule, [runtime.library]:

    active_before   false (default) | true    before a task's runs, one active run
    active_minutes  1 to 240 (default 30)     the active run's live time

`harness run` runs it once per task (the eval package's suite), in `<output>/<task>/active-<seed>`,
on the first seed's environment; the task's runs follow with `trigger = "passive"`.

The run asks its body's probe, never keys or pixels: the probe is the skill of the
embodiment's package with a [probe] table (runtime/execution/skills.py), which a learning run turns on
(config/agent.py). It exports

    probe(max_seconds=...) -> table   tries each of the body's controls and measures what it
                                      does; keeps the table in the library (keep())
    probe_summary(table) -> text      the table's lines

and its table's `try` text (what probe() measures) is the body's line of the learning goal.
A game probes its keys and mouse from its frames (the game package); a robot probes its
joints and grippers from its state and cameras (the robot package). A body without a probe
has no such line. A probe is bounded by its live time: Deadline(max_seconds).check()
raises OutOfTime once it is over, and the probe stops with what it measured.

Standard library only.
"""

from copy import copy
import time

from harness.paths import ROOT

PROMPT = ROOT / "prompts" / "shared" / "learning-goal.md"
DEFAULT_MINUTES = 30.0
# The task an active run plays where the environment has a practice sandbox: the task with
# this suffix (bench.py Bench.active_task). A worker allows its sandbox only in such an
# episode, never in a task run.
LEARN = "-learn"
# The lines of a body without a probe (a desktop, a browser): none.
GENERIC = {"try": ""}


class OutOfTime(Exception):
    """A probe's live time is over."""


class Deadline:
    """A probe's live time: `seconds` from now."""

    def __init__(self, seconds: float):
        self.began = time.monotonic()
        self.at = self.began + float(seconds)

    def check(self) -> None:
        if time.monotonic() > self.at:
            raise OutOfTime()

    def elapsed(self) -> float:
        return time.monotonic() - self.began


def schedule(runtime_library: dict | None) -> dict:
    """{"before", "minutes"} of a [runtime.library] table; ValueError for a value it does not take."""
    table = dict(runtime_library or {})
    before = table.get("active_before", False)
    if not isinstance(before, bool):
        raise ValueError(f"runtime.library.active_before is true or false, not {before!r}")
    minutes = table.get("active_minutes", DEFAULT_MINUTES)
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not 1 <= float(minutes) <= 240:
        raise ValueError(f"runtime.library.active_minutes is 1 to 240, not {minutes!r}")
    return {"before": before, "minutes": float(minutes)}


def is_active(runtime: dict) -> bool:
    """Whether a run's goal is to learn its environment (learn on, trigger active)."""
    library = runtime.get("library") or {}
    return library.get("learn") == "on" and library.get("trigger") == "active"


def body(skills=()) -> dict:
    """The body's lines of the learning goal: the [probe] table of the probe among `skills`
    (runtime/execution/skills.py), its missing keys from GENERIC."""
    from harness.runtime.execution.skills import load_skills

    known = load_skills()
    for name in skills:
        if name in known and known[name].probe:
            return {**GENERIC, **dict(known[name].probe)}
    return dict(GENERIC)


def goal(instruction: str, minutes: float, skills=(), sandbox: dict | None = None, *, legacy_memory=False) -> str:
    """The active run's instruction: learn the environment for the task `instruction`, the
    lines of the prompt for the run's `skills` kept, its body's lines (body()) in it, and,
    when the environment offers one, its practice sandbox (sandbox_lines())."""
    from harness.runtime.decision.prompts import select

    features = (*skills, "legacy_memory") if legacy_memory else skills
    text = select(PROMPT.read_text(encoding="utf-8"), features).strip()
    lines = body(skills)
    text = text.format(task=instruction.strip(), minutes=f"{minutes:g}", probe=lines["try"],
                       sandbox=sandbox_lines(sandbox))
    # A placeholder with nothing to say leaves no line.
    return "\n".join(line for line in text.split("\n") if line.strip() or not line).rstrip()


def sandbox_of(runtime: dict) -> dict | None:
    """The practice sandbox a run's kernel gets ({"what", "ops"}, the bench's [sandbox] that
    the suite put into an active run's runtime): an active run's with ops, else None."""
    sandbox = runtime.get("sandbox") or {}
    return dict(sandbox) if is_active(runtime) and sandbox.get("ops") else None


def sandbox_lines(sandbox: dict | None) -> str:
    """The learning goal's lines about the practice sandbox a bench declares ({"what",
    "ops"}: bench.py), or none: there is none, or it stages nothing."""
    if not sandbox or not sandbox.get("ops"):
        return ""
    ops = "; ".join(f"{op}: {what}" for op, what in sandbox["ops"].items())
    return (f"This environment offers a practice sandbox in this run only (never in the task's runs): "
            f"{sandbox.get('what', '').strip()} sandbox(op, **arguments) stages a scene ({ops}). Stage a scene for "
            "your practice drills. library.propose(kind, name, code, test=..., setup=...) stores the setup "
            "with the test for the host's verification.")


def keep(session, table: dict, summary: str, note: str = "") -> dict:
    """Keep what a body's probe measured in the run's library, through the learner (skills/
    learning): the memory entry "controls" (`summary`, the table attached as controls.json)
    and, when given, the note "controls" (`note`: the few facts every later call needs).
    {"memory": its answer, "note": its answer}; {} where the run's library does not learn."""
    import json

    from harness.runtime.learning.learner import MEMORY_MAX_CHARS, NOTE_MAX_CHARS

    library = getattr(session, "_library_api", None)
    if library is None:
        return {}
    library = library()
    if not library._learning:
        return {}
    kept = {"memory": library.propose("memory", "controls", fit(summary, MEMORY_MAX_CHARS, "(the rest: controls.json)"),
                                      summary="what each control does, measured",
                                      attachments={"controls.json": json.dumps(table, default=str)})}
    if note:
        kept["note"] = library.propose("note", "controls", fit(note, NOTE_MAX_CHARS), summary="the controls, measured")
    return kept


def fit(text: str, limit: int, tail: str = "") -> str:
    """`text` within `limit` characters: its first lines that fit, then `tail`."""
    if len(text) <= limit:
        return text
    lines, size = [], len(tail)
    for line in text.split("\n"):
        if size + len(line) + 1 > limit:
            break
        lines.append(line)
        size += len(line) + 1
    return "\n".join(lines + ([tail] if tail else [])) if lines else text[:limit]


CODE = ("skills", "reactive")
# The situations list as the model is shown it: its open items ([ ]) first, at most this many
# UTF-8 bytes (it is stored up to learner.SITUATIONS_MAX_BYTES).
SITUATIONS_BYTES = 8 * 1024


def show_situations(text: str | None) -> str:
    """The situations list as shown: its open lines ([ ]) first, then the rest in order, up
    to SITUATIONS_BYTES; how many lines did not fit is said."""
    lines = [line for line in (text or "").strip().splitlines() if line.strip()]
    ordered = sorted(lines, key=lambda line: "[ ]" not in line and "[unknown]" not in line)
    shown, size = [], 0
    for line in ordered:
        cost = len(line.encode("utf-8")) + 5  # four spaces and a newline
        if size + cost > SITUATIONS_BYTES:
            break
        shown.append(line)
        size += cost
    if len(shown) < len(lines):
        # Reserve room for the omission notice inside the same limit.
        while True:
            omitted = f"({len(lines) - len(shown)} more lines not shown: the memory entry situations has them)"
            if size + len(omitted) + 5 <= SITUATIONS_BYTES:
                break
            size -= len(shown.pop().encode("utf-8")) + 5
        shown.append(omitted)
    return "\n".join("    " + line for line in shown)


def progress(rows: list[dict], seconds_left: float, seconds: float, situations: str | None = None) -> dict:
    """Where an active run stands, from the learner's entries (runtime/learning/learner.py entries()):
    the live time, the code entries with a passing test (their uses), those whose test failed,
    the code waiting for its test, the notes and memory entries (nothing tests them) and the
    open lines of the situations list. What report() says to the model and the frontends show
    (the app's /api/app/learning, the terminal chat's /learn, harness run --learn)."""
    code = [row for row in rows if row["section"] in CODE]
    tested = [row for row in code if row["loaded"] and row["verified"]]

    def key(row):
        return f"{row['section']}/{row['name']}"

    shown = show_situations(situations)
    return {"seconds_left": round(max(0.0, seconds_left), 1), "seconds": round(float(seconds), 1),
            "entries": len(rows),
            "tested": [{"key": key(row), "name": row["name"], "uses": row["uses"], "success_rate": row.get("success_rate"),
                        "admitted_by": row.get("admitted_by")} for row in tested],
            "failing": [key(row) for row in code if row["evidence"] == "failed"],
            "verified_waiting": [key(row) for row in code if row["verified"] and not row["loaded"]],
            "situations_text": shown,
            "waiting": [key(row) for row in code if not row["verified"] and not row["loaded"] and row["evidence"] != "failed"],
            "untested": [key(row) for row in rows if row["section"] not in CODE],
            "situations": bool(situations and situations.strip()),
            "open": [line.strip() for line in shown.splitlines() if "[ ]" in line]}


def progress_line(now: dict, short: bool = False) -> str:
    """progress() in one line, as harness run --learn and the terminal chat show it (`short`:
    its status line's few words)."""
    if short:
        return (f"learning {now['seconds_left'] / 60:.0f}/{now['seconds'] / 60:.0f} min · {len(now['tested'])} tested · "
                f"{len(now['waiting'])} waiting · " + (f"{len(now['open'])} open" if now["situations"] else "no list"))
    return (f"learning: {now['seconds_left'] / 60:.0f} of {now['seconds'] / 60:.0f} min left · "
            f"{len(now['tested'])} tested ({sum(1 for row in now['tested'] if row['uses'])} used) · "
            f"{len(now['failing'])} failing · {len(now['waiting'])} waiting for verification · "
            f"{len(now['verified_waiting'])} verified and awaiting activation · {len(now['untested'])} notes · "
            + (f"{len(now['open'])} situations open" if now["situations"] else "no situations list yet"))


# What pending code waits for, by the admission level in force (learner.ADMISSION).
WAITS_FOR = {"fixture": "an independent fixture", "own_test": "the host to run its test between programs",
             "off": "nothing: the host admits no code here"}


def report(rows: list[dict], seconds_left: float | None, situations: str | None = None,
           admission: str = "fixture") -> str:
    """What an active run has learned so far (progress()): what the library holds, what is
    pending and what for, and the situations entry when there is one. Facts only: what to do
    next is the model's to decide. The lines the model reads with each call of an active
    run; `admission` is how the host admits code here (learner.admission). `seconds_left`
    None: the time the run has left is not said (runtime.tell_budget)."""
    now = progress(rows, seconds_left or 0.0, 0.0, situations)
    left = "" if seconds_left is None else f"; {now['seconds_left'] / 60:.0f} min of live time left"
    tested = now["tested"]

    def names(found):
        return ", ".join(found) or "none"

    lines = [f"Learned so far ({now['entries']} entries{left}):",
             "  skills with a passing test: " + (", ".join(
                 f"{row['name']}" + (" [own test]" if row.get("admitted_by") == "own_test" else "")
                 + (f" ({row['uses']} uses, {row['success_rate']:.0%} ok)"
                    if row["uses"] and row.get("success_rate") is not None else "")
                 for row in tested) or "none yet"),
             f"  untested (notes and memory entries have no test): {names(now['untested'])}"]
    if now["failing"]:
        lines.append(f"  skills whose test failed: {names(now['failing'])}")
    if now["waiting"]:
        lines.append(f"  code waiting for {WAITS_FOR[admission]}: {names(now['waiting'])}")
    if now["verified_waiting"]:
        lines.append(f"  verified, awaiting activation: {names(now['verified_waiting'])}")
    if situations:
        lines.append("  your situations entry (memory/situations):\n" + now["situations_text"])
    return "\n".join(lines)


def holdings(rows: list[dict], situations: str | None = None) -> str:
    """What the library holds, for the start of a task run: its tested skills and reflexes
    and the situations entry it was learned with."""
    tested = [row for row in rows if row["section"] in CODE and row["passed"]]
    if not tested and not situations:
        return ""
    lines = ["Your library:"]
    for section in CODE:
        found = [row["name"] + (" [own test]" if row.get("admitted_by") == "own_test" else "")
                 + (f" ({row['summary']})" if row.get("summary") else "")
                 for row in tested if row["section"] == section]
        if found:
            lines.append(f"  {section} with a passing test: " + "; ".join(found))
    if situations:
        lines.append("  the situations entry (memory/situations):\n" + show_situations(situations))
    return "\n".join(lines)


def wanted(runtime: dict) -> bool:
    """Whether a task's runs want an active run before them (learning on, active_before)."""
    library = runtime.get("library") or {}
    return library.get("learn") == "on" and schedule(library)["before"]


def active_config(config):
    """A copy of a task's configuration (config/agent.py TaskConfig) for its active
    run: trigger "active" and the active run's live time as its wall budget."""
    plan = schedule(config.runtime.get("library"))
    active = copy(config)
    active.runtime = {**config.runtime, "library": {**config.runtime["library"], "trigger": "active"}}
    active.max_wall_seconds = plan["minutes"] * 60.0
    return active
