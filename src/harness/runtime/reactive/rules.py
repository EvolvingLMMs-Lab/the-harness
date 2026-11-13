"""How reactive code is called: the conditions of the tree's nodes (runtime/reactive/tree.py),
controllers and until predicates run restricted (no file, network, process or input
operation) and within a time budget of the control period."""

from contextlib import contextmanager
import signal
import sys
import threading
import time
from typing import Any, Callable



# Guard actions a session takes itself: every embodiment stops and holds; an embodiment
# may add its own (opening a gripper, backing off).
STOP, HOLD, OPEN_GRIPPER, BACK_OFF = "stop", "hold", "open_gripper", "back_off"
BUILTIN_ACTIONS = (STOP, HOLD, OPEN_GRIPPER)

_FORBIDDEN_PREFIXES = (
    "open", "os.", "shutil.", "socket.", "subprocess.", "urllib.", "http.", "ftplib.",
    "smtplib.", "ctypes.", "sqlite3.", "webbrowser.", "pty.", "fcntl.", "time.sleep", "harness.model_request", "harness.execution",
)
_restricted = threading.local()
# Looked up at import, before an isolated kernel refuses ctypes symbol lookups
# (runtime/safety/isolation.py): the watchdog raises overruns with it.
try:
    import ctypes

    _set_async_exc = ctypes.pythonapi.PyThreadState_SetAsyncExc
except (ImportError, AttributeError, PermissionError):
    _set_async_exc = None


class ReactiveFault(Exception):
    """Reactive code that failed, identified by source and reason."""

    def __init__(self, source: str, reason: str):
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason


class NotJudged(Exception):
    """The control period's budget was used up before this reactive function could be
    called. It was not called: no fault of its own, and its turn comes in the next period."""


def _audit(event: str, _args) -> None:
    if getattr(_restricted, "active", False) and event.startswith(_FORBIDDEN_PREFIXES):
        raise PermissionError(f"reactive code may not perform '{event}'")


sys.addaudithook(_audit)


class _Overrun(BaseException):
    """Raised by the timer; a BaseException so broad excepts in user code miss it."""


class _Watchdog:
    """Interrupt Python callbacks at their deadline off the main thread."""

    def __init__(self):
        self._changed = threading.Condition()
        self._calls = {}  # token -> [deadline, thread id, fired]
        self._count = 0
        self._thread = None

    def arm(self, seconds: float) -> int:
        with self._changed:
            self._count += 1
            self._calls[self._count] = [time.monotonic() + seconds, threading.get_ident(), False]
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="harness-reactive-watchdog", daemon=True)
                self._thread.start()
            self._changed.notify()
            return self._count

    def disarm(self, token: int) -> None:
        with self._changed:
            call = self._calls.pop(token)
        if call[2]:
            # It fired as the call returned: take back the overrun not raised yet.
            restricted, _restricted.active = getattr(_restricted, "active", False), False
            try:
                _raise_in(call[1], None)
            finally:
                _restricted.active = restricted

    def _run(self):
        with self._changed:
            while True:
                now = time.monotonic()
                for call in self._calls.values():
                    if not call[2] and call[0] <= now:
                        call[2] = True
                        _raise_in(call[1], _Overrun)
                waiting = [call[0] for call in self._calls.values() if not call[2]]
                self._changed.wait(min(waiting) - now if waiting else None)


def _raise_in(thread_id: int, exception) -> None:
    """Raise `exception` in thread `thread_id` at its next bytecode (None: take one back)."""
    if _set_async_exc is not None:
        _set_async_exc(ctypes.c_ulong(thread_id), ctypes.py_object(exception) if exception is not None else None)


_watchdog = _Watchdog()


@contextmanager
def _deadline(seconds: float):
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        token = _watchdog.arm(seconds)
        try:
            yield
        finally:
            _watchdog.disarm(token)
        return

    def expire(_signum, _frame):
        raise _Overrun()

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def call_reactive(source: str, function: Callable, *args, budget_seconds: float, late=None) -> Any:
    """Run one reactive function under the audit restriction and time budget. NotJudged when
    the period's budget was used up before it. One that takes more than its budget is a
    ReactiveFault, unless the caller takes that itself: `late(seconds)` is then called (the
    tree of reflexes counts such periods: tree.py), and the result is returned, or, of one
    that was ended at the hard limit (four times the budget), NotJudged raised."""
    if getattr(_restricted, "active", False):
        return function(*args)
    allowance = getattr(_restricted, "allowance", None)
    whole = budget_seconds
    if allowance is not None:
        budget_seconds = min(budget_seconds, allowance[0])
        if budget_seconds <= 0:
            raise NotJudged(source)
    started = time.perf_counter()
    _restricted.active = True
    try:
        # The hard timer is looser than the budget so the soft check reports the overrun.
        with _deadline(max(budget_seconds * 4, 0.001)):
            result = function(*args)
    except _Overrun:
        if late is None:
            raise ReactiveFault(source, f"exceeded {budget_seconds * 1000:.1f} ms tick budget") from None
        late(time.perf_counter() - started)
        raise NotJudged(source) from None
    except ReactiveFault:
        raise
    except Exception as error:
        raise ReactiveFault(source, f"{type(error).__name__}: {error}") from None
    finally:
        _restricted.active = False
        elapsed = time.perf_counter() - started
        if allowance is not None:
            allowance[0] -= elapsed
    if elapsed > budget_seconds:
        if late is None:
            raise ReactiveFault(source, f"took {elapsed * 1000:.1f} ms; budget is {budget_seconds * 1000:.1f} ms")
        if elapsed > whole:
            # (Over what was left of the period only: the ones before it used that up.)
            late(elapsed)
    return result


@contextmanager
def period(budget_seconds):
    """One control period: the reactive calls in it share `budget_seconds`."""
    previous = getattr(_restricted, "allowance", None)
    _restricted.allowance = [budget_seconds]
    try:
        yield
    finally:
        _restricted.allowance = previous
