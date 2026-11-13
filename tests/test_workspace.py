"""Real target processes and the production worker/kernel contract; no model calls."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import helpers
from harness.core.worker import create_server
from harness.runtime.execution.kernel import Kernel, DEFAULT_BOOTSTRAP
from harness_workspace.worker import WorkspaceEnvironment
from harness.host.tasks import TaskHost, TaskServer
from harness.runtime.decision.model import ScriptedChat
from harness import settings


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.worker = WorkspaceEnvironment(self.root, self.base / "outputs")
        self.addCleanup(self.worker.close)
        self.observation = self.worker.reset("free", 0)

    def operate(self, **command):
        return self.worker._call_tick(self.observation.episode_id, self.worker._cursor.step, command)["result"]

    def wait(self, identifier):
        process = self.worker.processes[identifier]
        self.assertTrue(process.done.wait(15))
        return process.result()

    def test_target_environment_output_and_nonzero_exit(self):
        result = self.operate(type="run", command=[sys.executable, "-c",
            "import os; print(os.getcwd()); print('PYTHONPATH' in os.environ); print('MIDDLE'); print('x'*20000); raise SystemExit(7)"])
        result = self.wait(result["process_id"])
        self.assertEqual(result["exit_code"], 7)
        raw = Path(result["output_file"]).read_text()
        self.assertIn(str(self.root), raw)
        self.assertIn("False", raw)
        self.assertNotIn("MIDDLE", result["output"]["text"])
        self.assertIn("MIDDLE", self.operate(type="output", process_id=result["process_id"])["text"])

    def test_file_conflict_and_root(self):
        created = self.operate(type="write", path="note.txt", text="first")
        self.assertEqual(self.operate(type="read", path="note.txt")["text"], "first")
        (self.root / "note.txt").write_text("user edit")
        result = self.operate(type="write", path="note.txt", text="overwrite", expected=created["sha256"])
        self.assertEqual(result["error"], "conflict")
        self.assertEqual((self.root / "note.txt").read_text(), "user edit")
        self.assertEqual(self.operate(type="read", path="../outside")["error"], "ValueError")

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_new_file_gets_the_users_mode_and_a_replaced_one_keeps_its_own(self):
        umask = os.umask(0o022)
        os.umask(umask)
        self.operate(type="write", path="new.txt", text="one")
        self.assertEqual((self.root / "new.txt").stat().st_mode & 0o777, 0o666 & ~umask)
        script = self.root / "run.sh"
        script.write_text("echo one\n")
        script.chmod(0o750)
        self.operate(type="write", path="run.sh", text="echo two\n", expected=hashlib.sha256(b"echo one\n").hexdigest())
        self.assertEqual(script.stat().st_mode & 0o777, 0o750)

    def test_timeout_and_background_cleanup(self):
        started = self.operate(type="run", command=[sys.executable, "-c", "import time; time.sleep(60)"], timeout=.2)
        self.assertEqual(self.wait(started["process_id"])["status"], "timeout")
        background = self.operate(type="run", command=[sys.executable, "-c", "import time; time.sleep(60)"], timeout=60)
        self.worker.close()
        result = self.wait(background["process_id"])
        self.assertEqual(result["status"], "session_closed")
        self.assertIsNotNone(result["exit_code"])

    def test_stale_cursor_cannot_repeat_a_command(self):
        self.operate(type="write", path="a", text="one")
        with self.assertRaisesRegex(ValueError, "Stale"):
            self.worker._call_tick(self.observation.episode_id, 0, {"type":"write", "path":"b", "text":"two"})
        self.assertFalse((self.root / "b").exists())

    def test_kernel_controls_project_without_importing_it(self):
        (self.root / "harness.py").write_text("VALUE = 'target-only'\n")
        server = create_server(self.worker, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        kernel = Kernel(DEFAULT_BOOTSTRAP, {"endpoint": f"http://127.0.0.1:{server.server_address[1]}",
                        "episode_id": self.observation.episode_id, "embodiment":"workspace", "skills":["workspace"],
                        "isolation": {"sandbox":False}}, log_path=self.base / "kernel.log")
        self.addCleanup(kernel.close)
        code = f"r = run_command({[sys.executable, '-c', 'import harness; print(harness.VALUE)']!r}); print(r)"
        result = kernel.run(code, timeout=20)
        self.assertEqual(result["status"], "ok", result)
        self.assertIn("target-only", result["stdout"])
        self.assertIn("'exit_code': 0", result["stdout"])

    def test_native_host_binds_project_and_releases_processes(self):
        self.check_host_run()

    def test_pausing_a_pending_command_stops_the_real_process(self):
        server = create_server(self.worker, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        kernel = Kernel(DEFAULT_BOOTSTRAP, {"endpoint": f"http://127.0.0.1:{server.server_address[1]}",
                        "episode_id": self.observation.episode_id, "embodiment": "workspace", "skills": ["workspace"],
                        "isolation": {"sandbox": False}}, log_path=self.base / "pending.log")
        self.addCleanup(kernel.close)
        results = []
        command = [sys.executable, "-c", "import time; time.sleep(60)"]
        thread = threading.Thread(target=lambda: results.append(kernel.run(f"print(run_command({command!r}))", timeout=20)))
        thread.start()
        deadline = time.monotonic() + 5
        while not self.worker.processes and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(len(self.worker.processes), 1)
        kernel.pause()
        thread.join(15)
        self.assertFalse(thread.is_alive())
        process = next(iter(self.worker.processes.values()))
        self.assertTrue(process.done.wait(5))
        self.assertEqual(process.result()["status"], "cancelled")
        self.assertIsNotNone(process.process.poll())
        self.assertEqual(self.worker._cursor.step, 1)  # polling never redispatches the command

    def test_completed_reads_stream_evidence_without_growing_the_cell_reply(self):
        (self.root / "large.txt").write_text("BEGIN\n" + "x" * 40000 + "\nMIDDLE\n" + "y" * 19000)
        server = create_server(self.worker, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        records = []
        kernel = Kernel(DEFAULT_BOOTSTRAP, {"endpoint": f"http://127.0.0.1:{server.server_address[1]}",
                        "episode_id": self.observation.episode_id, "embodiment": "workspace", "skills": ["workspace"],
                        "isolation": {"sandbox": False}}, log_path=self.base / "reads.log", on_span=records.append)
        self.addCleanup(kernel.close)
        result = kernel.run("for _ in range(30):\n    r = read_file('large.txt', limit=64000)\n"
                            "assert 'MIDDLE' in r['text']\nprint(r['sha256'])", timeout=20)
        self.assertEqual(result["status"], "ok", result)
        self.assertLess(len(json.dumps(result)), 10000)
        receipts = [record for record in records if record.get("kind") == "execution_event"]
        self.assertEqual(len(receipts), 30)
        reference = receipts[-1]["execution"]["event"]["detail"]["evidence"]
        raw = json.loads(Path(reference["path"]).read_text(encoding="utf-8"))
        self.assertEqual(raw["text"], (self.root / "large.txt").read_bytes().decode("utf-8"))
        self.assertEqual(result["event_counts"], {"COMPLETED": 30})
        self.assertEqual(result["events"], [])

    def test_budget_ending_is_not_a_success_and_releases_processes(self):
        self.check_host_run(budget=True)

    def test_infinite_read_loop_can_be_interrupted_and_the_next_program_runs(self):
        (self.root / "data.txt").write_bytes(b"a" * 60000)
        server = create_server(self.worker, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        kernel = Kernel(DEFAULT_BOOTSTRAP, {"endpoint": f"http://127.0.0.1:{server.server_address[1]}",
                        "episode_id": self.observation.episode_id, "embodiment": "workspace", "skills": ["workspace"],
                        "isolation": {"sandbox": False}}, log_path=self.base / "loop.log")
        self.addCleanup(kernel.close)
        results = []
        thread = threading.Thread(target=lambda: results.append(kernel.run(
            "while True: read_file('data.txt', limit=64000)", timeout=20)))
        thread.start()
        deadline = time.monotonic() + 10
        while self.worker._cursor.step < 100 and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertGreaterEqual(self.worker._cursor.step, 100)
        kernel.pause()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertLess(len(json.dumps(results[0])), 10000)
        self.assertIn(results[0]["status"], ("escalated", "error"))
        kernel.resume()
        self.assertEqual(kernel.run("print('next decision')", timeout=5)["stdout"].strip(), "next decision")

    def test_target_output_limit_retains_partial_output_and_stops_process(self):
        with mock.patch("harness_workspace.worker.OUTPUT_LIMIT", 10000):
            result = self.operate(type="run", command=[sys.executable, "-c",
                                  "import sys\nwhile True: sys.stdout.write('x' * 1000); sys.stdout.flush()"])
            ended = self.wait(result["process_id"])
        self.assertEqual(ended["status"], "output_limit")
        self.assertIsNotNone(ended["exit_code"])
        self.assertEqual(Path(ended["output_file"]).stat().st_size, 10000)

    def test_host_runs_from_a_symlinked_data_directory(self):
        target = self.base / "real-host"
        target.mkdir()
        alias = self.base / "host-alias"
        try:
            alias.symlink_to(target, target_is_directory=True)
        except OSError as error:
            # (Windows without the privilege to make links.)
            self.skipTest(f"this account cannot make a symbolic link: {error}")
        self.check_host_run(host_directory=alias)

    def check_host_run(self, budget=False, host_directory=None):
        # Real host -> pool -> worker subprocess -> kernel -> target, with only model replies scripted.
        with mock.patch.dict(os.environ, {settings.KEY: "test-no-network", "HARNESS_HOME": str(self.base / "home")}), \
                mock.patch("harness_workspace.host.environment_python", return_value=sys.executable):
            (self.base / "home/libraries/project").mkdir(parents=True)
            chat = ScriptedChat([
                "<python>\nprint(write_file('result.txt', 'native target'))\n"
                f"print(start_process({[sys.executable, '-c', 'import time; time.sleep(60)']!r}))\n</python>",
                "<finish>Wrote the requested file.</finish>"])
            app = TaskHost(host_directory or self.base / "host", chat=chat, verifier=ScriptedChat([]))
            app.settings.update({"learning": {"mode": "frozen"}, "limits": {"agent_depth": 0}})
            server = TaskServer(("127.0.0.1", 0), app, token="test")
            try:
                run = app.start(server, "Write result.txt", agent="harness", folder=str(self.root),
                                budget={"max_model_calls": 1} if budget else None)
                conversation = server.conversations[run]
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if conversation.status == "ERROR" or conversation.kernel is not None and chat.calls == (1 if budget else 2) and conversation.waiting_since is not None:
                        break
                    time.sleep(.05)
                # The turn is over (an answer, or the budget): the conversation waits until it is closed.
                self.assertEqual(conversation.status, "IDLE", (Path(conversation.directory) / "events.jsonl").read_text()[-6000:])
                conversation.close()
                app._threads[run].join(15)
                deadline = time.monotonic() + 15
                while app.workspaces.of(run) is not None and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertEqual(conversation.status, "FINISHED", (Path(conversation.directory) / "events.jsonl").read_text()[-6000:])
                self.assertEqual((self.root / "result.txt").read_text(), "native target")
                self.assertEqual(conversation.workspace_kind, "project")
                self.assertEqual(conversation.summary["status"], "budget_exhausted" if budget else "finished")
                self.assertIsNone(conversation.summary["success"])
                trace_records = [json.loads(line) for line in
                                 (Path(conversation.directory) / "events.jsonl").read_text().splitlines()]
                executions = [row["execution"] for row in trace_records if row["event"] == "execution_event"]
                self.assertEqual(len(executions), 2)
                written = json.loads(Path(executions[0]["event"]["detail"]["evidence"]["path"]).read_text())
                self.assertEqual(written["sha256"], hashlib.sha256(b"native target").hexdigest())
                evidence = Path(conversation.directory) / "artifacts/evidence"
                records = [json.loads(line) for line in (evidence / "index.jsonl").read_text().splitlines()]
                ended = [row for row in records if row["kind"] == "process_end"]
                self.assertEqual(len(ended), 1)
                result = json.loads((evidence / ended[0]["payload"]).read_text())
                self.assertEqual(result["status"], "session_closed")
                self.assertIsNotNone(result["exit_code"])

            finally:
                for conversation in server.conversations.values():
                    conversation.close()
                app.close()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
