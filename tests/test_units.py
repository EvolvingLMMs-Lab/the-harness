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
        self.assertIn("Program 1 status: ok", texts(requests[2][-1]))


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
            "set_reflex('refill', lambda view: view['facts'].get('low'), refill, reads='facts.low', priority=5)",
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
        self.assertEqual([row["priority"] for row in started], [5])


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

    def test_a_tree_runs_its_branches_by_itself_and_tells_the_model_only_of_a_failure_nothing_takes(self):
        asked = "\n".join([
            "import time",
            "def work():",
            "    type_text(6, seconds=0.05)",
            "    facts.set('work_done', facts.get('work_done', 0) + 1)",
            "def urgent():",
            "    type_text(1)",
            "    facts.set('urgent_done', True)",
            "def broken():",
            "    raise RuntimeError('this leaf cannot work')",
            "subtree('handle_alarm', do(urgent))",
            "tree(select(",
            "    branch(lambda view: view['facts'].get('alarm') and not view['facts'].get('urgent_done'), ref('handle_alarm')),",
            "    branch(lambda view: view['facts'].get('work_done', 0) < 2, do(work)),",
            "    branch(lambda view: view['facts'].get('work_done', 0) >= 2, do(broken)),",
            "))",
            "time.sleep(0.15)",
            "facts.set('alarm', True)",
            "print([row['name'] for row in reflexes()])"])
        with Episode([program(asked), "<wait>8</wait>", "<finish>done</finish>"]) as episode:
            summary = episode.end()
            starts = [row["name"] for row in episode.records("entry_start") if row.get("rule") == "tree"]
            ends = {row["id"]: row["status"] for row in episode.records("entry_end")}
            work = [ends[row["id"]] for row in episode.records("entry_start")
                    if row.get("rule") == "tree" and row["name"] == "work"]
            facts = {row["name"]: json.loads(row["value"]) for row in episode.records("fact")}
            reasons = [row["reason"] for row in episode.records("model_request")]
            waits = episode.records("wait_end")
            last = texts(episode.chat.requests[-1][-1])
        self.assertEqual(summary["status"], "finished")
        # The first branch took over from the work that ran (ended there), and the tree went back to the work by itself.
        self.assertEqual(starts[:2], ["work", "urgent"])
        self.assertEqual(work[0], "cancelled")
        self.assertEqual((facts["urgent_done"], facts["work_done"]), (True, 2))
        # The ends of the tree's own programs started no call of the model: it was asked for its program,
        # then woken once, by the leaf whose failure nothing in the tree took.
        self.assertNotIn("unit_end", reasons)
        self.assertEqual(waits[0]["why"], "event")
        self.assertIn('"kind": "BRANCH_FAILED"', last)
        self.assertIn('"node": "broken"', last)

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
        # The model was asked for the program and for what came after it, and not in between.
        self.assertEqual(requests, 2)

    def test_a_condition_reads_a_value_the_environment_computes_from_code_the_model_defined(self):
        asked = "\n".join([
            "print(sense('far', 'step >= 3')['value'])",
            "try:",
            "    sense('bad', 'step >=')",
            "except ValueError as error:",
            "    print('refused')",
            "set_reflex('far', lambda view: view['sensed']['far'], lambda: facts.set('seen_at', get_state()['step']))",
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
