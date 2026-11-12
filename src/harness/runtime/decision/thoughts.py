"""The host's decision tick. A session owns one transport until its worker returns."""

from copy import deepcopy
from contextlib import contextmanager
import threading
import time
import uuid

from harness.core.http import Preempted, RequestCancellation
from harness.runtime.decision.model import ChatModel, ChatReply


class ThoughtCancelled(Exception):
    pass


class Thought:
    def __init__(self, role, trigger, chat, system, messages, *, timeout,
                 revision=0, origin=None, owner=None, call=None, invoke=None):
        self.id = uuid.uuid4().hex
        self.role, self.trigger = role, trigger
        self.origin, self.owner, self.revision, self.call = origin, owner, revision, call
        self.chat, self.system, self.messages = chat, system, deepcopy(messages)
        self.invoke = invoke
        self.deadline = time.monotonic() + max(0, timeout)
        self.cancellation = RequestCancellation()
        self.ready = threading.Event()
        self.reply, self.error, self.outcome = None, None, None
        self.cancelled, self.exited, self.started = False, False, False
        self.seconds = 0.0

    def back(self, timeout=None):
        return self.ready.wait(timeout)

    def wait(self):
        self.ready.wait()
        if self.cancelled:
            raise ThoughtCancelled(self.error or "The thought was superseded")
        if self.error is not None:
            raise self.error
        return self.reply

    def cancel(self, reason="The thought was superseded"):
        if not self.cancelled:
            self.cancelled = True
            self.error = ThoughtCancelled(reason)
            self.cancellation.cancel()
            self.ready.set()

    def complete(self):
        self.cancellation.check()
        if self.invoke is not None:
            return self.invoke(self)
        options = {"cancellation": self.cancellation} if isinstance(self.chat, ChatModel) else {}
        reply = self.chat.complete(self.system, self.messages, **options)
        if isinstance(reply, ChatReply):
            return reply
        return ChatReply(reply.text, usage=getattr(reply, "usage", None) or {},
                         response_id=getattr(reply, "response_id", None), seconds=getattr(reply, "seconds", 0.0),
                         reasoning=getattr(reply, "reasoning", ""))


class ThoughtQueue:
    """A condition-driven tick for decisions. Network workers only post exit receipts."""

    def __init__(self, condition, *, on_exit=None, trace=None):
        self.changed, self.on_exit, self.trace = condition, on_exit, trace
        self.pending = []
        self.active = self.receipt = self.thread = None
        self.closed = False

    def wake(self):
        with self.changed:
            if self.thread is None and not self.closed:
                self.thread = threading.Thread(target=self._tick, name="decision-tick", daemon=True)
                self.thread.start()
            self.changed.notify_all()

    def submit(self, thought):
        with self.changed:
            if self.closed:
                thought.cancel("The session has ended")
                return
            self.pending.append(thought)
            self._emit("thought_queued", thought)
            self.wake()

    def cancel_where(self, predicate, reason):
        with self.changed:
            for thought in [self.active, *self.pending]:
                if thought is not None and predicate(thought) and not thought.cancelled:
                    thought.cancel(reason)
                    self._emit("thought_cancelled", thought, reason=reason)
            self.changed.notify_all()

    def close(self):
        with self.changed:
            self.closed = True
            self.cancel_where(lambda thought: True, "The session has ended")

    def _emit(self, event, thought, **detail):
        if self.trace is not None:
            self.trace.emit(event, thought=thought.id, role=thought.role, trigger=thought.trigger,
                            owner=thought.owner, origin=thought.origin,
                            revision=thought.revision, **detail)

    def _tick(self):
        with self.changed:
            while True:
                if self.receipt is not None:
                    thought, self.receipt = self.active, None
                    self.active = None
                    thought.exited = True
                    self._emit("thought_exited", thought, seconds=thought.seconds, cancelled=thought.cancelled,
                               usage=thought.reply.usage if thought.reply is not None else None,
                               **({"result": thought.reply.text} if thought.reply is not None and thought.role != "main" else {}),
                               **({"error": str(thought.error)} if thought.error is not None else {}))
                    try:
                        if self.on_exit is not None:
                            self.on_exit(thought)
                    except Exception as error:
                        thought.error = error
                        self._emit("thought_failed", thought, error=f"{type(error).__name__}: {error}")
                    finally:
                        thought.ready.set()
                        self.changed.notify_all()
                if self.closed and self.active is None:
                    return
                now = time.monotonic()
                self.cancel_where(lambda thought: thought.deadline <= now, "Model transport deadline expired")
                self.pending[:] = [thought for thought in self.pending if not thought.cancelled]
                if self.active is None and self.pending:
                    # The model's decisions and synchronous role requests precede the observer.
                    thought = min(self.pending, key=lambda item: (item.role == "observer", item.role != "main"))
                    self.pending.remove(thought)
                    self.active = thought
                    thought.started = True
                    self._emit("thought_started", thought, deadline_in=max(0, thought.deadline - now))
                    threading.Thread(target=self._transport, args=(thought,), name="model-transport",
                                     daemon=True).start()
                deadlines = [item.deadline for item in [self.active, *self.pending]
                             if item is not None and not item.cancelled]
                self.changed.wait(max(0, min(deadlines) - time.monotonic()) if deadlines else None)

    @contextmanager
    def _span(self, thought):
        if self.trace is None or thought.role == "main":
            yield
            return
        identifier = uuid.uuid4().hex
        lane = {"reflection": "model", "verifier": "verifier", "observer": "observer"}.get(thought.role, "service")
        self.trace.emit("span_start", id=identifier, lane=lane, name=getattr(thought.chat, "model", thought.role),
                        thought=thought.id, role=thought.role, reason=thought.trigger, parent=None)
        try:
            yield
        finally:
            self.trace.emit("span_end", id=identifier)

    def _transport(self, thought):
        began = time.monotonic()
        reply, error = None, None
        try:
            with self._span(thought):
                reply = thought.complete()
        except Preempted:
            error = ThoughtCancelled("The model transport was interrupted")
        except Exception as failure:
            error = failure
        finally:
            with self.changed:
                thought.seconds = time.monotonic() - began
                thought.reply = reply
                if not thought.cancelled:
                    if time.monotonic() >= thought.deadline:
                        thought.cancel("Model transport deadline expired")
                        self._emit("thought_cancelled", thought, reason="Model transport deadline expired")
                    else:
                        thought.error = error
                self.receipt = thought.id
                self.changed.notify_all()


def think(chat, system: str, messages: list, *, role="reflection", trigger="reflect", trace=None):
    """Use the same dispatcher for offline proposals and session-bound reflection."""
    if getattr(chat, "thinks", False):
        return chat.complete(system, messages)
    queue = ThoughtQueue(threading.Condition(), trace=trace)
    try:
        thought = Thought(role, trigger, chat, system, messages, timeout=300)
        queue.submit(thought)
        return thought.wait()
    finally:
        queue.close()
