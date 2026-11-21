"""How a skill the agent wrote itself is admitted to its library: the host's level
(learning.admission: off, fixture, own_test) and the worker's profile decide; an entry's
own test is run by the host, on the staged revision, between programs; an entry admitted
that way is provisional, says so wherever it is shown, loads in later runs of the library,
and goes back to pending when it keeps failing in use. No model is called: the replies are
scripted, the environment is the core's own conversation without one."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import helpers  # noqa: F401
from harness import settings
from harness.core import memory as memory_view
from harness.host.tasks import TaskHost, TaskServer
from harness.runtime.decision.model import ScriptedChat
from harness.runtime.execution.noenv import NoEnvironment
from harness.runtime.learning import active
from harness.runtime.learning.learner import (ADMISSION, DEMOTE_RATE, DEMOTE_USES, STAGED_TEST, Learner, admission,
                                              candidate)
from harness.runtime.learning.library import CANDIDATES, Library, admitted_by, eligible

CODE = "def double(x):\n    \"\"\"Twice x.\"\"\"\n    return 2 * x\n"
TEST = "assert double(2) == 4\n"


def proof(entry, method):
    return {"revision": entry.revision().revision, "receipt": {"ok": True, "method": method},
            "conditions": {"method": method, "profile_sha256": "0" * 64}}


class LevelTests(unittest.TestCase):
    def test_own_test_needs_the_host_and_a_profile_that_says_not_physical(self):
        self.assertEqual(admission({"physical": False}, "own_test"), "own_test")
        # The worker alone cannot switch it on, and neither can the host on a physical one.
        self.assertEqual(admission({"physical": False}), "fixture")
        self.assertEqual(admission({"physical": False}, "fixture"), "fixture")
        self.assertEqual(admission({"physical": True}, "own_test"), "fixture")
        self.assertEqual(admission({}, "own_test"), "fixture")
        self.assertEqual(admission({"physical": None}, "own_test"), "fixture")
        self.assertEqual(admission({"physical": 0}, "own_test"), "fixture")
        self.assertEqual(admission(None, "own_test"), "fixture")

    def test_off_is_off_everywhere_and_an_unknown_level_is_refused(self):
        self.assertEqual(admission({"physical": False}, "off"), "off")
        self.assertEqual(admission({"physical": True}, "off"), "off")
        with self.assertRaisesRegex(ValueError, "learning.admission"):
            admission({"physical": False}, "always")

    def test_the_setting_is_the_users_and_defaults_to_fixture(self):
        self.assertEqual(settings.defaults()["learning"]["admission"], "fixture")
        self.assertEqual(tuple(settings.SCHEMA["learning"]["admission"].bounds), ADMISSION)
        with self.assertRaises(ValueError):
            settings.check("learning", "admission", "always")

    def test_the_marker_of_a_staged_test_is_the_learning_skills(self):
        from harness.paths import ROOT

        source = (ROOT / "skills" / "learning" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn(f'SETUP = "{STAGED_TEST}"', source)


class LibraryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "library"
        self.learner = Learner(self.directory, {"learn": "on"}, create=True)

    def admitted(self, name="double", method="own_test", learner=None):
        entry = candidate("skill", name, CODE.replace("double", name), TEST.replace("double", name))
        learner = learner or self.learner
        learner.admit(entry, "proposed", pending=True)
        outcome = learner.admit(entry, "provisional", proof=proof(entry, method), expected=entry.revision().revision)
        self.assertTrue(outcome["admitted"])
        return entry

    def loaded(self, directory=None, load="proposed"):
        library = Library(directory or self.directory, load=load)
        captured = library.capture()
        index = captured.index
        return [item.key for item in captured.entries
                if eligible(item, index.get(item.key) or {}, library.layers, library.load)]


class ProvisionalTests(LibraryCase):
    def test_a_self_tested_entry_is_provisional_and_loads_in_a_later_run(self):
        entry = self.admitted()
        row = self.learner.index()[entry.key]
        self.assertEqual((row["evidence"], admitted_by(row)), ("provisional", "own_test"))
        # A later run opens the library again, frozen or not, at the default load level.
        self.assertEqual(self.loaded(), ["skills/double.py"])
        self.assertEqual(self.loaded(load="provisional"), ["skills/double.py"])
        # Provisional is not more: a library that loads replayed or validated entries leaves it out.
        self.assertEqual(self.loaded(load="replayed"), [])
        self.assertEqual(self.loaded(load="validated"), [])

    def test_a_self_tested_change_reaches_the_library_file(self):
        # An entry the library already holds, changed by a proposal that its own test admits:
        # the file shows the admitted text, as the index loads it (the file kept the old one).
        self.admitted()
        changed = candidate("skill", "double", CODE + "\n# changed\n", TEST)
        self.learner.admit(changed, "proposed", pending=True)
        self.learner.admit(changed, "provisional", proof=proof(changed, "own_test"),
                           expected=changed.revision().revision)
        self.assertEqual((self.directory / "skills" / "double.py").read_text(encoding="utf-8"), changed.text)
        self.assertEqual((self.directory / "tests" / "double.py").read_text(encoding="utf-8"), TEST)
        self.assertFalse((self.directory / CANDIDATES / "skills" / "double.py").exists())
        captured = Library(self.directory, load="proposed").capture()
        self.assertEqual([item.source.decode("utf-8") for item in captured.entries if item.key == changed.key],
                         [changed.text])

    def test_a_proof_of_another_revision_admits_nothing(self):
        entry = candidate("skill", "double", CODE, TEST)
        other = candidate("skill", "double", CODE + "\n# changed\n", TEST)
        self.learner.admit(entry, "proposed", pending=True)
        with self.assertRaisesRegex(ValueError, "does not cover this revision"):
            self.learner.admit(entry, "provisional", proof=proof(other, "own_test"))
        self.assertEqual(self.loaded(), [])

    def test_the_kernel_cannot_grade_or_admit_code(self):
        with self.assertRaisesRegex(ValueError, "trusted host receipt"):
            self.learner.handle({"action": "grade", "key": "skills/double.py", "evidence": "provisional"},
                                source="active")
        value = self.learner.handle({"action": "admit", "entry": "skill", "name": "double", "text": CODE, "test": TEST},
                                    source="active")
        self.assertFalse(value["admitted"])
        self.assertEqual(self.loaded(), [])

    def test_development_gain_is_still_the_way_to_validated(self):
        entry = self.admitted()
        revision = entry.revision().revision
        self.assertTrue(self.learner.grade_development(entry, revision, pending=False, score={"gain": 0.1}))
        row = self.learner.index()[entry.key]
        self.assertEqual((row["evidence"], admitted_by(row)), ("validated", "own_test"))


class DemotionTests(LibraryCase):
    def use(self, entry, results, learner=None):
        (learner or self.learner).record_uses(entry.key, [(ok, None) for ok in results],
                                              revision=entry.revision().revision)

    def test_a_self_tested_entry_that_keeps_failing_goes_back_to_pending(self):
        self.assertEqual((DEMOTE_USES, DEMOTE_RATE), (3, 0.25))
        entry = self.admitted()
        before = self.learner.version()
        self.use(entry, [False, False])
        self.assertEqual(self.loaded(), ["skills/double.py"])       # two uses are not enough
        self.use(entry, [False])
        self.assertEqual(self.loaded(), [])
        index = self.learner.index()
        self.assertNotIn(entry.key, index)
        waiting = index[f"{CANDIDATES}/{entry.key}"]
        self.assertEqual(waiting["evidence"], "proposed")
        self.assertNotIn("proof", waiting)
        self.assertEqual((waiting["demoted"]["ok"], waiting["demoted"]["failed"]), (0, 3))
        self.assertIn("demoted: 0 of 3 uses succeeded", waiting["history"][-1]["why"])
        self.assertEqual(self.learner.demoted, [{"key": entry.key, "revision": entry.revision().revision,
                                                 "ok": 0, "failed": 3}])
        # Its files wait with the candidates: nothing a later run would load by its file alone.
        self.assertFalse((self.directory / "skills" / "double.py").exists())
        self.assertFalse((self.directory / "tests" / "double.py").exists())
        self.assertEqual((self.directory / CANDIDATES / "skills" / "double.py").read_text(encoding="utf-8"), CODE)
        self.assertNotEqual(self.learner.version(), before)
        row = next(row for row in self.learner.entries() if row["file"] == entry.key)
        self.assertEqual((row["waiting"], row["demoted"], row["loaded"], row["admitted_by"]), (True, True, False, None))

    def test_one_success_in_three_keeps_it_and_one_in_five_does_not(self):
        entry = self.admitted()
        self.use(entry, [True, False, False])
        self.assertEqual(self.loaded(), ["skills/double.py"])
        self.use(entry, [False])                # 1 of 4: a quarter, not below it
        self.assertEqual(self.loaded(), ["skills/double.py"])
        self.use(entry, [False])                # 1 of 5
        self.assertEqual(self.loaded(), [])

    def test_only_entries_admitted_by_their_own_test_and_still_provisional(self):
        fixture = self.admitted("by_fixture", "fixture")
        self.use(fixture, [False] * 5)
        validated = self.admitted("validated")
        self.learner.grade_development(validated, validated.revision().revision, pending=False, score={"gain": 0.1})
        self.use(validated, [False] * 5)
        self.assertEqual(sorted(self.loaded()), ["skills/by_fixture.py", "skills/validated.py"])
        self.assertEqual(self.learner.demoted, [])

    def test_a_frozen_library_is_never_changed_by_uses(self):
        entry = self.admitted()
        frozen = Learner(self.directory, {"learn": "off"})
        before = frozen.version()
        self.use(entry, [False] * 5, learner=frozen)
        self.assertEqual(self.loaded(), ["skills/double.py"])
        self.assertEqual((frozen.version(), frozen.demoted), (before, []))

    def test_an_entry_is_retired_with_why_and_later_runs_do_not_load_it(self):
        self.learner.handle({"action": "admit", "entry": "note", "name": "travel", "text": "Travel only by tunnel."},
                            source="active")
        with self.assertRaises(ValueError):
            self.learner.handle({"action": "retire", "entry": "note", "name": "travel"}, source="active")
        retired = self.learner.handle({"action": "retire", "entry": "note", "name": "travel",
                                       "why": "the open way was faster and safe"}, source="active")
        self.assertEqual(retired["key"], "notes/travel.md")
        row = self.learner.index()["notes/travel.md"]
        self.assertEqual((row["why"], bool(row.get("removed"))), ("the open way was faster and safe", True))
        self.assertNotIn("notes/travel.md", [item.key for item in Library(self.directory).capture().entries])
        with self.assertRaises(ValueError):
            self.learner.handle({"action": "retire", "entry": "note", "name": "travel", "why": "again"},
                                source="active")

    def test_a_rewritten_entry_is_a_new_proposal(self):
        entry = self.admitted()
        self.use(entry, [False] * 3)
        rewritten = candidate("skill", "double", CODE + "\n# rewritten\n", TEST)
        self.learner.admit(rewritten, "proposed", pending=True)
        waiting = self.learner.index()[f"{CANDIDATES}/{entry.key}"]
        self.assertNotIn("demoted", waiting)
        self.assertEqual(waiting["revision"], rewritten.revision().revision)


class ProvenanceTests(LibraryCase):
    def test_every_view_says_what_admitted_a_code_entry(self):
        self.admitted("own", "own_test")
        self.admitted("checked", "fixture")
        self.learner.admit(candidate("skill", "waits", CODE.replace("double", "waits"), "assert waits(1) == 2\n"),
                           "proposed", pending=True)
        rows = {row["name"]: row for row in self.learner.entries()}
        self.assertEqual({name: row["admitted_by"] for name, row in rows.items()},
                         {"own": "own_test", "checked": "fixture", "waits": None})
        shown = {row["name"]: row for row in memory_view.rows(library=self.directory)}
        evidence = memory_view.COLUMNS.index("evidence")
        self.assertEqual(shown["own"]["cells"][evidence], "provisional (own test)")
        self.assertEqual(shown["checked"]["cells"][evidence], "provisional (fixture)")
        self.assertEqual(shown["waits"]["cells"][evidence], "proposed")
        self.assertEqual((shown["own"]["admitted_by"], shown["checked"]["admitted_by"]), ("own_test", "fixture"))

    def test_harness_library_show_says_it(self):
        from harness.cli import main

        entry = self.admitted("own", "own_test")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["library", "show", str(self.directory)]), 0)
        self.assertIn("provisional (own test)", output.getvalue())
        self.learner.record_uses(entry.key, [(False, None)] * 3, revision=entry.revision().revision)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(["library", "show", str(self.directory)])
        self.assertIn("proposed (demoted)", output.getvalue())
        self.assertNotIn("own test", output.getvalue())

    def test_the_learning_report_says_what_code_waits_for_at_each_level(self):
        self.admitted("own", "own_test")
        self.learner.admit(candidate("skill", "waits", CODE.replace("double", "waits"), "assert waits(1) == 2\n"),
                           "proposed", pending=True)
        rows = self.learner.entries()
        for row in rows:
            row["loaded"] = row["name"] == "own"
        self.assertIn("own [own test]", active.report(rows, 60, None, "own_test"))
        # The time the run has left is said only where the run asks for it.
        self.assertIn("min of live time left", active.report(rows, 60, None, "own_test"))
        self.assertNotIn("time left", active.report(rows, None, None, "own_test"))
        self.assertIn("code waiting for the host to run its test between programs: skills/waits",
                      active.report(rows, 60, None, "own_test"))
        self.assertIn("code waiting for an independent fixture: skills/waits", active.report(rows, 60, None))
        self.assertIn("code waiting for nothing: the host admits no code here: skills/waits",
                      active.report(rows, 60, None, "off"))


PROPOSE = ("<python>\nuntil(None)\nexpect('nothing', lambda: True)\nr = library.propose('skill', 'double', " + repr(CODE) + ", test={test!r})\n"
           "print('PROPOSED', r['ok'], r.get('queued'), 'double' in globals())\n</python>")
USE = "<python>\nuntil(None)\nexpect('nothing', lambda: True)\nprint('HAS', 'double' in globals())\nprint('USED', double(21) if 'double' in globals() else None)\n</python>"


class HostCase(unittest.TestCase):
    """Real host, kernel and library; scripted replies; the conversation without an environment,
    its profile saying what the test needs of `physical`."""

    def host(self, level=None, physical=False, variable=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "data"
        self.root.mkdir()
        self.library = Path(self.tmp.name) / "library"
        environment = {"HARNESS_DATA": str(self.root), "OPENROUTER_API_KEY": "test-no-network"}
        if variable:
            environment["HARNESS_LEARNING_ADMISSION"] = variable
        patch = mock.patch.dict(os.environ, environment)
        patch.start()
        self.addCleanup(patch.stop)
        if not variable:
            os.environ.pop("HARNESS_LEARNING_ADMISSION", None)
        call = NoEnvironment.call

        def profiled(environment, name, /, **arguments):
            answer = call(environment, name, **arguments)
            if name == "profile" and physical is not None:
                answer = {**answer, "physical": physical}
            return answer

        patch = mock.patch.object(NoEnvironment, "call", profiled)
        patch.start()
        self.addCleanup(patch.stop)
        self.chat = ScriptedChat([])
        self.app = TaskHost(self.root, chat=self.chat)
        self.addCleanup(self.app.close)
        if level:
            self.app.settings.update({"learning": {"admission": level}})
        self.server = TaskServer(("127.0.0.1", 0), self.app, token="test")
        self.addCleanup(self.server.server_close)

    def run_to_end(self, replies, learn="on", seconds=120):
        self.chat.replies, self.chat.calls = list(replies), 0
        run = self.app.start(self.server, "learn to double", workspace="none",
                             library={"path": str(self.library), "learn": learn})
        conversation = self.server.conversations[run]
        deadline = time.monotonic() + seconds
        # (Its answer ends the turn; the conversation waits until it is closed below.)
        while (conversation.status not in ("FINISHED", "ERROR") and conversation.waiting_since is None
               and time.monotonic() < deadline):
            time.sleep(0.05)
        status = (conversation.summary or {}).get("status")
        self.said = [part.get("text", "") if isinstance(part, dict) else str(part)
                     for message in conversation.messages if message["role"] == "user"
                     for part in (message["content"] if isinstance(message["content"], list) else [message["content"]])]
        conversation.close()
        if run in self.app._threads:
            self.app._threads[run].join(30)     # the episode's end folds its uses into the library
        path = self.app.conversations_dir / Path(run).name / "events.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(status, "finished", records[-6:])
        outputs = [record["result"]["stdout"] for record in records if record["event"] == "cell"]
        return records, outputs

    @staticmethod
    def library_records(records, action):
        return [record for record in records if record["event"] == "library" and record.get("action") == action]

    def entry(self):
        learner = Learner(self.library, {"learn": "on"})
        return {(row["file"], row["waiting"]): row for row in learner.entries()}


class OwnTestRunTests(HostCase):
    def test_a_passing_own_test_admits_activates_and_a_second_run_starts_with_it(self):
        self.host("own_test")
        records, outputs = self.run_to_end([PROPOSE.format(test=TEST), USE, "<finish>done</finish>"])
        self.assertIn("PROPOSED True True False", outputs[0])       # queued, and not in the namespace yet
        self.assertIn("USED 42", outputs[1])                        # active in the next program
        level, = self.library_records(records, "admission")
        self.assertEqual((level["level"], level["allowed"], level["physical"]), ("own_test", "own_test", False))
        observed, = self.library_records(records, "trial_observed")
        self.assertEqual((observed["ok"], observed["method"]), (True, "own_test"))
        admitted = [record for record in self.library_records(records, "admitted") if record["admitted"]]
        self.assertEqual(len(admitted), 1)
        self.assertEqual(admitted[0]["evidence"], "provisional")
        self.assertEqual(admitted[0]["proof"]["conditions"]["method"], "own_test")
        self.assertEqual(admitted[0]["proof"]["receipt"]["revision"], admitted[0]["revision"])
        self.assertTrue(any("The host ran the test of your proposal skills/double.py and it passed" in text
                            for text in self.said), self.said)
        # The test's own execution is not a use; the program's call of the skill is.
        row = self.entry()[("skills/double.py", False)]
        self.assertEqual((row["evidence"], row["admitted_by"], row["verified"], row["uses"]),
                         ("provisional", "own_test", True, 1))

        # A second run of the same library, frozen: the skill is there before the first program.
        records, outputs = self.run_to_end([USE, "<finish>done</finish>"], learn="off")
        self.assertIn("HAS True", outputs[0])
        self.assertIn("USED 42", outputs[0])
        self.assertEqual(self.library_records(records, "trial_started"), [])

    def test_the_system_prompt_stays_as_it_began_and_a_change_of_the_library_is_a_note(self):
        # What the model read so far stays the prefix its provider caches: an entry that comes into force while the
        # conversation runs is told as a note, and the system prompt of every call of the conversation is the first one.
        self.host("own_test")
        systems, complete = [], self.chat.complete

        def recorded(system, messages):
            systems.append(system)
            return complete(system, messages)
        self.chat.complete = recorded
        records, outputs = self.run_to_end([PROPOSE.format(test=TEST), USE, "<finish>done</finish>"])
        self.assertIn("USED 42", outputs[1])
        main = [system for system in systems if system[:200] == systems[0][:200]]
        self.assertEqual(len(main), 3)
        self.assertEqual(len(set(main)), 1)
        self.assertTrue(any("The entries of your library in force changed" in text and "double" in text
                            for text in self.said), self.said)

    def test_a_failing_own_test_admits_nothing_and_marks_the_proposal_failed(self):
        self.host("own_test")
        records, outputs = self.run_to_end([PROPOSE.format(test="assert double(2) == 5\n"), USE, "<finish>done</finish>"])
        self.assertIn("HAS False", outputs[1])
        observed, = self.library_records(records, "trial_observed")
        self.assertFalse(observed["ok"])
        self.assertIn("AssertionError", observed["error"])
        self.assertEqual([record for record in self.library_records(records, "admitted") if record["admitted"]], [])
        row = self.entry()[("skills/double.py", True)]
        self.assertEqual((row["evidence"], row["admitted_by"], row["loaded"]), ("failed", None, False))
        # One attempt for a revision: the second boundary did not run it again.
        self.assertEqual(len(self.library_records(records, "trial_started")), 1)
        self.assertTrue(any("and it failed" in text and "AssertionError" in text for text in self.said), self.said)

    def test_a_tree_is_kept_on_the_trials_its_nodes_had_and_nothing_runs_again(self):
        self.host("own_test")
        tree = "\n".join([
            "def wet(view):",
            "    return bool(view['facts'].get('wet'))",
            "def dry():",
            "    facts.set('dried', facts.get('dried', 0) + 1)",
            "    facts.set('wet', False)",
            "def soak():",
            "    facts.set('wet', True)",
            "set_reflex('dry', wet, dry, test=soak, about='it is wet',",
            "           report=lambda view, returned: {'dried': view['facts'].get('dried')})",
        ])
        first = "\n".join([
            "<python>", "until(None)", "expect('nothing', lambda: True)", f"TREE = {tree!r}", "situations('it is wet')", "exec(TREE)",
            "print('TRIED', reflexes('dry')[0]['name'], facts.get('dried'))",
            "print('WITH TEST', library.propose('reactive', 'other', TREE, test='pass'))",
            "print('PROPOSED', library.propose('reactive', 'keepdry', TREE))", "</python>"])
        second = "\n".join([
            "<python>", "until(None)", "expect('nothing', lambda: True)",
            # The node was tried once, when it was set: keeping it ran nothing.
            "print('DRIED', facts.get('dried'))",
            "print('OTHER', library.propose('reactive', 'changed', TREE.replace('False', 'None')))", "</python>"])
        third = "<python>\nuntil(None)\nexpect('nothing', lambda: True)\nprint('DRIED', facts.get('dried'))\n</python>"
        # (The page on the tree is asked for in a program of its own: it is read from the next message on.)
        asks = "<python>\nuntil(None)\nexpect('nothing', lambda: True)\nreflex_method()\n</python>"
        records, outputs = self.run_to_end([asks, first, second, third, "<finish>done</finish>"])
        outputs = outputs[1:]
        self.assertIn("TRIED dry 1", outputs[0])
        self.assertIn("takes no test", outputs[0])
        self.assertIn("DRIED 1", outputs[1])
        self.assertIn("DRIED 1", outputs[2])
        kept, changed = self.library_records(records, "trial_observed")
        self.assertEqual((kept["ok"], kept["trials"]["dry"]["tried"], kept["trials"]["dry"]["done"]), (True, True, True))
        self.assertFalse(changed["ok"])
        self.assertIn("dry is not the node of that name in the tree (its do differ)", changed["error"])
        admitted = [record for record in self.library_records(records, "admitted") if record["admitted"]]
        self.assertEqual([record["proof"]["receipt"]["trials"]["dry"]["tried"] for record in admitted], [True])
        self.assertTrue(any("keepdry.py is kept on the trials its nodes had" in text for text in self.said), self.said)
        self.assertTrue(any("changed.py is not kept: dry is not the node" in text for text in self.said), self.said)

    def test_the_practice_text_says_what_practice_is_for(self):
        text = active.goal("Carry the box to the door.")
        self.assertIn("The task: Carry the box to the door.", text)
        self.assertIn("the task's rules do not bind you here", text)
        self.assertIn("Take the parts you have not learned yet in order", text)
        self.assertNotIn("Go straight", text)
        self.assertNotIn("proves nothing", text)

    def test_the_learning_page_tells_a_first_time_from_a_try_again(self):
        from harness.paths import ROOT

        text = (ROOT / "prompts" / "shared" / "learning.md").read_text(encoding="utf-8")
        text = " ".join(text.split())
        self.assertIn("The first time you come to a step, come to it by doing the steps before it", text)
        self.assertIn("When you try the step again, put that same start back directly", text)
        self.assertIn("nothing the steps before it did not leave", text)
        self.assertIn("and run it from the start of the task", text)
        self.assertNotIn("set up that starting situation directly", text)

    def test_a_test_that_needs_the_practice_sandbox_waits_where_there_is_none(self):
        self.host("own_test")
        propose = PROPOSE.format(test=TEST).replace(", test=", ", setup='sandbox(\"stage\")', test=")
        records, outputs = self.run_to_end([propose, USE, "<finish>done</finish>"])
        self.assertIn("PROPOSED True True", outputs[0])
        self.assertIn("HAS False", outputs[1])
        self.assertEqual(self.library_records(records, "trial_started"), [])
        waits, = self.library_records(records, "trial_pending")
        self.assertIn("practice sandbox", waits["reason"])
        self.assertEqual(self.entry()[("skills/double.py", True)]["evidence"], "proposed")

    def test_a_self_tested_skill_that_fails_in_use_is_demoted_and_gone_from_the_next_run(self):
        self.host("own_test")
        code = "def flaky(x):\n    \"\"\"x, when it is not negative.\"\"\"\n    assert x >= 0, 'negative'\n    return x\n"
        propose = ("<python>\nuntil(None)\nexpect('nothing', lambda: True)\nprint(library.propose('skill', 'flaky', " + repr(code) + ", test='assert flaky(1) == 1')['ok'])\n</python>")
        fail = ("<python>\nuntil(None)\nexpect('nothing', lambda: True)\nfor _ in range(3):\n    try:\n        flaky(-1)\n    except AssertionError:\n        print('FAILED')\n</python>")
        records, outputs = self.run_to_end([propose, fail, "<finish>done</finish>"])
        self.assertEqual(outputs[1].count("FAILED"), 3)
        demoted, = self.library_records(records, "demoted")
        self.assertEqual((demoted["key"], demoted["ok"], demoted["failed"]), ("skills/flaky.py", 0, 3))
        row = self.entry()[("skills/flaky.py", True)]
        self.assertEqual((row["evidence"], row["demoted"], row["admitted_by"]), ("proposed", True, None))
        # The next run that learns does not load it and does not run its test again.
        records, outputs = self.run_to_end(["<python>\nuntil(None)\nexpect('nothing', lambda: True)\nprint('HAS', 'flaky' in globals())\n</python>",
                                            "<finish>done</finish>"])
        self.assertIn("HAS False", outputs[0])
        self.assertEqual(self.library_records(records, "trial_started"), [])

    def test_the_default_level_leaves_the_proposal_pending_as_before(self):
        self.host()
        records, outputs = self.run_to_end([PROPOSE.format(test=TEST), USE, "<finish>done</finish>"])
        self.assertIn("HAS False", outputs[1])
        level, = self.library_records(records, "admission")
        self.assertEqual(level["level"], "fixture")
        self.assertEqual(self.library_records(records, "trial_started"), [])
        row = self.entry()[("skills/double.py", True)]
        self.assertEqual((row["evidence"], row["loaded"]), ("proposed", False))

    def test_a_profile_that_does_not_say_not_physical_stays_at_fixture_whatever_the_host_allows(self):
        self.host("own_test", physical=None)        # the profile as the core's own environment gives it
        records, outputs = self.run_to_end([PROPOSE.format(test=TEST), USE, "<finish>done</finish>"])
        self.assertIn("HAS False", outputs[1])
        level, = self.library_records(records, "admission")
        self.assertEqual((level["level"], level["allowed"], level["physical"]), ("fixture", "own_test", None))
        self.assertEqual(self.library_records(records, "trial_started"), [])

    def test_off_loads_no_learned_code_and_the_variable_wins_over_the_setting(self):
        self.host("own_test")
        self.run_to_end([PROPOSE.format(test=TEST), USE, "<finish>done</finish>"])
        self.assertEqual(self.entry()[("skills/double.py", False)]["admitted_by"], "own_test")
        # A skill somebody put there by hand is not learned code: off leaves it alone.
        (self.library / "skills" / "by_hand.py").write_text("def by_hand():\n    return 'hand'\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"HARNESS_LEARNING_ADMISSION": "off"}):
            records, outputs = self.run_to_end([USE.replace("</python>", "print('HAND', by_hand())\n</python>"),
                                                "<finish>done</finish>"], learn="off")
            self.assertIn("HAS False", outputs[0])
            self.assertIn("HAND hand", outputs[0])
            level, = self.library_records(records, "admission")
            self.assertEqual((level["level"], level["allowed"]), ("off", "off"))
            # A run that learns admits nothing either.
            records, outputs = self.run_to_end(
                [PROPOSE.format(test=TEST).replace("double", "triple"), USE, "<finish>done</finish>"])
            self.assertEqual(self.library_records(records, "trial_started"), [])
            self.assertIn("HAS False", outputs[1])


class ConditionCallTests(unittest.TestCase):
    """A library function called while a reflex's condition is judged writes no step: the
    record costs time the condition's budget would count."""

    def setUp(self):
        from harness.core import spans
        from harness.runtime.learning.library import _tracked

        self.records = []

        def slow_sink(record):
            # A trace that takes 2 ms to write a record.
            until = time.perf_counter() + 0.002
            while time.perf_counter() < until:
                pass
            self.records.append(record)

        spans.set_sink(slow_sink)
        self.addCleanup(spans.set_sink, None)
        origin = ("reactive/tree.py", "sha", "r1")
        self.helper = _tracked(lambda value: value + 1, origin, {"reactive/tree.py": ("r1",)}, spans)

    def test_a_condition_of_five_helper_calls_stays_within_its_budget(self):
        from harness.runtime.reactive.rules import call_reactive

        def condition(view):
            return sum(self.helper(view) for _ in range(5)) > 0

        late = []
        self.assertTrue(call_reactive("tree", condition, 1, budget_seconds=0.005, late=late.append))
        self.assertEqual(late, [])
        self.assertEqual([r for r in self.records if r.get("kind") == "skill_step"], [])

    def test_the_same_function_called_by_a_program_still_records_its_step(self):
        self.assertEqual(self.helper(1), 2)
        steps = [r for r in self.records if r.get("kind") == "skill_step"]
        self.assertEqual([(r["what"], r["library_revision"]) for r in steps], [("done", "r1")])


if __name__ == "__main__":
    unittest.main()


class ReadTests(LibraryCase):
    """library.read(kind, name): an entry as entries() lists it, with its texts."""

    def test_an_admitted_skill_is_read_with_its_test(self):
        entry = self.admitted()
        found = self.learner.read("skill", "double")
        self.assertEqual((found["text"], found["test"], found["waiting"], found["evidence"]), (CODE, TEST, False, "provisional"))
        self.assertEqual(found["revision"], self.learner.index()[entry.key]["revision"])

    def test_a_proposal_alone_is_read_as_waiting_and_a_note_has_no_test(self):
        waits = CODE.replace("double", "waits")
        self.learner.admit(candidate("skill", "waits", waits, "assert waits(1) == 2\n"), "proposed", pending=True)
        found = self.learner.read("skill", "waits")
        self.assertEqual((found["text"], found["waiting"]), (waits, True))
        self.learner.admit(candidate("note", "rule", "Doors open inward."), "proposed")
        found = self.learner.read("note", "rule")
        self.assertEqual((found["text"].strip(), found["test"], found["waiting"]), ("Doors open inward.", None, False))

    def test_an_entry_the_library_does_not_have_is_said_with_the_names_it_has(self):
        self.admitted()
        with self.assertRaisesRegex(ValueError, "no skill 'triple'; its skill entries: double"):
            self.learner.read("skill", "triple")
        with self.assertRaisesRegex(ValueError, "kind is one of"):
            self.learner.read("skills", "double")

    def test_a_frozen_run_reads_the_library_it_started_with(self):
        self.admitted()
        started = Library(self.directory).capture()
        newer = CODE.replace("2 * x", "x + x")
        entry = candidate("skill", "double", newer, TEST)
        self.learner.admit(entry, "proposed", pending=True)
        self.learner.admit(entry, "provisional", proof=proof(entry, "own_test"), expected=entry.revision().revision)
        self.assertEqual(self.learner.read("skill", "double", snapshot=started)["text"], CODE)
        self.assertEqual(self.learner.read("skill", "double")["text"], newer)


READ = ("<python>\nuntil(None)\nexpect('nothing', lambda: True)\nr = library.read('skill', 'double')\n"
        "row = next(row for row in library.entries() if row['name'] == 'double')\n"
        "print('READ', r['text'] == " + repr(CODE) + ", r['test'] == " + repr(TEST) + ", r['waiting'], row['kind'], 'file' in row)\n</python>")


class ReadRunTests(HostCase):
    def test_a_program_reads_an_entry_by_its_kind_and_name_learning_or_not(self):
        self.host("own_test")
        records, outputs = self.run_to_end([PROPOSE.format(test=TEST), READ, "<finish>done</finish>"])
        self.assertIn("READ True True False skill False", outputs[1])
        records, outputs = self.run_to_end([READ, "<finish>done</finish>"], learn="off")
        self.assertIn("READ True True False skill False", outputs[0])


KEPT_TREE = "\n".join([
    "def wet(view):",
    "    return bool(view['facts'].get('wet'))",
    "def dry():",
    "    facts.set('dried', facts.get('dried', 0) + 1)",
    "    facts.set('wet', False)",
    "def soak():",
    "    facts.set('wet', True)",
    # (It tells the model nothing, so that the program that watches it is not cut short by a call.)
    "set_reflex('dry', wet, dry, test=soak, tell='never', tell_failed='never')",
])


class KeptTreeTests(HostCase):
    def test_a_kept_tree_is_in_the_tree_of_a_later_run_and_acts_only_once_the_model_starts_it(self):
        self.host("own_test")
        asks = "<python>\nuntil(None)\nexpect('nothing', lambda: True)\nreflex_method()\n</python>"
        keeps = "\n".join([
            "<python>", "until(None)", "expect('nothing', lambda: True)", f"TREE = {KEPT_TREE!r}", "situations('it is wet')",
            "exec(TREE)", "print('KEPT', library.propose('reactive', 'keepdry', TREE)['ok'], reflexes('dry')[0].get('started'))",
            "</python>"])
        records, outputs = self.run_to_end([asks, keeps, "<finish>done</finish>"])
        # In the run that set it the node is started: the model set it.
        self.assertIn("KEPT True None", outputs[1])
        later = "\n".join([
            "<python>", "until(None)", "expect('nothing', lambda: True)", "import time",
            "def waited(seconds):",
            "    end = time.time() + seconds",
            "    while facts.get('wet') and time.time() < end: time.sleep(0.05)",
            "    return facts.get('wet'), facts.get('dried')",
            "print('THERE', [(row['name'], row.get('started')) for row in reflexes()])",
            "facts.set('wet', True)",
            "print('WAITS', waited(1.5))",
            "print('STARTED', start_reflex())",
            "print('ACTED', waited(15))",
            "print('STOPPED', stop_reflex('dry'), reflexes()[0].get('started'))",
            "facts.set('wet', True)",
            "print('WAITS AGAIN', waited(1.5))",
            "</python>"])
        records, outputs = self.run_to_end([later, "<finish>done</finish>"], learn="off")
        out = outputs[0]
        self.assertIn("THERE [('dry', False)]", out)
        self.assertIn("WAITS (True, None)", out)                 # in the tree, and nothing of it acts
        self.assertIn("STARTED ['dry']", out)
        self.assertIn("ACTED (False, 1)", out)                   # started, it answers its situation
        self.assertIn("STOPPED ['dry'] False", out)
        self.assertIn("WAITS AGAIN (True, 1)", out)              # stopped, it answers nothing again
        self.assertTrue(any("1 not started (start_reflex() starts it)" in text for text in self.said), self.said)
