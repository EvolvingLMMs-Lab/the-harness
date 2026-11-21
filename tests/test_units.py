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


# Under the required method a node that tells the model anything says what the model reads
# then (about=, report=): the nodes of these tests say the same thing unless a test says its own.
SAYS = "\n".join([
    "_set_reflex = set_reflex",
    "def set_reflex(*arguments, **settings):",
    "    settings.setdefault('about', 'a situation of the test')",
    "    settings.setdefault('report', lambda view, returned: 'as the test left it')",
    "    return _set_reflex(*arguments, **settings)",
    ""])


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
                     "skills": ["desktop"], "turn_grace_seconds": 0.3, "purpose": "optional", "reflex_method": "optional",
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
    def test_s1_the_turn_comes_back_while_a_program_runs_and_its_end_starts_the_next_turn_after_an_answer(self):
        with Episode([program("type_text(6, seconds=0.2)"), program("print('beside', get_state()['step'])"),
                      "It is on its way.", "It is typed."]) as episode:
            summary = episode.end()
            cells = {row["number"]: row["result"] for row in episode.records("cell")}
            turns = [(row["turn"], row.get("result")) for row in episode.records("turn_result")]
            requests = episode.chat.requests
            result = episode.run.result
        self.assertEqual(summary["status"], "finished")
        self.assertIn("Program 1 is still running", texts(requests[1][-1]))
        # The second program ran beside the first, with its own output and result.
        self.assertEqual((cells[2]["status"], cells[2]["stdout"].split()[0]), ("ok", "beside"))
        # Nobody talks to this run: the answer given while the first program ran ended the
        # turn and not the run. The program went on to its end, which started the next turn;
        # the answer given when nothing ran any more ended the run.
        self.assertEqual(cells[1]["status"], "ok")
        self.assertEqual(turns, [(1, "It is on its way."), (2, "It is typed.")])
        self.assertIn("Program 1 ended", texts(requests[3][-1]))
        self.assertEqual(result, "It is typed.")

    def test_an_answer_with_nothing_running_ends_a_run_nobody_talks_to(self):
        with Episode([program("type_text(1)"), "It is typed."]) as episode:
            summary = episode.end()
            turns = [row["turn"] for row in episode.records("turn_result")]
            calls = len(episode.chat.requests)
        self.assertEqual((summary["status"], turns, calls), ("finished", [1], 2))

    def test_every_call_after_a_reply_is_told_the_pace_of_that_reply(self):
        with Episode([program("type_text(1)"), "It is typed."]) as episode:
            episode.end()
            requests = episode.chat.requests
        # Nothing to say of a reply before the first one; then how long the last reply took
        # to write and for how much of that no program of the model ran.
        self.assertNotIn("Your last reply took", texts(requests[0][-1]))
        self.assertRegex(texts(requests[1][-1]), r"Your last reply took \d+ s to write; for \d+ s of them no program of yours ran\.")

    def test_the_pace_is_not_told_while_the_environment_says_the_agent_cannot_act(self):
        from harness.runtime.decision.loop import reply_pace
        from harness.runtime.execution.session import EpisodeCore

        self.assertEqual(reply_pace((12.4, 9.6), {"step": 3}),
                         "Your last reply took 12 s to write; for 10 s of them no program of yours ran.")
        self.assertEqual(reply_pace((12.4, 30.0), {}), "Your last reply took 12 s to write; for 12 s of them no program of yours ran.")
        # Nothing stands waiting for the model: there is no pace to keep.
        self.assertIsNone(reply_pace((12.4, 9.6), {"can_act": False}))
        self.assertIsNotNone(reply_pace((12.4, 9.6), {"can_act": True}))
        self.assertIsNone(reply_pace(None, {}))
        # The same word of the environment keeps the tree of reflexes from being judged.
        self.assertFalse(EpisodeCore.can_act(None, {"can_act": False}))
        self.assertTrue(EpisodeCore.can_act(None, {"step": 3}))
        self.assertTrue(EpisodeCore.can_act(None, None))

    def test_a_program_sent_while_another_runs_acts_after_it_with_after(self):
        first = program("type_text(6, seconds=0.2)")
        second = "<python>\nuntil(None)\nprint('GOT', after(UNIT), get_state()['step'])\n</python>"
        with Episode([first, "<wait>30</wait>", "<finish>done</finish>"]) as episode:
            episode.end()
            told = texts(episode.chat.requests[1][-1])
        unit = re.search(r"as unit (\S+?)\.", told).group(1)
        self.assertIn(f'after("{unit}")', told)
        with Episode([first, second.replace("UNIT", repr(unit)), "<wait>30</wait>", "<finish>done</finish>"]) as episode:
            summary = episode.end()
            cells = {row["number"]: row["result"] for row in episode.records("cell")}
        self.assertEqual(summary["status"], "finished")
        # The second program returned from after() only when the first had ended, done or not,
        # and then saw every step the first had made.
        self.assertEqual(cells[1]["status"], "ok")
        self.assertIn("'ended': 'done'", cells[2]["stdout"])
        self.assertEqual(cells[2]["stdout"].split()[-1], "6")

    def test_one_program_waits_behind_a_running_one_not_a_chain(self):
        # f179: walk, fight and portal queued one behind another, each written before the one
        # before it had ended.
        first = program("type_text(40, seconds=0.2)")
        second = program("until(None)\nafter('e1')\nprint('second')")
        third = program("until(None)\nafter('e2')\nprint('third')")
        with Episode([first, second, third, "<wait>30</wait>", "<finish>done</finish>"]) as episode:
            episode.end()
            requests = episode.chat.requests
            cells = {row["number"]: row["result"] for row in episode.records("cell")}
        # Once e2 waits behind e1, the model is told to send nothing more behind it.
        told = texts(requests[2][-1])
        self.assertIn("e2 waits for e1 to end and then acts. Send no program behind e2", told)
        self.assertNotIn("Write the program for what comes after it now", told)
        # And after() refuses to wait for a unit that itself still waits.
        self.assertIn("itself still waits for e1", str(cells[3]))
        self.assertNotIn("third", cells[3].get("stdout") or "")
        self.assertIn("second", cells[2]["stdout"])

    def test_every_call_while_a_program_runs_is_told_the_same_about_it(self):
        with Episode([program("type_text(60, seconds=0.2)"), "<wait>1</wait>", program("print('beside')"),
                      "<finish>done</finish>"]) as episode:
            episode.end()
            requests = episode.chat.requests
        started, waited, other = (texts(requests[index][-1]) for index in (1, 2, 3))
        # Just started, a wait over, another program ended: one moment, one text.
        for told in (started, waited, other):
            self.assertIn("A program of yours runs (e1). Write the program for what comes after it now", told)
            self.assertIn('it begins with after("e1")', told)
            self.assertIn("look in on this one well before it is due to end", told)
        self.assertIn("Program 1 is still running, as unit e1.", started)
        self.assertIn("Wait ended after", waited)
        # The program that ended beside it is not the task's end: the running one still is the work.
        self.assertIn("Program 2 ended", other)
        self.assertNotIn("The program ended. If the task is done", other)

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


    def test_the_pace_tells_how_long_the_model_waited_for_its_own_program(self):
        with Episode([program("type_text(100, seconds=0.2)"), "<wait>1.5</wait>", "<finish>done</finish>"]) as episode:
            episode.end()
            last = episode.chat.requests[2][-1]
        ambient = " ".join(part["text"] for part in last["content"] if part.get("ambient"))
        self.assertIn("Since your last program you waited 1 times, 2 s in all, for programs of yours to end.", ambient)

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

    def test_an_atomic_step_holds_off_every_node_for_its_seconds_at_most(self):
        body = "\n".join([
            "import time",
            "set_reflex('any', lambda view: view['facts'].get('go'), lambda: facts.set('ran', get_state()['step']))",
            "with atomic(0.6):",
            "    facts.set('go', True)",
            "    time.sleep(0.3)",
            "    print('within', facts.get('ran'))",
            "    time.sleep(0.9)",
            "print('after', facts.get('ran') is not None)"])
        with Episode([program(body), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}) as episode:
            episode.end()
            cell = episode.records("cell")[0]["result"]
        self.assertIn("within None", cell["stdout"])
        self.assertIn("atomic(): the step took longer than 0.6 s", cell["stdout"])
        self.assertIn("after True", cell["stdout"])

    def test_a_failed_node_is_tried_again_once_its_over_held_while_its_condition_did_not(self):
        # A node whose condition and `over` never hold together (hungry at 13, fed at 18): it fails, its
        # situation is past (fed) while its condition does not hold, and it acts again when it comes anew.
        body = "\n".join([
            "import time",
            "set_reflex('hungry', lambda view: view['facts'].get('f', 20) <= 13, lambda: 1 / 0,",
            "           over=lambda view: view['facts'].get('f', 20) >= 18, tell_failed='next')",
            "for f in (12, 20, 12):",
            "    facts.set('f', f)",
            "    time.sleep(0.8)"])
        with Episode([program(body), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}) as episode:
            episode.end()
            began = [row for row in episode.records("entry_start") if row.get("rule") == "hungry"]
        self.assertEqual(len(began), 2)

    def test_s3_a_rule_starts_its_program_when_a_fact_it_reads_changes(self):
        body = "\n".join([
            "def refill():",
            "    type_text(2)",
            "    facts.set('refills', facts.get('refills', 0) + 1)",
            "    facts.set('low', False)",
            "set_reflex('refill', lambda view: view['facts'].get('low'), refill)",
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
        self.assertEqual([row["priority"] for row in started], [0.5])   # (its place: the only node)

    def test_a_node_that_reads_the_state_is_judged_while_no_program_runs(self):
        # The environment changes by itself (the test sets its step) while the model waits and no program runs.
        body = "set_reflex('moved', lambda view: view['step'] >= 1000, lambda: facts.set('seen', True))"
        with Episode([program(body), "<wait>10</wait>", "<finish>done</finish>"]) as episode:
            episode.start()
            self.assertTrue(episode.until(lambda: episode.records("cell")))
            episode.environment.step = 1000
            moved = episode.until(lambda: [row for row in episode.records("entry_start") if row.get("rule") == "moved"], 5.0)
            episode.end()
        self.assertTrue(moved)


    def test_s4_a_rule_that_takes_the_embodiment_ends_the_lower_call_and_tells_the_model_at_once(self):
        asked = "\n".join([
            "def urgent():",
            "    facts.set('urgent_at', get_state()['step'])",
            "    type_text(1)",
            "    facts.set('done', True)",
            "set_reflex('urgent', lambda view: view['step'] >= view['facts'].get('at', 3) and not view['facts'].get('done'),",
            "           urgent)",
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
            self.assertIn(f"urgent took the environment from {name} during type_text", told)


    def test_a_node_and_the_program_it_interrupts_say_what_the_model_reads(self):
        asked = "\n".join([
            "def low():",
            "    type_text(1)",
            "    facts.set('lows', facts.get('lows', 0) + 1)",
            "    return 'pressed a key'",
            "set_reflex('low', lambda view: view.get('step', 0) >= 2 and view['facts'].get('lows', 0) < 1, low,",
            "           tell='never', tell_failed='never')",
            "until(lambda view: view.get('step', 0) >= 100,",
            "      report=lambda view: {'typed': view.get('step', 0), 'of': 100})",
            "type_text(8, seconds=0.05)"])
        with Episode([program(asked), "<wait>20</wait>", "<finish>done</finish>"], pauses=True,
                     runtime={"turn_grace_seconds": 30, "reflex_method": "optional"}) as episode:
            summary = episode.end()
            acted = [row["reported"] for row in episode.records("escalation") if row["reported"]["kind"] == "REFLEX_ACTED"]
            said = "\n".join(texts(request[-1]) for request in episode.chat.requests[1:])
            ended = episode.records("cell")[0]["result"]
        self.assertEqual(summary["status"], "finished")
        # The node says nothing of itself (tell="never"); the program asks to be told (the default), so
        # there is one message, at the program's place in the queue.
        self.assertEqual([(event["source"], event["detail"]["tell"]) for event in acted], [("low", "next")])
        self.assertIn("Event REFLEX_ACTED from low:\nlow did its work: its program ended by itself", said)
        self.assertIn("It took the environment from program 1, once so far", said)
        self.assertIn("low returned: pressed a key", said)
        self.assertRegex(said, r'program 1 reports: \{"typed": \d+, "of": 100\} \(running [\d.]+ s; done: no\)')
        # The message ends with whose choice it was to be told, and what to do with it.
        self.assertIn("You are told this because you chose to be when you wrote program 1: it matters to that "
                      "work. Do not wait on as before.", said)
        # Its end says what it reports then, and that what it was for is not the case.
        self.assertEqual(ended["done"], False)
        self.assertRegex(ended["says"], r'\{"typed": \d+, "of": 100\}')

    def test_a_node_that_tells_says_its_sentence_and_its_report_and_a_program_may_end_when_interrupted(self):
        asked = "\n".join([
            "def low():",
            "    type_text(1)",
            "    facts.set('lows', facts.get('lows', 0) + 1)",
            "try:",
            "    set_reflex('low', lambda view: False, low)",
            "except ValueError as error:",
            "    print('refused:', str(error)[:60])",
            "set_reflex('low', lambda view: view.get('step', 0) >= 2 and view['facts'].get('lows', 0) < 1, low,",
            "           tell='never', tell_failed='next', about='two keys were typed',",
            "           report=lambda view, returned: {'step': view.get('step', 0), 'lows': view['facts'].get('lows')})",
            "print('about', reflexes()[0].get('about'))",
            "until(lambda view: False, report=lambda view: 'typing the long word', interrupted='stop')",
            "type_text(8, seconds=0.05)"])
        # (The page on the tree is asked for in a program of its own: it is read from the next message on.)
        with Episode([program("reflex_method()"), program("situations('something happens to the agent')\n" + asked), "<finish>done</finish>"], pauses=True,
                     runtime={"turn_grace_seconds": 30, "reflex_method": "required"}) as episode:
            summary = episode.end()
            cell = episode.records("cell")[1]["result"]
            said = "\n".join(texts(request[-1]) for request in episode.chat.requests[2:])
        self.assertEqual(summary["status"], "finished")
        self.assertIn("refused: Nothing was set: a node that tells you anything says what yo", cell["stdout"])
        self.assertIn("about two keys were typed", cell["stdout"])
        # The program asked to end when a reflex takes the environment from it: it ended there, and the
        # model reads the node's sentence and the program's own report.
        self.assertEqual((cell["status"], cell["escalation"]["event"]["kind"]), ("escalated", "PREEMPTED"))
        self.assertIn("low (two keys were typed) took the environment from program 2 during type_text, which ended "
                      'there as it asked to (until(interrupted="stop")).', said)
        self.assertIn("program 2 reports: typing the long word (done: no)", said)
        self.assertIn("program 2 ended because you chose so when you wrote it.", said)

    def test_a_program_is_told_of_its_interruptions_three_times_and_the_rest_with_its_end(self):
        asked = "\n".join([
            "def low():",
            "    type_text(1)",
            "    facts.set('lows', facts.get('lows', 0) + 1)",
            "    facts.set('due', get_state()['step'] + 6)",
            "set_reflex('low', lambda view: view.get('step', 0) >= view['facts'].get('due', 2) and "
            "           view['facts'].get('lows', 0) < 5, low, tell='never', tell_failed='never')",
            "until(lambda view: True, report=lambda view: 'typing')",
            "type_text(60, seconds=0.05)"])
        # (Each message ends a wait; the waits left over run out after the program has ended.)
        with Episode([program(asked), *["<wait>3</wait>"] * 8, "<finish>done</finish>"], pauses=True,
                     runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            acted = [row for row in episode.records("escalation") if row["reported"]["kind"] == "REFLEX_ACTED"]
            ended = episode.records("cell")[0]["result"]
            said = "\n".join(texts(request[-1]) for request in episode.chat.requests[1:])
        self.assertEqual(summary["status"], "finished")
        self.assertEqual(len(acted), 3)
        self.assertEqual(ended["interruptions_untold"], 2)
        self.assertIn("Reflexes took the environment from it 2 times more than you were told one by one.", said)

    def test_a_report_is_a_message_with_text_pictures_and_files(self):
        asked = "\n".join([
            "from pathlib import Path",
            "Path('notes.txt').write_text('two keys so far')",
            "def low():",
            "    type_text(1)",
            "    facts.set('lows', facts.get('lows', 0) + 1)",
            "set_reflex('low', lambda view: view.get('step', 0) >= 2 and view['facts'].get('lows', 0) < 1, low,",
            "           tell='never', tell_failed='never')",
            "until(lambda view: False,",
            "      report=lambda view: ['typed', view.get('step', 0), look('screen', since=30), Path('notes.txt')])",
            "type_text(8, seconds=0.05)"])
        with Episode([program(asked), "<wait>20</wait>", "<finish>done</finish>"], pauses=True,
                     runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            requests = episode.chat.requests
            recorded = [row["reported"]["detail"] for row in episode.records("escalation")
                        if row["reported"]["kind"] == "REFLEX_ACTED"]
            cell = episode.records("cell")[0]["result"]
            looked = episode.environment.observe_asked
        self.assertEqual(summary["status"], "finished")
        parts = [part for request in requests[1:] for part in (request[-1]["content"] if isinstance(request[-1]["content"], list) else [])]
        said = "\n".join(part.get("text", "") for part in parts)
        # In the message about the reflex: the program's text, then its picture and its file, each under whose it is.
        self.assertRegex(said, r"program 1 reports: typed \d+ \(running")
        shown = [index for index, part in enumerate(parts) if part.get("text") == "program 1 shows screen:"]
        self.assertTrue(shown and parts[shown[0] + 1]["type"] == "input_image")
        self.assertRegex(said, r"program 1 attaches \S*notes\.txt:\ntwo keys so far")
        # At its end the same report again, under the program's name.
        ended = [index for index, part in enumerate(parts) if part.get("text") == "Program 1 shows screen:"]
        self.assertTrue(ended and parts[ended[0] + 1]["type"] == "input_image")
        # What a look in a report is asked with is passed on to the environment as given.
        self.assertEqual(looked, {"since": 30})
        # The record keeps the count of pictures and files, not the pictures.
        self.assertEqual((recorded[0]["interrupted"][0]["shows"], recorded[0]["interrupted"][0]["files"]), (1, 1))
        self.assertNotIn("shows", cell)
        # A look inside a report is the report's alone: nothing was put into the program's own result.
        self.assertFalse(cell.get("looks"))

    def test_what_a_report_may_return(self):
        import tempfile
        from pathlib import Path

        from harness.runtime.reactive import tree

        class Seen:
            _urls = {"screen": "data:image/png;base64,AAAA"}

        with tempfile.TemporaryDirectory() as root:
            note = Path(root) / "note.txt"
            note.write_text("x" * (tree.FILE_CHARS + 5), encoding="utf-8")
            self.assertEqual(tree.message(lambda: "plain text"), {"says": "plain text"})
            self.assertEqual(tree.message(lambda: {"ore": 3}), {"says": '{"ore": 3}'})
            self.assertEqual(tree.message(lambda: None), {})
            self.assertEqual(tree.message(None), {})
            told = tree.message(lambda: ["ore", 3, Seen(), note, Path(root) / "missing.txt", Path(root)])
            self.assertEqual(told["says"], f"ore 3 (no file {Path(root) / 'missing.txt'})")
            self.assertEqual(told["shows"], [{"caption": "screen", "image_url": "data:image/png;base64,AAAA"}])
            self.assertEqual([item["name"] for item in told["files"]], [str(note), str(root)])
            self.assertTrue(told["files"][0]["text"].endswith("[5 more characters]"))
            self.assertEqual(told["files"][1]["text"], "note.txt")
            # No more pictures than the limit, and a report that raises says so in its place.
            self.assertEqual(len(tree.message(lambda: [Seen()] * 9)["shows"]), tree.REPORT_PICTURES)
            self.assertEqual(tree.message(lambda: 1 / 0), {"says": "(its report raised ZeroDivisionError: division by zero)"})
            self.assertEqual(tree.said(lambda: ["ore", Seen()]), "ore")

    def test_code_that_runs_in_the_environment_asks_for_a_priority_for_one_action_of_it(self):
        asked = "\n".join([
            "def low():",
            "    type_text(1)",
            "    facts.set('low_at', get_state()['step'])",
            "set_reflex('low', lambda view: view.get('step', 0) >= 2 and not view['facts'].get('low_at'), low)",
            "type_text(8, seconds=0.05)",
            "facts.set('typed_at', get_state()['step'])"])
        with Episode([program(asked), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}, pauses=True) as episode:
            # What runs in the environment holds it above every node up to its sixth step, and says so with its state.
            episode.environment.asks = lambda step: True if step < 6 else None
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
            "set_reflex('known', lambda view: view['facts'].get('danger'), handle, under='trouble')",
            "set_reflex('unanswered', lambda view: True, 'UNANSWERED', under='trouble')",
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
            "set_reflex('broad', lambda view: view['facts'].get('on') and not view['facts'].get('seen'), broad)",
            "set_reflex('narrow', lambda view: view.get('step', 0) >= 3, narrow, under='broad')",
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
            "set_reflex('job', lambda view: not view['facts'].get('closed'))",
            "set_reflex('alarm', lambda view: view['facts'].get('alarm') and not view['facts'].get('urgent_done'), urgent,",
            "           under='job')",
            "set_reflex('work', lambda view: not view['facts'].get('work_done'), work, under='job')",
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
        self.assertIn("broken ran, and the agent is still in its situation with no other node answering it", last)

    def test_a_node_whose_program_ends_with_its_situation_not_over_gives_way_to_a_later_node_or_the_model_is_told(self):
        first = "\n".join([
            "import time",
            "def swing():",
            "    facts.set('swings', facts.get('swings', 0) + 1)",
            "    return {'hits': 0}",
            "def leave():",
            "    facts.set('danger', False)",
            "set_reflex('fight', lambda view: view['facts'].get('danger'), swing)",
            "set_reflex('retreat', lambda view: view['facts'].get('danger') and view['facts'].get('swings', 0) >= 1, leave)",
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
        self.assertIn("fight ran, and the agent is still in its situation with no other node answering it: "
                      "its program ended by itself", last)
        self.assertIn("fight returned: ", last)
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

    def summarizing(self, replies, summaries, seconds=0.0):
        """A scripted model whose summaries come from `summaries` (each after `seconds`)."""
        from harness.runtime.decision.model import USAGE, ChatReply

        class Summarizing(Recording):
            def __init__(self):
                super().__init__(replies)
                self.summaries, self.asked, self.summarizing, self.beside = list(summaries), [], 0, 0

            def complete(self, system, messages):
                if "Please write a summary of the transcript." in texts(messages[-1]):
                    self.asked.append(time.monotonic())
                    self.summarizing += 1
                    try:
                        time.sleep(seconds)
                    finally:
                        self.summarizing -= 1
                    text = self.summaries.pop(0) if self.summaries else ""
                    return ChatReply(text=text, usage=dict(USAGE))
                # (A call of the model made while a summary is being written.)
                self.beside += bool(self.summarizing)
                return super().complete(system, messages)

        return Summarizing()

    def test_the_summary_is_written_ahead_and_put_in_at_the_limit(self):
        # f148: 15 compactions of 43-70 s each, the conversation waiting for every one.
        big = "print('x' * 3000)"
        chat = self.summarizing([program(big), program(big), program(big), program(big), "<finish>done</finish>"],
                                ["<summary>Printed four long lines.</summary>"])
        with Episode([], runtime={"compact_arm_tokens": 1, "compact_at_tokens": 2400}) as episode:
            episode.run.chat = episode.chat = chat
            summary = episode.end()
            compactions = episode.records("compaction")
            requests = chat.requests
        self.assertEqual(summary["status"], "finished")
        actions = [(row["action"], row.get("how")) for row in compactions]
        self.assertEqual(actions, [("asked_ahead", None), ("done", "ahead")])
        done = compactions[-1]
        # Nothing waited for it: it was back before the limit.
        self.assertEqual(done["waited_seconds"], 0.0)
        # No call of the model was made for the summary in the conversation itself.
        self.assertFalse(any("Please write a summary" in texts(request[-1]) for request in requests))
        # The summary stands in the first message, and what came after it was asked for stays as it was.
        after = next(request for request in requests if "Printed four long lines." in texts(request[0]))
        self.assertEqual(texts(after[0]).count("Printed four long lines."), 1)
        self.assertLess(len(after), done["messages_before"] + 1)

    def test_where_the_model_says_its_window_compaction_is_at_a_share_of_it(self):
        # f179/f180: compaction at a fixed 150000 of a model that reads 1000000 (Claude Code: about 83% of it).
        big = "print('x' * 3000)"

        def told(window):
            chat = self.summarizing([program(big), program(big), program(big), program(big), "<finish>done</finish>"],
                                    ["<summary>Printed four long lines.</summary>"])
            complete = chat.complete

            def with_window(system, messages):
                reply = complete(system, messages)
                if window:
                    reply.usage["context_window"] = window
                return reply
            chat.complete = with_window
            return chat
        # The window said: the limit is its share, whatever compact_at_tokens is.
        with Episode([], runtime={"compact_arm_tokens": 1, "compact_at_tokens": 10 ** 9, "compact_at_share": 0.5}) as episode:
            episode.run.chat = episode.chat = told(4800)
            episode.end()
            rows = episode.records("compaction")
        self.assertEqual([(row["action"], row.get("limit")) for row in rows][:1], [("asked_ahead", 2400)])
        self.assertIn("done", [row["action"] for row in rows])
        # No window said: compact_at_tokens, as before.
        with Episode([], runtime={"compact_arm_tokens": 1, "compact_at_tokens": 10 ** 9, "compact_at_share": 0.5}) as episode:
            episode.run.chat = episode.chat = told(None)
            episode.end()
            rows = episode.records("compaction")
        self.assertEqual({row.get("limit") for row in rows}, {10 ** 9})
        self.assertNotIn("done", [row["action"] for row in rows])

    def test_a_summary_not_back_at_the_limit_is_waited_for_and_one_that_failed_is_written_then(self):
        big = "print('x' * 3000)"
        slow = self.summarizing([program(big), program(big), program(big), "<finish>done</finish>"],
                                ["<summary>Slow but there.</summary>"], seconds=5.0)
        with Episode([], runtime={"compact_arm_tokens": 1, "compact_at_tokens": 1500}) as episode:
            episode.run.chat = episode.chat = slow
            episode.end()
            done = [row for row in episode.records("compaction") if row["action"] == "done"]
        self.assertEqual([row["how"] for row in done], ["ahead"])
        # It was waited for at the limit, and the model was called while it was being written.
        self.assertGreater(done[0]["waited_seconds"], 0.0)
        self.assertGreaterEqual(slow.beside, 1)
        failed = self.summarizing([program(big), program(big), program(big), "<finish>done</finish>"],
                                  ["no summary at all", "<summary>Written at the limit.</summary>"])
        with Episode([], runtime={"compact_arm_tokens": 1, "compact_at_tokens": 1500}) as episode:
            episode.run.chat = episode.chat = failed
            episode.end()
            rows = [(row["action"], row.get("how"), row.get("why")) for row in episode.records("compaction")]
        self.assertEqual(rows[:3], [("asked_ahead", None, None), ("ahead_dropped", None, "it gave no summary"),
                                    ("done", "waited", None)])

    def test_a_summary_asked_for_ahead_is_dropped_when_the_past_it_summarizes_changed(self):
        from types import SimpleNamespace

        from harness.runtime.task.run import TaskRun

        run = TaskRun.__new__(TaskRun)
        emitted = []
        run.trace = SimpleNamespace(emit=lambda event, **detail: emitted.append((event, detail)))
        first, kept = {"role": "user", "content": "task"}, {"role": "assistant", "content": "a"}
        reply = SimpleNamespace(text="<summary>past</summary>")
        thought = SimpleNamespace(ready=threading.Event(), error=None, cancelled=False, reply=reply)
        thought.ready.set()
        run.messages = [{"role": "user", "content": "another first"}, kept, {"role": "user", "content": "b"}]
        run._precomputed = {"thought": thought, "first": first, "kept": kept, "asked": time.monotonic(), "tokens": 9}
        self.assertFalse(run._put_precomputed(SimpleNamespace()))
        self.assertEqual(emitted[0][1]["why"], "the conversation changed before the messages it keeps")
        self.assertIsNone(run._precomputed)

    def test_a_node_that_failed_is_not_tried_again_until_its_situation_was_past(self):
        # f151: a node whose program returned at once with its situation unchanged was begun again
        # every 0.2 s, 52 times, and each time took the place of the node above it.
        asked = "\n".join([
            "import time",
            "def nothing():",
            "    facts.set('tries', facts.get('tries', 0) + 1)",
            "set_reflex('tick', lambda view: bool(view['facts'].get('go')), nothing, every=0.05,",
            "           tell='never', tell_failed='never')",
            "facts.set('go', True)",
            "time.sleep(0.8)",
            "first = facts.get('tries')",
            "facts.set('go', False)",
            "time.sleep(0.3)",
            "facts.set('go', True)",
            "time.sleep(0.5)",
            "print('tries', first, facts.get('tries'))"])
        with Episode([program(asked), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}) as episode:
            episode.end()
            rows = [row["action"] for row in episode.records("rule") if row.get("name") == "tick"]
            tries = episode.records("cell")[0]["result"]["stdout"].split()
        # It began once, failed (it returned and the situation stood), and was left alone; when the
        # situation had been past and came anew, once more.
        self.assertEqual(tries, ["tries", "1", "2"])
        self.assertEqual(rows[:3], ["holds", "began", "failed"])
        self.assertEqual(rows.count("began"), 2)

    def test_after_a_compaction_how_things_stand_is_told_as_it_is_then(self):
        from harness.runtime.task.run import TaskRun as Run

        told = []
        real = Run._ambient

        def ambient(run, loop):
            part = dict(real(run, loop))
            told.append(len(told) + 1)
            part["text"] += f"\n(ambient {len(told)})"
            return part

        with mock.patch.object(Run, "_ambient", ambient), \
                Episode([program("print(1)"), program("print(2)"),
                         "<analysis>one, two</analysis><summary>Printed 1 and 2; next is to finish.</summary>",
                         "<finish>done</finish>"],
                        runtime={"compact_at_tokens": 1}) as episode:
            episode.end()
            requests = episode.chat.requests
        # The summary was asked with the state as it was told before it; the call after it ends with the
        # state told anew after the summary (the last one built), and with that one only.
        before, after = texts(requests[2][-1]), texts(requests[3][-1])
        self.assertIn(f"(ambient {len(told) - 1})", before)
        self.assertTrue(after.endswith(f"(ambient {len(told)})"))
        self.assertEqual(after.count("(ambient "), 1)

    def test_after_a_compaction_the_pages_read_are_named_and_not_given_again(self):
        with Episode([program("print(guide('units'))"), program("print(2)"),
                      "<analysis>one, two</analysis><summary>Read the page on units; next is to finish.</summary>",
                      "<finish>done</finish>"],
                     runtime={"compact_at_tokens": 1}) as episode:
            episode.end()
            requests = episode.chat.requests
        first = json.dumps(requests[3][0])
        self.assertIn('Note: you read these pages before this summary: \\"units\\"', first)
        self.assertNotIn("the page you asked for", first)
        self.assertLess(len(first), 40_000)

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
            "           urgent)",
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
            "           urgent, ends=True)",
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
                      "<python>\nuntil(None)\nexpect('nothing', lambda: True)\nprint('read')\n</python>",
                      "<python>\nuntil(lambda view: view['step'] >= 1)\nexpect('nothing', lambda: True)\n"
                      "type_text(1)\n</python>",
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

    def test_a_program_checks_what_it_relies_on_before_it_acts(self):
        with Episode(["<python>\nuntil(None)\nprint('read')\n</python>",
                      "<python>\nuntil(None)\nexpect('the door is open', lambda: 'the door is shut')\n"
                      "print('read on')\n</python>",
                      "<python>\nuntil(lambda view: view['step'] >= 1)\ntype_text(1)\n</python>",
                      "<python>\nuntil(lambda view: view['step'] >= 1)\n"
                      "expect('the way is free', lambda: 'a wall is in the way')\ntype_text(1)\n</python>",
                      "<python>\nuntil(lambda view: view['step'] >= 99)\nexpect('the way is free', lambda: True)\n"
                      "type_text(1)\n</python>",
                      "<finish>done</finish>"], runtime={"purpose": "required"}) as episode:
            summary = episode.end()
            cells = [row["result"] for row in episode.records("cell")]
            refused = episode.records("program_refused")
            told = [json.dumps(request) for request in episode.chat.requests]
        self.assertEqual(summary["status"], "finished")
        # A program that does not act is held to nothing: it runs without an expect.
        self.assertEqual(refused, [])
        self.assertEqual(len(cells), 5)
        self.assertIn("read", cells[0]["stdout"])
        # One that only reads goes on, and its end says where what it found differs.
        self.assertIn("read on", cells[1]["stdout"])
        self.assertEqual(cells[1]["expected"], [{"text": "the door is open", "held": False,
                                                 "found": "the door is shut"}])
        self.assertIn("it does not hold: the door is shut", told[2])
        # An action with no expect before it is refused where it is called, and nothing acted.
        self.assertEqual(cells[2]["status"], "error")
        self.assertIn("has not checked what it relies on", cells[2]["error"])
        self.assertIn("what else the action changes", cells[2]["error"])
        # One that acts ends at the expectation that is not so: nothing after it ran.
        self.assertEqual(cells[3]["status"], "error")
        self.assertIn("Nothing further ran: you expected", cells[3]["error"])
        self.assertIn("a wall is in the way", cells[3]["error"])
        # With its expectation held it acts; the result is not there, and it is told so.
        self.assertEqual(cells[4]["status"], "ok")
        self.assertEqual(cells[4]["expected"], [{"text": "the way is free", "held": True}])
        self.assertIs(cells[4]["done"], False)
        self.assertIn("relied on something it did not check", told[5])

    def test_a_program_acts_only_when_every_listed_situation_is_answered_and_a_failure_adds_an_expectation(self):
        acts = "until(lambda view: view['step'] >= 99)\nexpect('the way is free', lambda: True)\ntype_text(1)"
        with Episode([program("until(None)\nreflex_method()"),
                      program(acts),
                      program("until(None)\nprint(situations('a key is typed'))"),
                      program(acts),
                      program("set_reflex('typed', lambda view: False, lambda: None, tell='never', tell_failed='never',"
                              " covers=['a key is typed'])\n" + acts),
                      program(acts),
                      program(acts.replace("type_text(1)", "expect('the key is there', lambda: True)\ntype_text(1)")),
                      "<finish>done</finish>"],
                     runtime={"purpose": "required", "reflex_method": "required"}) as episode:
            summary = episode.end()
            cells = [row["result"] for row in episode.records("cell")]
        self.assertEqual(summary["status"], "finished")
        # Nothing listed: no action. A line with nothing that answers it: no action.
        self.assertIn("you have not said what can happen to the agent", cells[1]["error"])
        self.assertIn('nothing answers these lines of situations() yet: "a key is typed"', cells[3]["error"])
        # Answered: it acts. Its expectation held and its result is not there.
        self.assertEqual((cells[4]["status"], cells[4]["done"]), ("ok", False), cells[4].get("error"))
        # The same expectations again: refused. With one that is new: it acts.
        self.assertIn("relied on something that was not checked", cells[5]["error"])
        self.assertEqual(cells[6]["status"], "ok")

    def test_a_new_check_that_fails_lifts_the_refusal_of_the_old_ones(self):
        # f111: after a failed program, a new check found what had not been checked (it failed, nothing acted);
        # the next program, which put it right with the old checks only, was refused all the same.
        acts = "until(lambda view: view['step'] >= 99)\nexpect('the way is free', lambda: True)\ntype_text(1)"
        with Episode([program("until(None)\nreflex_method()"),
                      program("until(None)\nprint(situations('a key is typed'))"),
                      program("set_reflex('typed', lambda view: False, lambda: None, tell='never', tell_failed='never',"
                              " covers=['a key is typed'])\n" + acts),
                      program(acts.replace("type_text(1)", "expect('the hand is empty', lambda: 'a stone')\ntype_text(1)")),
                      program(acts),
                      "<finish>done</finish>"],
                     runtime={"purpose": "required", "reflex_method": "required"}) as episode:
            summary = episode.end()
            cells = [row["result"] for row in episode.records("cell")]
        self.assertEqual(summary["status"], "finished")
        self.assertEqual((cells[2]["status"], cells[2]["done"]), ("ok", False), cells[2].get("error"))
        # The new check did not hold: nothing acted; the program after it acts with the old checks.
        self.assertIn("the hand is empty", str(cells[3].get("error")))
        self.assertEqual(cells[4]["status"], "ok", cells[4].get("error"))

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
            "def fix():",
            "    facts.set('level', 9)",
            "facts.set('level', 5)",
            "# The trial takes away the value the condition compares with: it raises.",
            "shown = set_reflex('low', lambda view: view['facts'].get('level') < 3, fix,",
            "                   test=lambda: facts.drop('level'))",
            "print('shown', shown['turn'], 'TypeError' in shown.get('error', ''))",
            "print('still', [row['name'] for row in reflexes()])",
            "# Once the value is there the same node is judged and has its turn.",
            "facts.set('level', 1)",
            "import time",
            "time.sleep(1.5)",
            "print('level', facts.get('level'))"])
        with Episode([program(SAYS + asked), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 60, "reflex_method": "optional"}) as episode:
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
            "def refill():",
            "    # The answer takes steps of the environment: the node above is judged at each.",
            "    type_text(3, seconds=0.05)",
            "    facts.set('level', 9)",
            "set_reflex('low', lambda view: (view['facts'].get('level') or 9) < 3, 'LEVEL_LOW', ends=True)",
            "# The node under it says only what distinguishes it within that situation.",
            "shown = set_reflex('refill', lambda view: bool(view['facts'].get('supply')), refill, under='low',",
            "                   test=lambda: (facts.set('supply', 1), facts.set('level', 1)))",
            "print('shown', shown['turn'], shown['done'], shown['last']['ended'], facts.get('level'))"])
        with Episode([program(SAYS + asked), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 60, "reflex_method": "optional"}) as episode:
            summary = episode.end()
            out = episode.records("cell")[0]["result"]["stdout"]
            told = json.dumps(episode.chat.requests[1])
        self.assertEqual(summary["status"], "finished")
        # The node under it did its work to the end, and is done although its own condition still holds.
        self.assertIn("shown True True by itself 9", out)
        # The node above never had its turn: the situation was answered.
        self.assertNotIn("LEVEL_LOW from", told)
        self.assertIn("tells you LEVEL_LOW and ends what runs; 0 times", told)

    def test_a_guide_is_read_on_demand_and_the_tree_guide_opens_set_reflex(self):
        asked = "\n".join([
            "print('units', guide('units'))",
            "try:",
            "    guide('everything')",
            "except ValueError as error:",
            "    print('refused:', str(error)[:40])",
            "# The tree's guide is what set_reflex waits for: asked for here, it is not read yet.",
            "print('tree', guide('tree'))",
            "try:",
            "    set_reflex('idle', lambda view: view['facts'].get('never'), lambda: None)",
            "except ValueError as error:",
            "    print('not yet:', str(error)[:40])"])
        later = ("try:\n    set_reflex('idle', lambda view: view['facts'].get('never'), lambda: None)\n"
                 "except ValueError as error:\n    print('no list:', str(error)[:70])\n"
                 "print('listed', situations('a key is typed', ('the screen is dark', 'nothing to do then')))\n"
                 "print('set', set_reflex('idle', lambda view: view['facts'].get('never'), lambda: None, covers=[1]))\n"
                 "print('now', situations()['unanswered'])\n"
                 "try:\n    set_reflex('other', lambda view: False, lambda: None, covers=['no such line'])\n"
                 "except ValueError as error:\n    print('no line:', str(error)[:40])")
        with Episode([program(SAYS + asked), program(SAYS + later), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 60, "reflex_method": "required"}) as episode:
            summary = episode.end()
            first, second = (row["result"]["stdout"] for row in episode.records("cell")[:2])
            out = first
            system = json.dumps(episode.chat.requests[0][0]) if episode.chat.requests else ""
            given = texts(episode.chat.requests[1][-1])
        self.assertEqual(summary["status"], "finished")
        # What the call returns says the page is on its way; the page itself is in the next message.
        self.assertIn('units guide("units"): the page is given to you with your next message', out)
        self.assertIn("refused: guide(name): name is one of", out)
        self.assertIn('tree guide("tree"): the page is given to you with your next message', out)
        self.assertIn("not yet: Nothing was set: read how a tree of re", out)
        self.assertIn('guide("units"), the page you asked for:\n\nguide("units"): how units run', given)
        self.assertIn("Reference: every call and setting of the tree", given)
        # A node is set only once the model has said what can happen to the agent; a node names
        # the lines it answers, and the list says which lines nothing answers yet.
        self.assertIn("no list: Nothing was set: say first what can happen to the agent", second)
        self.assertIn("'unanswered': ['a key is typed']", second)
        self.assertIn("set idle", second)
        self.assertIn("now []", second)
        self.assertIn("no line: covers='no such line' is no line", second)

    def test_a_node_is_set_after_the_method_was_read_does_something_and_can_be_judged(self):
        asked = "\n".join([
            "def refused(*arguments, **named):",
            "    try:",
            "        set_reflex(*arguments, **named)",
            "    except (ValueError, TypeError) as error:",
            "        print('refused:', str(error)[:62])",
            "def fix():",
            "    facts.set('broken', False)",
            "refused('repair', lambda view: view['facts'].get('broken'), fix)",
            "print('page', reflex_method())"])
        after = "\n".join([
            "def refused(*arguments, **named):",
            "    try:",
            "        set_reflex(*arguments, **named)",
            "    except (ValueError, TypeError) as error:",
            "        print('refused:', str(error)[:62])",
            "def fix():",
            "    facts.set('broken', False)",
            "# Every node does something.",
            "refused('empty', lambda view: view['facts'].get('broken'))",
            "# A node whose condition cannot be judged on the state as it is, is not set.",
            "refused('bad', lambda view: view['facts'].get('level') < 3, fix)",
            "print('set', sorted(row['name'] for row in reflexes()))",
            "# No trial is required: the node is set and acts.",
            "print('plain', set_reflex('idle', lambda view: view['facts'].get('never'), fix))",
            "# With a trial, the situation is brought about and what the node showed comes back.",
            "shown = set_reflex('repair', lambda view: view['facts'].get('broken'), fix,",
            "                   test=lambda: facts.set('broken', True))",
            "print('shown', shown['tried'], shown['turn'], shown['done'], facts.get('broken'))",
            "never = set_reflex('idle', lambda view: view['facts'].get('never'), fix, test=lambda: None)",
            "print('never', never['turn'])",
            "# A trial is a function, not a sentence in its place.",
            "refused('far', lambda view: view['facts'].get('far'), fix, test='it needs another machine')"])
        with Episode([program(SAYS + asked), program(SAYS + "situations('something happens to the agent')\n" + after), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 60, "reflex_method": "required"}) as episode:
            summary = episode.end()
            out = "\n".join(row["result"]["stdout"] for row in episode.records("cell")[:2])
        self.assertEqual(summary["status"], "finished")
        self.assertIn("refused: Nothing was set: read how a tree of reflexes is designed", out)
        self.assertIn('page guide("tree"): the page is given to you with your next message', out)
        self.assertIn("refused: Nothing was set: every node does something", out)
        self.assertIn("refused: Nothing was set: the node's condition cannot be judged", out)
        self.assertIn("set []", out)
        self.assertIn("plain idle", out)
        # The trial showed the node have its turn and leave the situation over.
        self.assertIn("shown True True True False", out)
        self.assertIn("never False", out)
        self.assertIn("refused: test= is a function that brings the node's situation", out)

    def test_the_node_above_answers_what_the_node_under_it_did_not_solve(self):
        asked = "\n".join([
            "import time",
            "def wide():",
            "    facts.set('by', 'wide')",
            "    facts.set('level', 9)",
            "def narrow():",
            "    # It runs and leaves the situation as it was.",
            "    facts.set('narrow_ran', True)",
            "set_reflex('low', lambda view: (view['facts'].get('level') or 9) < 3, wide, tell_failed='never')",
            "set_reflex('refill', lambda view: bool(view['facts'].get('supply')), narrow, under='low',",
            "           tell_failed='never')",
            "facts.set('supply', 1)",
            "facts.set('level', 1)",
            "time.sleep(4.0)",
            "print('answered', facts.get('narrow_ran'), facts.get('by'), facts.get('level'))"])
        with Episode([program(SAYS + asked), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 60, "reflex_method": "optional"}) as episode:
            summary = episode.end()
            out = episode.records("cell")[0]["result"]["stdout"]
        self.assertEqual(summary["status"], "finished")
        # The narrower node had its turn first; what it did not solve, the node above answered.
        self.assertIn("answered True wide 9", out)

    def test_a_node_says_what_the_model_hears_of_its_work(self):
        asked = "\n".join([
            "import time",
            "set_reflex('repair', lambda view: view['facts'].get('broken'), lambda: facts.set('broken', False))",
            "set_reflex('dust', lambda view: view['facts'].get('dusty'), lambda: facts.set('dusty', False), tell='never')",
            "set_reflex('fire', lambda view: view['facts'].get('hot'), lambda: facts.set('hot', False), tell='now')",
            "set_reflex('note', lambda view: view['facts'].get('odd'), lambda: facts.set('odd', False), tell='later')",
            "for _ in range(2):",
            "    for name in ('broken', 'dusty', 'hot', 'odd'):",
            "        facts.set(name, True)",
            "    time.sleep(1.2)",
            "try:",
            "    set_reflex('wrong', lambda view: False, lambda: None, tell='loudly')",
            "except ValueError as error:",
            "    print('refused:', str(error)[:16])"])
        with Episode([program("reflex_method()"), program(SAYS + "situations('something happens to the agent')\n" + asked), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 60, "reflex_method": "required"}) as episode:
            summary = episode.end()
            out = episode.records("cell")[1]["result"]["stdout"]
            acted = [(row["reported"]["source"], row["reported"]["detail"]["tell"])
                     for row in episode.records("escalation") if row["reported"]["kind"] == "REFLEX_ACTED"]
        self.assertEqual(summary["status"], "finished")
        # Nothing said: the first time only, with the next call. "never": not told. Else each time, at its place.
        self.assertEqual(acted.count(("repair", "next")), 1)
        self.assertEqual([row for row in acted if row[0] == "dust"], [])
        self.assertEqual(acted.count(("fire", "now")), 2)
        self.assertEqual(acted.count(("note", "later")), 2)
        self.assertIn("refused: tell is one of", out)

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


class SharedBody(unittest.TestCase):
    """A node gives the environment back when its situation is over; where the environment
    pauses and has channels a node takes only the channels it uses; the reflexes' units are
    not the model's own programs; the pages read go on with the conversation."""

    def test_over_ends_a_nodes_program_and_its_condition_going_away_does_not(self):
        # f151: a node that steps away from what is near stopped being "near" at its first step, and
        # was ended there 57 times. When the action begins and when the situation is past are two
        # things: `when` begins it, `over` ends it.
        asked = "\n".join([
            "import time",
            "def guard():",
            "    type_text(200, seconds=0.02)",
            "set_reflex('guard', lambda view: view['facts'].get('near'), guard,",
            "           over=lambda view: bool(view['facts'].get('far')))",
            "facts.set('near', True)",
            "time.sleep(0.4)",
            "facts.set('near', False)",
            "time.sleep(0.5)",
            "mid = get_state()['step']",
            "running = [unit.name for unit in entries()]",
            "facts.set('far', True)",
            "time.sleep(0.5)",
            "print('steps', mid, get_state()['step'], 'guard' in running)"])
        with Episode([program(asked), "<finish>done</finish>"], pauses=True,
                     runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            rows = [row["action"] for row in episode.records("rule") if row.get("name") == "guard"]
            out = episode.records("cell")[0]["result"]["stdout"].split()
        self.assertEqual(summary["status"], "finished")
        # It still ran after its condition had stopped holding, and was ended when `over` held.
        self.assertEqual(out[3], "True")
        self.assertEqual(rows.count("began"), 1)
        self.assertEqual(rows[-1], "released")
        self.assertLess(int(out[2]), 150)

    def test_a_node_without_over_runs_until_its_program_returns(self):
        asked = "\n".join([
            "def guard():",
            "    type_text(12, seconds=0.02)",
            "set_reflex('guard', lambda view: view['facts'].get('danger'), guard)",
            "facts.set('danger', True)",
            "import time",
            "time.sleep(0.2)",
            "facts.set('danger', False)",
            "time.sleep(1.0)",
            "print('steps', get_state()['step'])"])
        with Episode([program(asked), "<finish>done</finish>"], pauses=True,
                     runtime={"turn_grace_seconds": 30}) as episode:
            episode.end()
            rows = [row["action"] for row in episode.records("rule") if row.get("name") == "guard"]
            steps = int(episode.records("cell")[0]["result"]["stdout"].split()[-1])
        self.assertNotIn("released", rows)
        self.assertNotIn("failed", rows)
        self.assertGreaterEqual(steps, 12)

    def test_a_node_under_another_that_fails_leaves_the_one_above_to_act_undisturbed(self):
        # The tree is a behaviour tree: the narrower node is tried first, fails, and the node above
        # acts; the failed one is not begun again and does not take the upper one's place again.
        asked = "\n".join([
            "import time",
            "def narrow():",
            "    facts.set('narrow', facts.get('narrow', 0) + 1)",
            "def wide():",
            "    facts.set('wide', facts.get('wide', 0) + 1)",
            "    type_text(20, seconds=0.02)",
            "    facts.set('danger', False)",
            "set_reflex('wide', lambda view: view['facts'].get('danger'), wide, tell='never', tell_failed='never')",
            "set_reflex('narrow', lambda view: True, narrow, under='wide', tell='never', tell_failed='never')",
            "facts.set('danger', True)",
            "time.sleep(1.5)",
            "print('ran', facts.get('narrow'), facts.get('wide'), facts.get('danger'))"])
        with Episode([program(asked), "<finish>done</finish>"], pauses=True,
                     runtime={"turn_grace_seconds": 30}) as episode:
            episode.end()
            rows = [(row["name"], row["action"]) for row in episode.records("rule") if row["action"] in ("began", "failed", "released")]
            out = episode.records("cell")[0]["result"]["stdout"].split()
        self.assertEqual(out, ["ran", "1", "1", "False"])
        self.assertEqual(rows, [("narrow", "began"), ("narrow", "failed"), ("wide", "began")])

    def test_the_earlier_node_at_a_place_is_the_one_set_first_or_the_one_that_says_before(self):
        from harness.runtime.reactive.tree import Reflexes

        layer = Reflexes(0.005)
        layer.set("a", lambda view: True, lambda: None)
        layer.set("b", lambda view: True, lambda: None)
        layer.set("c", lambda view: True, lambda: None, before="a")
        self.assertEqual([node.name for node in layer.children()], ["c", "a", "b"])
        self.assertGreater(layer.rank(layer.nodes["c"]), layer.rank(layer.nodes["a"]))
        self.assertGreater(layer.rank(layer.nodes["a"]), layer.rank(layer.nodes["b"]))
        with self.assertRaises(ValueError):
            layer.set("d", lambda view: True, lambda: None, before="nowhere")
        with self.assertRaises(TypeError):
            layer.set("e", lambda view: True, lambda: None, priority=3)

    def test_a_program_holds_the_environment_with_the_place_of_the_node_it_names(self):
        asked = "\n".join([
            "import time",
            "def first():",
            "    facts.set('first_at', time.monotonic())",
            "    facts.set('a', False)",
            "def second():",
            "    facts.set('second_at', time.monotonic())",
            "    facts.set('b', False)",
            "set_reflex('first', lambda view: bool(view['facts'].get('a')), first, tell='never', tell_failed='never')",
            "set_reflex('second', lambda view: bool(view['facts'].get('b')), second, tell='never', tell_failed='never')",
            "with at_priority('first'):",
            "    facts.set('a', True)",
            "    facts.set('b', True)",
            "    time.sleep(0.5)",
            "    facts.set('left_at', time.monotonic())",
            "time.sleep(0.5)",
            "print(facts.get('first_at') < facts.get('left_at') <= facts.get('second_at'))",
            "try:",
            "    at_priority(3)",
            "except ValueError as error:",
            "    print('refused')"])
        with Episode([program(asked), "<finish>done</finish>"], runtime={"turn_grace_seconds": 30}) as episode:
            episode.end()
            out = episode.records("cell")[0]["result"]["stdout"].split()
            held = [row["rule"] for row in episode.records("held_back")]
        # The named node acted during the block; the one after it waited for the block's end.
        self.assertEqual(out, ["True", "refused"])
        self.assertEqual(held, ["second"])

    def test_a_node_that_uses_no_channel_takes_the_environment_from_nobody(self):
        # A node that only sets a rule for other code (a fact) while its situation lasts: the program
        # that runs is not paused, and a node after it is not kept waiting.
        asked = "\n".join([
            "import time",
            "def mark():",
            "    facts.set('marked', True)",
            "    time.sleep(3)",
            "def later():",
            "    facts.set('later', True)",
            "set_reflex('mark', lambda view: view['step'] >= 2, mark, over=lambda view: bool(view['facts'].get('typed')),",
            "           claims=[], tell='never', tell_failed='never')",
            "set_reflex('later', lambda view: bool(view['facts'].get('marked')) and not view['facts'].get('later'), later,",
            "           tell='never', tell_failed='never')",
            "typed = type_text(12, seconds=0.03)",
            "print('typed', typed.ok, facts.get('marked'), facts.get('later'))",
            "facts.set('typed', True)",
            "time.sleep(0.4)"])
        with Episode([program(asked), "<finish>done</finish>"], pauses=True,
                     runtime={"turn_grace_seconds": 30}) as episode:
            episode.end()
            out = episode.records("cell")[0]["result"]["stdout"].split()
            paused = [row["rule"] for row in episode.records("call_paused")]
            rows = [(row["name"], row["action"]) for row in episode.records("rule") if row["action"] in ("began", "released")]
        self.assertEqual(out, ["typed", "True", "True", "True"])
        # Only the later node, which uses the environment, paused the typing; the channelless one did not.
        self.assertNotIn("mark", paused)
        self.assertIn(("mark", "released"), rows)

    def test_nothing_of_the_tree_is_judged_while_the_agent_cannot_act(self):
        # f151: the body had died where a node's condition held, and the node was begun on it 52 times.
        asked = "\n".join([
            "import time",
            "def act():",
            "    facts.set('acted', facts.get('acted', 0) + 1)",
            "    facts.set('go', False)",
            "set_reflex('node', lambda view: bool(view['facts'].get('go')), act, every=0.05,",
            "           tell='never', tell_failed='never')",
            "facts.set('unable', True)",
            "facts.set('go', True)",
            "time.sleep(0.5)",
            "before = facts.get('acted', 0)",
            "facts.set('unable', False)",
            "time.sleep(0.5)",
            "print('acted', before, facts.get('acted', 0))"])
        with Episode([program(asked), "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 30, "bootstrap": "view_fixtures:unable_session"}) as episode:
            episode.end()
            out = episode.records("cell")[0]["result"]["stdout"].split()
        self.assertEqual(out, ["acted", "0", "1"])

    def channel_episode(self, node_claims):
        asked = "\n".join([
            "def keys():",
            "    type_text(10, 'keys', seconds=0.03)",
            "unit = spawn(keys, 'typing', claims=['keys'])",
            "def other():",
            "    type_text(2, " + repr(node_claims[0]) + ")",
            "    facts.set('done', True)",
            "set_reflex('other', lambda view: view['step'] >= 3 and not view['facts'].get('done'), other,",
            "           claims=" + repr(node_claims) + ")",
            "unit.wait(20)",
            "print('typed', unit.status)"])
        episode = Episode([program(asked), "<finish>done</finish>"], pauses=True,
                          runtime={"turn_grace_seconds": 30, "bootstrap": "view_fixtures:channel_session"})
        return episode

    def test_a_node_on_another_channel_leaves_what_runs_on_its_own(self):
        with self.channel_episode(["pointer"]) as episode:
            summary = episode.end()
            paused = episode.records("call_paused")
            held = episode.environment.held
            facts_done = episode.records("cell")[0]["result"]["stdout"].split()
        self.assertEqual(summary["status"], "finished")
        self.assertEqual((paused, held), ([], []))
        self.assertEqual(facts_done, ["typed", "done"])

    def test_a_node_on_the_same_channel_pauses_what_uses_it(self):
        with self.channel_episode(["keys"]) as episode:
            summary = episode.end()
            paused = [(row["rule"], row["name"]) for row in episode.records("call_paused")]
            held = episode.environment.held
        self.assertEqual(summary["status"], "finished")
        self.assertEqual(paused, [("other", "typing")])
        # The environment was told which channels the node takes.
        self.assertEqual((held[0][0], held[0][2], held[0][3]), ("pause", "other", ["keys"]))

    def test_the_units_of_reflexes_are_not_the_models_programs(self):
        from harness.runtime.task.run import _models

        self.assertTrue(_models({"kind": "program", "cell": 3}))
        self.assertFalse(_models({"kind": "program", "rule": "threat"}))
        self.assertFalse(_models({"kind": "agent"}))

    def test_the_pages_read_go_on_with_the_conversation(self):
        with Episode([program("guide('units')\nprint('read')"), "Read."], interactive=True) as episode:
            episode.start()
            self.assertTrue(episode.until(lambda: episode.records("turn_result") and episode.run.status == "IDLE"))
            episode.run.close()
            episode.end()
            kept = saved(episode.directory)
            again = TaskRun(episode.run.base_config, 0, episode.directory, chat=Recording([]), interactive=True,
                            restore=kept)
        self.assertIn("units", kept["guides"])
        self.assertIn("units", again._guides_read)


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
        layer.set("slow", slow, lambda: None)
        layer.set("quick", lambda view: True, lambda: None)
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
        layer.set("slow", lambda view: True, lambda: None)
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

    def test_only_a_message_of_priority_now_sets_the_call_in_flight_aside(self):
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
            # An urgent event is told first with the next call; the reply being written is still used
            # (f149: a program written for 36 s was dropped for a PERIL and the body stood 63 s).
            self.assertEqual((settled, run._current_output(loop)), ([], True))
            run._put("message", NOW, ("user", "stop", []), reason="environment message")
        # A message of the user sets the call aside, and a reply that did not know does nothing.
        self.assertEqual(settled, [("discarded", "environment message")])
        self.assertFalse(run._current_output(loop))
        self.assertEqual([notice.data.get("id") if notice.kind == "event" else notice.data[1]
                          for notice in run._notices.pending()], ["b", "stop", "hello", "a"])
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
        # The first waits to be told first; the same again while it waits is counted with it. No call is set aside.
        waiting = run._notices.pending()
        self.assertEqual((len(settled), len(waiting), waiting[0].data["times"], run._urgent), (0, 1, 3, 0))
        self.assertIn('"times": 3', run._notice_parts(waiting[0])[0]["text"])
        # Told and not answered yet: the same once more comes with the next call and sets nothing aside.
        run._told_sources.add(run._event_key(run._notices.take()[0].data))
        failed("d")
        self.assertEqual((len(settled), run._urgent, [notice.priority for notice in run._notices.pending()]),
                         (0, 0, [NEXT]))
        # Another source is news, told first.
        failed("e", source="buried")
        self.assertEqual((len(settled), run._urgent, [notice.priority for notice in run._notices.pending()]),
                         (0, 0, [NOW, NEXT]))

    def test_an_urgent_event_does_not_set_aside_the_answer_to_another(self):
        # f107: the threat node failed, acted, failed again, each failure told `now` (its tell_failed);
        # each set aside the call answering the last, and the model never answered while the body died.
        from types import SimpleNamespace

        from harness.runtime.decision.notices import NEXT, NOW, Notices
        from harness.runtime.task.run import TaskRun

        run = TaskRun.__new__(TaskRun)
        run._condition, run._notices, run._revision, run._urgent = threading.Condition(), Notices(), 0, 0
        run._event_times = {}
        run._seen_events, run._told_sources, run._told_urgent = set(), set(), False
        settled = []
        run._request = SimpleNamespace(outcome=None)
        run._settle = lambda thought, outcome, reason=None: settled.append(outcome)
        run._thoughts = SimpleNamespace(cancel_where=lambda match, reason: None)
        run.trace = SimpleNamespace(emit=lambda *args, **detail: None)

        def failed(identifier, source="threat"):
            run._escalation({"id": identifier, "event": {"kind": "REFLEX_FAILED", "source": source,
                                                         "detail": {"reflex": source, "tell": "now"}}})

        failed("a")
        self.assertEqual((len(settled), [notice.priority for notice in run._notices.pending()]), (0, [NOW]))
        # The call that answers it is in flight: the same node failing again waits for the next call.
        told = run._notices.take()[0]
        run._told_sources.add(run._event_key(told.data)); run._told_urgent = True
        failed("b")
        # So does another node's event told at once: one urgency does not interrupt its own kind.
        failed("c", source="peril")
        self.assertEqual((len(settled), run._urgent, [notice.priority for notice in run._notices.pending()]),
                         (0, 0, [NEXT, NEXT]))
        # With nothing urgent being answered, an urgent event is told first again; no call is set aside.
        run._notices.take(); run._told_sources.clear(); run._told_urgent = False
        failed("d", source="falling")
        self.assertEqual((len(settled), [notice.priority for notice in run._notices.pending()]), (0, [NOW]))


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
