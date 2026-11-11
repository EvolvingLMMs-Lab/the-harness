"""A program prepared while another ran is set aside when the environment reported, during
that program, an event its session declares as voiding one (ahead_voiding_event_kinds): it
was written before the event, so its own <assume> check cannot know of it."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import helpers  # noqa: F401
from harness.config.agent import TaskConfig
from harness.core.worker import create_server
from harness.runtime.decision import loop as decisions
from harness.runtime.decision.model import ScriptedChat
from harness.runtime.task.run import TaskRun

from view_fixtures import ScreenEnvironment, screen_session

FIXTURES = os.pathsep.join([str(Path(__file__).resolve().parent), os.environ.get("PYTHONPATH", "")])
PREPARED = '<assume>result["status"] == "ok"</assume>\n<python>\nprint("prepared")\n</python>'


def _reporting(options, raised):
    """The screen session declaring the observation events `scene_changed` (which voids a
    program prepared ahead) and `window_opened` (which does not); its environment reports
    `raised` (an event kind, or None) once, at the second step of an execution."""
    from harness.runtime.events import Event

    session = screen_session(options)
    session.observation_event_kinds = frozenset({"scene_changed", "window_opened"})
    session.ahead_voiding_event_kinds = frozenset({"scene_changed"})

    def take(state):
        if raised is None or state["step"] < 2 or session.__dict__.get("_reported"):
            return ()
        session._reported = True
        return (Event(raised, "environment", {}, state["step"]),)

    session._take_observation_events = take
    return session


def quiet_session(options):
    return _reporting(options, None)


def voiding_session(options):
    return _reporting(options, "scene_changed")


def observing_session(options):
    return _reporting(options, "window_opened")


def undeclared_session(options):
    return _reporting(options, "light_flickered")


def episode(bootstrap):
    """One episode whose first program is long enough to be thought past: (the trace's
    `ahead` record of program 1, the programs that ran, what the model was told)."""
    environment = ScreenEnvironment()
    worker = create_server(environment, port=0)
    threading.Thread(target=worker.serve_forever, daemon=True).start()
    chat = ScriptedChat(["<python>\ntype_text(8, seconds=0.2)\n</python>", PREPARED, "<finish>done</finish>"],
                        ahead=True)
    told = []
    complete = chat.complete
    chat.complete = lambda system, messages: (told.append(json.dumps(messages[-1])), complete(system, messages))[1]
    with tempfile.TemporaryDirectory() as root:
        try:
            config = TaskConfig(
                path=Path("."), environment={"endpoint": f"http://127.0.0.1:{worker.server_address[1]}"},
                main={"model": "scripted"}, system_prompt="You act by writing programs.",
                runtime={"bootstrap": f"test_ahead_events:{bootstrap}", "verifier": False, "isolation": False,
                         "think_while_acting": "on", "skills": ["desktop"]},
                task="free", seeds=[0], max_model_calls=12, max_wall_seconds=120, embodiment="desktop")
            with mock.patch.dict(os.environ, {"PYTHONPATH": FIXTURES}), \
                    mock.patch.object(decisions, "AHEAD_SECONDS", 0.05):
                TaskRun(config, 0, Path(root) / "seed-0", chat=chat).run()
            records = [json.loads(line) for line in
                       (Path(root) / "seed-0" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        finally:
            worker.shutdown()
            worker.server_close()
    ahead = next(record for record in records if record["event"] == "ahead" and record["program"] == 1)
    return ahead, [record["code"] for record in records if record["event"] == "cell"], "\n".join(told)


class AheadEventsTest(unittest.TestCase):
    def test_a_voiding_event_sets_the_prepared_program_aside(self):
        ahead, programs, told = episode("voiding_session")
        self.assertEqual(ahead["outcome"], "discarded")
        self.assertEqual(ahead["why"], "the environment reported scene_changed while the program ran")
        self.assertEqual(len(programs), 1)
        self.assertIn("Executions: observe: scene_changed", told)

    def test_without_an_event_the_prepared_program_runs(self):
        ahead, programs, _ = episode("quiet_session")
        self.assertEqual(ahead["outcome"], "used")
        self.assertEqual(programs[1].strip(), 'print("prepared")')

    def test_an_observation_event_not_declared_as_voiding_changes_nothing(self):
        ahead, programs, told = episode("observing_session")
        self.assertEqual(ahead["outcome"], "used")
        self.assertEqual(programs[1].strip(), 'print("prepared")')
        self.assertIn("Executions: observe: window_opened", told)

    def test_an_event_of_a_kind_the_session_does_not_declare_changes_nothing(self):
        ahead, programs, told = episode("undeclared_session")
        self.assertEqual(ahead["outcome"], "used")
        self.assertEqual(programs[1].strip(), 'print("prepared")')
        self.assertIn("Executions: observe: light_flickered", told)


if __name__ == "__main__":
    unittest.main()
