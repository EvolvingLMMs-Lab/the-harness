"""Project binding, toolchain provisioning and resource ownership belong to this package."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.error import URLError

from harness.sdk import (WorkerPool, WorkspaceProvider, RemoteEnvironment, approval, free_port,
                         python_path, bench_spec, bench_environment, environments, load_deploy,
                         toml_dumps)

def environment_python(spec, log):
    environment = bench_environment(load_deploy(None), spec.name)
    if environment is None:
        return sys.executable
    if environment.installed() is None:
        environments.install(environment, log=log)
    return str(environment.python)


class NativePool(WorkerPool):
    def check_kind(self, kind):
        if kind != "project":
            raise ValueError(f"Unknown native workspace {kind}")

    def _launch(self, worker, log):
        spec = bench_spec("workspace")
        worker.python = environment_python(spec, log)
        port = free_port()
        self.logs.mkdir(parents=True, exist_ok=True)
        options = self.logs / f"{worker.id}.toml"
        options.write_text(toml_dumps(worker.options), encoding="utf-8")
        command = [worker.python, "-m", "harness.core.worker", "--factory", spec.factory,
                   "--options", str(options), "--port", str(port), "--exit-with-stdin", approval.APPROVAL_PIPE_FLAG]
        env = {**os.environ, "PYTHONPATH": python_path(), "PYTHONUTF8": "1"}
        env.pop(approval.WORKER_APPROVAL_KEY, None)
        with (self.logs / f"{worker.id}.log").open("ab") as log_file:
            worker.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log_file, stderr=log_file, env=env)
        worker.approval_key = secrets.token_hex(32)
        approval.write_approval_key(worker.process.stdin, worker.approval_key)
        worker.endpoint = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if worker.process.poll() is not None:
                raise RuntimeError(f"Target worker exited; see {self.logs / (worker.id + '.log')}")
            try:
                client = RemoteEnvironment(worker.endpoint, timeout=2, approval_key=worker.approval_key)
                try:
                    client.tools()
                finally:
                    client.close()
                return
            except (OSError, URLError, RuntimeError):
                time.sleep(.1)
        raise RuntimeError("Target worker did not start within 60 seconds")

    def python(self, kind, log=print):
        return environment_python(bench_spec("workspace"), log)

    def _stop(self, worker):
        process = worker.process
        if process is not None and process.poll() is None:
            process.stdin.close()
            try:
                process.wait(15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
        worker.status = "stopped"

    def release(self, run):
        worker = self.of(run)
        if worker is not None:
            try:
                client = RemoteEnvironment(worker.endpoint, timeout=15, approval_key=worker.approval_key)
                try:
                    profile = client.call("profile")
                    client.call("release", episode_id=profile["episode_id"])
                finally:
                    client.close()
            except Exception as error:
                worker.error = f"cleanup unconfirmed: {error}"
            # Target bindings and resources never pass to another task implicitly.
            worker.status = "stopped"
        super().release(run)

    def close(self):
        for worker in list(self.workers):
            self.release(worker.run)
            self._stop(worker)


class Workspaces(WorkspaceProvider):
    def __init__(self, directory, settings):
        self.directory, self.settings = Path(directory), settings
        self.pool = NativePool(self.directory / "logs/targets",
                              limits=lambda: {"workspaces": settings.get()["workspace"]["workers"]})

    def kinds(self):
        return ("project",)

    def accepts(self, binding):
        return set(binding) == {"folder"}

    def kind(self, requested=None, text=None):
        return "project"

    def bench(self, kind):
        return "workspace"

    def describe(self, kind):
        return {"label": "Project folder", "folder": True,
                "about": "read and change files and run commands in one folder; no screen"}

    def bind(self, kind, directory, request, parent=None):
        folder = request.get("folder")
        while folder is None and parent is not None:
            if getattr(parent, "workspace_kind", None) == kind:
                folder = getattr(parent, "workspace_options", {}).get("folder")
            parent = parent.parent
        if not folder:
            raise ValueError("a project workspace requires an explicitly bound folder")
        folder = Path(folder).expanduser().resolve(strict=True)
        if not folder.is_dir():
            raise ValueError("folder must be an existing directory")
        return ({"folder": str(folder), "artifacts": str(Path(directory) / "artifacts")},
                {"folder": str(folder), "backend": "trusted-local"})

    def tree(self, tree, kind):
        spec = bench_spec("workspace")
        tree["bench"] = spec.name
        agent = tree["overrides"]["agent"]
        agent["prompt"][spec.kind] = str(Path(__file__).resolve().parents[1] / "prompts/workspace")
        agent[spec.kind] = {"roles": ["main"], "runtime": {
            "contract": "native", "verifier": False, "max_history_turns": 10,
            "think_while_acting": "on_events", "bootstrap": "harness.runtime.execution.session:create_session"}}
        return tree

    def builtin_skills(self, kind):
        return ("workspace",)

    def acquire(self, run, kind, *, options=None, **waiting):
        return self.pool.acquire(run, kind, options, **waiting)
