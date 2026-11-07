"""Trusted admission of proposals onto the existing desktop tick."""

import math
import threading

from harness.sdk import EpisodeEnded, Escalation, ExecutionTrace, Tick, input_sent

DESKTOP = ("get_state", "get_observation", "show", "click", "double_click", "right_click", "drag", "scroll",
           "type_text", "press", "wait", "windows", "use_window", "elements", "act")
BROWSER = ("navigate", "read_page")


class _Receipt:
    """Resume the original tick after the host settles its worker approval."""

    def __init__(self, conversation, session, pending, refusal):
        self.conversation, self.session, self.pending = conversation, session, pending
        self.refusal = refusal

    def ready(self):
        return self.conversation.worker_approval_ready(self.pending)

    def cancel(self, reason):
        self.conversation.cancel_worker_approval(self.pending, reason=reason)

    def finish(self, episode, step):
        workspace = self.session.env
        with workspace.lease_guard() as live:
            if not live:
                self.cancel("the managed workspace lease has ended")
                return self.refusal
            arguments = self.conversation.claim_managed_worker_retry(self.pending, episode, step)
            if arguments is None:
                return self.refusal
            try:
                receipt = workspace.retry_approved(arguments)
            except Exception:
                try:
                    receipt = workspace.approval_receipt(arguments)
                except Exception:
                    receipt = None
                if receipt is None:
                    self._record_result(arguments, None, "unknown")
                    try:
                        workspace.retire()
                    except (OSError, RuntimeError) as error:
                        self.conversation.trace.emit("cleanup_error", message=f"worker retirement: {type(error).__name__}")
                    raise RuntimeError("The approved worker input's delivery is unverified") from None
        self._record_result(arguments, receipt, "undispatched" if receipt is None else "receipt")
        return self.refusal if receipt is None else self.session._receive(arguments["command"], receipt)

    def _record_result(self, arguments, receipt, outcome):
        self.conversation.trace.emit("worker_approval_result", id=arguments["request_id"],
                                     action_id=arguments["action_id"], outcome=outcome,
                                     executed=receipt["executed"] if receipt is not None else None,
                                     worker_step=receipt["state"].get("step") if receipt is not None else None)


class _ManagedTick(Tick):
    def __init__(self, session, dispatch):
        self.dispatch = dispatch
        super().__init__(session)

    def _interruption(self, entry, tree, take=False):
        if self.dispatch.stopped():
            return RuntimeError("The managed cell was interrupted")
        return super()._interruption(entry, tree, take=take)

    def _execution_live(self, entry):
        return not self.dispatch.stopped() and super()._execution_live(entry)

    def _send(self, action, command, cameras, *, approval_id=None):
        if approval_id is not None:
            raise PermissionError("A managed workspace uses its original private approval receipt")
        workspace = self.session.env
        conversation = self.dispatch._conversation
        with workspace.lease_guard() as live:
            if not live:
                raise PermissionError("The managed workspace lease has ended")
            with conversation._condition:
                if self.dispatch.stopped():
                    raise RuntimeError("The managed cell was interrupted")
            if action is None:
                return super()._send(action, command, cameras)
            execution = action.parts[0].execution
            reply, tick = workspace.deliver(action.id, execution.execution_id, command, cameras)
            self.session._receive(command, reply)
            pending = conversation.offer_managed_worker_approval(workspace, reply, tick)
        return _Receipt(conversation, self.session, pending, reply) if pending is not None else reply


class ManagedDispatch:
    """One host cell and one proposal at a time, with a latched host stop."""

    def __init__(self, conversation, workspace, kind):
        from harness_computer.session import DesktopSession
        from skills.desktop import Desktop

        dispatch = self

        class Session(Desktop, DesktopSession):
            def _new_tick(self):
                return _ManagedTick(self, dispatch)

            def _record_receipt(self, command, receipt):
                conversation.trace.emit("input", command=command.get("type"), sent=input_sent(command),
                                        action_id=receipt["action_id"], executed=receipt["executed"],
                                        **(receipt.get("delivery") or {}))

            def _record_late_receipt(self, detail):
                conversation.trace.emit("late_receipt", **detail)

        session_type = Session
        if kind == "browser":
            from skills.browser import Browser

            class BrowserSession(Browser, Session):
                pass

            session_type = BrowserSession

        self._condition = threading.Condition()
        self._cell = self._last = self._thread = None
        self._stopped = True
        self._replied = False
        self._attachments = []
        self._conversation = conversation
        self.operations = DESKTOP + (BROWSER if kind == "browser" else ())
        self.session = session_type({"episode_id": conversation.episode, "skills": []}, environment=workspace)

    def options(self):
        return {"operations": self.operations, "screen": self.session.screen, "hz": self.session.hz}

    def stopped(self):
        return self._stopped or self._conversation._pause or self._conversation._closing

    def begin(self, cell):
        with self._condition:
            if not self._condition.wait_for(lambda: self._thread is None, timeout=125):
                raise RuntimeError("The preceding managed delivery has no final receipt")
            self._cell, self._last = cell, 0
            self._attachments = []
            self._replied = self._stopped = False

    def stop(self):
        with self._condition:
            self._stopped = True

    def accept_result(self, cell):
        with self._condition:
            if type(cell) is not int or cell != self._cell or self._replied:
                return False
            self._replied = self._stopped = True
            return True

    def close(self):
        self.stop()
        self.session.close()

    def submit(self, message, reply):
        with self._condition:
            identifier = message.get("id")
            cell = message.get("cell")
            if (type(cell) is not int or cell != self._cell or self._stopped or self._thread is not None
                    or type(identifier) is not int or identifier <= self._last):
                return False
            self._last = identifier
            self._thread = threading.Thread(target=self._run, args=(message, reply), daemon=True,
                                            name="managed-workspace-proposal")
            self._thread.start()
            return True

    def _run(self, message, reply):
        response = {"error": "The managed proposal ended"}
        try:
            response = {"value": self._perform(message.get("name"), message.get("args"), message.get("kwargs"))}
        except (Escalation, EpisodeEnded) as error:
            response = {"error": f"{error.trace.event.kind}: {error.trace.event.detail}"}
        except Exception as error:
            response = {"error": str(error)[:500] or type(error).__name__}
        finally:
            with self._condition:
                self._thread = None
                self._condition.notify_all()
        try:
            reply(response)
        except OSError:
            pass

    def _perform(self, name, args, kwargs):
        if (not isinstance(name, str) or name not in self.operations or type(args) is not list
                or type(kwargs) is not dict or len(args) + len(kwargs) > 12
                or any(type(value) not in (str, int, float, bool, type(None)) or
                       (isinstance(value, str) and len(value) > 8192)
                       or (type(value) is float and not math.isfinite(value))
                       for value in [*args, *kwargs.values()])):
            raise ValueError("Unsupported managed workspace proposal")
        with self._conversation._condition:
            if self.stopped() or self._conversation._pause or self._conversation._closing:
                raise RuntimeError("The managed cell was interrupted")
        session = self.session
        if name == "show":
            if args or set(kwargs) - {"caption"}:
                raise ValueError("Managed show() takes only an optional caption")
            session.show(session.get_observation(), kwargs.get("caption"))
            self._attachments.extend(session._attachments)
            session._attachments.clear()
            return None
        result = getattr(session, name)(*args, **kwargs)
        if name == "get_observation":
            return {"state": result.state, "images": result._urls}
        if isinstance(result, ExecutionTrace):
            return result.to_dict()
        return result

    def result(self, message):
        """Only host attachments and state are authoritative for a managed cell."""
        out = {name: message[name][:8000] for name in ("stdout", "error", "finish") if isinstance(message.get(name), str)}
        status = message.get("status")
        out["status"] = status if status in ("ok", "error", "finished") else "error"
        out["seconds"] = 0
        out["attachments"] = list(self._attachments)
        out["state"] = self.session.state
        out["events"] = []
        return out
