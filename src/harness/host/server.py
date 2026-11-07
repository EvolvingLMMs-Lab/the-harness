"""The session host's process (`python -m harness.host.server [--port N]`): the assistant's server over
DATA, with the sessions of every frontend as a tree, an index of them, and an end once
nothing is open and nobody asks (see host/__init__.py)."""

import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

from .tasks import TaskHost, TaskHandler, TaskServer
from ..core.episodes import new_name
from ..core.ports import free_port
from ..core import atomic_write
from ..core.wait import wait_until
from ..paths import data
from . import PORT, PORT_ENV, address_file, identity, idle_seconds, index_file, read_address, _reachable
from .sessions import Sessions, history, live


class HostHandler(TaskHandler):
    def get_host(self, query):
        self._json(self.server.state())

    def post_host_stop(self, body):
        self.server.stop(force=bool(body.get("force")))
        self._json({"ok": True})

    def get_sessions(self, query):
        rows = self.server.conversations.sessions()
        if (query.get("all") or ["0"])[0] in ("1", "true"):
            rows += history(self.server.conversations.index, skip={row["id"] for row in rows})
        limit = int((query.get("limit") or ["50"])[0])
        self._json({"host": self.server.state(), "sessions": rows[:limit] if limit > 0 else rows})


class HostServer(TaskServer):
    """The app's server as the session host: sessions started by any client, idle
    tracking (touch(), the watchdog) and stop()."""

    handler_class = HostHandler

    def __init__(self, address, app: TaskHost, token: str | None = None, idle: float | None = None):
        super().__init__(address, app, token=token)
        self.conversations = Sessions(index=index_file(app.directory), default_frontend="app")
        self.conversations.notes = lambda run: app.starting.get(run)
        self.idle = idle_seconds() if idle is None else idle
        self.started = time.time()
        self._last = time.monotonic()
        self.background = {}

    def start_background(self):
        from ..extensions import hosts

        self.conversations.registered = self._registered
        for package, module in hosts():
            factory = getattr(module, "background", None)
            if factory is not None:
                service = factory(self)
                self.background[package.name] = service
                service.start()

    def _registered(self, run, conversation):
        for service in self.background.values():
            registered = getattr(service, "registered", None)
            if registered is not None:
                registered(run, conversation)

    def info(self) -> dict:
        return {**super().info(), "host": True}

    def touch(self) -> None:
        self._last = time.monotonic()

    def running(self) -> bool:
        """Whether a session is open (or one is being prepared)."""
        return self.conversations.running() or any(not str(note).startswith("error")
                                                   for note in self.app.starting.values())

    def state(self) -> dict:
        host, port = self.server_address[:2]
        return {**identity(), "pid": os.getpid(), "url": f"http://127.0.0.1:{port}", "started": self.started,
                "idle_seconds": round(time.monotonic() - self._last, 1), "idle_limit": self.idle,
                "running": self.running(), "open": sum(1 for row in self.conversations.sessions() if row["live"])}

    def session_directory(self, request: dict, config, seed: int):
        """Where the client asked (an absolute path: its own `--output`), else
        DATA/sessions/<time>-<task>/seed-<seed>; the run is the session's id."""
        given = request.get("directory")
        if given:
            directory = Path(given)
            if not directory.is_absolute():
                raise ValueError("directory must be an absolute path")
        else:
            directory = self.root / "sessions" / new_name(config.task) / f"seed-{seed}"
        return directory, None

    def start_conversation(self, request: dict) -> str:
        # The client's model keys the host lacks (a key exported in the client's shell only).
        for name, value in (request.get("environment") or {}).items():
            if str(name).endswith("_API_KEY") and value and not os.environ.get(name):
                os.environ[name] = str(value)
        return super().start_conversation(request)

    def stop(self, force: bool = False) -> None:
        """Exit (after the answer to the request that asked): refused while a session is
        open, unless `force`, which ends them first."""
        if self.running():
            if not force:
                raise ValueError("sessions are open: end them first (/sessions and /end in harness), or force")
            for conversation in list(self.conversations.values()):
                if live(conversation.status):
                    conversation.close()
        threading.Thread(target=self.shutdown, name="host-stop", daemon=True).start()

    def watch(self) -> None:
        """Exit once no session is open and no client asked for anything for `idle` seconds."""
        step = max(0.2, min(30.0, self.idle / 4))
        while True:
            time.sleep(step)
            if self.running() or any(service.keep_alive() for service in self.background.values()):
                self.touch()
            elif time.monotonic() - self._last > self.idle:
                print(json.dumps({"host": "idle", "seconds": self.idle}), flush=True)
                self.shutdown()
                return


def serve(port: int | None = None, idle: float | None = None) -> int:
    """Run the host until it is idle or stopped; refused while another host answers."""
    from ..extensions import focus

    other = _reachable(read_address())
    if other is not None:
        raise RuntimeError(f"a session host already runs at {other.url} (process {other.pid})")
    if port is None:
        port = int(os.environ.get(PORT_ENV) or PORT)
    app = TaskHost(data())
    try:
        server = HostServer(("127.0.0.1", port), app, idle=idle)
    except OSError:
        server = HostServer(("127.0.0.1", free_port()), app, idle=idle)
    path = address_file(app.directory)
    atomic_write(path, json.dumps({**server.state(), "token": server.token}), private=True)
    app.focus_chat = focus
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(json.dumps({"host": server.state()["url"], "pid": os.getpid(), "data": str(app.directory)}), flush=True)
    try:
        with server:
            server.start_background()
            threading.Thread(target=server.watch, name="host-idle", daemon=True).start()
            server.serve_forever()
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
    finally:
        for service in reversed(list(server.background.values())):
            service.close()
        mine = read_address(app.directory)
        if mine and mine.get("pid") == os.getpid():
            try:
                path.unlink()
            except OSError:
                pass
        open_ = [conversation for conversation in server.conversations.values()
                 if live(conversation.status)]
        for conversation in open_:
            conversation.close()
        # Their episodes end (and write their summaries) before the process does.
        wait_until(lambda: not any(live(item.status) for item in open_), 30)
        app.close()
    return 0


def main(argv=None):
    import argparse

    parsed = argparse.ArgumentParser(prog="python -m harness.host.server")
    parsed.add_argument("--port", type=int, help="port to take (default $HARNESS_HOST_PORT or 8780, else a free one)")
    parsed.add_argument("--idle", type=float, help="seconds with nothing open and no client before it exits "
                                                   "(default $HARNESS_HOST_IDLE or 1800)")
    given = parsed.parse_args(argv)
    return serve(port=given.port, idle=given.idle)


if __name__ == "__main__":
    sys.exit(main())
