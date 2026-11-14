"""A run is one model and the units it starts. One small test per step of the design."""
from contextlib import contextmanager
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import helpers  # noqa: F401
from harness.config.agent import TaskConfig
from harness.core.worker import create_server
from harness.runtime.decision.model import USAGE, ChatReply, ScriptedChat
from harness.runtime.execution.kernel import DEFAULT_BOOTSTRAP, Kernel
from harness.runtime.execution.managed import Admission
from harness.runtime.task.delegation import Agents, Place
from harness.runtime.task.run import TaskRun, saved

from view_fixtures import ScreenEnvironment, screen_session

FIXTURES = os.pathsep.join([str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "src"),
                            os.environ.get("PYTHONPATH", "")])


def texts(message) -> str:
    content = message["content"]
    return content if isinstance(content, str) else "\n".join(part.get("text", "") for part in content)


def program(body):
    return f"<python>\n{body}\n</python>"


class Recording(ScriptedChat):
    """A scripted model that keeps its requests and takes a reply for every call."""

    def __init__(self, replies):
        super().__init__(replies, waits=False)
        self.requests = []

    def complete(self, system, messages):
        self.requests.append(json.loads(json.dumps(messages)))
        return super().complete(system, messages)


class Episode:
    """One episode on the screen worker, run on a thread so that a test may act while it runs."""

    def __init__(self, replies, *, runtime=None, seconds=0.0, interactive=False, tells=False, pauses=False,
                 references=()):
        self.environment = ScreenEnvironment(seconds, tells=tells, pauses=pauses, references=references)
        self.worker = create_server(self.environment, port=0)
        threading.Thread(target=self.worker.serve_forever, daemon=True).start()
        self.chat = Recording(replies)
        self.root = tempfile.TemporaryDirectory()
        config = TaskConfig(
            path=Path("."), environment={"endpoint": f"http://127.0.0.1:{self.worker.server_address[1]}"},
            main={"model": "scripted"}, system_prompt="You act by writing programs.",
            runtime={"bootstrap": "view_fixtures:screen_session", "verifier": False, "isolation": False,
                     "skills": ["desktop"], "turn_grace_seconds": 0.3, "purpose": "optional", "reflex_trials": "optional",
                     **(runtime or {})},
            task="free", seeds=[0], max_model_calls=12, max_wall_seconds=120, embodiment="desktop")
        self.directory = Path(self.root.name) / "seed-0"
        self.run = TaskRun(config, 0, self.directory, chat=self.chat, interactive=interactive)
        self.summary = None

    def __enter__(self):
        self.patch = mock.patch.dict(os.environ, {"PYTHONPATH": FIXTURES})
        self.patch.start()
        self.thread = threading.Thread(target=self._run, daemon=True)
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

    def start(self):
        if not self.thread.is_alive() and self.summary is None:
            self.thread.start()

    def end(self):
        self.start()
        self.thread.join(90)
        return self.summary

    def __exit__(self, *_):
        self.run.close()
        if self.thread.is_alive():
            self.thread.join(30)
        self.patch.stop()
        self.worker.shutdown()
        self.worker.server_close()
        self.root.cleanup()


class RunOnUnits(unittest.TestCase):
    def test_s1_the_turn_comes_back_while_a_program_runs_and_finish_ends_its_units(self):
        with Episode([program("type_text(100, seconds=0.2)"), program("print('beside', get_state()['step'])"),
                      "<finish>done</finish>"]) as episode:
            summary = episode.end()
            cells = {row["number"]: row["result"] for row in episode.records("cell")}
            requests = episode.chat.requests
        self.assertEqual(summary["status"], "finished")
        self.assertIn("Program 1 is still running", texts(requests[1][-1]))
        # The second program ran beside the first, with its own output and result.
        self.assertEqual((cells[2]["status"], cells[2]["stdout"].split()[0]), ("ok", "beside"))
        self.assertEqual(cells[1]["status"], "cancelled")

    def test_s2_the_model_waits_by_choice_and_a_unit_that_ends_wakes_it(self):
        with Episode([program("type_text(8, seconds=0.2)"), "<wait>30</wait>", "<finish>done</finish>"]) as episode:
            summary = episode.end()
            waits = episode.records("wait_end")
            requests = episode.chat.requests
        self.assertEqual(summary["status"], "finished")
        self.assertEqual([row["why"] for row in waits], ["unit"])
        self.assertLess(waits[0]["seconds"], 20)
        # No call was made while it waited: the start, the turn that came back, the wait's end.
        self.assertEqual(len(requests), 3)
        self.assertIn("a unit you started ended", texts(requests[2][-1]))
        self.assertIn("Program 1 ended: by itself", texts(requests[2][-1]))


    def test_every_call_is_told_how_things_stand_also_when_a_wait_only_ran_out(self):
        with Episode([program("type_text(100, seconds=0.2)"), "<wait>1.5</wait>", "<finish>done</finish>"]) as episode:
            summary = episode.end()
            waits = episode.records("wait_end")
            last = episode.chat.requests[2][-1]
        self.assertEqual(summary["status"], "finished")
        self.assertEqual([row["why"] for row in waits], ["time"])
        # First what the wait came to, last how things stand now: once, whatever the call is for.
        self.assertTrue(last["content"][0]["text"].startswith("Wait ended after 1.5 s: its time is over."))
        ambient = [part for part in last["content"] if part.get("ambient")]
        self.assertEqual((len(ambient), last["content"][-1]), (1, ambient[0]))
        # The state is the one the program has made meanwhile, not the one of its start.
        self.assertGreater(int(re.search(r'Computer state: \{"step": (\d+)', ambient[0]["text"]).group(1)), 0)
        self.assertRegex(ambient[0]["text"], r"Units running: e\d+ program 1 \(program, \d+ s")
        # What the run has left is the host's to keep: no countdown comes with the call.
        for countdown in ("calls left", "Env steps used", "time left"):
            self.assertNotIn(countdown, ambient[0]["text"])

    def test_a_run_that_asks_for_it_is_told_what_it_has_left_with_every_call(self):
        with Episode([program("print('x')"), "<finish>done</finish>"], runtime={"tell_budget": "always"}) as episode:
            summary = episode.end()
            told = texts(episode.chat.requests[1][-1])
        self.assertEqual(summary["status"], "finished")
        self.assertRegex(told, r"Env steps used: \d+ \(20 per second\); left: \d+")
        self.assertIn("Model calls left: 11", told)

    def test_a_message_of_the_user_ends_a_wait_and_is_told_with_the_call_that_follows(self):
        with Episode([program("type_text(100, seconds=0.2)"), "<wait>30</wait>", "<finish>done</finish>"]) as episode:
            episode.start()
            self.assertTrue(episode.until(lambda: episode.records("wait")))
            episode.run.send_message("how far are you?")
            summary = episode.end()
            waits = episode.records("wait_end")
            last = texts(episode.chat.requests[-1][-1])
        self.assertEqual(summary["status"], "finished")
        self.assertEqual((waits[0]["why"], waits[0]["seconds"] < 10), ("message", True))
        self.assertIn("Message from the user: how far are you?", last)

    def test_what_a_running_unit_printed_is_read_while_it_runs_and_stays_in_its_result(self):
        with Episode([program("print('alpha')\ntype_text(100, seconds=0.2)"),
                      program("print('seen', [output_of(unit.id) for unit in entries() if unit.cell == 1])"),
                      "<wait>1.5</wait>", "<finish>done</finish>"]) as episode:
            summary = episode.end()
            cells = {row["number"]: row["result"] for row in episode.records("cell")}
            requests = episode.chat.requests
        self.assertEqual(summary["status"], "finished")
        self.assertIn("seen ['alpha\\n']", cells[2]["stdout"])
        self.assertIn("alpha", cells[1]["stdout"])
        # The wait's end says when the unit that still runs last printed.
        self.assertRegex(texts(requests[3][-1]), r"Units running: e\d+ .*\(program, \d+ s, last printed \d+ s ago\)")

    def test_s3_a_rule_starts_its_program_when_a_fact_it_reads_changes(self):
        body = "\n".join([
            "def refill():",
            "    type_text(2)",
            "    facts.set('refills', facts.get('refills', 0) + 1)",
            "    facts.set('low', False)",
            "set_reflex('refill', lambda view: view['facts'].get('low'), refill, priority=5)",
            "facts.set('low', True)",
            "import time",
            "while facts.get('low'):",
            "    time.sleep(0.05)",
            "print('refills', facts.get('refills'), get_state()['step'])"])
        with Episode([program(body), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
            started = [row for row in episode.records("entry_start") if row.get("rule") == "refill"]
        self.assertEqual(summary["status"], "finished")
        self.assertEqual(cell["stdout"].strip(), "refills 1 2")
        self.assertEqual([row["priority"] for row in started], [5.5])


    def test_s4_a_rule_that_takes_the_embodiment_ends_the_lower_call_and_tells_the_model_at_once(self):
        asked = "\n".join([
            "def urgent():",
            "    facts.set('urgent_at', get_state()['step'])",
            "    type_text(1)",
            "    facts.set('done', True)",
            "set_reflex('urgent', lambda view: view['step'] >= view['facts'].get('at', 3) and not view['facts'].get('done'),",
            "           urgent, priority=5)",
            "typed = spawn(lambda: type_text(8, seconds=0.05), name='typing', restart=True).wait()",
            "print('restarts', typed.restarts, get_state()['step'] - facts.get('urgent_at'))"])
        default = "\n".join([
            "facts.set('at', get_state()['step'] + 3)",
            "facts.set('done', False)",
            "type_text(8, seconds=0.05)",
            "print('not reached')"])
        with Episode([program(asked), program(default), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            cells = {row["number"]: row["result"] for row in episode.records("cell")}
            preempted = [(row["rule"], row["name"], row["restart"]) for row in episode.records("preempted")]
            requests = episode.chat.requests
        self.assertEqual(summary["status"], "finished")
        # A unit that asked for it has its call started again when the rule's program is over: all eight keys anew.
        word, restarts, typed = cells[1]["stdout"].split()
        self.assertEqual((word, restarts), ("restarts", "1"))
        self.assertGreaterEqual(int(typed), 9)
        # By default the call ends there with PREEMPTED, and the program with it.
        self.assertEqual((cells[2]["status"], cells[2]["escalation"]["event"]["kind"], cells[2]["stdout"]),
                         ("escalated", "PREEMPTED", ""))
        self.assertEqual(preempted, [("urgent", "typing", True), ("urgent", "program 2", False)])
        # The model is told which rule took the environment from which program, each time.
        for request, name in ((requests[1], "typing"), (requests[2], "program 2")):
            told = texts(request[-1])
            self.assertIn("Event PREEMPTED from", told)
            self.assertIn('"rule": "urgent"', told)
            self.assertIn(f'"name": "{name}"', told)


    def test_a_program_at_a_priority_keeps_the_embodiment_from_the_reflexes_below_it_only(self):
        asked = "\n".join([
            "def urgent():",
            "    type_text(1)",
            "    facts.set('urgent_at', get_state()['step'])",
            "def fatal():",
            "    type_text(1)",
            "    facts.set('fatal_at', get_state()['step'])",
            # (Both under one group of priority 0: the program's priority is compared with the node that runs.)
            "set_reflex('survive', lambda view: True)",
            "set_reflex('urgent', lambda view: view.get('step', 0) >= 3 and not view['facts'].get('urgent_at'), urgent,",
            "           under='survive', priority=5)",
            "set_reflex('fatal', lambda view: view.get('step', 0) >= 3 and not view['facts'].get('fatal_at'), fatal,",
            "           under='survive', priority=9)",
            "with at_priority(7):",
            "    type_text(8, seconds=0.05)",
            "    facts.set('typed_at', get_state()['step'])",
            "at_priority(3)",
            "type_text(4, seconds=0.05)",
            "facts.set('ended_at', get_state()['step'])",
            "print('typed', [(row['name'], row['priority']) for row in reflexes('survive')])"])
        with Episode([program(asked), "<wait>10</wait>", "<wait>10</wait>", "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 30}, pauses=True) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
            held = [(row["rule"], row["by_name"]) for row in episode.records("held_back")]
            preempted = episode.records("preempted")
            facts = {row["name"]: row.get("data", row.get("value")) for row in episode.records("fact")}
            told = "\n".join(texts(request[-1]) for request in episode.chat.requests)
            running = "\n".join(texts(message) for request in episode.chat.requests for message in request)
        self.assertEqual(summary["status"], "finished")
        def step(name):
            return int(json.loads(facts[name]) if isinstance(facts[name], str) else facts[name])

        # The program typed all its keys and ended by itself. (A priority named outside a `with` holds nothing,
        # and says so.)
        self.assertEqual(cell["status"], "ok")
        self.assertIn("typed [('fatal', 9), ('urgent', 5)]", cell["stdout"])
        self.assertIn("at_priority(3) did nothing", cell["stdout"])
        self.assertEqual(preempted, [])
        # The reflex above it took the embodiment while it ran: its call was paused and went on.
        self.assertLess(step("fatal_at"), step("typed_at"))
        self.assertEqual([by for kind, _, by in episode.environment.held if kind == "pause"], ["fatal"])
        # The reflex below it did not: the model was told once that it was held back, and by which program.
        self.assertEqual(held, [("urgent", "program 1")])
        self.assertIn("Event HELD_BACK from", told)
        # It is of priority `later`: not told with the call the program's end made, told after the wait.
        ends = [texts(request[-1]) for request in episode.chat.requests]
        self.assertIn("Program 1 ended", ends[1])
        self.assertNotIn("HELD_BACK", ends[1])
        self.assertIn("Event HELD_BACK from", ends[2])
        # Judged again when the block had ended, its condition still held: it acted then, while the program
        # went on with what it does outside the block.
        self.assertGreater(step("urgent_at"), step("typed_at"))
        self.assertLess(step("urgent_at"), step("ended_at"))

    def test_code_that_runs_in_the_environment_asks_for_a_priority_for_one_action_of_it(self):
        asked = "\n".join([
            "def low():",
            "    type_text(1)",
            "    facts.set('low_at', get_state()['step'])",
            "set_reflex('low', lambda view: view.get('step', 0) >= 2 and not view['facts'].get('low_at'), low, priority=5)",
            "type_text(8, seconds=0.05)",
            "facts.set('typed_at', get_state()['step'])"])
        with Episode([program(asked), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}, pauses=True) as episode:
            # What runs in the environment holds it with 9 up to its sixth step, and says so with its state.
            episode.environment.asks = lambda step: 9 if step < 6 else None
            summary = episode.end()
            held = [row["rule"] for row in episode.records("held_back")]
            facts = {row["name"]: row.get("data", row.get("value")) for row in episode.records("fact")}
        self.assertEqual(summary["status"], "finished")

        def step(name):
            return int(json.loads(facts[name]) if isinstance(facts[name], str) else facts[name])

        # The reflex below it waited for that action to be over, then took the environment from the program.
        self.assertEqual(held, ["low"])
        self.assertGreaterEqual(step("low_at"), 6)
        self.assertLess(step("low_at"), step("typed_at"))

    def test_a_node_that_tells_has_its_turn_only_when_none_before_it_answers(self):
        body = "\n".join([
            "import time",
            "def handle():",
            "    facts.set('handled', facts.get('handled', 0) + 1)",
            "    facts.set('danger', False)",
            "set_reflex('trouble', lambda view: view['facts'].get('danger') or view['facts'].get('odd'))",
            "set_reflex('known', lambda view: view['facts'].get('danger'), handle, under='trouble', priority=2)",
            "set_reflex('unanswered', lambda view: True, 'UNANSWERED', under='trouble', priority=1)",
            "for kind in ('danger', 'odd', 'danger', 'odd'):",
            "    facts.set(kind, True)",
            "    time.sleep(0.6)",
            "    facts.set('told_' + kind, True)",
            "    facts.set(kind, False)",
            "    time.sleep(0.3)",
            "print('handled', facts.get('handled'))"])
        with Episode([program(body), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
            told = [row["reported"]["kind"] for row in episode.records("escalation")]
        self.assertEqual(summary["status"], "finished")
        # What a node before it answers is not told; what none answers is told, each time it comes.
        self.assertIn("handled 2", cell["stdout"])
        self.assertEqual(told, ["UNANSWERED", "UNANSWERED"])

    def test_what_a_node_does_itself_answers_what_none_under_it_answers(self):
        body = "\n".join([
            "import time",
            "def rest():",
            "    facts.set('rest', facts.get('rest', 0) + 1)",
            "    facts.set('odd', False)",
            "def known():",
            "    facts.set('known', facts.get('known', 0) + 1)",
            "    facts.set('danger', False)",
            "def put_out():",
            "    facts.set('burn', False)",
            "set_reflex('trouble', lambda view: view['facts'].get('danger') or view['facts'].get('odd'), rest)",
            "facts.set('odd', True)",
            "time.sleep(0.6)",
            "# What is learned later goes under the node, which is not set again.",
            "set_reflex('known', lambda view: view['facts'].get('danger'), known, under='trouble')",
            "for kind in ('danger', 'odd'):",
            "    facts.set(kind, True)",
            "    time.sleep(0.6)",
            "# The same for a node that tells: it tells what none under it answers.",
            "set_reflex('harm', lambda view: view['facts'].get('burn') or view['facts'].get('hurt'), 'HARM')",
            "set_reflex('burning', lambda view: view['facts'].get('burn'), put_out, under='harm')",
            "for kind in ('burn', 'hurt'):",
            "    facts.set(kind, True)",
            "    time.sleep(0.6)",
            "    facts.set(kind, False)",
            "    time.sleep(0.3)",
            "print('rest', facts.get('rest'), 'known', facts.get('known'))",
            "print([(row['name'], row.get('under')) for row in reflexes()])"])
        with Episode([program(body), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
            told = [row["reported"]["kind"] for row in episode.records("escalation")]
        self.assertEqual(summary["status"], "finished")
        # The node answered the odd case twice itself; the case it has a node for went to that node.
        self.assertIn("rest 2 known 1", cell["stdout"])
        self.assertIn("[('trouble', ['known']), ('harm', ['burning'])]", cell["stdout"])
        # Burning was put out by the node under it; being hurt, which none answers, was told.
        self.assertEqual(told, ["HARM"])

    def test_what_a_node_does_itself_gives_way_when_a_node_under_it_has_its_turn(self):
        body = "\n".join([
            "import time",
            "def broad():",
            "    type_text(60, seconds=0.05)",
            "def narrow():",
            "    facts.set('narrow_at', get_state()['step'])",
            "    facts.set('seen', True)",
            "set_reflex('broad', lambda view: view['facts'].get('on') and not view['facts'].get('seen'), broad, priority=5)",
            "set_reflex('narrow', lambda view: view.get('step', 0) >= 3, narrow, under='broad', priority=1)",
            "facts.set('on', True)",
            "time.sleep(2.5)",
            "print('narrow_at', facts.get('narrow_at'), 'step', get_state()['step'])"])
        with Episode([program(body), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
        self.assertEqual(summary["status"], "finished")
        narrow_at, step = (int(word) for word in cell["stdout"].split() if word.isdigit())
        # The narrower node had its turn while the broad one's program ran, though its priority is the
        # lower: that program gave way, and did not go on to its end.
        self.assertGreaterEqual(narrow_at, 3)
        self.assertLess(step, 15)

    def test_a_condition_sees_what_changed_what_did_not_and_what_runs(self):
        body = "\n".join([
            "import time",
            "set_reflex('moved', lambda view: view['was'].get('step') is not None and view['step'] > view['was']['step'],",
            "           'MOVED')",
            "set_reflex('stalled', lambda view: view['unchanged']['step'] > 0.6 and any(",
            "               unit['kind'] == 'program' and unit['seconds'] > 0.6 for unit in view['units']), 'STALLED',",
            "           every=0.2)",
            "type_text(2)",
            "time.sleep(1.5)"])
        with Episode([program(body), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            told = [row["reported"]["kind"] for row in episode.records("escalation")]
        self.assertEqual(summary["status"], "finished")
        # The step rose, then it stayed while a program still ran: both are read from the view.
        self.assertEqual(sorted(set(told)), ["MOVED", "STALLED"])

    def test_what_the_environment_tells_reaches_the_waiting_model_at_once_with_its_picture(self):
        with Episode([program("print('nothing runs')"), "<wait>20</wait>", "<finish>done</finish>"], tells=True) as episode:
            episode.start()
            self.assertTrue(episode.until(lambda: episode.records("wait")))
            # Something happens in the environment by itself: its worker tells the run.
            self.assertTrue(episode.environment.tell([
                {"type": "text", "text": "The alarm rang."},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]))
            summary = episode.end()
            waits = episode.records("wait_end")
            last = episode.chat.requests[-1][-1]
        self.assertEqual(summary["status"], "finished")
        self.assertEqual((waits[0]["why"], waits[0]["seconds"] < 5), ("message", True))
        self.assertIn("Message from the environment", texts(last))
        self.assertIn("The alarm rang.", texts(last))
        self.assertTrue(any(part.get("type") == "input_image" for part in last["content"]))

    def test_the_tree_gives_the_earlier_node_the_environment_goes_back_to_the_later_and_tells_only_a_failure_nothing_takes(self):
        asked = "\n".join([
            "import time",
            "def work():",
            "    type_text(6, seconds=0.05)",
            "    facts.set('work_done', True)",
            "def urgent():",
            "    type_text(1)",
            "    facts.set('urgent_done', True)",
            "def broken():",
            "    raise RuntimeError('this node cannot work')",
            "set_reflex('job', lambda view: not view['facts'].get('closed'), priority=1)",
            "set_reflex('alarm', lambda view: view['facts'].get('alarm') and not view['facts'].get('urgent_done'), urgent,",
            "           under='job', priority=2)",
            "set_reflex('work', lambda view: not view['facts'].get('work_done'), work, under='job', priority=1)",
            "set_reflex('broken', lambda view: view['facts'].get('work_done'), broken, under='job')",
            "set_reflex('shut', lambda view: view['facts'].get('closed'))",
            "set_reflex('never', lambda view: True, lambda: facts.set('never', True), under='shut')",
            "time.sleep(0.15)",
            "facts.set('alarm', True)",
            "print([(row['name'], row.get('under', [])) for row in reflexes()], [row['name'] for row in reflexes('job')])"])
        with Episode([program(asked), "<wait>8</wait>", "<finish>done</finish>"]) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
            mine = ("alarm", "work", "broken", "never")
            starts = [row["name"] for row in episode.records("entry_start") if row.get("rule") in mine]
            ends = {row["id"]: row["status"] for row in episode.records("entry_end")}
            work = [ends[row["id"]] for row in episode.records("entry_start") if row.get("rule") == "work"]
            facts = {row["name"]: json.loads(row["value"]) for row in episode.records("fact")}
            reasons = [row["reason"] for row in episode.records("model_request")]
            waits = episode.records("wait_end")
            preempted = [row.get("of_reflex") for row in episode.records("preempted")]
            last = texts(episode.chat.requests[-1][-1])
        self.assertEqual(summary["status"], "finished")
        # One call made the tree: nodes under a group, the higher priority first.
        # reflexes() gives the top, each group with the names under it; reflexes(name) the nodes under one.
        self.assertEqual(cell["stdout"].strip(),
                         "[('job', ['alarm', 'work', 'broken']), ('shut', ['never'])] ['alarm', 'work', 'broken']")
        # The earlier node took the environment from the work that ran, and the work began again by itself.
        self.assertEqual(starts[:2], ["work", "alarm"])
        self.assertEqual((work[0], work[-1]), ("failed", "done"))
        self.assertEqual((facts["urgent_done"], facts["work_done"]), (True, True))
        # A node under a group whose condition does not hold never had its turn.
        self.assertNotIn("never", facts)
        # The tree's own programs started no call of the model, the one that was interrupted included: it
        # was asked for its program, then woken once, by the node whose failure nothing at its place took.
        self.assertNotIn("unit_end", reasons)
        self.assertEqual(preempted, [True])
        self.assertEqual(waits[0]["why"], "event")
        self.assertIn("Event REFLEX_FAILED from", last)
        self.assertIn('"reflex": "broken"', last)

    def test_a_node_whose_program_ends_with_its_situation_not_over_gives_way_to_a_later_node_or_the_model_is_told(self):
        first = "\n".join([
            "import time",
            "def swing():",
            "    facts.set('swings', facts.get('swings', 0) + 1)",
            "    return {'hits': 0}",
            "def leave():",
            "    facts.set('danger', False)",
            "set_reflex('fight', lambda view: view['facts'].get('danger'), swing, priority=2)",
            "set_reflex('retreat', lambda view: view['facts'].get('danger') and view['facts'].get('swings', 0) >= 1, leave, priority=1)",
            "facts.set('danger', True)",
            "time.sleep(1.0)",
            "print(facts.get('danger'), [(row['name'], row['last']['ended'], row['last']['done'], row['last'].get('returned')) for row in reflexes()])"])
        second = "\n".join([
            "drop_reflex('retreat')",
            "facts.set('danger', True)"])
        with Episode([program(first), program(second), "<wait>5</wait>", "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            cells = {row["number"]: row["result"] for row in episode.records("cell")}
            reasons = [row["reason"] for row in episode.records("model_request")]
            last = "\n".join(texts(request[-1]) for request in episode.chat.requests[2:])
        self.assertEqual(summary["status"], "finished")
        # The program of `fight` ended by itself, but the danger it answers was not over: that is not done. The
        # later node at its place had the environment and ended the danger; the model was told nothing.
        self.assertEqual(cells[1]["stdout"].strip(),
                         "False [('fight', 'by itself', False, \"{'hits': 0}\"), ('retreat', 'by itself', True, None)]")
        self.assertEqual(reasons[:2], ["start", "program_end"])
        # With no later node, the model is told, with the report of what the program did.
        self.assertIn("Event REFLEX_FAILED from", last)
        self.assertIn('"reflex": "fight"', last)
        self.assertIn('"ended": "by itself"', last)
        self.assertIn('"done": false', last)
        self.assertIn("hits", last)
        # Every turn is told how many nodes act in the tree and what changed in it since the last.
        self.assertRegex(last, r"Reflex tree: 1 node; changed since you were last told:\n"
                               r"  fight: began \d+, did its work 0, did not \d+")

    def test_a_program_can_read_what_the_environment_gives_it_to_act_with(self):
        with tempfile.TemporaryDirectory() as given, tempfile.TemporaryDirectory() as other:
            Path(given, "library").mkdir()
            Path(given, "library", "readme.md").write_text("speed defaults to 1", encoding="utf-8")
            Path(other, "secret.txt").write_text("not given", encoding="utf-8")
            read = "\n".join([
                "import os",
                f"print(os.listdir({given!r}), open(os.path.join({given!r}, 'library', 'readme.md')).read())",
                "try:",
                f"    print(open(os.path.join({other!r}, 'secret.txt')).read())",
                "except PermissionError as error:",
                "    print('refused')"])
            # With the file guard on, programs read the installation, the source and their own folder only.
            with Episode([program(read), "<finish>done</finish>"], references=[given],
                         runtime={"isolation": {"sandbox": False}}) as episode:
                summary = episode.end()
                first = texts(episode.chat.requests[0][0])
                printed = episode.records("cell")[0]["result"]["stdout"]
        self.assertEqual(summary["status"], "finished")
        # The first message says where it is; a program reads it there, and nothing beside it.
        self.assertIn(f"in these folders, which a program can read: {given}", first)
        self.assertEqual(printed.strip(), "['library'] speed defaults to 1\nrefused")

    def test_a_node_that_keeps_failing_is_told_once_though_its_situation_comes_and_goes(self):
        body = "\n".join([
            "import time",
            "def swing():",
            "    facts.set('swings', facts.get('swings', 0) + 1)",
            "set_reflex('fight', lambda view: view['facts'].get('danger'), swing)",
            "for _ in range(4):",
            "    facts.set('danger', True)",
            "    time.sleep(0.6)",
            "    facts.set('danger', False)",
            "    time.sleep(0.2)",
            "print('swings', facts.get('swings'))"])
        with Episode([program(body), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
            failures = [row for row in episode.records("escalation") if row["reported"]["kind"] == "REFLEX_FAILED"]
        self.assertEqual(summary["status"], "finished")
        # The danger came four times and the node failed every time: the model hears of it once.
        self.assertGreaterEqual(int(cell["stdout"].split()[-1]), 4)
        self.assertEqual(len(failures), 1)

    def test_a_turn_is_told_of_the_tree_only_what_changed_in_it(self):
        from harness.runtime.reactive.tree import NO_REFLEXES, told

        nodes = {f"n{number}": "began 0, did its work 0, did not 0" for number in range(14)}
        self.assertEqual(told({}, {}), NO_REFLEXES)
        first = told(nodes, {})
        # A tree larger than a turn tells of: the first 10 that changed, and how many more.
        self.assertEqual(len(first.splitlines()), 12)
        self.assertIn("Reflex tree: 14 nodes, 14 of them never had their turn; changed since you were last told:", first)
        self.assertIn("... 4 more changed: reflexes()", first)
        self.assertEqual(told(nodes, dict(nodes)), "Reflex tree: 14 nodes, 14 of them never had their turn, as you were last told "
                         "(reflexes() lists them)")
        self.assertEqual(told({**nodes, "n3": "began 1, did its work 1, did not 0"}, nodes).splitlines()[1:],
                         ["  n3: began 1, did its work 1, did not 0"])

    def test_output_too_large_to_tell_is_saved_and_told_by_its_beginning(self):
        with Episode([program("print('a' * 100 + 'b' * 39900)"),
                      program("print('c' * 39000)\nraise ValueError('no')"), "<finish>done</finish>"]) as episode:
            summary = episode.end()
            told = [texts(request[-1]) for request in episode.chat.requests]
            large, failed = (row["result"]["stdout"] for row in episode.records("cell"))
        self.assertEqual(summary["status"], "finished")
        # More than 30000 characters: the file it was saved to, which has all of it, and the first 2000.
        self.assertTrue(large.startswith("Output too large (40001 characters). Full output saved to: "))
        saved_to = Path(large.splitlines()[0].split("saved to: ", 1)[1])
        self.addCleanup(lambda: (saved_to.unlink(), saved_to.parent.rmdir()))
        self.assertEqual(saved_to.read_text(encoding="utf-8"), "a" * 100 + "b" * 39900 + "\n")
        self.assertTrue(large.endswith("Preview (first 2000 characters):\n" + "a" * 100 + "b" * 1900))
        self.assertIn(large, told[1])
        # A program that failed: the first and last 5000 characters, and how many lie between.
        self.assertEqual(failed, "c" * 5000 + "\n... [29001 characters omitted] ...\n" + "c" * 4999 + "\n")

    def test_a_conversation_at_its_limit_is_replaced_by_the_models_summary(self):
        from harness.runtime.decision.messages import rebuild_messages

        with Episode([program("print(1)"), program("print(2)"),
                      "<analysis>one, two</analysis><summary>Printed 1 and 2; next is to finish.</summary>",
                      "<finish>done</finish>"],
                     runtime={"compact_at_tokens": 1}) as episode:
            summary = episode.end()
            requests = episode.chat.requests
            compactions = episode.records("compaction")
            rebuilt = rebuild_messages(episode.records())
        self.assertEqual(summary["status"], "finished")
        # The third call asked for the summary, after the whole conversation.
        self.assertEqual([len(request) for request in requests], [1, 3, 5, 3])
        self.assertIn("Please write a summary of the transcript.", texts(requests[2][-1]))
        self.assertEqual([(row["action"], row["messages_before"], row["messages"]) for row in compactions], [("done", 5, 3)])
        # The summary, without its analysis, stands in the first message, after the instruction; a
        # conversation that fits whole keeps its last exchange as it was.
        first = texts(requests[3][0])
        self.assertEqual(first.count("Printed 1 and 2; next is to finish."), 1)
        self.assertNotIn("one, two", first)
        self.assertTrue(first.startswith(texts(requests[2][0])))
        self.assertEqual(requests[3][1], requests[2][3])
        self.assertTrue(texts(requests[2][-1]).startswith(texts(requests[3][-1])))
        self.assertEqual(summary["compaction_calls"], 1)
        # The trace rebuilds the conversation as it is after the compaction.
        self.assertEqual([texts(message) for message in rebuilt[:3]], [texts(message) for message in requests[3]])

    def test_what_a_compaction_keeps_and_what_a_cold_cache_clears(self):
        from harness.runtime.decision.messages import clear_results, recent_start

        def message(role, chars, result=False):
            return {"role": role, "content": [{"type": "input_text", "text": "x" * chars, **({"result": True} if result else {})}]}

        # 4000 tokens a message: back from the end until 10000 tokens and five messages are kept, then on to
        # a reply of the model (the fifth from the end is a result, which stays with its program).
        long = [message("user", 100)] + [message(("assistant", "user")[index % 2], 16_000, index % 2 == 1) for index in range(20)]
        self.assertEqual(len(long) - recent_start(long, 10_000, 5, 40_000), 4)
        # 20000 tokens a message: no more than 40000 tokens, and from a reply of the model on.
        huge = [message("user", 100)] + [message(("assistant", "user")[index % 2], 80_000) for index in range(20)]
        self.assertEqual(len(huge) - recent_start(huge, 10_000, 5, 40_000), 2)
        # Of ten results the last five stay; a second pass has nothing left to clear.
        self.assertEqual(clear_results(long, 5, "[cleared]"), 5)
        self.assertEqual([part["text"] == "[cleared]" for item in long[2::2] for part in item["content"]],
                         [True] * 5 + [False] * 5)
        self.assertEqual(clear_results(long, 5, "[cleared]"), 0)

    def test_a_request_marks_what_the_provider_is_to_cache_where_it_caches_to_a_mark(self):
        from harness.runtime.decision.model import ChatModel

        messages = [{"role": "user", "content": [{"type": "input_text", "text": "first"}]},
                    {"role": "assistant", "content": "reply"},
                    {"role": "user", "content": [{"type": "input_text", "text": "a"}, {"type": "input_text", "text": "b"}]}]
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}):
            marked = ChatModel({"model": "anthropic/some-model"}).payload("system", messages)["messages"]
            plain = ChatModel({"model": "deepseek/some-model"}).payload("system", messages)["messages"]
        mark = {"cache_control": {"type": "ephemeral"}}
        self.assertEqual(marked[0]["content"], [{"type": "text", "text": "system", **mark}])
        self.assertEqual(marked[-1]["content"], [{"type": "text", "text": "a"}, {"type": "text", "text": "b", **mark}])
        self.assertNotIn("cache_control", json.dumps(marked[1:-1]))
        # A provider that caches a prefix by itself gets no mark.
        self.assertNotIn("cache_control", json.dumps(plain))

    def test_a_program_says_what_it_is_for_and_its_end_says_whether_that_is_the_case(self):
        with Episode([program("until(lambda view: view['facts'].get('made'))\ntype_text(1)"),
                      program("until(lambda view: view['facts'].get('made'))\nfacts.set('made', True)"),
                      "<finish>done</finish>"]) as episode:
            summary = episode.end()
            told = [texts(request[-1]) for request in episode.chat.requests]
            done = [row["result"].get("done") for row in episode.records("cell")]
        self.assertEqual(summary["status"], "finished")
        # Both programs ended by themselves; only the second had done what it was for.
        self.assertIn("Program 1 ended: by itself; done: no", told[1])
        self.assertIn("Reflex tree: empty (nothing acts without you)", told[1])
        self.assertIn("Program 2 ended: by itself; done: yes", told[2])
        self.assertEqual(done, [False, True])

    def test_a_node_raises_an_event_and_a_node_that_answers_it_keeps_it_from_the_model(self):
        asked = "\n".join([
            "import time",
            "set_reflex('heard', 'RING', lambda event: facts.set('heard', event.kind))",
            "set_reflex('ring', lambda view: view['facts'].get('go'), 'RING')",
            "set_reflex('other', lambda view: view['facts'].get('go'), 'KNOCK')",
            "facts.set('go', True)",
            "time.sleep(0.3)",
            "print(facts.get('heard'))"])
        with Episode([program(asked), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
            told = "\n".join(texts(request[-1]) for request in episode.chat.requests)
        self.assertEqual(summary["status"], "finished")
        # The event one node raised was answered by the node set for it; the one nobody answers reached the model.
        self.assertEqual(cell["stdout"].strip(), "RING")
        self.assertIn("reflex: RING (handled)", told)
        self.assertIn("reflex: KNOCK", told)
        self.assertNotIn("reflex: KNOCK (handled)", told)

    def test_where_the_environment_pauses_the_lower_call_goes_on_after_the_reflex_and_the_model_is_not_asked(self):
        asked = "\n".join([
            "facts.set('at', get_state()['step'] + 3)",
            "def urgent():",
            "    facts.set('urgent_at', get_state()['step'])",
            "    type_text(2)",
            "    facts.set('done', True)",
            "set_reflex('urgent', lambda view: view['step'] >= view['facts']['at'] and not view['facts'].get('done'),",
            "           urgent, priority=5)",
            "before = get_state()['step']",
            "typed = type_text(8, seconds=0.05)",
            "print('went on', typed.ok, get_state()['step'] - before)"])
        with Episode([program(asked), "<finish>done</finish>"], pauses=True,
                     runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
            paused = [(row["rule"], row["name"]) for row in episode.records("call_paused")]
            resumed = [row["name"] for row in episode.records("call_resumed")]
            held, requests = episode.environment.held, len(episode.chat.requests)
        self.assertEqual(summary["status"], "finished")
        # The lower call was not ended: it typed its eight keys around the reflex's two, in one program.
        self.assertEqual((cell["status"], cell["stdout"].strip()), ("ok", "went on True 10"))
        self.assertEqual((paused, resumed), ([("urgent", "program 1")], ["program 1"]))
        self.assertEqual(episode.records("preempted"), [])
        # The environment was asked to hold what ran and given the same back when it went on.
        self.assertEqual([item[0] for item in held], ["pause", "resume"])
        self.assertEqual(held[1][1], held[0][1])
        # It was told who took it.
        self.assertEqual(held[0][2], "urgent")
        # The model was asked for the program and for what came after it, and not in between.
        self.assertEqual(requests, 2)

    def test_a_node_that_ends_what_it_interrupts_ends_the_lower_call_where_the_environment_pauses(self):
        asked = "\n".join([
            "facts.set('at', get_state()['step'] + 3)",
            "def urgent():",
            "    type_text(2)",
            "    facts.set('done', True)",
            "set_reflex('urgent', lambda view: view['step'] >= view['facts']['at'] and not view['facts'].get('done'),",
            "           urgent, priority=5, ends=True)",
            "print(reflexes('urgent')[0].get('ends'))",
            "typed = type_text(8, seconds=0.05)",
            "print('went on', typed.ok)"])
        with Episode([program(asked), "<finish>done</finish>"], pauses=True,
                     runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
            taken = [(row["rule"], row["name"]) for row in episode.records("preempted")]
            held = episode.environment.held
        self.assertEqual(summary["status"], "finished")
        self.assertIn("True", cell["stdout"])
        # The lower call was ended where it was, not held and resumed: the model was told who took it.
        self.assertEqual(taken, [("urgent", "program 1")])
        self.assertEqual(episode.records("call_paused"), [])
        self.assertEqual(held, [])
        self.assertNotIn("went on True", cell["stdout"])

    def test_a_program_that_does_not_say_what_it_is_for_is_not_started(self):
        with Episode(["<python>\nprint('ran')\n</python>",
                      "<python>\nuntil(None)\nprint('read')\n</python>",
                      "<python>\nuntil(lambda view: view['step'] >= 1)\ntype_text(1)\n</python>",
                      "<finish>done</finish>"], runtime={"purpose": "required"}) as episode:
            summary = episode.end()
            cells = [row["result"] for row in episode.records("cell")]
            refused = episode.records("program_refused")
            told = json.dumps(episode.chat.requests[1])
        self.assertEqual(summary["status"], "finished")
        # The first program ran nothing and the model was told why; the two that said it ran.
        self.assertEqual([row["reason"] for row in refused], ["no_purpose"])
        self.assertIn("does not say what it is for", told)
        self.assertEqual(len(cells), 2)
        self.assertIn("read", cells[0]["stdout"])

    def test_a_node_that_tells_and_ends_what_runs_ends_the_execution_with_its_event(self):
        asked = "\n".join([
            "facts.set('at', get_state()['step'] + 3)",
            "set_reflex('alarm', lambda view: view['step'] >= view['facts']['at'], 'ALARM', ends=True)",
            "print(reflexes('alarm')[0]['does'])",
            "typed = type_text(30, seconds=0.05)",
            "print('went on', typed.ok)"])
        with Episode([program(asked), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
            told = json.dumps(episode.chat.requests[1])
        self.assertEqual(summary["status"], "finished")
        self.assertIn("raises an event and ends what runs", cell["stdout"])
        # What ran was ended where it was, with the node's event, and the model was told that event.
        self.assertNotIn("went on True", cell["stdout"])
        self.assertIn("ALARM", told)

    def test_a_condition_that_raises_in_its_trial_is_told_and_the_node_stays(self):
        asked = "\n".join([
            "reflex_method()",
            "def fix():",
            "    facts.set('level', 9)",
            "# The condition compares with a value that is not there at first: it raises.",
            "shown = set_reflex('low', lambda view: view['facts'].get('level') < 3, fix,",
            "                   test=lambda: facts.set('other', 1))",
            "print('shown', shown['turn'], 'TypeError' in shown.get('error', ''))",
            "print('still', [row['name'] for row in reflexes()])",
            "# Once the value is there the same node is judged and has its turn.",
            "facts.set('level', 1)",
            "import time",
            "time.sleep(1.5)",
            "print('level', facts.get('level'))"])
        with Episode([program(asked), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 60, "reflex_trials": "required"}) as episode:
            summary = episode.end()
            out = episode.records("cell")[0]["result"]["stdout"]
            told = json.dumps(episode.chat.requests[1])
        self.assertEqual(summary["status"], "finished")
        self.assertIn("shown False True", out)
        self.assertIn("still ['low']", out)
        self.assertIn("level 9", out)
        # Told once what went wrong, with the node kept.
        self.assertEqual(told.count("The node stays in the tree"), 1, told)
        self.assertIn("REACTIVE_FAULT", told)

    def test_a_node_that_tells_and_ends_gives_way_to_the_node_under_it(self):
        asked = "\n".join([
            "reflex_method()",
            "def refill():",
            "    # The answer takes steps of the environment: the node above is judged at each.",
            "    type_text(3, seconds=0.05)",
            "    facts.set('level', 9)",
            "set_reflex('low', lambda view: (view['facts'].get('level') or 9) < 3, 'LEVEL_LOW', ends=True,",
            "           test='tried with the node under it')",
            "# The node under it says only what distinguishes it within that situation.",
            "shown = set_reflex('refill', lambda view: bool(view['facts'].get('supply')), refill, under='low',",
            "                   test=lambda: (facts.set('supply', 1), facts.set('level', 1)))",
            "print('shown', shown['turn'], shown['done'], shown['last']['ended'], facts.get('level'))"])
        with Episode([program(asked), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 60, "reflex_trials": "required"}) as episode:
            summary = episode.end()
            out = episode.records("cell")[0]["result"]["stdout"]
            told = json.dumps(episode.chat.requests[1])
        self.assertEqual(summary["status"], "finished")
        # The node under it did its work to the end, and is done although its own condition still holds.
        self.assertIn("shown True True by itself 9", out)
        # The node above never had its turn: the situation was answered.
        self.assertNotIn("LEVEL_LOW from", told)
        self.assertIn("tells you LEVEL_LOW and ends what runs; 0 times", told)

    def test_a_node_is_set_with_its_trial_after_the_method_was_read(self):
        asked = "\n".join([
            "def refused(*arguments, **named):",
            "    try:",
            "        set_reflex(*arguments, **named)",
            "    except ValueError as error:",
            "        print('refused:', str(error)[:60])",
            "def fix():",
            "    facts.set('broken', False)",
            "refused('repair', lambda view: view['facts'].get('broken'), fix, test=lambda: None)",
            "page = reflex_method()",
            "print('page', 'designed and tried' in page)",
            "refused('repair', lambda view: view['facts'].get('broken'), fix)",
            "# The trial brings the situation about; the node is watched and what it showed comes back.",
            "shown = set_reflex('repair', lambda view: view['facts'].get('broken'), fix,",
            "                   test=lambda: facts.set('broken', True))",
            "print('shown', shown['tried'], shown['turn'], shown['done'], facts.get('broken'))",
            "never = set_reflex('idle', lambda view: view['facts'].get('never'), fix, test=lambda: None)",
            "print('never', never['turn'])",
            "far = set_reflex('far', lambda view: view['facts'].get('far'), fix, test='it needs another machine')",
            "print('far', far)",
            "print([(row['name'], row['trial'].get('tried'), row['trial'].get('turn')) for row in reflexes()])"])
        with Episode([program(asked), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 60, "reflex_trials": "required"}) as episode:
            summary = episode.end()
            out = episode.records("cell")[0]["result"]["stdout"]
            told = json.dumps(episode.chat.requests[1])
        self.assertEqual(summary["status"], "finished")
        self.assertIn("refused: Nothing was set: read how a tree of reflexes is designed", out)
        self.assertIn("page True", out)
        self.assertIn("refused: Nothing was set: a node is set with its trial", out)
        # The trial showed the node have its turn and leave the situation over.
        self.assertIn("shown True True True False", out)
        self.assertIn("never False", out)
        self.assertIn("far {'name': 'far', 'tried': False, 'why': 'it needs another machine'}", out)
        self.assertIn("[('repair', True, True), ('idle', True, False), ('far', False, None)]", out)
        # The model is told what the trials left open.
        self.assertIn("1 not tried", told)
        self.assertIn("1 did not work in its trial", told)

    def test_the_first_time_a_node_does_its_work_by_itself_the_model_is_told(self):
        asked = "\n".join([
            "import time",
            "reflex_method()",
            "def fix():",
            "    facts.set('broken', False)",
            "set_reflex('repair', lambda view: view['facts'].get('broken'), fix, test='not here')",
            "for _ in range(2):",
            "    facts.set('broken', True)",
            "    time.sleep(1.0)"])
        with Episode([program(asked), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 60, "reflex_trials": "required"}) as episode:
            summary = episode.end()
            acted = [row for row in episode.records("escalation") if row["reported"]["kind"] == "REFLEX_ACTED"]
        self.assertEqual(summary["status"], "finished")
        # Told once, for the first of the two times, with what its program did.
        self.assertEqual(len(acted), 1)
        self.assertEqual(acted[0]["reported"]["source"], "repair")

    def test_a_turn_is_told_how_many_nodes_only_tell(self):
        from harness.runtime.reactive.tree import told

        nodes = {"a": "tells you A; 2 times", "b": "tells you B and ends what runs; 0 times",
                 "c": "began 1, did its work 1, did not 0"}
        self.assertEqual(told(nodes, dict(nodes)),
                         "Reflex tree: 3 nodes, 1 of them never had its turn, 1 of them only tells you, "
                         "as you were last told (reflexes() lists them)")
        # A tree in which nothing changed, every node has had its turn and acts itself: no line.
        quiet = {"a": "began 2, did its work 2, did not 0", "b": "tells you B and ends what runs; 1 times"}
        self.assertEqual(told(quiet, dict(quiet)), "")
        self.assertIn("changed since you were last told", told(quiet, {}))

    def test_ends_goes_with_a_program_or_an_event_to_tell(self):
        asked = "\n".join([
            "for do in (None, 'stop'):",
            "    try:",
            "        set_reflex('odd', lambda view: False, do, ends=True)",
            "    except ValueError as error:",
            "        print('refused:', error)"])
        with Episode([program(asked), "<finish>done</finish>"]) as episode:
            episode.end()
            cell = episode.records("cell")[0]["result"]
        self.assertEqual(cell["stdout"].count("refused: ends=True goes with a program or with the name of an event"), 2)

    def test_a_condition_reads_a_value_the_environment_computes_from_code_the_model_defined(self):
        asked = "\n".join([
            "print(sense('far', 'step >= 3')['value'])",
            "try:",
            "    sense('bad', 'step >=')",
            "except ValueError as error:",
            "    print('refused')",
            "set_reflex('far', lambda view: view['sensed']['far'] and not view['facts'].get('seen_at'), lambda: facts.set('seen_at', get_state()['step']))",
            "type_text(6)",
            "print(sorted(senses()), get_state()['sensed'])",
            "drop_sense('far')",
            "print(get_state()['sensed'])"])
        with Episode([program(asked), "<finish>done</finish>"]) as episode:
            episode.end()
            facts = {row["name"]: json.loads(row["value"]) for row in episode.records("fact")}
            printed = texts(episode.chat.requests[-1][-1])
        # The rule's condition read what the environment computed: it began once the value held.
        self.assertGreaterEqual(facts["seen_at"], 3)
        self.assertIn("False\nrefused\n['far'] {'far': True}\n{}", printed)

    def test_s5_a_sub_agent_whose_turn_ends_wakes_the_model_that_started_it_and_goes_on_when_sent_a_message(self):
        class SamePlace(Place):
            """Sub-agents on the worker of the agent that starts them."""
            kinds = ("screen",)

            def begin(self, child, kind, cancelled):
                return lambda: None

        class Both(Recording):
            """The script for the first model; a sub-agent types and answers, and
            answers a later message with how many replies its history holds."""

            def complete(self, system, messages):
                if "You are a sub-agent" not in system:
                    return super().complete(system, messages)
                replies = sum(message["role"] == "assistant" for message in messages)
                return ChatReply(text=(program("type_text(5)"), "<finish>hello from the sub-agent</finish>",
                                       f"hello again after {replies} replies")[min(replies, 2)], usage=dict(USAGE))

        with Episode([program("print(delegate('say hello'))"), "<wait>60</wait>",
                      program("print(send_agent('a1', 'say it again'))"), "<wait>60</wait>", "Both greeted."],
                     interactive=True) as episode:
            run = episode.run
            run.chat = run.agent_chat = Both(episode.chat.replies)
            run.agents, run.workspace_kind = Agents(place=SamePlace()), "screen"
            episode.start()
            # The first model's answer ends its turn; the conversation and its sub-agent stay.
            self.assertTrue(episode.until(lambda: episode.records("turn_result") and run.status == "IDLE"))
            waits = episode.records("wait_end")
            reports = [(row["agent"], row["status"], row["result"]) for row in episode.records("agent_report")]
            requests = run.chat.requests
            run.close()
            summary = episode.end()
        self.assertEqual(summary["status"], "finished")
        self.assertEqual([row["why"] for row in waits], ["unit", "unit"])
        self.assertIn("hello from the sub-agent", texts(requests[2][-1]))
        # The message went to the same sub-agent, which went on with its history.
        self.assertEqual(reports, [("a1", "finished", "hello from the sub-agent"),
                                   ("a1", "finished", "hello again after 2 replies")])
        self.assertIn("hello again after 2 replies", texts(requests[-1][-1]))

    def test_a1_an_answer_ends_the_turn_and_the_conversation_goes_on_with_what_it_has(self):
        with Episode([program("kept = 41"), "The value is set.",
                      program("print(kept + 1)\ntype_text(8, seconds=0.2)"), "It types on.",
                      "<finish>typed</finish>"], interactive=True) as episode:
            run = episode.run
            episode.start()

            def turns():
                return episode.records("turn_result")

            self.assertTrue(episode.until(lambda: len(turns()) == 1 and run.status == "IDLE"))
            # A message after the answer goes to the same conversation, with a turn's limits anew.
            run.send_message("add one and type")
            # The second answer leaves the program typing; its end starts the third turn by itself.
            self.assertTrue(episode.until(lambda: len(turns()) == 3 and run.status == "IDLE"))
            cells = {row["number"]: row["result"] for row in episode.records("cell")}
            said = [row["text"] for row in episode.records("user_message") if row["text"]]
            results = [(row["reason"], row["turn"], row["model_calls"]) for row in turns()]
            run.close()
            summary = episode.end()
        self.assertEqual(results, [("answer", 1, 2), ("answer", 2, 2), ("answer", 3, 1)])
        self.assertEqual(said, ["add one and type"])
        # The namespace was kept, and the program the second answer left running was not cancelled.
        self.assertEqual((cells[2]["status"], cells[2]["stdout"].split()[0]), ("ok", "42"))
        # Closed between turns, the summary keeps how the last turn ended.
        self.assertEqual(summary["status"], "finished")

    def test_a3_an_ended_conversation_goes_on_in_a_new_process_with_its_messages_and_facts(self):
        with Episode([program("facts.set('door', 'open')\nkept = 1"), "The door is open."], interactive=True) as episode:
            episode.start()
            self.assertTrue(episode.until(lambda: episode.records("turn_result") and episode.run.status == "IDLE"))
            episode.run.close()
            episode.end()
            # Another process: a new conversation object and kernel on what the first one kept.
            chat = Recording([program("print(facts.get('door'), 'kept' in globals())"), "Still open."])
            again = TaskRun(episode.run.base_config, 0, episode.directory, chat=chat, interactive=True,
                            restore=saved(episode.directory))
            thread = threading.Thread(target=again.run, daemon=True)
            thread.start()
            # It waits for a message: what died with the old process starts no turn.
            self.assertTrue(episode.until(lambda: episode.records("resumed") and again.status == "IDLE"))
            self.assertEqual(chat.requests, [])
            again.send_message("is it still open?")
            self.assertTrue(episode.until(lambda: any(row["turn"] == 2 and row["reason"] == "answer"
                                                      for row in episode.records("turn_result"))))
            first = chat.requests[0]
            stdout = episode.records("cell")[-1]["result"]["stdout"].split()
            again.close()
            thread.join(30)
        self.assertEqual(stdout, ["open", "False"])
        self.assertIn("The door is open.", [message["content"] for message in first if message["role"] == "assistant"])
        self.assertIn("continued in a new process", texts(first[-1]))
        self.assertIn("is it still open?", texts(first[-1]))


    def test_a_run_nobody_talks_to_is_continued_with_a_message(self):
        from harness.sdk import saved_conversation

        with Episode([program("facts.set('door', 'open')"), "The door is open."]) as episode:
            episode.start()
            episode.end()
            self.assertEqual(episode.summary["status"], "finished")
            kept = saved_conversation(episode.directory)
            chat = Recording(["It is still open."])
            again = TaskRun(episode.run.base_config, 0, episode.directory, chat=chat, restore=kept)
            again.send_message("is it still open?")
            summary = again.run()
            turns = [row["turn"] for row in episode.records("turn_result")]
        self.assertEqual(summary["status"], "finished")
        self.assertEqual(again.result, "It is still open.")
        self.assertIn("is it still open?", texts(chat.requests[0][-1]))
        self.assertEqual(turns, [1, 2])


class ReflexBudget(unittest.TestCase):
    """A moment in which a condition is slow costs the tree nothing but that moment."""

    def tree(self):
        from harness.runtime.reactive.tree import Reflexes

        def slow(view):
            until = time.perf_counter() + 0.07
            while time.perf_counter() < until:
                pass
            return True

        layer = Reflexes(0.05)
        layer.set("slow", slow, lambda: None, priority=2)
        layer.set("quick", lambda view: True, lambda: None, priority=1)
        return layer, layer.nodes["slow"], layer.nodes["quick"]

    def test_a_node_the_period_had_no_time_for_is_judged_in_the_next_one(self):
        from harness.runtime.reactive.rules import period

        layer, slow, quick = self.tree()
        with period(0.05):
            # Slower than the budget once: its answer counts, and nothing goes.
            self.assertTrue(layer._run(slow, {}))
            # The period is used up: the next node is not called, and is no fault.
            self.assertIsNone(layer._run(quick, {}))
        self.assertTrue(quick.waits)
        self.assertEqual(sorted(layer.nodes), ["quick", "slow"])
        with period(0.05):
            self.assertTrue(layer._run(quick, {}))
        self.assertFalse(quick.waits)
        # Judged before, it keeps what it was while it waits.
        quick.holds = True
        with period(0.05):
            layer._run(slow, {})
            self.assertTrue(layer._run(quick, {}))

    def test_a_condition_slower_than_its_budget_time_after_time_is_set_aside_not_removed(self):
        from harness.runtime.reactive.rules import period

        layer, slow, quick = self.tree()
        layer.set("under", lambda view: True, lambda: None, under="slow")
        for _ in range(2):
            with period(0.05):
                self.assertTrue(layer._run(slow, {}))
        with period(0.05):
            self.assertFalse(layer._run(slow, {}))
        with period(0.05):
            # Set aside, it no longer uses up the period the next node shares.
            self.assertFalse(layer._run(slow, {}))
            self.assertTrue(layer._run(quick, {}))
        self.assertTrue(slow.set_aside)
        self.assertIn("3 times in a row", slow.fault_tell)
        self.assertEqual(sorted(layer.nodes), ["quick", "slow", "under"])
        self.assertIn("not judged, its condition is too slow", layer.digest()["slow"])
        # Set again, the node is judged again.
        layer.set("slow", lambda view: True, lambda: None, priority=2)
        with period(0.05):
            self.assertTrue(layer._run(layer.nodes["slow"], {}))
        self.assertFalse(layer.nodes["slow"].set_aside)
        # One period within the budget and the count begins anew.
        slow = layer.nodes["slow"]
        slow.late = 2
        with period(0.05):
            layer._run(slow, {})
        self.assertEqual(slow.late, 0)

    def test_a_condition_that_raises_keeps_its_node_and_is_judged_again(self):
        from harness.runtime.reactive.rules import period
        from harness.runtime.reactive.tree import Reflexes

        layer = Reflexes(0.05)
        seen = {"was": None}
        layer.set("above", lambda view: 3 < seen["was"], None)
        layer.set("below", lambda view: True, lambda: None, under="above")
        above = layer.nodes["above"]
        for _ in range(2):
            with period(0.05):
                self.assertFalse(layer._run(above, {}))
        # Both nodes stay; the reason is told once, and the line says how often.
        self.assertEqual(sorted(layer.nodes), ["above", "below"])
        self.assertEqual((above.faults, len(above.fault_told)), (2, 1))
        self.assertIn("TypeError", above.fault_tell)
        self.assertIn("The node stays in the tree", above.fault_tell)
        self.assertEqual(layer.digest()["above"], "its condition raised 2 times")
        # The next time it can be judged, it is, and the node under it has its turn.
        seen["was"] = 5
        with period(0.05):
            self.assertTrue(layer._run(above, {}))
            self.assertTrue(layer._above_hold(layer.nodes["below"], {}))

    def test_a_condition_ended_at_the_hard_limit_once_keeps_its_node(self):
        from harness.runtime.reactive.rules import period

        layer, slow, quick = self.tree()

        def stalls(view):
            # Far over four times the budget: it is ended where it is.
            until = time.perf_counter() + 2.0
            while time.perf_counter() < until:
                pass
            return True

        slow.when, slow.holds = stalls, True
        with period(0.05):
            # Ended, not answered: the node keeps what it was and waits for the next period.
            self.assertTrue(layer._run(slow, {}))
        self.assertEqual((slow.late, slow.waits, sorted(layer.nodes)), (1, True, ["quick", "slow"]))
        with period(0.05):
            layer._run(slow, {})
        with period(0.05):
            # The third time in a row it is set aside: it does not hold, and stays in the tree.
            self.assertFalse(layer._run(slow, {}))
        self.assertEqual((slow.set_aside, sorted(layer.nodes)), (True, ["quick", "slow"]))


class OneQueue(unittest.TestCase):
    """What reaches the model is one queue with three priorities (runtime/decision/notices.py)."""

    def test_the_more_urgent_is_told_first_and_later_waits_for_a_wait(self):
        from harness.runtime.decision.notices import LATER, NEXT, NOW, Notice, Notices

        queue = Notices()
        for kind, priority, data, wakes in (("unit", NEXT, 1, True), ("event", LATER, 2, True), ("message", NEXT, 3, True),
                                            ("event", NOW, 4, True), ("unit", NEXT, 5, False)):
            queue.put(Notice(kind, priority, data, wakes))
        # A call that follows a reply is told down to `next`; the more urgent first, each in order of arrival.
        self.assertEqual([notice.data for notice in queue.pending(NEXT)], [4, 1, 3, 5])
        self.assertEqual([notice.data for notice in queue.pending(kinds=("message",))], [3])
        # The end of a unit that was cancelled wakes nobody.
        self.assertEqual([notice.data for notice in queue.pending(waking=True)], [4, 1, 3, 2])
        self.assertEqual([notice.data for notice in queue.take(NEXT)], [4, 1, 3, 5])
        # After a wait the queue is told whole.
        self.assertEqual([notice.data for notice in queue.take()], [2])
        self.assertEqual(queue.pending(), [])
        with self.assertRaises(ValueError):
            queue.put(Notice("note", "soon", "x"))

    def test_only_a_notice_of_priority_now_sets_the_call_in_flight_aside(self):
        from types import SimpleNamespace

        from harness.runtime.decision.notices import LATER, NEXT, NOW, Notices
        from harness.runtime.task.run import TaskRun

        run = TaskRun.__new__(TaskRun)
        run._condition, run._notices, run._revision, run._urgent = threading.Condition(), Notices(), 0, 0
        run._event_times = {}
        settled, cancelled = [], []
        run._request = SimpleNamespace(outcome=None)
        run._settle = lambda thought, outcome, reason=None: settled.append((outcome, reason))
        run._thoughts = SimpleNamespace(cancel_where=lambda match, reason: cancelled.append(reason))
        loop = SimpleNamespace(urgent=0)
        with run._condition:
            run._put("message", NEXT, ("user", "hello", []))
            run._put("event", LATER, {"id": "a", "event": {"kind": "HELD_BACK", "source": "r", "detail": {}}})
            # The call goes on, and what its reply does is done.
            self.assertEqual((settled, run._current_output(loop)), ([], True))
            run._put("event", NOW, {"id": "b", "event": {"kind": "REFLEX_FAILED", "source": "r", "detail": {}}},
                     reason="unhandled escalation")
        # The call is set aside, and a reply that did not know does nothing.
        self.assertEqual(settled, [("discarded", "unhandled escalation")])
        self.assertFalse(run._current_output(loop))
        self.assertEqual([notice.data.get("id") if notice.kind == "event" else notice.data[1]
                          for notice in run._notices.pending()], ["b", "hello", "a"])
        self.assertEqual(run._notice_parts(run._notices.pending()[0])[0]["text"], "Event REFLEX_FAILED from r")

    def test_an_event_that_repeats_one_not_answered_yet_sets_no_call_aside(self):
        from types import SimpleNamespace

        from harness.runtime.decision.notices import NEXT, NOW, Notices
        from harness.runtime.task.run import TaskRun

        run = TaskRun.__new__(TaskRun)
        run._condition, run._notices, run._revision, run._urgent = threading.Condition(), Notices(), 0, 0
        run._event_times = {}
        run._seen_events, run._told_sources = set(), set()
        settled = []
        run._request = SimpleNamespace(outcome=None)
        run._settle = lambda thought, outcome, reason=None: settled.append(outcome)
        run._thoughts = SimpleNamespace(cancel_where=lambda match, reason: None)
        run.trace = SimpleNamespace(emit=lambda *args, **detail: None)

        def failed(identifier, source="adrift"):
            run._escalation({"id": identifier, "event": {"kind": "REFLEX_FAILED", "source": source, "detail": {}}})

        failed("a")
        failed("b")
        failed("c")
        # The first sets the call aside; the same again while it waits is counted with it.
        waiting = run._notices.pending()
        self.assertEqual((len(settled), len(waiting), waiting[0].data["times"], run._urgent), (1, 1, 3, 1))
        self.assertIn('"times": 3', run._notice_parts(waiting[0])[0]["text"])
        # Told and not answered yet: the same once more comes with the next call and sets nothing aside.
        run._told_sources.add(run._event_key(run._notices.take()[0].data))
        failed("d")
        self.assertEqual((len(settled), run._urgent, [notice.priority for notice in run._notices.pending()]),
                         (1, 1, [NEXT]))
        # Another source is news.
        failed("e", source="buried")
        self.assertEqual((len(settled), run._urgent, [notice.priority for notice in run._notices.pending()]),
                         (2, 2, [NOW, NEXT]))


class ScriptedModel(unittest.TestCase):
    def test_a_script_waits_by_itself_only_while_something_runs(self):
        from harness.runtime.decision.model import still_running

        def said(text, now="Reflex tree: empty (nothing acts without you)", *more):
            # What a request ends with: what the model's output came to, what reached it, how things stand.
            return [{"role": "user", "content": [{"type": "input_text", "text": text},
                                                 *({"type": "input_text", "text": item} for item in more),
                                                 {"type": "input_text", "text": now, "ambient": True}]}]

        running = "Units running: e5 program 3 (program, 70 s)\nReflex tree: empty (nothing acts without you)"
        self.assertTrue(still_running(said("Program 3 is still running, as unit e5.")))
        self.assertTrue(still_running(said("Wait ended after 60.0 s: its time is over.", running)))
        # Nothing runs: the wait that is over is the script's own to answer, not to wait on for ever.
        self.assertFalse(still_running(said("Wait ended after 10.0 s: its time is over.")))
        # Something reached the model with it: that is the script's to answer.
        self.assertFalse(still_running(said("Wait ended after 60.0 s: its time is over.", running,
                                            "Message from the user: stop")))


class ManagedKernelUnits(unittest.TestCase):
    """The managed kernel's protocol with its isolated process replaced by an ordinary one
    (no sandbox): the admission of proposals in the host, and programs as units."""

    def test_a_managed_kernel_runs_its_programs_as_units_and_the_host_keeps_what_they_did(self):
        environment = ScreenEnvironment()
        worker = create_server(environment, port=0)
        threading.Thread(target=worker.serve_forever, daemon=True).start()
        self.addCleanup(worker.server_close)
        self.addCleanup(worker.shutdown)
        session = screen_session({"endpoint": f"http://127.0.0.1:{worker.server_address[1]}",
                                  "episode_id": "screen-1"})
        heard, ended = [], []
        conversation = SimpleNamespace(_pause=False, _closing=False, _condition=threading.Condition(),
                                       _kernel_span=heard.append)

        class Screen(Admission):
            def options(self):
                return {"operations": self.operations, "screen": [8, 6], "hz": 20}

        admission = Screen(conversation, session, ("type_text", "get_state"))
        self.addCleanup(admission.close)
        root = Path(__file__).resolve().parents[1]
        paths = [str(root / "src"), str(root / "packages" / "computer" / "harness_computer")]

        @contextmanager
        def launcher(options):
            argv = ["kernel", "--bootstrap", "managed_program:ManagedProgram", "--forward-workspace-requests",
                    "--options", json.dumps(options)]
            code = (f"import runpy, sys; sys.path[:0] = {paths!r}; sys.argv = {argv!r}; "
                    "runpy.run_module('harness.runtime.execution.kernel', run_name='__main__')")
            yield [sys.executable, "-u", "-c", code], ()

        process = Kernel(DEFAULT_BOOTSTRAP, {}, managed=admission, managed_launcher=launcher, start_timeout=60,
                         on_span=lambda record: ended.append(record) if record.get("op") == "unit_end" else None)
        self.addCleanup(process.close)
        first = process.start("typed = type_text(30, seconds=0.05)\nprint('typed', typed['event']['kind'])",
                              grace=0.2, timeout=60, name="program 1")
        second = process.start("print('step', get_state()['step'] >= 0)", grace=20, timeout=60, name="program 2")
        self.assertEqual(first["status"], "running")
        # The second program ran beside the first, with its own output.
        self.assertEqual((second["status"], second["stdout"]), ("ok", "step True\n"))
        deadline = time.monotonic() + 30
        while not ended and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(ended), 1)
        result = ended[0]
        self.assertEqual((result["unit"], result["status"], result["stdout"]), (first["unit"], "ok", "typed COMPLETED\n"))
        # The state and the unit's start and end are the host's own, not the isolated process's word.
        self.assertEqual(result["state"]["step"], 30)
        self.assertEqual([(row["op"], row["id"]) for row in heard if row["id"] == first["unit"]],
                         [("entry_start", first["unit"]), ("entry_end", first["unit"])])


if __name__ == "__main__":
    unittest.main()
