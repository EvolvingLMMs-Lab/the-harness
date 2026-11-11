"""A run is one model and the units it starts: every program runs as a unit beside the
others, the model's turn is never held, and finish, pause, a user's message and a direct
action are restated on units. One test per property."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import helpers  # noqa: F401
from harness.config.agent import TaskConfig
from harness.core.worker import create_server
from harness.runtime.decision.model import ScriptedChat
from harness.runtime.execution.kernel import Kernel
from harness.runtime.task.run import TaskRun

from view_fixtures import ScreenEnvironment

FIXTURES = os.pathsep.join([str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "src"),
                            os.environ.get("PYTHONPATH", "")])
PLAIN = "harness.runtime.execution.kernel:PlainSession"


def texts(message) -> str:
    content = message["content"]
    return content if isinstance(content, str) else "\n".join(part.get("text", "") for part in content)


def program(body):
    return f"<python>\n{body}\n</python>"


class Recording(ScriptedChat):
    """A scripted model that keeps its requests; a reply may be a function of the request's
    last message (called when the request comes)."""

    def __init__(self, replies):
        super().__init__(replies)
        self.requests = []

    def complete(self, system, messages):
        self.requests.append(json.loads(json.dumps(messages)))
        reply = super().complete(system, messages)
        if callable(reply.text):
            reply.text = reply.text(texts(messages[-1]))
        return reply


class Episode:
    """One episode on the screen worker, run on a thread so that a test may act while it runs."""

    def __init__(self, replies, *, runtime=None, seconds=0.0, interactive=False):
        self.environment = ScreenEnvironment(seconds)
        self.worker = create_server(self.environment, port=0)
        threading.Thread(target=self.worker.serve_forever, daemon=True).start()
        self.chat = Recording(replies)
        self.root = tempfile.TemporaryDirectory()
        config = TaskConfig(
            path=Path("."), environment={"endpoint": f"http://127.0.0.1:{self.worker.server_address[1]}"},
            main={"model": "scripted"}, system_prompt="You act by writing programs.",
            runtime={"bootstrap": "view_fixtures:screen_session", "verifier": False, "isolation": False,
                     "skills": ["desktop"], "turn_grace_seconds": 0.3, **(runtime or {})},
            task="free", seeds=[0], max_model_calls=12, max_wall_seconds=120, embodiment="desktop")
        self.directory = Path(self.root.name) / "seed-0"
        self.run = TaskRun(config, 0, self.directory, chat=self.chat, interactive=interactive)
        self.summary = None

    def __enter__(self):
        self.patch = mock.patch.dict(os.environ, {"PYTHONPATH": FIXTURES})
        self.patch.start()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def _run(self):
        self.summary = self.run.run()

    def records(self, event=None):
        path = self.directory / "events.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        return [row for row in rows if event is None or row["event"] == event]

    def until(self, ready, seconds=30.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if ready():
                return True
            time.sleep(0.05)
        return False

    def end(self):
        self.thread.join(60)
        return self.summary

    def __exit__(self, *_):
        self.run.close()
        self.thread.join(30)
        self.patch.stop()
        self.worker.shutdown()
        self.worker.server_close()
        self.root.cleanup()


def kernel(ended):
    env = {**os.environ, "PYTHONPATH": FIXTURES}
    return Kernel(PLAIN, {}, python=sys.executable, env=env,
                  on_span=lambda record: ended.append(record) if record.get("op") == "unit_end" else None)


def wait_for(ready, seconds=20.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not ready():
        time.sleep(0.02)
    return ready()


class KernelUnits(unittest.TestCase):
    def test_a_long_program_gives_the_turn_back_within_the_grace_and_goes_on(self):
        ended = []
        process = kernel(ended)
        try:
            began = time.monotonic()
            reply = process.start("import time\ntime.sleep(1.5)\nprint('late')", grace=0.2)
            self.assertEqual(reply["status"], "running")
            self.assertLess(time.monotonic() - began, 1.2)
            self.assertTrue(wait_for(lambda: ended))
            self.assertEqual((ended[0]["unit"], ended[0]["status"], ended[0]["stdout"]), (reply["unit"], "ok", "late\n"))
        finally:
            process.close()

    def test_programs_side_by_side_keep_their_own_output_and_result(self):
        ended = []
        process = kernel(ended)
        try:
            first = process.start("import time\nprint('one')\ntime.sleep(1.0)\nprint('one again')\n1 / 0", grace=0.1)
            second = process.start("print('two')", grace=5)
            self.assertEqual(first["status"], "running")
            self.assertEqual((second["status"], second["stdout"]), ("ok", "two\n"))
            self.assertTrue(wait_for(lambda: ended))
            self.assertEqual((ended[0]["cell"], ended[0]["status"], ended[0]["stdout"]), (1, "error", "one\none again\n"))
            self.assertIn("ZeroDivisionError", ended[0]["error"])
        finally:
            process.close()


class RunOnUnits(unittest.TestCase):
    def test_what_a_program_starts_outlives_it_and_ends_with_the_model(self):
        keep = ("import time\ndef keep():\n    while True:\n        time.sleep(0.05)\n"
                "spawn(keep, name='keeper')\nwhen(lambda view: view['step'] >= 3, 'stop', name='limit')")
        with Episode([program(keep), program("type_text(5)"), "<finish>done</finish>"]) as episode:
            summary = episode.end()
            cells = episode.records("cell")
            ends = {row["id"]: row["status"] for row in episode.records("entry_end")}
            starts = {row["name"]: row["id"] for row in episode.records("entry_start")}
            requests = episode.chat.requests
        self.assertEqual(summary["status"], "finished")
        # The unit the first program started still runs when the model is told of that program.
        self.assertIn("keeper", texts(requests[1][-1]))
        self.assertIn("Units running", texts(requests[1][-1]))
        # The rule the first program set stops the second program's execution.
        self.assertEqual(cells[1]["result"]["escalation"]["event"]["kind"], "GUARD_TRIGGERED")
        self.assertEqual(cells[1]["result"]["state"]["step"], 3)
        # It ends with the model: the finish cancels it.
        self.assertEqual(ends[starts["keeper"]], "cancelled")

    def test_the_turn_comes_back_while_a_program_runs_and_finish_ends_its_units(self):
        with Episode([program("type_text(100, seconds=0.2)"), program("print('beside', get_state()['step'])"),
                      "<finish>done</finish>"]) as episode:
            summary = episode.end()
            cells = {row["number"]: row["result"] for row in episode.records("cell")}
            requests = episode.chat.requests
        self.assertEqual(summary["status"], "finished")
        self.assertIn("Program 1 is still running", texts(requests[1][-1]))
        self.assertEqual(cells[2]["status"], "ok")
        self.assertIn("beside", cells[2]["stdout"])
        self.assertEqual(cells[1]["status"], "cancelled")

    def test_a_pause_stops_the_units_and_the_model_is_called_again_after_resume(self):
        with Episode([program("type_text(100, seconds=0.2)"), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 60}) as episode:
            self.assertTrue(episode.until(lambda: episode.environment.step >= 2))
            episode.run.pause()
            self.assertTrue(episode.until(lambda: episode.records("cell")))
            time.sleep(0.5)
            calls = len(episode.chat.requests)
            episode.run.resume()
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
            requests = episode.chat.requests
        self.assertEqual(calls, 1)
        self.assertEqual(cell["escalation"]["event"]["kind"], "USER_PAUSED")
        self.assertIn("USER_PAUSED", texts(requests[1][-1]))
        self.assertEqual(summary["status"], "finished")

    def test_a_user_message_is_an_event_to_the_model_and_stops_no_program(self):
        seen = {}

        def after_message(told):
            seen["told"] = told
            return program("print('still', get_state()['step'])")

        with Episode([program("type_text(12, seconds=0.2)"), after_message, "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 60}, interactive=True) as episode:
            self.assertTrue(episode.until(lambda: episode.environment.step >= 2))
            episode.run.send_message("how far are you?")
            summary = episode.end()
            cells = {row["number"]: row["result"] for row in episode.records("cell")}
        self.assertEqual(summary["status"], "finished")
        # The program that held the turn went on to its end; the message reached the model after it.
        self.assertEqual((cells[1]["status"], cells[1]["state"]["step"]), ("ok", 12))
        self.assertIn("how far are you?", seen["told"])

    def test_a_direct_action_is_a_program_of_one_call(self):
        with Episode(["<action>2</action>", "<finish>done</finish>"],
                     runtime={"mode": "direct", "actions": "view_fixtures:actions"}) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]
        self.assertEqual(summary["status"], "finished")
        self.assertEqual((cell["action"], cell["code"], cell["result"]["status"], cell["result"]["state"]["step"]),
                         ("2", "type_text(2)", "ok", 2))


if __name__ == "__main__":
    unittest.main()
