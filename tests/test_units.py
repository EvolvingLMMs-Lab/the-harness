"""A run is one model and the units it starts. One small test per step of the design."""
from contextlib import contextmanager
import json
import os
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

    def __init__(self, replies, *, runtime=None, seconds=0.0, interactive=False, tells=False, pauses=False):
        self.environment = ScreenEnvironment(seconds, tells=tells, pauses=pauses)
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
            self.assertIn('"kind": "PREEMPTED"', told)
            self.assertIn('"rule": "urgent"', told)
            self.assertIn(f'"name": "{name}"', told)


    def test_an_uninterruptible_program_keeps_the_embodiment_and_the_rule_acts_after_it(self):
        asked = "\n".join([
            "def urgent():",
            "    type_text(1)",
            "    facts.set('urgent_at', get_state()['step'])",
            "set_reflex('urgent', lambda view: view['facts'].get('armed') and not view['facts'].get('urgent_at'), urgent,",
            "           priority=5)",
            "uninterruptible()",
            "facts.set('armed', True)",
            "type_text(8, seconds=0.05)",
            "facts.set('typed_at', get_state()['step'])",
            "print('typed', [(row['name'], row['priority']) for row in reflexes()])"])
        with Episode([program(asked), "<wait>10</wait>", "<wait>10</wait>", "<finish>done</finish>"],
                     runtime={"turn_grace_seconds": 30}) as episode:
            summary = episode.end()
            cell = episode.records("cell")[0]["result"]
            held = [(row["rule"], row["by_name"]) for row in episode.records("held_back")]
            preempted = episode.records("preempted")
            facts = {row["name"]: row.get("data", row.get("value")) for row in episode.records("fact")}
            told = "\n".join(texts(request[-1]) for request in episode.chat.requests)
            running = "\n".join(texts(message) for request in episode.chat.requests for message in request)
        self.assertEqual(summary["status"], "finished")
        # The rule of priority 5 did not take the embodiment: the program typed all eight keys and ended by itself.
        self.assertEqual((cell["status"], cell["stdout"].strip()), ("ok", "typed [('urgent', 5)]"))
        self.assertEqual(preempted, [])
        # The model was told once that the rule was held back, and by which program.
        self.assertEqual(held, [("urgent", "program 1")])
        self.assertIn('"kind": "HELD_BACK"', told)
        # Judged again when the program had ended, its condition still held: it acted then.
        self.assertGreater(int(json.loads(facts["urgent_at"]) if isinstance(facts["urgent_at"], str) else facts["urgent_at"]),
                           int(json.loads(facts["typed_at"]) if isinstance(facts["typed_at"], str) else facts["typed_at"]))

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
        self.assertIn('"kind": "REFLEX_FAILED"', last)
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
        self.assertIn('"kind": "REFLEX_FAILED"', last)
        self.assertIn('"reflex": "fight"', last)
        self.assertIn('"ended": "by itself"', last)
        self.assertIn('"done": false', last)
        self.assertIn("hits", last)
        # Every turn is told how many nodes act in the tree and what changed in it since the last.
        self.assertRegex(last, r"Reflex tree: 1 node; changed since you were last told:\n"
                               r"  fight: began \d+, did its work 0, did not \d+")

    def test_a_turn_is_told_of_the_tree_only_what_changed_in_it(self):
        from harness.runtime.reactive.tree import NO_REFLEXES, told

        nodes = {f"n{number}": "began 0, did its work 0, did not 0" for number in range(14)}
        self.assertEqual(told({}, {}), NO_REFLEXES)
        first = told(nodes, {})
        # A tree larger than a turn tells of: the first 10 that changed, and how many more.
        self.assertEqual(len(first.splitlines()), 12)
        self.assertIn("Reflex tree: 14 nodes; changed since you were last told:", first)
        self.assertIn("... 4 more changed: reflexes()", first)
        self.assertEqual(told(nodes, dict(nodes)), "Reflex tree: 14 nodes, as you were last told (reflexes() lists them)")
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

        with Episode([program("print(1)"), program("print(2)"), program("print(3)"),
                      "<summary>Printed 1, 2 and 3; next is to finish.</summary>", "<finish>done</finish>"],
                     runtime={"compact_at_tokens": 1}) as episode:
            summary = episode.end()
            requests = episode.chat.requests
            compactions = episode.records("compaction")
            rebuilt = rebuild_messages(episode.records())
        self.assertEqual(summary["status"], "finished")
        # The fourth call asked for the summary, after the whole conversation.
        self.assertEqual([len(request) for request in requests], [1, 3, 5, 7, 5])
        self.assertIn("Please write a summary of the transcript.", texts(requests[3][-1]))
        self.assertEqual([(row["action"], row["messages_before"], row["messages"]) for row in compactions], [("done", 7, 5)])
        # The summary stands in the first message, after the instruction; the last four messages are as they were.
        first = texts(requests[4][0])
        self.assertEqual(first.count("Printed 1, 2 and 3; next is to finish."), 1)
        self.assertTrue(first.startswith(texts(requests[3][0])))
        self.assertEqual(requests[4][1:-1], requests[3][3:-1])
        self.assertTrue(texts(requests[3][-1]).startswith(texts(requests[4][-1])))
        self.assertEqual(summary["compaction_calls"], 1)
        # The trace rebuilds the conversation as it is after the compaction.
        self.assertEqual([texts(message) for message in rebuilt[:5]], [texts(message) for message in requests[4]])

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
            self.assertTrue(episode.until(lambda: episode.records("call_resumed") and again.status == "IDLE"))
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


class ScriptedModel(unittest.TestCase):
    def test_a_script_waits_by_itself_only_while_something_runs(self):
        from harness.runtime.decision.model import still_running

        said = lambda text: [{"role": "user", "content": text}]
        self.assertTrue(still_running(said("Program 3 is still running, as unit e5.")))
        self.assertTrue(still_running(said(
            "Wait ended after 60.0 s: its time is over.\nUnits running: e5 program 3 (program, 70 s)")))
        # Nothing runs: the wait that is over is the script's own to answer, not to wait on for ever.
        self.assertFalse(still_running(said("Wait ended after 10.0 s: its time is over.")))


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
