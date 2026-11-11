"""The learner: one mechanism for in-context learning and self-improvement, for any action
scenario. A candidate entry (a note, a memory entry, a skill with its test, a reactive
entry) comes from the model in the middle of a run, or from reflection on an episode after
it; graded evidence decides whether it enters the library (runtime/learning/library.py):

    its own test, run in the run (fast)          -> provisional
    its test passing again when a later run starts (replay)  -> replayed
    a rise of the score on held-out development seeds (harness self-improve)
                                                 -> validated

An entry admitted in a run takes effect in that run (the conversation and the kernel load
it at once: runtime/conversation.py, skills/learning); every admission changes the library
version and the trace records it. Learning has two triggers, one path: active, a run whose
goal is to learn the environment (`trigger = "active"`), and passive, the task runs and the
reflection after them (`trigger = "passive"`). Evaluation reads a frozen library and learns
nothing (`learn = "off"`, the default).

The settings, [runtime.library] (SETTINGS):

    learn     "off" | "on"              admit in a run (in-context) or not (frozen)
    trigger   "passive" | "active"      what the run is: a task, or learning the environment
    evidence  "test" | "validated"      what admits an entry in a run: its own test (a note
                                        or memory entry has none: admitted as proposed), or
                                        only development seeds (it waits in candidates/)
    load      proposed | provisional | replayed | validated
                                        the lowest evidence an entry needs to be loaded
    replay    false | true              at a run's start, test the provisional entries again
    reflect   false | true              after each episode, reflection proposes one entry

How a skill or a reactive entry the agent wrote itself is admitted is the host's to say, not
the run's (ADMISSION; admission()): the user's setting learning.admission, or
$HARNESS_LEARNING_ADMISSION, which wins over it.

    off       no learned code is admitted or loaded
    fixture   a fixture the host provisioned for the entry verifies it (fixtures.py); the default
    own_test  where the worker's profile says physical is False: the host runs the entry's
              own test on the staged revision, in the kernel, between programs; a pass admits
              it as provisional with a proof whose method is "own_test". A fixture for the
              entry, where there is one, is used instead. Such an entry goes back to
              candidates/ when it keeps failing in use (DEMOTE_USES, DEMOTE_RATE).

Standard library only.
"""

import base64
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time

from harness.runtime.learning.library import (ADMISSIONS, CANDIDATES, EVIDENCE, FAILED, INDEX, OWN_TEST, SECTIONS, TESTS,
                                              Library, Revision, admitted_by, executable, rank)
from harness.core import atomic_write
from harness.core.procs import file_lock
from harness.paths import home

SETTINGS = {
    "learn": ("off", "on"),
    "trigger": ("passive", "active"),
    "evidence": ("test", "validated"),
    "load": EVIDENCE,
    "replay": (False, True),
    "reflect": (False, True),
}
# An entry's kind and the library section it goes into (library.SECTIONS: its file suffix).
KINDS = {"note": "notes", "memory": "memory", "skill": "skills", "reactive": "reactive"}
ORIGINS = ("model", "reflection", "self_improve", "hand")
NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
# Notes go into every prompt, memory entries only when recall finds them: a longer entry is
# refused (the reflection request says so; before it did not, and half the proposals were lost).
NOTE_MAX_CHARS, MEMORY_MAX_CHARS = 600, 1200
# The longest situations list (memory/situations: the plan an active run learns by).
SITUATIONS_MAX_BYTES = 32 * 1024
# An attachment is at most this large in all, per proposal (a small trained model fits).
ATTACHMENT_BYTES = 64 * 1024 * 1024
# Test runs and uses kept per entry in the index.
KEPT = 20
# How learned code is admitted, strictest first (the module docstring).
ADMISSION = ("off", "fixture", OWN_TEST)
ADMISSION_VARIABLE = "HARNESS_LEARNING_ADMISSION"
# The longest an entry's own test may run when the host runs it.
OWN_TEST_SECONDS = 120.0
# A kept test that stages its scene in the practice sandbox starts with this line (skills/learning SETUP).
STAGED_TEST = "# setup: stages the scene in the practice sandbox"
# An entry admitted by its own test goes back to candidates/ once this many uses of its
# revision are recorded and fewer than this share of them succeeded.
DEMOTE_USES, DEMOTE_RATE = 3, 0.25
_LOCK = threading.Lock()


def admission(profile: dict | None, allowed: str | None = None) -> str:
    """How learned code is admitted on a worker with this `profile`, given what the host
    allows (`allowed`: one of ADMISSION; None is "fixture"): "own_test" only where the host
    allows it and the profile says physical is False, "off" where the host says so, else
    "fixture". ValueError for a level that does not exist."""
    level = "fixture" if allowed in (None, "") else allowed
    if level not in ADMISSION:
        raise ValueError(f"learning.admission is one of {list(ADMISSION)}, not {level!r}")
    if level == OWN_TEST and (profile or {}).get("physical") is not False:
        return "fixture"
    return level


def settings(runtime_library: dict | None) -> dict:
    """The learning settings of a [runtime.library] table, defaults filled in; ValueError
    for a value it does not take."""
    given = dict(runtime_library or {})
    chosen = {}
    for key, values in SETTINGS.items():
        value = given.get(key, values[0])
        if value not in values:
            raise ValueError(f"runtime.library.{key} is one of {list(values)}, not {value!r}")
        chosen[key] = value
    return chosen


def library_path(path) -> Path:
    """A library's directory: `$HARNESS_HOME/...` is under the harness's home."""
    text = str(path)
    for prefix in ("$HARNESS_HOME/", "${HARNESS_HOME}/"):
        if text.startswith(prefix):
            return home() / text[len(prefix):]
    return Path(text)


def libraries() -> list[dict]:
    """The libraries under $HARNESS_HOME/libraries: [{"name", "directory", "version", "entries"}]."""
    base = home() / "libraries"
    rows = []
    for path in sorted(base.iterdir()) if base.is_dir() else []:
        if path.is_dir():
            library = Library(path)
            rows.append({"name": path.name, "directory": str(path), "version": library.version(),
                         "entries": sum(len(library.entries(section)) for section in SECTIONS)})
    return rows


def entry_key(kind: str, name: str) -> str:
    """Where an entry is in a library: "<section>/<name><suffix>" (skills/walk.py)."""
    return f"{KINDS[kind]}/{name}{SECTIONS[KINDS[kind]]}"


@dataclass
class Candidate:
    """An entry proposed for the library."""

    kind: str                       # note, memory, skill, reactive
    name: str
    text: str
    test: str | None = None
    summary: str = ""
    attachments: dict = field(default_factory=dict)       # {filename: bytes}
    source: str = "passive"                                # active, passive
    origin: str = "model"                                  # ORIGINS
    run: str | None = None                                 # the episode it came from
    bindings: tuple = ()

    @property
    def section(self) -> str:
        return KINDS[self.kind]

    @property
    def filename(self) -> str:
        return self.name + SECTIONS[self.section]

    @property
    def key(self) -> str:
        return entry_key(self.kind, self.name)


    def revision(self, dependencies=(), bindings=None):
        return Revision(self.key, self.text.encode("utf-8"),
                        None if self.test is None else self.test.encode("utf-8"),
                        tuple((f"{self.section}/{self.name}.files/{name}", data)
                              for name, data in sorted(self.attachments.items())),
                        tuple(sorted(dependencies)), tuple(sorted(self.bindings if bindings is None else bindings)))


def entry_name_problem(name) -> str | None:
    """Why `name` cannot name a library entry (None when it can): the learner's one rule,
    also checked by the learning skill before an entry's test acts."""
    if not isinstance(name, str) or not NAME.match(name):
        return f"an entry's name is lowercase letters, digits and _ (2-41, a letter first), not {name!r}"
    return None


def candidate(kind, name, text, test=None, *, summary="", attachments=None, source="passive", origin="model",
              run=None) -> Candidate:
    """A Candidate, checked: its kind and name, a code entry that parses (and has a test,
    when it is code), a note or memory entry not too long, attachments within the cap."""
    if kind not in KINDS:
        raise ValueError(f"an entry's kind is one of {list(KINDS)}, not {kind!r}")
    problem = entry_name_problem(name)
    if problem:
        raise ValueError(problem)
    if source not in ("active", "passive") or origin not in ORIGINS:
        raise ValueError(f"source is active or passive and origin one of {list(ORIGINS)}")
    text = str(text).strip() + "\n"
    if kind in ("skill", "reactive"):
        import ast

        try:
            ast.parse(text)
            if test is not None:
                ast.parse(test)
        except SyntaxError as error:
            raise ValueError(f"the code does not parse: {error}") from None
    else:
        # The situations list (runtime/learning/active.py) is a plan, not a lesson: it gets more room.
        situations = kind == "memory" and name == "situations"
        limit = SITUATIONS_MAX_BYTES if situations else (NOTE_MAX_CHARS if kind == "note" else MEMORY_MAX_CHARS) + 1
        if (len(text.encode("utf-8")) if situations else len(text)) > limit:
            raise ValueError(f"a {kind} is at most {limit} characters")
    files = {}
    for filename, value in (attachments or {}).items():
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$", str(filename)):
            raise ValueError(f"an attachment has a plain file name, not {filename!r}")
        files[str(filename)] = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    if sum(len(value) for value in files.values()) > ATTACHMENT_BYTES:
        raise ValueError(f"attachments are at most {ATTACHMENT_BYTES // (1024 * 1024)} MB in all")
    return Candidate(kind, name, text, None if test is None else str(test).strip() + "\n", str(summary or ""),
                     files, source, origin, run)


def _now() -> float:
    return round(time.time(), 3)


class Learner:
    """The library at `directory` with what a run's learning settings allow."""

    def __init__(self, directory, runtime_library: dict | None = None, create: bool = False):
        self.directory = library_path(directory).resolve()
        if create:
            for section in SECTIONS:
                (self.directory / section).mkdir(parents=True, exist_ok=True)
        self.settings = settings(runtime_library)
        self.layers = tuple((runtime_library or {}).get("layers", ("notes", "skills", "reactive")))
        self.library = Library(self.directory, self.layers, self.settings["load"])
        # The entries record_uses() sent back to candidates/: [{"key", "revision", "ok", "failed"}].
        self.demoted = []

    def version(self) -> str:
        return self.library.version()

    # -- the index ----------------------------------------------------------------------

    def index(self) -> dict:
        return self.library.index()

    def _save_index(self, index: dict) -> None:
        atomic_write(self.directory / INDEX, json.dumps(index, indent=1, sort_keys=True))

    def migrate_experience(self):
        from harness.runtime.learning.experience import MIGRATION, legacy_entries

        index = self.index()
        if index.get(MIGRATION) or not list(legacy_entries(self.directory, index)):
            return
        with _LOCK, file_lock(self.directory / ".library.lock"):
            index = self.index()
            if index.get(MIGRATION):
                return
            for item in list(legacy_entries(self.directory, index)):
                key = item["id"]
                if key not in index:
                    revision = Revision(key, item["text"].encode("utf-8")).save(self.directory)
                    index[key] = {"memory": item, "evidence": "validated", "origin": "legacy", "revision": revision}
            index[MIGRATION] = True
            self._save_index(index)

    def store_memory(self, item, *, forgotten=False):
        key = item["id"]
        if not isinstance(key, str) or not re.fullmatch(r"memory/[^/\\]+\.md", key):
            raise ValueError("invalid persistent memory key")
        if "notes" not in self.layers or self.settings["learn"] != "on":
            raise ValueError("this library is read-only")
        with _LOCK, file_lock(self.directory / ".library.lock"):
            index = self.index()
            row = dict(index.get(key) or {})
            if forgotten:
                row["forgotten"] = True
            else:
                content = dict(item, scope="library")
                data = content["text"].encode("utf-8")
                if content.get("name") == "situations" and len(data) > SITUATIONS_MAX_BYTES:
                    raise ValueError("the situations list is limited to 32 KiB")
                revision = Revision(key, data).save(self.directory)
                row.update(evidence="proposed", origin="memory", memory=content, revision=revision,
                           forgotten=False)
            index[key] = row
            self._save_index(index)
        return {**item, "scope": "library", "evidence": "proposed", "forgotten": forgotten}

    def entries(self, *, snapshot=None) -> list[dict]:
        """Every entry in the library (loaded or not) with its evidence, source, origin and
        summary, and the candidates waiting: [{"section", "name", "file", "evidence",
        "source", "origin", "summary", "admitted_at", "tests", "passed", "uses", "loaded",
        "admitted_by", "demoted"}] (admitted_by: what verified a code entry's revision,
        "own_test" or "fixture", None when nothing did; demoted: it failed in use and waits)."""
        captured = snapshot if snapshot is not None else self.library.capture()
        index = captured.index
        loaded = {item.key for item in captured.entries}
        rows = []
        for section, suffix in SECTIONS.items():
            for root, waiting in ((self.directory / section, False), (self.directory / CANDIDATES / section, True)):
                prefix = f"{CANDIDATES}/{section}/" if waiting else f"{section}/"
                if snapshot is None:
                    paths = set(root.glob(f"*{suffix}"))
                    paths.update(root / key.removeprefix(prefix) for key, row in index.items()
                                 if key.startswith(prefix) and row.get("revision"))
                else:
                    paths = {root / key.removeprefix(prefix) for key in loaded if key.startswith(prefix)}
                for path in sorted(paths):
                    key = f"{section}/{path.name}"
                    row = index.get(f"{CANDIDATES}/{key}" if waiting else key) or {}
                    if row.get("forgotten"):
                        continue
                    tests = row.get("tests") or []
                    uses = (row.get("uses_by_revision") or {}).get(row.get("revision")) or {}
                    rows.append({"section": section, "name": (row.get("memory") or {}).get("name") or path.stem, "file": key,
                                 "evidence": row.get("evidence", "proposed" if waiting else "validated"),
                                 "revision": row.get("revision"),
                                 "verified": bool(row.get("proof") and row["proof"].get("revision") == row.get("revision")
                                                  and row.get("evidence") in ("provisional", "replayed", "validated")),
                                 "admitted_by": admitted_by(row), "demoted": bool(row.get("demoted")),
                                 "waiting": waiting, "source": row.get("source", "-"),
                                 "origin": row.get("origin", "hand"), "summary": row.get("summary", ""),
                                 "admitted_at": row.get("admitted_at"), "tests": len(tests),
                                 "passed": sum(1 for run in tests if run.get("ok")),
                                 "uses": int(uses.get("ok", 0)) + int(uses.get("failed", 0)),
                                 "success_rate": uses.get("rate"), "loaded": key in loaded and not waiting})
        return rows

    # -- admitting --------------------------------------------------------------------

    def wanted(self, candidate: Candidate, evidence: str) -> bool:
        """Whether an entry with this evidence enters the library now (else it waits)."""
        if self.settings["evidence"] == "validated":
            return evidence == "validated"
        return rank(evidence) >= rank("proposed")

    def admit(self, candidate: Candidate, evidence: str, *, test_run: dict | None = None,
              gain: float | None = None, why: str = "", proof=None, dependencies=(), bindings=None,
              pending=False, expected=None, check=None) -> dict:
        """Put a candidate into the library with this evidence (or, when the settings want
        more, into candidates/): its files written, its index row (source, origin, the test
        run, the gain) kept. {"admitted", "evidence", "version_before", "version_after",
        "key"}."""
        if evidence not in EVIDENCE:
            raise ValueError(f"evidence is one of {list(EVIDENCE)}, not {evidence!r}")
        with _LOCK, file_lock(self.directory / ".library.lock"):
            before = self.version()
            revision = candidate.revision(dependencies, bindings)
            if proof is not None and (proof.get("revision") != revision.revision or not proof.get("conditions")):
                raise ValueError("verification proof does not cover this revision")
            index = self.index()
            waiting = index.get(f"{CANDIDATES}/{candidate.key}") or {}
            if expected is not None and (waiting.get("revision") != expected
                                         or waiting.get("evidence") == FAILED):
                raise ValueError("the pending proposal changed while being verified")
            if proof is not None and expected is None and waiting.get("revision") not in (
                    None, candidate.revision().revision, revision.revision):
                raise ValueError("the pending proposal changed while being verified")
            admitted = not pending and self.wanted(candidate, evidence)
            stored_evidence = evidence if admitted or proof is not None else "proposed"
            # Preserve the imported revision before writing the editable file mirror.
            previous = index.get(candidate.key) or {}
            if admitted and not previous.get("revision"):
                old = next((item for item in self.library.capture().entries if item.key == candidate.key), None)
                if old is not None:
                    index[candidate.key] = {**previous, "revision": old.save(self.directory)}
                    self._save_index(index)
            root = self.directory if admitted else self.directory / CANDIDATES
            target = root / candidate.section / candidate.filename
            replaced = target.is_file() and target.read_bytes() != candidate.text.encode("utf-8")
            if expected is None:
                atomic_write(target, candidate.text)
                if candidate.test is not None:
                    atomic_write(root / TESTS / f"{candidate.name}.py", candidate.test)
                folder = root / candidate.section / f"{candidate.name}.files"
                if candidate.attachments:
                    shutil.rmtree(folder, ignore_errors=True)
                    for filename, data in candidate.attachments.items():
                        atomic_write(folder / filename, data)
            index_key = candidate.key if admitted else f"{CANDIDATES}/{candidate.key}"
            row = dict(index.get(index_key) or {})
            if admitted:
                index.pop(f"{CANDIDATES}/{candidate.key}", None)
            revision_id = revision.save(self.directory)
            if row.get("revision") != revision_id:
                row.pop("proof", None)
                row.pop("tests", None)
                row.pop("demoted", None)
            row["revision"] = revision_id
            if proof is not None:
                row["proof"] = proof
            history = list(row.get("history") or [])
            history.append({"at": _now(), "evidence": stored_evidence,
                            "revision": revision_id, **({"proof": proof} if proof is not None else {}),
                            **({"gain": round(gain, 4)} if gain is not None else {}), **({"why": why} if why else {})})
            if admitted and replaced and (row.get("uses") or {}).get("sha256"):
                history[-1]["previous_uses"] = row.pop("uses")
            row.update(evidence=stored_evidence, source=candidate.source,
                       origin=candidate.origin, summary=candidate.summary or row.get("summary", ""),
                       admitted_at=row.get("admitted_at") or _now(), updated_at=_now(), history=history[-KEPT:],
                       **({"run": candidate.run} if candidate.run else {}))
            if test_run is not None:
                row["tests"] = [*(row.get("tests") or []), {"at": _now(), **test_run}][-KEPT:]
            index[index_key] = row
            if check is not None:
                check()
            self._save_index(index)
            if admitted:
                for stale in (self.directory / CANDIDATES / candidate.section / candidate.filename,
                              self.directory / CANDIDATES / TESTS / f"{candidate.name}.py"):
                    stale.unlink(missing_ok=True)
            after = self.version()
            outcome = {"admitted": admitted, "evidence": row["evidence"], "version_before": before,
                       "version_after": after, "key": candidate.key, "row": row, "revision": revision_id,
                       "sha256": hashlib.sha256(candidate.text.encode("utf-8")).hexdigest()}
            if admitted:
                # The library's log of what entered it (the audit's evidence that an entry
                # was admitted, benches/minecraft/audit.py): section, file, its bytes' sha256.
                with (self.directory / ADMISSIONS).open("a", encoding="utf-8") as log:
                    log.write(json.dumps({**self.record_of(outcome), "source": candidate.source,
                                          "origin": candidate.origin, "at": _now()}) + "\n")
        return outcome

    @staticmethod
    def record_of(outcome: dict) -> dict:
        """An admission as the library's log and the trace record it: section, name (the
        entry's file), sha256 of its bytes, the version after it, its evidence, and whether
        it entered the library (or waits)."""
        section, _, filename = outcome["key"].partition("/")
        return {"section": section, "name": filename, "sha256": outcome["sha256"], "version": outcome["version_after"],
                "version_before": outcome["version_before"], "evidence": outcome["evidence"],
                "admitted": outcome["admitted"], "revision": outcome.get("revision"),
                **({"proof": outcome["row"]["proof"]} if (outcome.get("row") or {}).get("proof") else {})}

    def grade(self, key: str, evidence: str, *, test_run: dict | None = None, gain: float | None = None,
              why: str = "", sha256: str | None = None) -> dict | None:
        """Set an entry's evidence (a replay passed: replayed; failed: failed; development
        seeds: validated), recorded in its history. Its index row, or None."""
        if evidence not in (*EVIDENCE, FAILED):
            raise ValueError(f"evidence is one of {[*EVIDENCE, FAILED]}, not {evidence!r}")
        with _LOCK, file_lock(self.directory / ".library.lock"):
            if sha256 is not None:
                section, _, filename = key.partition("/")
                if (section not in SECTIONS or not filename.endswith(SECTIONS[section])
                        or any(char in filename for char in "/\\:")):
                    raise ValueError(f"invalid library revision key {key!r}")
                path = self.directory / section / filename
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
                    raise ValueError(f"{key} changed while it was being graded")
            index = self.index()
            row = dict(index.get(key) or {"source": "-", "origin": "hand"})
            row["evidence"] = evidence
            row["history"] = [*(row.get("history") or []), {
                "at": _now(), "evidence": evidence, **({"gain": round(gain, 4)} if gain is not None else {}),
                **({"sha256": sha256} if sha256 is not None else {}),
                **({"revision": row["revision"]} if row.get("revision") else {}),
                **({"why": why} if why else {})}][-KEPT:]
            if test_run is not None:
                row["tests"] = [*(row.get("tests") or []), {"at": _now(), **test_run}][-KEPT:]
            index[key] = row
            self._save_index(index)
            return row

    def remove(self, key: str, why: str = "") -> None:
        """Take an entry (or a waiting candidate) out of the library: its file, test and
        attachments; its index row says why."""
        section, _, filename = key.partition("/")
        stem = Path(filename).stem
        with _LOCK, file_lock(self.directory / ".library.lock"):
            for root in (self.directory, self.directory / CANDIDATES):
                (root / section / filename).unlink(missing_ok=True)
                (root / TESTS / f"{stem}.py").unlink(missing_ok=True)
                shutil.rmtree(root / section / f"{stem}.files", ignore_errors=True)
            index = self.index()
            if key in index:
                index[key] = {**index[key], "evidence": FAILED, "removed": _now(), **({"why": why} if why else {})}
                self._save_index(index)

    def grade_development(self, candidate, revision, *, pending, score):
        """Accept development evidence for exactly the verified candidate that ran."""
        key = candidate.key
        current = self.index().get(f"{CANDIDATES}/{key}" if pending else key) or {}
        proof = current.get("proof") or {}
        if proof.get("revision") != revision or candidate.revision().revision != revision:
            return False
        proof = {**proof, "development": score}
        if pending:
            self.admit(candidate, "validated", proof=proof, expected=revision, gain=score["gain"],
                       why="paired development scores")
            return True
        with _LOCK, file_lock(self.directory / ".library.lock"):
            index = self.index()
            row = index.get(key) or {}
            if row != current or row.get("evidence") not in ("provisional", "replayed"):
                return False
            row.update(evidence="validated", proof=proof)
            row["history"] = [*(row.get("history") or []),
                              {"at": _now(), "revision": revision, "evidence": "validated",
                               "development": score}][-KEPT:]
            self._save_index(index)
            return True

    def record_trial(self, key, expected, item, *, pending, evidence, receipt, check):
        """Record a verdict on the immutable revision that actually ran."""
        if item.key != key or receipt["revision"] != item.revision:
            raise ValueError("the trial receipt has a different revision")
        with _LOCK, file_lock(self.directory / ".library.lock"):
            index = self.index()
            index_key = f"{CANDIDATES}/{key}" if pending else key
            row = index.get(index_key)
            if row is None or row.get("revision") != expected:
                return False
            if row.get("evidence") != ("proposed" if pending else "provisional"):
                return False
            revision = item.save(self.directory)
            history = list(row.get("history") or [])
            result = {"at": _now(), "revision": revision, "evidence": evidence, "receipt": receipt}
            row.update(revision=revision, evidence=evidence, history=[*history, result][-KEPT:],
                       tests=[*(row.get("tests") or []), receipt][-KEPT:])
            if evidence == FAILED:
                row.pop("proof", None)
                if not pending:
                    failed = {revision, *(grade.get("revision") for grade in history
                                          if grade.get("evidence") == FAILED)}
                    earlier = next((grade for grade in reversed(history)
                                    if grade.get("revision") not in failed and grade.get("proof")), None)
                    if earlier is not None:
                        previous = Revision.read(self.directory, earlier["revision"])
                        if previous.key == key:
                            index.setdefault(f"{CANDIDATES}/{key}", dict(row))
                            row.update(revision=previous.revision, evidence=earlier["evidence"],
                                       proof=earlier["proof"], tests=[])
            check()
            self._save_index(index)
            return True

    def record(self, key: str, ok: bool, detail=None) -> None:
        """A use of an entry in play: counted, its rate kept."""
        self.record_uses(key, [(ok, detail)])

    def record_uses(self, key, results, digest=None, *, revision=None, run=None):
        """Record outcomes once under the version that ran, including replaced versions."""
        with _LOCK, file_lock(self.directory / ".library.lock"):
            index = self.index()
            row = dict(index.get(key) or {"source": "-", "origin": "hand", "evidence": "validated"})
            if revision is None and digest is not None:
                matching = [item for item in self.library.capture().entries
                            if item.key == key and item.source_sha256 == digest]
                if not matching:
                    return 0
                revision = matching[0].revision
            versions = row.setdefault("uses_by_revision", {})
            uses = versions.setdefault(revision or "unknown", {"ok": 0, "failed": 0})
            if run is not None:
                processed = uses.setdefault("runs", [])
                if run in processed:
                    return 0
                processed.append(run)
            for result in results:
                ok, detail = result[:2]
                uses["ok" if ok else "failed"] += 1
                if len(result) > 2:
                    uses["seconds"] = round(uses.get("seconds", 0) + (result[2] or 0), 3)
                if detail:
                    uses["last"] = str(detail)[:200]
            count = uses["ok"] + uses["failed"]
            uses["rate"] = round(uses["ok"] / count, 3) if count else None
            index[key] = row
            if (self.settings["learn"] == "on" and executable(key) and row.get("revision") == revision
                    and row.get("evidence") == "provisional" and admitted_by(row) == OWN_TEST
                    and count >= DEMOTE_USES and uses["ok"] / count < DEMOTE_RATE):
                self._demote(index, key, row, uses)
            self._save_index(index)
            return len(results)

    def _demote(self, index, key, row, uses) -> None:
        """An entry admitted by its own test that keeps failing in use goes back to
        candidates/: no proof, not loaded, and its own test is not run again for this
        revision (a rewritten one is a new proposal; a fixture may still admit this one)."""
        revision = row["revision"]
        item = Revision.read(self.directory, revision)
        section, _, filename = key.partition("/")
        stem = Path(filename).stem
        why = f"demoted: {uses['ok']} of {uses['ok'] + uses['failed']} uses succeeded"
        waiting = {name: value for name, value in row.items() if name != "proof"}
        waiting.update(evidence="proposed", updated_at=_now(),
                       demoted={"at": _now(), "revision": revision, "ok": uses["ok"], "failed": uses["failed"]},
                       history=[*(row.get("history") or []),
                                {"at": _now(), "evidence": "proposed", "revision": revision, "why": why}][-KEPT:])
        index[f"{CANDIDATES}/{key}"] = waiting
        del index[key]
        pending = self.directory / CANDIDATES
        atomic_write(pending / section / filename, item.source)
        if item.test is not None:
            atomic_write(pending / TESTS / f"{stem}.py", item.test)
        for relative, data in item.attachments:
            atomic_write(pending / relative, data)
        (self.directory / section / filename).unlink(missing_ok=True)
        (self.directory / TESTS / f"{stem}.py").unlink(missing_ok=True)
        shutil.rmtree(self.directory / section / f"{stem}.files", ignore_errors=True)
        self.demoted.append({"key": key, "revision": revision, "ok": uses["ok"], "failed": uses["failed"]})

    # -- reading --------------------------------------------------------------------------

    def candidate_from(self, key: str, *, source="passive", origin="hand", pending=None) -> Candidate | None:
        """Read a waiting or admitted candidate from its pinned revision."""
        section, _, filename = key.partition("/")
        kind = {value: name for name, value in KINDS.items()}[section]
        stem = Path(filename).stem
        index = self.index()
        for waiting in (True, False) if pending is None else (pending,):
            row = index.get(f"{CANDIDATES}/{key}" if waiting else key) or {}
            if row.get("forgotten"):
                continue
            if row.get("revision"):
                item = Revision.read(self.directory, row["revision"])
                if item.key != key:
                    raise ValueError(f"library index points {key} at a different candidate")
                prefix = f"{section}/{stem}.files/"
                return Candidate(kind, stem, item.source.decode("utf-8"),
                                 item.test.decode("utf-8") if item.test is not None else None,
                                 row.get("summary", ""), {name.removeprefix(prefix): data
                                                          for name, data in item.attachments},
                                 row.get("source", source), row.get("origin", origin), row.get("run"), item.bindings)
            root = self.directory / CANDIDATES if waiting else self.directory
            path = root / section / filename
            if path.is_file():
                test = root / TESTS / f"{stem}.py"
                folder = root / section / f"{stem}.files"
                return Candidate(kind, stem, path.read_text(encoding="utf-8"),
                                 test.read_text(encoding="utf-8") if test.is_file() else None,
                                 row.get("summary", ""),
                                 {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()} if folder.is_dir()
                                 else {}, row.get("source", source), row.get("origin", origin), row.get("run"))
        return None

    def attachment(self, sha256: str) -> bytes:
        """The bytes of the attachment with this sha256, wherever it is in the library."""
        for item in self.library.capture().entries:
            for _, data in item.attachments:
                if hashlib.sha256(data).hexdigest() == sha256:
                    return data
        for section in SECTIONS:
            for path in sorted((self.directory / CANDIDATES / section).glob("*.files/**/*")):
                if path.is_file():
                    data = path.read_bytes()
                    if hashlib.sha256(data).hexdigest() == sha256:
                        return data
        raise KeyError(f"no attachment {sha256} in {self.directory}")

    def trial(self, candidate: Candidate, root: Path | None = None, *, proof=None) -> Path:
        """A copy of the library with the candidate in it, to measure it on development seeds."""
        trial = Path(tempfile.mkdtemp(prefix="library-trial-", dir=root))
        shutil.copytree(self.directory, trial, dirs_exist_ok=True, ignore=shutil.ignore_patterns(CANDIDATES))
        copy = Learner(trial, {**self.settings, "evidence": "test", "layers": list(self.layers)})
        if proof is None:
            from dataclasses import replace

            candidate = replace(candidate, origin="hand")
        copy.admit(candidate, "provisional", proof=proof)
        return trial

    def without(self, key: str, root: Path | None = None) -> Path:
        """A copy of the library without one entry, to measure what it adds."""
        trial = Path(tempfile.mkdtemp(prefix="library-trial-", dir=root))
        shutil.copytree(self.directory, trial, dirs_exist_ok=True, ignore=shutil.ignore_patterns(CANDIDATES))
        Learner(trial, {"layers": list(self.layers)}).remove(key, "measured without it")
        return trial

    # -- a run's requests (the host answers the kernel's, runtime/conversation.py) ----------

    def handle(self, request: dict, *, source: str, run: str | None = None):
        """What the kernel asks: admit (a candidate whose test, if any, passed in the
        kernel), grade (a replay's result), record (a use), entries, version, attachment."""
        action = request.get("action")
        if action == "admit":
            files = {name: base64.b64decode(value) for name, value in (request.get("attachments") or {}).items()}
            entry = candidate(request.get("entry") or request.get("kind"), request["name"], request["text"], request.get("test"),
                              summary=request.get("summary", ""), attachments=files, source=source, origin="model",
                              run=run)
            if executable(entry.key):
                if not entry.test:
                    raise ValueError("an executable proposal needs a verification condition")
                return self.admit(entry, "proposed", pending=True)
            return self.admit(entry, "proposed")
        if action == "grade":
            raise ValueError("verification grades require a trusted host receipt")
        if action == "record":
            self.record(request["key"], bool(request.get("ok")), request.get("detail"))
            return None
        if action == "entries":
            return self.entries()
        if action == "version":
            return self.version()
        if action == "attachment":
            return base64.b64encode(self.attachment(request["sha256"])).decode("ascii")
        raise ValueError(f"unknown library request {action!r}")

    # -- passive: reflection after an episode -------------------------------------------

    def reflect(self, chat, run: Path, names, *, since=0, holdings=None) -> tuple[Candidate | None, str]:
        """One candidate from an episode (reflect.py), checked as every candidate is
        (candidate()), as passive learning; (None, reply) when the model proposes none, or
        one that does not pass."""
        from harness.runtime.learning.reflect import propose

        found, reply = propose(chat, Path(run), self.library, names, since=since, holdings=holdings)
        if found is None:
            return None, reply
        try:
            return candidate(*found, source=self.settings["trigger"], origin="reflection", run=str(run)), reply
        except ValueError:
            return None, reply
