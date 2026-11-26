"""What an identity learns, by default and without a switch.

Skills are SKILL.md-compatible folders (agentskills.io: a name, a one-line description and a
body) that also hold our program and its test: `skills/<name>/SKILL.md`, `program.py`,
`test.py` in the identity folder. A skill it learns lives in its learning library
(library/skills/<name>.py with tests/<name>.py: the core's learning library, its evidence
and its versions) and its folder is written beside it; someone else's SKILL.md installs as a
skill with instructions and no program, at evidence "proposed". Context holds only names and
descriptions; the full text is read when used.

Evidence levels: proposed, own test passed, replay passed, effective. "Effective" means a
better score on development seeds where an environment is scored per episode; elsewhere a
skill is promoted after PROMOTE_USES uses with at least PROMOTE_RATE ending done. The
library's demotion rule stays (after 3 uses, under 25% success goes back to proposed).
Admission follows what the environment declares about itself: in an environment with outside
consequences a new skill is called only by the model by hand, and the tree may call it only
once it is effective; where the environment can save state it tests itself on a copy.
Anything unused for ARCHIVE_DAYS is archived and can be restored.

Learning has two beats. When a turn of a chat ends and no new event comes for REVIEW_QUIET
seconds, a background review proposes at most one new thing (a skill with its test, a
reaction for the tree, a memory, or practice). Every day at 0:30 dreaming merges duplicates,
archives what is unused, turns what it often does by hand into a skill, and writes the day's
summary. Both may use learning.review_model and count toward the daily limit.

learning.mode (per identity): on (new learning takes effect at once and can be undone),
review_first (it waits for the owner), frozen (use without learning), off (nothing learned
and nothing learned loaded); replay_always stays as an advanced option."""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from harness.sdk import SpendingLimit, atomic_write
from .chats import MAIN
from .state import read, save

MODES = ("on", "review_first", "frozen", "off", "replay_always")
PROMOTE_USES, PROMOTE_RATE = 5, 0.8
ARCHIVE_DAYS = 30
REVIEW_QUIET = 600
DREAM_AT = (0, 30)
TEST_SECONDS = 120

REVIEW = """You review a stretch of your own work, in the background, after it ended. Propose at most one new
thing worth keeping, or nothing. Return one JSON object:
{"propose":"skill","name":"snake_case_name","description":"one line: when to use it","body":"how to do it, for
SKILL.md","code":"Python defining a function named like the skill","test":"Python that imports nothing from
outside the standard library, calls the function and raises when it does not work"}
{"propose":"reaction","name":"short","about":"condition -> answer","when":CONDITION,"do":ANSWER,"under":null}
{"propose":"memory","key":"specific fact","text":"what to remember"}
{"propose":"practice","what":"what you did badly and want to practise","minutes":20}
{"propose":"nothing","why":"..."}
A skill records a reusable way of doing something, not a one-off change: it must help again in a different
situation of the same kind. A reaction is only for an objective condition needed even when you are passive
(CONDITION and ANSWER as in your tree). Do not propose what is already in your skills or tree."""


def _slug(name) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(name).lower()).strip("_")[:60] or "skill"


def skill_md(name, description, body) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body.strip()}\n"


def parse_skill_md(text) -> dict:
    """{name, description, body} of a SKILL.md. Its front matter is read as the skills of other
    products write it: `key: value` on a line, a value that goes on over indented lines, and
    a block (`key: >` folded into one line, `key: |` kept as lines)."""
    head, body = {}, text
    if text.startswith("---"):
        _, _, rest = text.partition("---")
        front, _, body = rest.partition("\n---")
        key, block = None, None
        for line in front.splitlines():
            if line[:1] in (" ", "\t") and key:
                # More of the value above.
                piece = line.strip()
                joined = "\n" if block == "|" else " "
                head[key] = (head[key] + joined + piece) if head[key] else piece
                continue
            name, found, value = line.partition(":")
            if not found or not name.strip() or name.lstrip().startswith("#"):
                continue
            key, value = name.strip(), value.strip()
            block = value[:1] if value[:1] in (">", "|") and value.strip(">|+-0123456789 ") == "" else None
            head[key] = "" if block else value.strip('"').strip("'")
    if not head.get("name"):
        raise ValueError("a SKILL.md names its skill (name: in its front matter)")
    return {"name": head["name"], "description": head.get("description", ""), "body": body.strip()}


def run_test(code, test, *, name=None, folder=None) -> dict:
    """The skill's own test, in a fresh interpreter: {ok, output, seconds}. The program is
    importable as `skill` and by the skill's own name."""
    with tempfile.TemporaryDirectory() as root:
        Path(root, "skill.py").write_text(code, encoding="utf-8")
        if name and name != "skill":
            Path(root, f"{name}.py").write_text(code, encoding="utf-8")
        Path(root, "check.py").write_text("from skill import *\n" + test, encoding="utf-8")
        started = time.time()
        try:
            done = subprocess.run([sys.executable, "-E", "-s", "check.py"], cwd=root, capture_output=True, text=True,
                                  timeout=TEST_SECONDS, encoding="utf-8", errors="replace")
            ok, output = done.returncode == 0, (done.stdout + done.stderr)[-2000:]
        except subprocess.TimeoutExpired:
            ok, output = False, "the test ran out of time"
    return {"ok": ok, "output": output, "seconds": round(time.time() - started, 2), "method": "own_test"}


class Learning:
    """One identity's learning (its life's)."""

    def __init__(self, life):
        self.life = life
        self.identity = life.identity
        self.skills_root = self.identity.directory / "skills"
        self.skills_root.mkdir(exist_ok=True)
        self.state_path = self.identity.directory / "learning-state.json"
        self.state = read(self.state_path, {})
        if "dreamed" not in self.state:
            # The first night it lives through is the first it dreams.
            self.state["dreamed"] = datetime.fromtimestamp(life.clock()).date().isoformat()
            self._save()
        self.reviews = {}            # chat -> when its last turn ended
        self._lock = threading.RLock()

    def _save(self) -> None:
        save(self.state_path, self.state)

    def mode(self) -> str:
        own = (self.identity.settings_section("learning") or {}).get("mode")
        if own in MODES:
            return own
        try:
            from harness.sdk import Settings, data

            value = Settings(data()).get().get("learning", {}).get("mode", "on")
        except Exception:
            value = "on"
        return value if value in MODES else "on"

    def learner(self):
        from harness.runtime.learning.learner import Learner

        return Learner(self.identity.library, {"path": str(self.identity.library), "learn": "on"}, create=True)

    # Beats.

    def turn_ended(self, chat) -> None:
        if self.mode() in ("on", "review_first", "replay_always"):
            self.reviews[chat] = self.life.clock()

    def tick(self, now) -> None:
        for chat, ended in list(self.reviews.items()):
            last = max([r["time"] for r in self.life.chats.read(chat, limit=5)] or [ended])
            if chat in self.life.busy or now - max(ended, last) < REVIEW_QUIET:
                continue
            self.reviews.pop(chat, None)
            threading.Thread(target=self._quietly, args=(self.review, chat), daemon=True).start()
        moment = datetime.fromtimestamp(now)
        today = moment.date().isoformat()
        if (moment.hour, moment.minute) >= DREAM_AT and self.state.get("dreamed") != today:
            self.state["dreamed"] = today
            self._save()
            threading.Thread(target=self._quietly, args=(self.dream,), daemon=True).start()

    def _quietly(self, function, *args):
        try:
            function(*args)
        except SpendingLimit as error:
            self.life.chats.record(MAIN, "deferred", reason=f"learning waits: {error}")
        except Exception as error:
            self.life.chats.record(MAIN, "error", error=f"learning: {type(error).__name__}: {error}")

    def _model(self):
        from .cli import model as chat_model

        chosen = self.identity.effective().get("learning.review_model") or self.identity.model_entry()
        return self.life.review_model() if hasattr(self.life, "review_model") and self.life.review_model else chat_model(chosen)

    def _ask(self, system, content, chat) -> dict:
        account = self.identity.account()
        model = self._model()
        refused = account.refusal(model, whose="own")
        if refused:
            raise SpendingLimit(refused)
        reply = model.complete(system, [{"role": "user", "content": content}])
        account.charge(model, reply.usage, {"kind": "learning", "id": chat, "whose": "own"})
        text = reply.text.strip()
        found = re.search(r"\{.*\}", text, re.S)
        return json.loads(found.group(0)) if found else {"propose": "nothing"}

    def review(self, chat) -> dict:
        """Look back at a chat's last turn and propose at most one new thing."""
        records = [r for r in self.life.chats.read(chat, limit=120)
                   if r["event"] not in ("model_request", "model_reply", "queued", "wake_queued", "turn_started")]
        if not records:
            return {"propose": "nothing"}
        known = {"skills": [row["name"] for row in self.skills()], "tree": self.life.tree.describe()}
        content = json.dumps({"what_happened": records[-80:], "you_know": known}, ensure_ascii=False)[-60000:]
        proposal = self._ask(REVIEW, content, chat)
        return self.take(chat, proposal)

    def take(self, chat, proposal) -> dict:
        kind = proposal.get("propose")
        if kind == "skill":
            return self.learn_skill(chat, proposal)
        if kind == "reaction":
            try:
                row = self.life.tree.add(str(proposal.get("name") or ""), proposal.get("when"), proposal.get("do"),
                                         under=proposal.get("under"), about=str(proposal.get("about") or ""),
                                         source="learned", evidence="proposed",
                                         origin={"chat": chat, "time": self.life.clock()})
            except (ValueError, TypeError) as error:
                return {"propose": "nothing", "why": str(error)}
            if self.mode() == "review_first":
                self.life.tree.enable(row["name"], False)
            self.life.chats.record(chat, "learned", kind="reaction", name=row["name"], evidence="proposed",
                                   under=row["under"])
            return {"learned": row["name"]}
        if kind == "memory" and proposal.get("key") and proposal.get("text"):
            self.identity.remember(str(proposal["key"])[:160], str(proposal["text"])[:1200], source=chat,
                                   expected=self.identity.memory()["revision"])
            self.life.chats.record(chat, "learned", kind="memory", name=proposal["key"])
            return {"learned": proposal["key"]}
        if kind == "practice" and proposal.get("what") and self.life.proactive_allows("learn"):
            self.life.intend(chat, {"what": f"practise: {proposal['what']}",
                                    "in_minutes": 60})
            return {"practice": proposal["what"]}
        return {"propose": "nothing"}

    def learn_skill(self, chat, proposal) -> dict:
        """A skill with its program and test: its own test runs first; passed, it takes effect
        at once (or waits for the owner with review_first)."""
        from harness.runtime.learning.learner import candidate

        name = _slug(proposal.get("name"))
        code, test = str(proposal.get("code") or ""), str(proposal.get("test") or "")
        if not code.strip() or not test.strip():
            return {"propose": "nothing", "why": "a skill needs its program and its test"}
        try:
            item = candidate("skill", name, code, test, summary=str(proposal.get("description") or "")[:300],
                             source="passive", origin="model")
        except ValueError as error:
            return {"propose": "nothing", "why": str(error)}
        result = run_test(code, test, name=name)
        learner = self.learner()
        if not result["ok"]:
            self.life.chats.record(chat, "learned", kind="skill", name=name, evidence="failed own test",
                                   note=result["output"][-300:])
            return {"failed": name, "test": result}
        evidence = "proposed" if self.mode() == "review_first" else "provisional"
        learner.admit(item, evidence, test_run={"ok": True, "method": "own_test", "output": result["output"][-500:]},
                      why="its own test passed", pending=evidence == "proposed")
        folder = self.skills_root / name
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write(folder / "SKILL.md", skill_md(name, proposal.get("description") or name, proposal.get("body") or ""))
        atomic_write(folder / "program.py", code.strip() + "\n")
        atomic_write(folder / "test.py", test.strip() + "\n")
        save(folder / "origin.json", {"chat": chat, "time": self.life.clock(), "source": "learned"})
        level = "own test passed" if evidence == "provisional" else "proposed (waits for review)"
        self.life.chats.record(chat, "learned", kind="skill", name=name, evidence=level,
                               note=str(proposal.get("description") or "")[:200])
        return {"learned": name, "evidence": evidence}

    # Outside skills.

    def install(self, source) -> dict:
        """Someone else's SKILL.md (a file, or a folder holding one): a skill with instructions and
        no program, at evidence proposed."""
        path = Path(source)
        text_path = path / "SKILL.md" if path.is_dir() else path
        parsed = parse_skill_md(text_path.read_text(encoding="utf-8"))
        name = _slug(parsed["name"])
        folder = self.skills_root / name
        if path.is_dir():
            shutil.copytree(path, folder, dirs_exist_ok=True)
        else:
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, folder / "SKILL.md")
        save(folder / "origin.json", {"source": "installed", "from": str(source), "time": self.life.clock(),
                                      "evidence": "proposed"})
        self.life.chats.record(MAIN, "learned", kind="skill", name=name, evidence="proposed",
                               note="installed from a SKILL.md")
        return {"installed": name, "evidence": "proposed"}

    def read_skill(self, name) -> str:
        folder = self.skills_root / _slug(name)
        if not (folder / "SKILL.md").exists():
            raise ValueError(f"no skill {name!r}")
        return (folder / "SKILL.md").read_text(encoding="utf-8")

    # What it learned.

    def skills(self) -> list:
        """Every skill: learned ones from the library (with evidence, uses, success) and
        installed SKILL.md ones, with where each came from."""
        rows = {}
        if self.mode() != "off":
            for entry in self.learner().entries():
                if entry["section"] != "skills":
                    continue
                name = entry["name"]
                if not entry.get("waiting") and not (self.identity.library / entry["file"]).exists():
                    continue  # archived (listed below) or removed
                origin = read(self.skills_root / name / "origin.json", {})
                rows[name] = {"name": name, "description": entry.get("summary"), "evidence": _level(entry),
                              "uses": entry.get("uses", 0), "success_rate": entry.get("success_rate"),
                              "loaded": entry.get("loaded"), "waiting": entry.get("waiting"), "file": entry["file"],
                              "source": origin or {"source": entry.get("origin")}, "archived": False}
        for folder in sorted(self.skills_root.iterdir()) if self.skills_root.is_dir() else ():
            if folder.name in rows or not (folder / "SKILL.md").exists():
                continue
            try:
                parsed = parse_skill_md((folder / "SKILL.md").read_text(encoding="utf-8"))
            except ValueError:
                continue
            origin = read(folder / "origin.json", {})
            rows[folder.name] = {"name": folder.name, "description": parsed["description"],
                                 "evidence": origin.get("evidence", "proposed"), "uses": 0, "success_rate": None,
                                 "loaded": self.mode() != "off", "instructions_only": not (folder / "program.py").exists(),
                                 "source": origin, "archived": False}
        for path in sorted((self.identity.library / "archive" / "skills").glob("*.py")) \
                if (self.identity.library / "archive" / "skills").is_dir() else ():
            rows.setdefault(path.stem, {"name": path.stem, "evidence": "archived", "archived": True, "uses": 0,
                                        "source": read(self.skills_root / path.stem / "origin.json", {})})
        return sorted(rows.values(), key=lambda row: row["name"])

    def notes(self, chat) -> str:
        """Names and descriptions of its skills, for the model (the full text when used)."""
        if self.mode() == "off":
            return ""
        rows = [row for row in self.skills() if not row.get("archived") and row.get("loaded", True)]
        if not rows:
            return ""
        return "Your skills (read one with {\"action\":\"read_skill\",\"name\":...}):\n" + "\n".join(
            f"- {row['name']}: {row.get('description') or ''} [{row['evidence']}]" for row in rows[:60])

    def undo(self, name) -> dict:
        """Back to the previous version, or, with none, no longer loaded."""
        learner = self.learner()
        key = f"skills/{_slug(name)}.py"
        row = learner.index().get(key) or {}
        previous = [h for h in row.get("history") or [] if h.get("revision") and h.get("revision") != row.get("revision")]
        if previous:
            from harness.runtime.learning.library import Revision

            item = Revision.read(learner.directory, previous[-1]["revision"])
            atomic_write(learner.directory / "skills" / f"{_slug(name)}.py", item.source)
            learner.grade(key, row.get("evidence", "provisional"), why="undone to the previous version")
            result = {"undone": name, "to": previous[-1]["revision"]}
        else:
            learner.remove(key, why="undone by the owner")
            shutil.rmtree(self.skills_root / _slug(name), ignore_errors=True)
            result = {"undone": name, "removed": True}
        self.life.chats.record(MAIN, "learned", kind="skill", name=name, evidence="undone")
        return result

    def diff(self, name) -> dict:
        """What changed in a skill: its versions, newest first, and the text of the last change."""
        import difflib

        learner = self.learner()
        key = f"skills/{_slug(name)}.py"
        row = learner.index().get(key) or {}
        revisions = [h["revision"] for h in row.get("history") or [] if h.get("revision")]
        current = (self.identity.library / key).read_text(encoding="utf-8") if (self.identity.library / key).exists() else ""
        previous = ""
        older = [r for r in revisions if r != row.get("revision")]
        if older:
            from harness.runtime.learning.library import Revision

            previous = Revision.read(learner.directory, older[-1]).source
        text = "".join(difflib.unified_diff(previous.splitlines(True), current.splitlines(True),
                                            "previous", "current"))
        return {"name": name, "history": row.get("history") or [], "diff": text}

    def delete(self, name) -> dict:
        """Remove a skill for good (its folder too)."""
        self.learner().remove(f"skills/{_slug(name)}.py", why="deleted by the owner")
        shutil.rmtree(self.skills_root / _slug(name), ignore_errors=True)
        self.life.chats.record(MAIN, "learned", kind="skill", name=name, evidence="deleted")
        return {"deleted": name}

    def approve(self, name) -> dict:
        """With review_first: the owner lets a waiting skill take effect."""
        learner = self.learner()
        key = f"skills/{_slug(name)}.py"
        item = learner.candidate_from(f"candidates/{key}", pending=True) or learner.candidate_from(key)
        if item is None:
            raise ValueError(f"no skill {name!r} waits")
        if item.test:
            result = run_test(item.text, item.test, name=_slug(name))
            if not result["ok"]:
                return {"approved": False, "test": result}
        learner.admit(item, "provisional", why="the owner approved it and its own test passed",
                      test_run={"ok": True, "method": "own_test"} if item.test else None)
        return {"approved": name}

    def restore(self, name) -> dict:
        archive = self.identity.library / "archive"
        for section in ("skills", "tests"):
            source = archive / section / f"{_slug(name)}.py"
            if source.exists():
                (self.identity.library / section).mkdir(exist_ok=True)
                shutil.move(str(source), str(self.identity.library / section / source.name))
        return {"restored": name}

    # Dreaming.

    def promote(self) -> list:
        """Effective after PROMOTE_USES uses with at least PROMOTE_RATE done."""
        learner = self.learner()
        promoted = []
        for entry in learner.entries():
            if entry["section"] != "skills" or entry["evidence"] not in ("provisional", "replayed"):
                continue
            uses, rate = entry.get("uses") or 0, entry.get("success_rate")
            if uses >= PROMOTE_USES and rate is not None and rate >= PROMOTE_RATE:
                learner.grade(entry["file"], "validated", why=f"{uses} uses, {rate:.0%} done")
                promoted.append(entry["name"])
                self.life.chats.record(MAIN, "learned", kind="skill", name=entry["name"], evidence="effective",
                                       note=f"{uses} uses, {rate:.0%} done")
        return promoted

    def archive(self, now) -> list:
        """Skills unused for ARCHIVE_DAYS go to library/archive (restorable)."""
        archived = []
        index = self.learner().index()
        for path in sorted((self.identity.library / "skills").glob("*.py")):
            row = index.get(f"skills/{path.name}") or {}
            # The last time it was used, else when it was admitted.
            last = max([row.get("admitted_at") or 0,
                        *[(u or {}).get("last_at", 0) for u in (row.get("uses_by_revision") or {}).values()]])                 or path.stat().st_mtime
            if now - last > ARCHIVE_DAYS * 86400:
                for section in ("skills", "tests"):
                    source = self.identity.library / section / path.name
                    if source.exists():
                        (self.identity.library / "archive" / section).mkdir(parents=True, exist_ok=True)
                        shutil.move(str(source), str(self.identity.library / "archive" / section / path.name))
                archived.append(path.stem)
        return archived

    def merge(self) -> list:
        """Skills with the same program: the later ones go."""
        seen, gone = {}, []
        learner = self.learner()
        for path in sorted((self.identity.library / "skills").glob("*.py"), key=lambda p: p.stat().st_mtime):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in seen:
                learner.remove(f"skills/{path.name}", why=f"the same as {seen[digest]}")
                gone.append(path.stem)
            else:
                seen[digest] = path.stem
        return gone

    def dream(self) -> dict:
        now = self.life.clock()
        result = {"merged": self.merge(), "archived": self.archive(now), "promoted": self.promote()}
        # What it often did by hand today becomes a skill: one review over the day's turns.
        if self.mode() in ("on", "review_first") and self.life.proactive_allows("learn"):
            turns = [r for r in self.life.calendar.happened(now - 86400, now) if r.get("kind") == "turn"]
            if len(turns) >= 2:
                content = json.dumps({"what_happened": turns[-60:], "you_know": {
                    "skills": [row["name"] for row in self.skills()], "tree": self.life.tree.describe()}},
                    ensure_ascii=False)
                proposal = self._ask(REVIEW + "\nLook for something you did by hand several times today.", content, MAIN)
                result["proposal"] = self.take(MAIN, proposal)
        summary = self.life.calendar.summary(now - 86400)
        dreams = self.identity.directory / "DREAMS.md"
        old = dreams.read_text(encoding="utf-8") if dreams.exists() else "# Dreams\n"
        lines = [f"\n## Dreaming {datetime.fromtimestamp(now).date().isoformat()}\n", summary["text"]]
        for key, label in (("merged", "Merged"), ("archived", "Archived"), ("promoted", "Now effective")):
            if result[key]:
                lines.append(f"- {label}: {', '.join(result[key])}")
        atomic_write(dreams, old.rstrip("\n") + "\n" + "\n".join(lines) + "\n")
        self.life.chats.record(MAIN, "dreamed", **{k: v for k, v in result.items() if k != "proposal"})
        return result


def _level(entry) -> str:
    if entry.get("waiting"):
        return "proposed"
    return {"provisional": "own_test", "replayed": "replayed", "validated": "effective"}.get(entry["evidence"],
                                                                                         entry["evidence"])
