"""In-context learning, in a program: the model proposes a library entry (a note, a memory
entry, a skill with its test, a reactive entry) while it works, the entry's own test runs
here, in the environment as it is, and an entry that passes is admitted to the library
(runtime/learning/learner.py) and takes effect at once: its code runs in this namespace, a memory
entry is recallable, a note joins the prompt from the next call. The same library and the
same learner as self-improvement between runs; the run's [runtime.library] settings say
whether a run learns at all (`learn = "on"`).

    library.propose(kind, name, text, test=None, summary="", attachments=None, max_seconds=120, setup=None)
    library.entries() / library.version() / library.attachment(sha256)
    ClosedLoop                          the base class of a skill: confirm, do, check, retry, reason
    sandbox(op, **arguments)            the environment's practice sandbox, in an active run that has
                                        one (else None): stages a scene through the worker

A test's `setup` runs in the sandbox before it, to stage its scene; it is kept with the test
(SETUP, at its start), and a replay where there is no sandbox (a task run) leaves such a
test alone instead of failing it.

The kernel may not write files: an admission goes to the conversation that runs the program
(a note it answers), which writes the library. A kernel without a host (a test, a script)
admits through a Learner of its own (the option `library_directory`)."""

import ast
import base64
import uuid

from harness.sdk import spans
from harness.sdk import control

from harness.sdk import ClosedLoop, Result, Stop, candidate, entry_key

# Default limit accepted for old proposal callers.
TEST_SECONDS = 120.0
# A kept test that stages its scene in the practice sandbox starts with its setup between these.
SETUP = "# setup: stages the scene in the practice sandbox"
SETUP_END = "# the test"


class LibraryApi:
    """The library as a program sees it (`library`)."""

    def __init__(self, session, given: dict):
        self._session = session
        self._given = dict(given or {})

    # -- the host ---------------------------------------------------------------------------

    def _ask(self, action, wait=True, **request):
        # A note's own kind is its first argument: an entry's kind travels as "entry".
        request = {("entry" if key == "kind" else key): value for key, value in request.items()}
        if spans.connected():
            identifier = uuid.uuid4().hex[:12]
            spans.note("library", action=action, id=identifier, wait=wait, **request)
            if not wait:
                return None
            answer = control.wait_answer(identifier)
            if answer is None:
                raise RuntimeError("the host did not answer (paused)")
            if answer.get("error"):
                raise RuntimeError(answer["error"])
            return answer.get("value")
        if not self._given.get("directory"):
            raise RuntimeError("no library in this run")
        from harness.sdk import Learner

        learner = Learner(self._given["directory"], self._given.get("settings"))
        return learner.handle({"action": action, **request}, source=learner.settings["trigger"])

    @property
    def _learning(self) -> bool:
        return (self._given.get("settings") or {}).get("learn") == "on"

    def propose(self, kind, name, text, test=None, summary="", attachments=None, max_seconds=TEST_SECONDS,
                setup=None):
        """Store a note, memory, skill or rule proposal. Executable candidates need a test
        and stay pending until a trusted host verifies their exact revision. An optional
        setup is stored with the test for the verifier. Attachments are {filename: bytes}.
        Returns {"ok", "evidence", "version", "queued"} or {"ok": False, "reason"}."""
        if not self._learning:
            return {"ok": False, "reason": "learning is off in this run: the library is frozen"}
        try:
            # The learner's checks (its kind, its name, ...), here before the test acts (the
            # host checks again).
            entry = candidate(kind, name, text, test, summary=summary, attachments=attachments)
        except ValueError as error:
            return {"ok": False, "reason": str(error)}
        if setup:
            if kind not in ("skill", "reactive") or not test:
                return {"ok": False, "reason": "setup requires an executable proposal with a test"}
            test = staged(setup, test)
        if kind in ("skill", "reactive"):
            if not test:
                return {"ok": False, "reason": f"a {kind} entry needs its test"}
            blind = blind_check(entry.text)
            if blind:
                return {"ok": False, "reason": blind}
        files = {filename: base64.b64encode(value.encode("utf-8") if isinstance(value, str) else bytes(value))
                 .decode("ascii") for filename, value in (attachments or {}).items()}
        try:
            admitted = self._ask("admit", kind=kind, name=name, text=entry.text, test=test, summary=summary, attachments=files)
        except (ValueError, RuntimeError) as error:
            return {"ok": False, "reason": str(error)}
        return {"ok": True, "evidence": admitted["evidence"], "version": admitted["version_after"],
                **({"queued": True} if not admitted.get("admitted") else {})}

    def entries(self):
        """The library's entries: [{"section", "name", "evidence", "source", "origin",
        "summary", ...}] (evidence: proposed, provisional, replayed, validated)."""
        return self._ask("entries")

    def version(self):
        """The library's version now (each admission changes it)."""
        return self._ask("version")

    def attachment(self, sha256):
        """The bytes of an attachment in the library, by its sha256."""
        return base64.b64decode(self._ask("attachment", sha256=str(sha256)))

    def record(self, name, ok, detail=None, kind="skill"):
        """How a use of an entry went in play (its uses and success rate)."""
        self._ask("record", wait=getattr(self._session, "embodiment", None) != "robot", key=entry_key(kind, name), ok=bool(ok),
                  detail=None if detail is None else str(detail)[:200])

    def __repr__(self):
        return "<library: propose(kind, name, text, test), entries(), version(), attachment(sha256), record(...)>"


def staged(setup, test) -> str:
    """A test with the setup that stages its scene in the sandbox, as it is kept."""
    return f"{SETUP}\n{str(setup).strip()}\n{SETUP_END}\n{str(test).strip()}\n"


class Sandbox:
    """The environment's practice sandbox in an active run (`sandbox`): its bench's [sandbox]
    (bench.py), each op a worker call that the worker allows only in the active run's
    episode. sandbox(op, **arguments) returns the worker's answer."""

    def __init__(self, session, given: dict):
        self._session = session
        self.what = str(given.get("what") or "")
        self.ops = dict(given.get("ops") or {})

    def __call__(self, op, **arguments):
        if op not in self.ops:
            raise ValueError(f"the sandbox's ops are {sorted(self.ops)}, not {op!r}")
        with spans.span("service", "sandbox", op=op):
            return self._session.env.call("sandbox", episode_id=self._session.episode_id, op=op, **arguments)

    def __repr__(self):
        return f"<sandbox: {self.what} ops: {', '.join(f'{op} ({what})' for op, what in self.ops.items())}>"


def blind_check(code):
    """Why a ClosedLoop of a code entry checks nothing (None when each checks something):
    its check() is missing or always True, so every try "succeeds" whatever happened. A
    text that does not parse is left to the run."""
    try:
        entry = ast.parse(code)
    except SyntaxError:
        return None
    for node in entry.body:
        if not isinstance(node, ast.ClassDef) or not any(
                getattr(base, "id", getattr(base, "attr", None)) == "ClosedLoop" for base in node.bases):
            continue
        check = next((item for item in node.body if isinstance(item, ast.FunctionDef) and item.name == "check"), None)
        body = [statement for statement in (check.body if check else []) if not (
            isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))]
        if check is None or (len(body) == 1 and isinstance(body[0], ast.Return)
                             and isinstance(body[0].value, ast.Constant) and body[0].value.value is True):
            return (f"{node.name}.check() always says True: a closed loop looks at the world after do() (the "
                    f"screen, a value it reads) and returns True or why not")
    return None


class Learning:
    def _library_api(self):
        api = self.__dict__.get("_library_api_data")
        if api is None:
            api = self.__dict__["_library_api_data"] = LibraryApi(self, getattr(self, "library_given", None) or {})
        return api

    def _sandbox(self):
        """The practice sandbox, in an active run whose environment has one; else None."""
        given = getattr(self, "sandbox_given", None) or {}
        return Sandbox(self, given) if given.get("ops") else None


def exports(session):
    return {"library": session._library_api(), "ClosedLoop": ClosedLoop, "sandbox": session._sandbox()}
