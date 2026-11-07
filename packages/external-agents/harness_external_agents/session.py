"""Conversation contract for user-controlled external sessions."""

from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
import secrets
import threading
import time
from types import SimpleNamespace

from harness.sdk import Trace, atomic_write


@dataclass
class Permission:
    id: str
    turn: int
    deadline: float
    tool: str
    description: str
    options: dict
    reply: object
    timer: threading.Timer


class Session:
    """One host-owned conversation, with serialized state and one-use permission replies."""

    def __init__(self, directory, adapter, cwd, model=None, effort=None, *, append=False):
        self.directory = Path(directory)
        self.trace = Trace(self.directory, append=append)
        self.cwd = cwd
        self.instruction = ""
        self.identity = None
        self.identity_changed = lambda: None
        self.session_metadata = {"kind": adapter.split(":", 1)[0], "adapter_id": adapter,
                                 "source": "managed", "owner": "harness",
                                 "project": str(cwd) if cwd else None, "cwd": str(cwd) if cwd else None}
        self.config = SimpleNamespace(main={"model": model, "reasoning_effort": effort}, runtime={})
        self.summary = None
        self.status = "IDLE"
        self.lock = threading.RLock()
        self.turn = 0
        self.generation = secrets.token_hex(12)
        self.trace.context = lambda: {"turn": self.turn, "generation": self.generation}
        self.pending = deque()
        self.closing = False
        self.ended = False
        self.transport_stopped = False
        self._transport_cleanup = threading.Lock()
        self.controls = {"close": True}
        self.project = None

    @property
    def capabilities(self):
        project = ({"diff": bool(self.project.directory),
                    "merge": bool(self.transport_stopped and self.project.worktree and self.project.ref),
                    "discard": bool(self.transport_stopped and self.project.worktree)} if self.project else {})
        return {**project, **({} if self.ended else {**self.controls, "approve": bool(self.pending)})}

    def diff(self):
        return self.project.diff()

    def merge(self):
        with self.lock:
            if not self.transport_stopped:
                raise ValueError("close the session before merging")
            return self.project.merge()

    def discard(self):
        with self.lock:
            if not self.transport_stopped:
                raise ValueError("close the session before discarding its worktree")
            result = self.project.discard()
            self.session_metadata.update(self.project.metadata())
            self.identity_changed()
            return result

    @property
    def approval_id(self):
        try:
            return self.pending[0].id
        except IndexError:
            return None

    def state(self, status, reason, **detail):
        self.status = status
        self.trace.emit("state", status=status, reason=reason, **detail)

    def start(self, text, files):
        with self.lock:
            (self.directory / "summary.json").unlink(missing_ok=True)
            self.trace.emit("external_connection" if self.trace.sequence else "reset")
            self.state("RUNNING", "connecting to the external agent")
            threading.Thread(target=self._open, args=(text, files), daemon=True,
                             name=self.session_metadata["adapter_id"]).start()

    def _open(self, text, files):
        try:
            self.open(text, files)
        except Exception as error:
            self.fail(error)

    def fail(self, error):
        with self.lock:
            if self.ended:
                return
            if not self.closing:
                self.trace.emit("error", message=str(error))
            self.end("FINISHED" if self.closing else "ERROR")
        self.stop_transport()

    def begin(self, text):
        self.turn += 1
        self.trace.emit("user_message", text=text, sender="user")
        self.state("RUNNING", "message")

    def end(self, status):
        if self.ended:
            return
        self.ended = True
        self.cancel_permissions()
        self.summary = {**(self.summary or {}), "status": {
            "FINISHED": "closed", "ERROR": "error", "INTERRUPTED": "interrupted"}[status]}
        atomic_write(self.directory / "summary.json", json.dumps(self.summary))
        self.state(status, "external session ended")

    def offer(self, tool, description, options, reply, *, seconds=120):
        """Queue an immutable decision for this turn. `reply(None)` cancels at the peer."""
        with self.lock:
            if self.closing or self.ended or self.status not in ("RUNNING", "WAITING_FOR_CONFIRMATION"):
                reply(None)
                return
            identifier = secrets.token_urlsafe(18)
            timer = threading.Timer(seconds, self.expire, args=(identifier,))
            timer.daemon = True
            item = Permission(identifier, self.turn, time.monotonic() + seconds, tool, description,
                              dict(options), reply, timer)
            self.pending.append(item)
            if len(self.pending) == 1:
                self._present_permission()
            timer.start()
            return identifier

    def _present_permission(self):
        if self.pending:
            item = self.pending[0]
            request = {"id": item.id, "tool": item.tool, "code": item.description,
                       "options": list(item.options), "expires_in": max(0, item.deadline - time.monotonic())}
            self.trace.emit("confirmation_request", **request)
            self.state("WAITING_FOR_CONFIRMATION", "approval", request=request)
        elif self.status == "WAITING_FOR_CONFIRMATION":
            self.state("RUNNING", "approval resolved")

    def _answer(self, item, choice, reason):
        was_first = item is self.pending[0]
        self.pending.remove(item)
        item.timer.cancel()
        self.trace.emit("confirmation", id=item.id, accepted=choice == "allow_once", reason=reason)
        try:
            item.reply(item.options.get(choice))
        finally:
            if was_first:
                self._present_permission()

    def expire(self, identifier):
        with self.lock:
            item = next((item for item in self.pending if item.id == identifier), None)
            if item is not None:
                self._answer(item, None, "approval expired")

    def confirm(self, accept, reason="", remember=None, *, request_id=None):
        with self.lock:
            item = self.pending[0] if self.pending else None
            if (item is None or item.id != request_id or item.turn != self.turn
                    or self.closing or self.ended or item.deadline <= time.monotonic()):
                raise ValueError("the original approval request is no longer pending")
            if remember not in (None, "once"):
                raise ValueError("external session approvals only apply once")
            choice = "allow_once" if accept else "reject_once"
            if accept and choice not in item.options:
                raise ValueError("the agent did not offer a one-time approval")
            self._answer(item, choice, reason)

    def cancel_permissions(self):
        items = list(self.pending)
        self.pending.clear()
        for item in items:
            item.timer.cancel()
            self.trace.emit("confirmation", id=item.id, accepted=False, reason="request cancelled")
            try:
                item.reply(None)
            except (OSError, RuntimeError):
                pass

    def pause(self):
        self.cancel()

    def resume(self):
        raise ValueError("send a new message after the current turn stops")

    def close(self):
        with self.lock:
            if self.ended:
                return
            self.closing = True
            self.end("FINISHED")
        self.stop_transport()

    def stop_transport(self):
        with self._transport_cleanup:
            if not self.transport_stopped:
                self.close_transport()
                self.transport_stopped = True
