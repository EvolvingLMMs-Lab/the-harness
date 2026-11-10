"""Another environment taken into a running conversation (use_environment).

A conversation starts in one environment, whose session is the kernel's and whose calls
are the program's plain names. When a step cannot be done there, the model asks for
another kind (skills/environments): the session host asks the user as their settings say,
takes a workspace of that kind and answers with what its session needs. The kernel then
builds that kind's session beside its own, each with its tick (runtime/tick.py) and its
entries, and gives programs its calls under the kind's name:

    desktop.click(x, y)      project.run_command("npm test")      browser.read_page()

The attached session never connects to its worker itself. Every call goes over the
kernel's connection to the host (RelayedEnvironment), which holds the worker's key, checks
the call as it checks the conversation's own and keeps the user's approvals: a step with
the real mouse and keyboard stays under the physical-input policy after the desktop is
attached. So the kernel's network guard is as it was when the kernel started.
"""

from harness.runtime.events import EpisodeEnded
from harness.runtime.execution import control

# Names of an attached session that programs do not get: ending the task is the
# conversation's own finish(), and library entries are the conversation's.
WITHHELD = ("finish", "library", "ClosedLoop")


class RelayedEnvironment:
    """An attached environment's worker, reached through the session host."""

    approval_key = None
    program_controls = frozenset()

    def __init__(self, name: str, timeout: float = 300.0, host_controls=()):
        self.name = name
        self.timeout = float(timeout)
        self.host_controls = frozenset(host_controls)

    def call(self, name: str, **arguments):
        return control.host_call({"environment": self.name, "name": name, "arguments": arguments}, self.timeout)

    def close(self) -> None:
        pass


class Attached:
    """The calls of an attached environment as attributes: desktop.click, project.read_file.
    A call made after it was released, or after its episode ended, says so."""

    def __init__(self, name: str, session):
        calls = {key: value for key, value in session.namespace.items()
                 if not key.startswith("_") and key not in WITHHELD}
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_calls", calls)
        object.__setattr__(self, "_live", True)

    def __getattr__(self, key):
        calls = object.__getattribute__(self, "_calls")
        name = object.__getattribute__(self, "_name")
        if key not in calls:
            raise AttributeError(f"{name} has no call {key}; it has {', '.join(sorted(calls))}")
        value = calls[key]
        if not callable(value):
            return value

        def call(*args, **kwargs):
            if not object.__getattribute__(self, "_live"):
                raise RuntimeError(f"{name} was released; use_environment({name!r}, why) takes it again")
            try:
                return value(*args, **kwargs)
            except EpisodeEnded:
                # Its worker ended its episode (a step limit): this conversation goes on.
                raise RuntimeError(f"{name} has ended; release_environment({name!r}) gives it back") from None

        call.__name__ = key
        call.__doc__ = getattr(value, "__doc__", None)
        return call

    def __setattr__(self, key, value):
        raise AttributeError("an attached environment's calls cannot be rebound")

    def __dir__(self):
        return sorted(object.__getattribute__(self, "_calls"))

    def __repr__(self):
        name = object.__getattribute__(self, "_name")
        return f"<environment {name}: {', '.join(dir(self))}>"


def build(name: str, given: dict):
    """The session of an attached environment from what the host answered: {"embodiment",
    "knowledge", "episode_id", "skills", "timeout_seconds", "host_controls", and the keys a
    session of that kind reads}. Its worker is reached through the host."""
    from harness.runtime.execution.session import session_class

    environment = RelayedEnvironment(name, given.get("timeout_seconds", 300.0), given.get("host_controls", ()))
    return session_class(given["embodiment"], given.get("knowledge"))(dict(given), environment=environment)
