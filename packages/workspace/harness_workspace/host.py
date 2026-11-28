"""Project binding, toolchain provisioning and resource ownership belong to this package."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from urllib.error import URLError

from harness.sdk import (WorkerPool, WorkspaceProvider, RemoteEnvironment, approval, create_server,
                         free_port, python_path, bench_spec, bench_environment, environments,
                         load_deploy, toml_dumps, ssh as harness_ssh)

def environment_python(spec, log):
    environment = bench_environment(load_deploy(None), spec.name)
    if environment is None:
        return sys.executable
    if environment.installed() is None:
        environments.install(environment, log=log)
    return str(environment.python)


class NativePool(WorkerPool):
    def check_kind(self, kind):
        if kind not in ("project", "ssh"):
            raise ValueError(f"Unknown native workspace {kind}")

    def alive(self, worker):
        if getattr(worker, "_server", None) is not None:
            return worker.status != "stopped"
        return super().alive(worker)

    def _launch(self, worker, log):
        if worker.kind == "ssh" and isinstance(worker.options, dict) and isinstance(worker.options.get("ssh"), dict):
            from .worker import WorkspaceEnvironment

            spec = dict(worker.options["ssh"])
            env = WorkspaceEnvironment(
                artifacts=worker.options.get("artifacts"),
                environment=worker.options.get("environment"),
                ssh=spec,
                ssh_client=harness_ssh.POOL.get(spec),
            )
            worker.python = sys.executable
            worker.approval_key = secrets.token_hex(32)
            server = create_server(env, "127.0.0.1", 0, approval_key=worker.approval_key)
            thread = threading.Thread(target=server.serve_forever, name=f"ssh-worker-{worker.id}", daemon=True)
            thread.start()
            worker._env = env
            worker._server = server
            worker._thread = thread
            worker.endpoint = f"http://127.0.0.1:{server.server_address[1]}"
            return
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
        server = getattr(worker, "_server", None)
        if server is not None:
            worker._server = None
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
            env = getattr(worker, "_env", None)
            if env is not None:
                worker._env = None
                try:
                    env.close()
                except Exception:
                    pass
            worker.status = "stopped"
            return
        process = worker.process
        if process is not None and process.poll() is None:
            process.stdin.close()
            try:
                process.wait(15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
        worker.status = "stopped"

    @staticmethod
    def _same_ssh_target(worker, kind, options) -> bool:
        return (kind == "ssh" and worker.kind == "ssh"
                and isinstance(options, dict) and isinstance(worker.options, dict)
                and worker.options.get("ssh") == options.get("ssh"))

    def _decide(self, run, kind, options, *, reusable=True):
        if kind == "ssh" and reusable:
            free = [worker for worker in self.workers
                    if worker.run is None and worker.status == "ready" and worker.reusable]
            same = next((worker for worker in free if self._same_ssh_target(worker, kind, options)), None)
            if same is not None:
                with same._approval_lock:
                    same.run, same.since = run, time.time()
                return "reuse", same, None
        return super()._decide(run, kind, options, reusable=reusable)

    def acquire(self, run, kind: str, options=None, **kwargs):
        worker = super().acquire(run, kind, options, **kwargs)
        if (kind == "ssh" and isinstance(options, dict) and options.get("artifacts")
                and worker.options.get("artifacts") != options.get("artifacts")):
            try:
                client = RemoteEnvironment(worker.endpoint, timeout=15, approval_key=worker.approval_key)
                try:
                    client.call("rebind", artifacts=options["artifacts"])
                finally:
                    client.close()
                worker.options = dict(options)
            except Exception:
                worker.reusable = False
                worker.status = "error"
                super().release(run)
                return super().acquire(run, kind, options, **kwargs)
        return worker

    def release(self, run):
        worker = self.of(run)
        if worker is not None:
            keep_warm = worker.kind == "ssh" and worker.reusable and worker.alive()
            try:
                client = RemoteEnvironment(worker.endpoint, timeout=15, approval_key=worker.approval_key)
                try:
                    profile = client.call("profile")
                    client.call("release", episode_id=profile["episode_id"])
                finally:
                    client.close()
            except Exception as error:
                worker.error = f"cleanup unconfirmed: {error}"
                keep_warm = False
            # Local target bindings never pass implicitly; warm SSH workers release all
            # episode processes and keep only the persistent SSH bridge alive until rebound.
            if not keep_warm:
                worker.status = "stopped"
        super().release(run)

    def close(self):
        for worker in list(self.workers):
            if worker.run is not None:
                self.release(worker.run)
            self._stop(worker)
        self.workers.clear()


class Workspaces(WorkspaceProvider):
    def __init__(self, directory, settings):
        self.directory, self.settings = Path(directory), settings
        self.pool = NativePool(self.directory / "logs/targets",
                              limits=lambda: {"workspaces": settings.get()["workspace"]["workers"]})

    def kinds(self):
        return ("project", "ssh")

    def accepts(self, binding):
        return set(binding) == {"folder"} or bool((binding or {}).get("ssh"))

    def kind(self, requested=None, text=None):
        if requested == "ssh":
            return "ssh"
        return "project"

    def bench(self, kind):
        return "workspace"

    def describe(self, kind):
        if kind == "ssh":
            return {"label": "Remote SSH project", "order": 12,
                    "about": "read and change files and run commands in a remote folder over SSH"}
        return {"label": "Project folder", "folder": True, "order": 10,
                "about": "read and change files and run commands in one folder; no screen"}

    def bind(self, kind, directory, request, parent=None):
        if kind == "ssh":
            ssh_req = request.get("ssh")
            while ssh_req is None and parent is not None:
                if getattr(parent, "workspace_kind", None) == "ssh":
                    ssh_req = getattr(parent, "workspace_options", {}).get("ssh")
                parent = parent.parent
            if not isinstance(ssh_req, dict) or not (ssh_req.get("host") or ssh_req.get("target")):
                raise ValueError("an SSH workspace requires an explicitly bound remote target and folder")
            spec = harness_ssh.normalize_spec(
                ssh_req.get("host") or ssh_req.get("target"),
                user=ssh_req.get("user"),
                port=ssh_req.get("port"),
                folder=ssh_req.get("folder") or request.get("folder") or "~",
                target=ssh_req.get("target"),
            )
            probe = harness_ssh.POOL.get(spec).call("probe", {"path": spec["folder"]})
            if not probe.get("path_exists") or not probe.get("path_is_dir"):
                raise ValueError(f"remote directory does not exist: {spec['folder']}")
            spec["folder"] = str(probe.get("path") or spec["folder"])
            spec["os"] = str(probe.get("os") or "Linux")
            return ({"ssh": spec, "artifacts": str(Path(directory) / "artifacts")},
                    {"ssh": spec, "folder": spec["folder"], "backend": "remote-ssh"})
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
            "contract": "native", "verifier": False,
            "reflex_method": "optional", "purpose": "optional", "turn_grace_seconds": 30.0,
            "bootstrap": "harness.runtime.execution.session:create_session"}}
        return tree

    def builtin_skills(self, kind):
        return ("workspace",)

    def acquire(self, run, kind, *, options=None, **waiting):
        return self.pool.acquire(run, kind, options, **waiting)
