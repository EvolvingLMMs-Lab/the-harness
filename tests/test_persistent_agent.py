"""Persistent dialogue is optional and never leaks identity into a raw task."""
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from harness.runtime.decision.model import ScriptedChat, ChatReply
from harness_agent.state import Identity, read, save
from harness_agent.session import Session


class Tasks:
    def __init__(self):
        self.goals, self.observed = [], []
    def submit(self, goal, *, library=None):
        self.goals.append((goal, library))
        return "run-1"
    def observe(self, run, after=-1):
        self.observed.append(run)
        return {"run": run, "status": "ended", "summary": {"status": "finished", "success": None}, "answer": "done"}

    def status(self, run):
        return "FINISHED"


def chat(*actions):
    return ScriptedChat([json.dumps(x) for x in actions])


class PersistentAgentTests(TestCase):
    def test_identity_memory_survives_sessions_but_not_between_identities(self):
        with tempfile.TemporaryDirectory() as root:
            first = Identity("one", root=root)
            task = Tasks()
            session = Session(first, chat({"action":"remember","key":"PR language","text":"English"},
                                         {"action":"reply","text":"Saved"}), task)
            self.assertEqual(session.turn("Remember English PRs"), "Saved")
            self.assertEqual(Identity("one", root=root).memory()["entries"]["PR language"]["text"], "English")
            self.assertEqual(Identity("two", root=root).memory()["entries"], {})
            resumed = Session(first, chat({"action":"reply","text":"English"}), task, session=session.id)
            self.assertEqual(resumed.turn("Which language?"), "English")
            self.assertGreater(len(resumed.state["messages"]), 2)
            self.assertEqual(task.goals, [])

    def test_task_uses_explicit_context_and_separate_learning_library(self):
        with tempfile.TemporaryDirectory() as root:
            identity, tasks = Identity("one", root=root), Tasks()
            self.assertTrue(identity.library.is_dir())
            session = Session(identity, chat({"action":"task","goal":"Fix the parser; preserve valid records; run its tests", "learn":True},
                                             {"action":"reply","text":"Task finished; evaluator did not report success"}), tasks)
            session.turn("Fix it")
            self.assertEqual(len(tasks.goals), 1)
            self.assertEqual(tasks.goals[0][1]["path"], str(identity.library))
            self.assertEqual(tasks.goals[0][1]["learn"], "on")
            self.assertIsNone(session.state["pending"])
            self.assertEqual(identity.memory()["entries"], {})

    def test_uncertain_submission_is_not_automatically_repeated(self):
        class Broken(Tasks):
            def submit(self, goal, **kw):
                self.goals.append(goal)
                raise OSError("response lost after submission")
        with tempfile.TemporaryDirectory() as root:
            identity, tasks = Identity("one", root=root), Broken()
            session = Session(identity, chat({"action":"task","goal":"Write a file"}), tasks)
            with self.assertRaises(OSError): session.turn("Do it")
            state = read(session.directory / "state.json", {})
            self.assertEqual(state["pending"]["status"], "submission_unknown")
            resumed = Session(identity, chat({"action":"task","goal":"Write a file"}, {"action":"reply","text":"Inspect the existing task"}), tasks, session=session.id)
            resumed.turn("Continue")
            self.assertEqual(len(tasks.goals), 1)

    def test_long_context_compaction_retains_raw_history_and_tail(self):
        with tempfile.TemporaryDirectory() as root:
            identity = Identity("one", root=root)
            class Dialogue(ScriptedChat):
                def complete(self, system, messages):
                    text = ("Earlier messages establish English PRs." if system.startswith("Summarize")
                            else json.dumps({"action":"reply","text":"English"}))
                    return ChatReply(text=text, usage={})
            scripted = Dialogue([])
            session = Session(identity, scripted, Tasks(), context_chars=1)
            for i in range(5): session.turn("Use English for PRs " + str(i))
            self.assertEqual(session.turn("What language?"), "English")
            self.assertEqual(session.state["summary"], "Earlier messages establish English PRs.")
            events = [json.loads(s) for s in (session.directory / "events.jsonl").read_text().splitlines()]
            self.assertEqual(len([r for r in events if r["event"] == "user"]), 6)
            self.assertGreaterEqual(len([r for r in events if r["event"] == "compacted"]), 1)

    def test_memory_revision_conflict_preserves_other_writer(self):
        with tempfile.TemporaryDirectory() as root:
            identity = Identity("one", root=root)
            identity.remember("first", "A", source="session-a", expected=0)
            with self.assertRaisesRegex(ValueError, "memory changed"):
                identity.remember("second", "B", source="session-b", expected=0)
            self.assertEqual(set(identity.memory()["entries"]), {"first"})

    def test_external_approval_completion_is_recovered_without_resubmission(self):
        with tempfile.TemporaryDirectory() as root:
            identity, tasks = Identity("one", root=root), Tasks()
            session = Session(identity, chat({"action":"reply","text":"The task has now ended"}), tasks)
            state = read(session.directory / "state.json", {})
            state["pending"] = {"run":"run-1", "after":8, "status":"waiting_approval"}
            save(session.directory / "state.json", state)
            session.turn("I handled approval through the task interface; continue")
            self.assertEqual(tasks.observed, ["run-1"])
            self.assertEqual(tasks.goals, [])
            self.assertIsNone(session.state["pending"])

    def test_dialogue_cannot_answer_a_pending_approval(self):
        class Waiting(Tasks):
            def status(self, run): return "WAITING_FOR_CONFIRMATION"
            def resume(self, run, text): raise AssertionError("dialogue answered an approval")
        with tempfile.TemporaryDirectory() as root:
            identity, tasks = Identity("one", root=root), Waiting()
            session = Session(identity, chat({"action":"answer_task","text":"yes"},
                                            {"action":"reply","text":"Use the task approval interface"}), tasks)
            state = read(session.directory / "state.json", {})
            state["pending"] = {"run":"run-1", "after":8, "status":"waiting_approval"}
            save(session.directory / "state.json", state)
            session.turn("Continue")
            self.assertEqual(tasks.observed, [])
            self.assertEqual(session.state["pending"]["status"], "waiting_approval")
