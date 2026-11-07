"""Host-owned worker leases shared by all target environments."""
import itertools
from pathlib import Path
import threading
import time

LIMITS = {"workspaces": 4}
SPARE = 1

class Cancelled(Exception):
    """The lease requester stopped waiting."""

class Worker:
    """A workspace's worker process. `status`: starting, ready, error or stopped; `run`:
    the conversation it serves (None: free)."""

    def __init__(self, number: int, kind: str, options: dict, run, *, reusable=True):
        self.id = f"w{number}"
        self.kind = kind
        self.options = dict(options)
        self.run = run
        self.status = "starting"
        self.error = None
        self.endpoint = None
        self.approval_key = None
        self.python = None
        self.process = None
        self._approval_lock = threading.RLock()
        self._lease = object()
        self.reusable = reusable
        self.since = time.time()

    def alive(self) -> bool:
        return self.process is None or self.process.poll() is None

    def describe(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "run": self.run, "error": self.error,
                "since": self.since}

class WorkerPool:
    """Capacity and ownership of package-provided worker leases. `limits()`
    gives LIMITS' values (the app's settings, read at each decision); `launch(worker, log)`
    starts a worker's process and sets its endpoint and python (tests give their own)."""

    def __init__(self, logs: Path, limits=None, launch=None):
        self.logs = Path(logs)
        self.limits = limits or (lambda: dict(LIMITS))
        self.launch = launch or self._launch
        self.workers = []
        # Why the last worker could not start; whether a bench environment is installing.
        self.error = None
        self.installing = False
        self._numbers = itertools.count(1)
        self._changed = threading.Condition()
        self._releases = 0

    worker_class = Worker

    def check_kind(self, kind):
        return kind

    def kind_limit(self, kind, limits):
        return None

    def alive(self, worker):
        return worker.alive()

    def _start(self, worker, log):
        try:
            self.launch(worker, log)
            worker.status = "ready"
        except Exception as error:
            worker.status, worker.error = "error", str(error)
            self.error = worker.error
            with self._changed:
                self.workers.remove(worker)
            self._stop(worker)
            raise
        finally:
            with self._changed:
                self._changed.notify_all()

    # What the app shows.

    def status(self) -> str:
        """stopped, installing, starting, ready (one worker is) or error (the last start failed)."""
        with self._changed:
            states = {worker.status for worker in self.workers}
        if "ready" in states:
            return "ready"
        if self.installing:
            return "installing"
        if "starting" in states:
            return "starting"
        return "error" if self.error else "stopped"

    def describe(self) -> list[dict]:
        with self._changed:
            return [worker.describe() for worker in self.workers]

    def of(self, run) -> Worker | None:
        """The worker serving `run`."""
        with self._changed:
            return next((worker for worker in self.workers if run is not None and worker.run == run), None)

    def held(self) -> list[Worker]:
        with self._changed:
            return [worker for worker in self.workers if worker.run is not None]

    # Taking and giving back.

    def acquire(self, run, kind: str, options=None, *, log=print, evict=None, cancelled=None,
                poll=0.5, reusable=True) -> Worker:
        """A ready worker of `kind` with `options` for `run`: a free one, a new one, or once
        one frees (calling `evict(runs)`, the conversations whose end would make room, at
        most once per release). Cancelled when `cancelled()` holds while it waits."""
        self.check_kind(kind)
        options = dict(options or {})
        noted = evicted = None
        while True:
            stop = []
            with self._changed:
                if cancelled is not None and cancelled():
                    raise Cancelled()
                self._prune(stop)
                action, worker, waiting = self._decide(run, kind, options, reusable=reusable)
                if action == "stop":
                    stop.append(worker)
                releases = self._releases
            for item in stop:
                self._stop(item)
                item.status = "stopped"
            if action == "reuse":
                return worker
            if action == "start":
                self._start(worker, log)
                return worker
            if action == "stop":
                continue
            message, runs = waiting
            if message != noted:
                log(message)
                noted = message
            if evict is not None and evicted != releases and runs:
                if evict(runs):
                    evicted = releases
            with self._changed:
                if self._releases == releases:
                    self._changed.wait(poll)

    def _decide(self, run, kind, options, *, reusable=True):
        """What acquire() does now (under the lock): ("reuse" | "start", worker, None),
        ("stop", a free worker in the way, None) or ("wait", None, (why, the runs whose end
        makes room))."""
        limits = self.limits()
        live = [worker for worker in self.workers if worker.status in ("starting", "ready")]
        free = [worker for worker in live if worker.run is None and worker.status == "ready"]
        same = next((worker for worker in free if worker.kind == kind and worker.options == options), None)
        if same is not None and reusable and same.reusable:
            with same._approval_lock:
                same.run, same.since = run, time.time()
            return "reuse", same, None
        cap = max(1, int(limits["workspaces"]))
        kind_cap = self.kind_limit(kind, limits)
        of_kind = [worker for worker in live if worker.kind == kind]
        kind_room = kind_cap is None or len(of_kind) < kind_cap
        if len(live) < cap and kind_room:
            worker = self.worker_class(next(self._numbers), kind, options, run, reusable=reusable)
            self.workers.append(worker)
            return "start", worker, None
        # A free worker of another kind or other settings makes room by stopping.
        in_the_way = [worker for worker in free if kind_room or worker.kind == kind]
        if in_the_way:
            worker = min(in_the_way, key=lambda item: item.since)
            self.workers.remove(worker)
            return "stop", worker, None
        if not kind_room:
            why = f"waiting for a {kind} workspace: {len(of_kind)} of {kind_cap} in use"
            runs = [worker.run for worker in of_kind if worker.run is not None]
        else:
            why = f"waiting for a workspace: {len(live)} of {cap} in use"
            runs = [worker.run for worker in live if worker.run is not None]
        return "wait", None, (why, runs)

    def _prune(self, stop):
        """Drop free workers whose resource died; mark taken ones as failed."""
        for worker in list(self.workers):
            dead = worker.status == "ready" and (not self.alive(worker))
            if not dead:
                continue
            if worker.run is None:
                self.workers.remove(worker)
                stop.append(worker)
            else:
                with worker._approval_lock:
                    worker.status, worker.error = "error", "its worker exited"

    def release(self, run) -> None:
        """A stopped lease remains attributable until its process has been reaped."""
        stop = []
        with self._changed:
            worker = self.of(run)
            if worker is None:
                return
            with worker._approval_lock:
                worker.since = time.time()
                worker._lease = object()
            if not worker.reusable or worker.status != "ready" or not worker.alive():
                worker.status = "stopping"
                stop.append(worker)
            else:
                worker.run = None
            free = sorted((w for w in self.workers if w.run is None and w.status == "ready"),
                          key=lambda w: w.since)
            for item in free[:max(0, len(free) - SPARE)]:
                item.status = "stopping"
                stop.append(item)
        try:
            for item in stop:
                self._stop(item)
                item.status = "stopped"
                with self._changed:
                    if item in self.workers:
                        self.workers.remove(item)
        finally:
            with self._changed:
                self._releases += 1
                self._changed.notify_all()

    def warm(self, kind: str, options=None, log=print) -> Worker | None:
        """Start a free worker of `kind` with `options` when none is ready and there is room
        (the app's Restart, after its settings changed)."""
        self.check_kind(kind)
        options = dict(options or {})
        with self._changed:
            limits = self.limits()
            live = [worker for worker in self.workers if worker.status in ("starting", "ready")]
            if any(worker.run is None and worker.kind == kind and worker.options == options for worker in live) or \
                    len(live) >= max(1, int(limits["workspaces"])):
                return None
            worker = self.worker_class(next(self._numbers), kind, options, None)
            self.workers.append(worker)
        self._start(worker, log)
        return worker

    def stop_free(self) -> int:
        """Stop the workers no conversation uses; how many are in use (they run on)."""
        with self._changed:
            free = [worker for worker in self.workers if worker.run is None and worker.status != "starting"]
            for worker in free:
                self.workers.remove(worker)
            used = sum(1 for worker in self.workers if worker.run is not None)
            self._changed.notify_all()
        for worker in free:
            self._stop(worker)
        return used

