"""This computer's hooks for `harness run` (harness.bench), and the background browser's:
one task, "free", and one worker, on this machine. The browser bench runs several
(`--workspaces N`), each in a context of its own in the headless Chromes they share
(args.chromes, set by the suite); this computer's desktop runs one, and display
workspaces (the worker's workspace "display", harness run --workspace display) as many,
each on a display of its own. Standard library at import."""

from harness.sdk import Bench
from harness_computer.workspaces import CHROME_ENV


class Computer(Bench):
    def expand_tasks(self, items, layouts, deploy):
        unknown = [item for item in items if item != "free"]
        if unknown:
            raise ValueError(f"The computer bench has one task, \"free\" (the instruction is yours), not {unknown}")
        return ["free"]

    def worker_options(self, args, task, directory, slot):
        return {key: value for key, value in args.worker.items() if key in self.spec.worker}

    def slots(self, args):
        # One computer: the one the suite runs on.
        return [0]

    def workspace_slots(self, args, count):
        display = (getattr(args, "worker", None) or {}).get("workspace") == "display"
        if self.spec.name != "browser" and not display and count > 1:
            raise ValueError("this computer's desktop runs one workspace at a time; --workspaces N is for the "
                             "background browser (bench browser) and for displays of their own (--workspace "
                             "display)")
        return list(range(count))

    def worker_process(self, args, slot, env):
        python = super().worker_process(args, slot, env)
        chromes = getattr(args, "chromes", None)
        if self.spec.name == "browser" and chromes is not None:
            env[CHROME_ENV] = chromes.attach(slot, python)
        return python

    def where(self, slot):
        return f"background browser {slot}" if self.spec.name == "browser" else "this computer"
