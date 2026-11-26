"""How a failure is said, the same in every frontend: what went wrong in one line
(`reason`), what to do about it (`fix`), and where the log is when there is one (`log`,
which adds to the reason and never stands for it). `code` names the kind for programs.

A Problem is raised where the failure is understood; the host's API carries it as
{"error": reason, "fix": ..., "code": ..., "log": ...} (as_dict / of), and the terminal chat,
the command line and the app's page show it from lines().

Standard library only.
"""

import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError


class Problem(RuntimeError):
    """A failure with its reason, its fix and optionally its log."""

    def __init__(self, reason: str, fix: str = "", *, code: str = "error", log=None):
        super().__init__(reason)
        self.reason, self.fix, self.code = str(reason), str(fix or ""), code
        self.log = str(log) if log else ""

    def __str__(self) -> str:
        # Read as one sentence where only str(error) is shown.
        return f"{self.reason}. {self.fix}" if self.fix else self.reason

    def as_dict(self) -> dict:
        out = {"error": self.reason, "code": self.code}
        if self.fix:
            out["fix"] = self.fix
        if self.log:
            out["log"] = self.log
        return out

    @classmethod
    def of(cls, payload: dict, default: str = "") -> "Problem":
        """The Problem an API answer {"error", "fix", "code", "log"} stands for."""
        return cls(payload.get("error") or default, payload.get("fix") or "", code=payload.get("code") or "error",
                   log=payload.get("log"))


def explain(error: BaseException) -> Problem:
    """Any error as a Problem. One that is a Problem already is itself; a failed connection
    says so; anything else keeps its own words (with its type when the words alone do not
    say what kind of thing failed)."""
    if isinstance(error, Problem):
        return error
    if isinstance(error, HTTPError):
        return Problem(f"the server answered {error.code} {error.reason}", code="http")
    if isinstance(error, (URLError, ConnectionError, TimeoutError)):
        cause = getattr(error, "reason", None) or error
        return Problem(f"no connection ({cause})", "check the network, then try again", code="network")
    text = str(error).strip()
    if isinstance(error, KeyError) or not text:
        text = f"{type(error).__name__}: {text}" if text else type(error).__name__
    return Problem(text, code=type(error).__name__)


def lines(error: BaseException) -> list[str]:
    """What a frontend shows: the reason, then the fix, then the log, each on its line."""
    problem = explain(error)
    out = [problem.reason]
    if problem.fix:
        out.append(problem.fix)
    if problem.log:
        out.append(f"log: {problem.log}")
    return out


def said(error: BaseException, program: bool = False) -> str:
    """The failure for a terminal's stderr: lines for a person, one JSON object for a
    program (which keeps the "Type: message" text programs read before)."""
    problem = explain(error)
    if program:
        return json.dumps(problem.as_dict() if isinstance(error, Problem) else
                          {"error": f"{type(error).__name__}: {error}"})
    first, *rest = lines(problem)
    return "\n".join([f"harness: {first}"] + [f"  {line}" for line in rest])


# The line of a Python traceback that names the exception.
_RAISED = re.compile(r"^(?:[A-Za-z_][\w.]*\.)?([A-Z]\w*(?:Error|Exception|Exit|Interrupt|Warning))(?::\s*(.*))?$")
# A frame of a traceback inside an installed package: .../packages/<name>/<version>-<hash>/...
_PACKAGE_FRAME = re.compile(r'File "[^"]*[\\/]packages[\\/]([A-Za-z0-9_.-]+)[\\/]')


def from_log(text: str, log=None, *, what: str = "the session host stopped while starting") -> Problem:
    """Why a process that only left a log stopped (`what` says what happened to it): the
    exception its last traceback names, and the package whose code raised it when the
    traceback passes through one."""
    raised, package = "", ""
    rows = text.splitlines()
    for index in range(len(rows) - 1, -1, -1):
        found = _RAISED.match(rows[index].strip())
        if found and not rows[index].startswith((" ", "\t")):
            raised = rows[index].strip()
            for earlier in reversed(rows[:index]):
                if earlier.startswith("Traceback"):
                    break
                frame = _PACKAGE_FRAME.search(earlier)
                if frame:
                    package = frame.group(1)
                    break
            break
    if not raised:
        tail = next((row.strip() for row in reversed(rows) if row.strip()), "")
        reason = what + (f": {tail[:300]}" if tail else " and left nothing in its log")
        return Problem(reason, "harness doctor checks this computer", code="host_exited", log=log)
    if package:
        return Problem(f"{what}, in the package {package}: {raised[:400]}",
                       f"update the package (harness install --update {package}) or remove it "
                       f"(harness remove {package}), then try again", code="host_exited", log=log)
    return Problem(f"{what}: {raised[:400]}", "harness doctor checks this computer",
                   code="host_exited", log=log)


def read_tail(path, start: int = 0, limit: int = 65536) -> str:
    """What was written to the file `path` after byte `start` (its last `limit` bytes)."""
    try:
        with Path(path).open("rb") as file:
            file.seek(0, 2)
            end = file.tell()
            file.seek(max(start if start <= end else 0, end - limit))
            return file.read().decode("utf-8", "replace")
    except OSError:
        return ""
