"""The minebot workspace: a conversation that works as a bot body in the game server the
settings name. The package owns what runs beside the body (stack.py): it is started when a
conversation takes the workspace and stopped when the host closes. One body at a time: the
body is one player on one server."""

from harness.sdk import WorkerPool, WorkspaceProvider

from . import stack
from .config import data_dir, settings


KIND = "minebot"
BENCH = "mineflayer"


class BodyPool(WorkerPool):
    """The one worker of the body, with what runs beside it."""

    settings = None

    def check_kind(self, kind):
        if kind != KIND:
            raise ValueError(f"Unknown workspace {kind}")

    def kind_limit(self, kind, limits):
        return 1

    def alive(self, worker):
        return stack.alive("worker")

    def _launch(self, worker, log):
        values = settings(store=self.settings)
        options = stack.worker_options(values, more=worker.options)
        if not stack.up(values, store=data_dir() / "store", options=options,
                        events_log=stack.logs_dir() / "body-events.jsonl", log=log):
            raise RuntimeError(f"the body did not come up; see the logs in {stack.logs_dir()}")
        worker.endpoint = stack.endpoint(values)
        worker.python = stack.worker_python(log)

    def python(self, kind, log=print):
        return stack.worker_python(log)

    def _stop(self, worker):
        stack.down(log=lambda message: None)
        worker.status = "stopped"

    def close(self):
        for worker in list(self.workers):
            self._stop(worker)


class Workspaces(WorkspaceProvider):
    def __init__(self, directory, settings):
        self.directory, self.settings = directory, settings
        self.pool = BodyPool(stack.logs_dir(), limits=lambda: {"workspaces": 1})
        self.pool.settings = settings   # (the host's own settings: where the body's connection is read from)

    def kinds(self):
        return (KIND,)

    def kind(self, requested=None, text=None):
        return KIND

    def bench(self, kind):
        return BENCH

    def describe(self, kind):
        values = settings(store=self.settings)
        return {"label": "Bot body in a game server", "order": 60, "views": values["window"] == "on",
                "about": f"a player in the Minecraft: Java Edition server at {values['host']}:{values['port']} "
                         "(the settings minebot.*): code runs on the body"}

    def tree(self, tree, kind):
        # The prompt and the agent on a bot body are the kind's own (kinds.toml).
        tree["bench"] = BENCH
        return tree

    def builtin_skills(self, kind):
        return ("body",)

    def acquire(self, run, kind, *, options=None, **waiting):
        return self.pool.acquire(run, kind, options, **waiting)
