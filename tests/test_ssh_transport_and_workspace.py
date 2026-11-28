"""End-to-end tests for the unified SSH config parser, persistent JSON-RPC bridge,
and first-class `ssh` workspace backend (zero mocked protocol internals)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import helpers  # noqa: F401
from harness.core import ssh
from harness_workspace.host import Workspaces
from harness_workspace.worker import WorkspaceEnvironment


def _local_bridge_spawn(target: str, port: int | None) -> subprocess.Popen:
    """Spawn the EXACT unmodified remote bridge script locally over stdin/stdout pipes."""
    return subprocess.Popen(
        [sys.executable, "-u", "-c", "import base64,sys;exec(base64.b64decode(sys.stdin.readline()))"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )


def _init_git_repo(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for args in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test User"],
    ):
        subprocess.run(args, cwd=str(folder), check=True, capture_output=True)
    (folder / "README.md").write_text("# Demo\nhello\n", encoding="utf-8")
    (folder / "AGENTS.md").write_text("Always run tests.\n", encoding="utf-8")
    (folder / "src").mkdir()
    (folder / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(folder), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(folder), check=True, capture_output=True)


class SshConfigAndErrorTests(unittest.TestCase):
    def test_parse_ssh_config_supports_recursive_include_proxyjump_and_wildcards(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conf_d = root / "config.d"
            conf_d.mkdir()
            (conf_d / "gpu.conf").write_text(
                "Host gpu-a gpu-b *\n"
                "  HostName 111.225.217.131\n"
                "  User weiyang\n"
                "  Port 2222\n"
                "  ProxyJump bastion\n",
                encoding="utf-8",
            )
            main_cfg = root / "config"
            main_cfg.write_text(
                "Include config.d/*.conf\n"
                "Host bastion\n"
                "  HostName 10.0.0.1\n"
                "  User ops\n"
                "Host *.internal\n"
                "  User ignored\n",
                encoding="utf-8",
            )
            hosts = ssh.parse_ssh_config(main_cfg)
            by_name = {h["host"]: h for h in hosts}
            self.assertEqual(list(by_name), ["gpu-a", "gpu-b", "bastion"])
            self.assertEqual(by_name["gpu-a"]["hostname"], "111.225.217.131")
            self.assertEqual(by_name["gpu-a"]["port"], 2222)
            self.assertEqual(by_name["gpu-a"]["proxy_jump"], "bastion")
            self.assertEqual(by_name["bastion"]["user"], "ops")

    def test_normalize_spec_and_terminal_cmd_safety(self):
        # Config alias without explicit port keeps port=None so OpenSSH reads ~/.ssh/config
        spec = ssh.normalize_spec("gpu-a", folder="/pfs/echo_folder/weiyang")
        self.assertEqual(spec, {"host": "gpu-a", "target": "gpu-a", "folder": "/pfs/echo_folder/weiyang"})
        self.assertNotIn("port", spec)

        spec2 = ssh.normalize_spec("root@111.225.217.131:2200", folder="/data/my project")
        self.assertEqual(spec2["user"], "root")
        self.assertEqual(spec2["host"], "111.225.217.131")
        self.assertEqual(spec2["port"], 2200)
        self.assertEqual(spec2["target"], "root@111.225.217.131")

        cmd = ssh.interactive_terminal_cmd(spec2)
        self.assertIn("-tt", cmd)
        self.assertIn("2200", cmd)
        # Base64 encoded path avoids fish/csh syntax and Windows quoting corruption
        self.assertNotIn("my project", cmd[-1])
        self.assertIn("base64", cmd[-1])

        with self.assertRaises(ValueError):
            ssh.normalize_spec("bad host;rm -rf /")

    def test_classify_ssh_error_covers_auth_hostkey_timeout_and_missing_python(self):
        self.assertEqual(ssh.classify_ssh_error("Host key verification failed.").code, "host_key_unknown")
        self.assertEqual(ssh.classify_ssh_error("Permission denied (publickey,password).").code, "auth_required")
        self.assertEqual(ssh.classify_ssh_error("ssh: Could not resolve hostname nope").code, "dns_failed")
        self.assertEqual(ssh.classify_ssh_error("Connection refused").code, "connection_refused")
        self.assertEqual(ssh.classify_ssh_error("Connection timed out").code, "timeout")
        self.assertEqual(ssh.classify_ssh_error("HARNESS_NO_PYTHON", 127).code, "no_python3")


class SshBridgeAndWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "pfs" / "echo_folder" / "weiyang"
        _init_git_repo(self.repo)
        self.client = ssh.SshClient("gpu-node", spawn_fn=_local_bridge_spawn)
        self.addCleanup(self.client.close)

    def test_bridge_primitives_browse_files_git_process_and_reconnect(self):
        # 1. Probe arbitrary path (not just ~)
        pr = self.client.call("probe", {"path": str(self.repo)})
        self.assertTrue(pr["path_exists"] and pr["path_is_dir"])
        self.assertTrue(pr["git"])

        # 2. Browse arbitrary directory with .git badge
        br = self.client.call("browse", {"path": str(self.repo.parent)})
        names = {f["name"]: f for f in br["folders"]}
        self.assertIn("weiyang", names)
        self.assertTrue(names["weiyang"]["git"])

        # 3. Read / Write with optimistic CAS hash + path traversal rejection
        rd = self.client.call("read", {"root": str(self.repo), "path": "src/app.py"})
        self.assertIn("print('ok')", rd["text"])
        conflict = self.client.call("write", {
            "root": str(self.repo), "path": "src/app.py", "text": "x\n", "expected": "wrong-sha",
        })
        self.assertEqual(conflict["error"], "conflict")
        wr = self.client.call("write", {
            "root": str(self.repo), "path": "src/app.py", "text": "print('updated')\n", "expected": rd["sha256"],
        })
        self.assertIn("sha256", wr)
        with self.assertRaises(ValueError):
            self.client.call("read", {"root": str(self.repo), "path": "../../outside.txt"})

        # 4. Tree + Search + Git info / changes / revert
        tree = self.client.call("tree", {"root": str(self.repo), "path": ""})
        by_name = {e["name"]: e for e in tree["entries"]}
        self.assertEqual(by_name["src"]["status"], "M")

        srch = self.client.call("search", {"root": str(self.repo), "query": "app.py"})
        self.assertEqual([m["path"] for m in srch["matches"]], ["src/app.py"])

        ginfo = self.client.call("git_info", {"root": str(self.repo)})
        self.assertTrue(ginfo["is_git"])
        self.assertEqual(ginfo["branch"], "main")
        self.assertEqual(ginfo["dirty_count"], 1)
        self.assertGreaterEqual(ginfo["diff_added"], 1)

        chg = self.client.call("git_changes", {"root": str(self.repo)})
        self.assertEqual([f["path"] for f in chg["files"]], ["src/app.py"])
        self.assertIn("updated", chg["files"][0]["diff"])

        rev = self.client.call("git_revert", {"root": str(self.repo), "path": "src/app.py"})
        self.assertEqual(rev["files"], [])

        # 5. Remote process execution + polling + cancellation + auto-reconnect after kill
        p_res = self.client.call("proc_start", {
            "root": str(self.repo),
            "command": [sys.executable, "-c", "print('hello from ssh workspace')"],
            "cwd": ".",
            "timeout": 15,
        })
        pid = p_res["process_id"]
        deadline = time.monotonic() + 10
        while not p_res.get("ready") and time.monotonic() < deadline:
            time.sleep(0.05)
            p_res = self.client.call("proc_poll", {"process_id": pid})
        self.assertTrue(p_res["ready"])
        self.assertEqual(p_res["exit_code"], 0)
        self.assertIn("hello from ssh workspace", p_res["output"]["text"])

        # Force-kill bridge process and verify transparent auto-reconnect on next call
        self.client._proc.kill()
        self.client._proc.wait(timeout=5)
        pr2 = self.client.call("probe", {"path": str(self.repo)})
        self.assertTrue(pr2["path_is_dir"])

    def test_first_class_ssh_workspace_bind_and_environment_ticks(self):
        pool = ssh.SshPool(spawn_fn=_local_bridge_spawn)
        self.addCleanup(pool.close_all)
        fake_settings = mock.Mock(get=lambda: {"workspace": {"workers": 2}})
        ws_provider = Workspaces(self.root / "host", fake_settings)
        self.addCleanup(ws_provider.close)

        real_client = ssh.SshClient
        with mock.patch.object(ssh, "POOL", pool), \
                mock.patch.object(ssh, "SshClient", lambda t, p=None, **kw: real_client(t, p, spawn_fn=_local_bridge_spawn)):
            self.assertIn("ssh", ws_provider.kinds())
            self.assertTrue(ws_provider.accepts({"ssh": {"host": "gpu-node", "folder": str(self.repo)}}))
            opts, meta = ws_provider.bind("ssh", self.root / "run1", {
                "ssh": {"host": "gpu-node", "folder": str(self.repo)},
            })
            self.assertEqual(meta["backend"], "remote-ssh")
            self.assertEqual(Path(meta["folder"]).resolve(), self.repo.resolve())

            env = WorkspaceEnvironment(artifacts=opts["artifacts"], ssh=opts["ssh"])
            self.addCleanup(env.close)
            obs = env.reset("free", 0)
            self.assertEqual(obs.state["backend"], "remote-ssh")
            self.assertEqual(obs.state["ssh_target"], "gpu-node")

            # Tick 0: read_file
            r0 = env._call_tick(obs.episode_id, 0, {"type": "read", "path": "README.md"}, action_id="a0")
            self.assertIn("# Demo", r0["result"]["text"])

            # Tick 1: run_command inside remote folder
            r1 = env._call_tick(obs.episode_id, 1, {
                "type": "run",
                "command": [sys.executable, "-c", "import os; print(os.getcwd())"],
                "cwd": ".",
                "timeout": 15,
            }, action_id="a1")
            pid = r1["result"]["process_id"]
            deadline = time.monotonic() + 10
            polled = env._call_process(obs.episode_id, pid)
            while not polled.get("ready") and time.monotonic() < deadline:
                time.sleep(0.05)
                polled = env._call_process(obs.episode_id, pid)
            self.assertEqual(polled["exit_code"], 0)
            self.assertIn("weiyang", polled["output"]["text"])

            # Tick 2: write_file atomically
            r2 = env._call_tick(obs.episode_id, 2, {
                "type": "write", "path": "created_via_ssh.txt", "text": "remote ok\n", "expected": None,
            }, action_id="a2")
            self.assertIn("sha256", r2["result"])
            self.assertEqual((self.repo / "created_via_ssh.txt").read_text(encoding="utf-8"), "remote ok\n")

    def test_ssh_worker_reuses_persistent_bridge_and_isolates_artifacts_across_runs(self):
        import threading
        from harness.core.worker import create_server
        from harness_workspace.host import NativePool

        real_client = ssh.SshClient
        with mock.patch.object(ssh, "SshClient", lambda t, p=None, **kw: real_client(t, p, spawn_fn=_local_bridge_spawn)):
            spec = {"host": "gpu-node", "target": "gpu-node", "folder": str(self.repo)}
            art1 = self.root / "run1-artifacts"
            art2 = self.root / "run2-artifacts"
            env = WorkspaceEnvironment(artifacts=art1, ssh=spec)
            self.addCleanup(env.close)
            bridge_pid_before = env.ssh_client._proc.pid if env.ssh_client._proc else None

            # Episode 1: start a long-running background process, then release episode 1.
            obs1 = env.reset("free", 0)
            r_bg = env._call_tick(obs1.episode_id, 0, {
                "type": "start",
                "command": [sys.executable, "-c", "import time; time.sleep(60)"],
                "cwd": ".",
                "timeout": 60,
            }, action_id="bg1")
            bg_pid = r_bg["result"]["process_id"]
            rel = env._call_release(obs1.episode_id)
            self.assertIn(bg_pid, rel["processes"])
            self.assertEqual(rel["processes"][bg_pid]["status"], "session_closed")
            # Persistent SSH bridge stayed alive after release.
            self.assertTrue(env.ssh_client._alive())
            if bridge_pid_before is not None:
                self.assertEqual(env.ssh_client._proc.pid, bridge_pid_before)

            # Rebind to run 2 artifacts and start episode 2 on the exact same bridge.
            rebound = env._call_rebind(str(art2))
            self.assertEqual(Path(rebound["artifacts"]).resolve(), art2.resolve())
            obs2 = env.reset("free", 0)
            self.assertNotEqual(obs2.episode_id, obs1.episode_id)
            r2 = env._call_tick(obs2.episode_id, 0, {"type": "read", "path": "README.md"}, action_id="r2")
            self.assertIn("# Demo", r2["result"]["text"])
            # Evidence for run 2 is written only to art2, isolated from art1.
            self.assertTrue((art2 / "evidence" / "index.jsonl").is_file())
            self.assertNotEqual(env.artifacts, art1.resolve())
            if bridge_pid_before is not None:
                self.assertEqual(env.ssh_client._proc.pid, bridge_pid_before)
            with self.assertRaises(ValueError):
                env._call_tick(obs1.episode_id, 0, {"type": "read", "path": "README.md"}, action_id="stale-ep")

            # Verify NativePool reuses a warm SSH worker across runs with different artifacts dirs.
            launches = []
            servers = []

            def fake_launch(worker, log):
                launches.append(worker.id)
                w_env = WorkspaceEnvironment(artifacts=worker.options["artifacts"], ssh=worker.options["ssh"])
                srv = create_server(w_env, "127.0.0.1", 0)
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                servers.append((srv, w_env))
                worker.endpoint = f"http://127.0.0.1:{srv.server_address[1]}"
                worker.approval_key = None

            pool = NativePool(self.root / "pool-logs", limits=lambda: {"workspaces": 2}, launch=fake_launch)

            def _cleanup_pool():
                pool.close()
                for srv, w_env in servers:
                    srv.shutdown()
                    srv.server_close()
                    w_env.close()

            self.addCleanup(_cleanup_pool)
            a1 = str(self.root / "pool-art-1")
            a2 = str(self.root / "pool-art-2")
            w1 = pool.acquire("run-1", "ssh", {"ssh": spec, "artifacts": a1})
            _, w_env1 = servers[0]
            w_env1.reset("free", 0)
            pool.release("run-1")
            w2 = pool.acquire("run-2", "ssh", {"ssh": spec, "artifacts": a2})
            self.assertIs(w1, w2)
            self.assertEqual(len(launches), 1)
            self.assertEqual(w_env1.artifacts.resolve(), Path(a2).resolve())
            pool.release("run-2")

    def test_native_pool_ssh_worker_reuses_host_pool_without_second_ssh_connection(self):
        from harness.core.remote import RemoteEnvironment

        spawns = []

        def counting_spawn(target: str, port: int | None):
            spawns.append((target, port))
            return _local_bridge_spawn(target, port)

        pool = ssh.SshPool(spawn_fn=counting_spawn)
        self.addCleanup(pool.close_all)
        fake_settings = mock.Mock(get=lambda: {"workspace": {"workers": 2}})
        ws_provider = Workspaces(self.root / "host-inproc", fake_settings)
        self.addCleanup(ws_provider.close)

        with mock.patch.object(ssh, "POOL", pool):
            opts1, meta1 = ws_provider.bind("ssh", self.root / "inproc-run1", {
                "ssh": {"host": "gpu-node", "folder": str(self.repo)},
            })
            self.assertEqual(meta1["backend"], "remote-ssh")
            self.assertEqual(len(spawns), 1)

            w1 = ws_provider.acquire("run-1", "ssh", options=opts1)
            # No second SSH connection was opened for the worker!
            self.assertEqual(len(spawns), 1)
            client1 = RemoteEnvironment(w1.endpoint, timeout=15, approval_key=w1.approval_key)
            try:
                # Verify authenticated controls are enabled (required by SpaceEnvironment.for_worker).
                client1.tools()
                self.assertIn("tick", client1.host_controls)
                self.assertIn("rebind", client1.host_controls)
                obs1 = client1.reset("free", 0)
                r1 = client1.call("tick", episode_id=obs1.episode_id, step=0,
                                  command={"type": "read", "path": "README.md"}, action_id="a1")
                self.assertIn("# Demo", r1["result"]["text"])
            finally:
                client1.close()
            # Also verify the real SpaceEnvironment.for_worker path (used by TaskHost.start).
            from harness.space.environment import SpaceEnvironment
            space_env = SpaceEnvironment.for_worker(w1.endpoint, timeout=15, approval_key=w1.approval_key)
            try:
                space_env.tools()
                self.assertIn("tick", space_env.host_controls)
            finally:
                space_env.close()
            ws_provider.release("run-1")

            opts2, _ = ws_provider.bind("ssh", self.root / "inproc-run2", {
                "ssh": {"host": "gpu-node", "folder": str(self.repo)},
            })
            w2 = ws_provider.acquire("run-2", "ssh", options=opts2)
            self.assertIs(w1, w2)
            self.assertEqual(len(spawns), 1)
            ws_provider.release("run-2")
            ws_provider.close()
            # Closing the workspace provider stops the local worker HTTP server without
            # killing the shared host SSH bridge in ssh.POOL.
            self.assertTrue(pool.get({"target": "gpu-node"})._alive())

    def test_task_host_end_to_end_ssh_task_executes_command_and_reuses_bridge(self):
        from harness import settings
        from harness.host.tasks import TaskHost, TaskServer
        from harness.runtime.decision.model import ScriptedChat

        spawns = []

        def counting_spawn(target: str, port: int | None):
            spawns.append((target, port))
            return _local_bridge_spawn(target, port)

        pool = ssh.SshPool(spawn_fn=counting_spawn)
        self.addCleanup(pool.close_all)
        home = self.root / "e2e-home"
        (home / "libraries" / "ssh").mkdir(parents=True)

        with mock.patch.object(ssh, "POOL", pool), \
                mock.patch.dict(os.environ, {settings.KEY: "test-no-network", "HARNESS_HOME": str(home)}):
            chat = ScriptedChat([
                f"<python>\nres = run_command({[sys.executable, '-c', 'print(\"ssh-gpu-ok\")']!r})\n"
                "print(res['output']['text'].strip())\n</python>",
                "SSH GPU check done: ssh-gpu-ok.",
            ])
            app = TaskHost(self.root / "e2e-host", chat=chat, verifier=ScriptedChat([]))
            app.settings.update({"learning": {"mode": "frozen"}, "limits": {"agent_depth": 0}})
            server = TaskServer(("127.0.0.1", 0), app, token="test")
            try:
                run = app.start(server, "Check GPU via SSH", agent="harness", workspace="ssh",
                                ssh={"host": "gpu-node", "folder": str(self.repo)})
                conversation = server.conversations[run]
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if conversation.status == "ERROR" or (
                        conversation.kernel is not None and chat.calls == 2 and conversation.waiting_since is not None
                    ):
                        break
                    time.sleep(0.05)
                events_text = (Path(conversation.directory) / "events.jsonl").read_text(encoding="utf-8")
                self.assertEqual(conversation.status, "IDLE", events_text[-4000:])
                self.assertEqual(conversation.summary["model_calls"], 2)
                self.assertEqual(conversation.summary["cells"], 1)
                self.assertEqual(conversation.result, "SSH GPU check done: ssh-gpu-ok.")
                self.assertEqual(len(spawns), 1)
            finally:
                for conversation in list(server.conversations.values()):
                    conversation.close()
                for thread in list(app._threads.values()):
                    thread.join(15)
                app.close()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
