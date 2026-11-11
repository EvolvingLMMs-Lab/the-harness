"""Trusted admission of a managed kernel's proposals onto the desktop session and its tick."""

import importlib

from harness.sdk import Admission, Tick, input_sent

DESKTOP = ("get_state", "get_observation", "show", "click", "double_click", "right_click", "drag", "scroll",
           "type_text", "press", "wait")
BROWSER = ("navigate", "read_page", "windows", "use_window", "elements", "act")


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
            return RuntimeError("The managed program was interrupted")
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
                    raise RuntimeError("The managed program was interrupted")
            if action is None:
                return super()._send(action, command, cameras)
            execution = action.parts[0].execution
            reply, tick = workspace.deliver(action.id, execution.execution_id, command, cameras)
            self.session._receive(command, reply)
            pending = conversation.offer_managed_worker_approval(workspace, reply, tick)
        return _Receipt(conversation, self.session, pending, reply) if pending is not None else reply


class ManagedDispatch(Admission):
    """The managed desktop (or browser) session in the host, and the admission of the
    isolated kernel's proposals onto it as units (harness.sdk Admission)."""

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
            # The browser package depends on this one, so its skill is loaded by name: a
            # browser workspace exists only where that package is installed.
            Browser = importlib.import_module("skills.browser").Browser
            from skills.windowtools import WindowTools

            class BrowserSession(Browser, WindowTools, Session):
                pass

            session_type = BrowserSession

        # (The session's tick asks whether the host stopped the units: set before it is made.)
        self._conversation, self._stopped = conversation, False
        session = session_type({"episode_id": conversation.episode, "skills": []}, environment=workspace)
        super().__init__(conversation, session, DESKTOP + (BROWSER if kind == "browser" else ()))

    def options(self):
        return {"operations": self.operations, "screen": self.session.screen, "hz": self.session.hz}
