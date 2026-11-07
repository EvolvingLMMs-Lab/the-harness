"""Desktop and browser bindings inside the isolated proposal kernel."""

from functools import partial

from harness.sdk import ProgramFinished


class ManagedProgram:
    def __init__(self, options, propose):
        self.namespace = {name: partial(propose, name) for name in options["operations"]}

        def show(observation=None, caption=None):
            return propose("show", caption=caption)

        self.namespace.update({"finish": _finish, "show": show, "__wrap_up__": lambda: None,
                               "SCREEN": tuple(options["screen"]), "CONTROL_HZ": options["hz"]})

    def drain(self):
        return {}

    def close(self):
        pass


def _finish(summary=""):
    raise ProgramFinished(str(summary)[:8000])
