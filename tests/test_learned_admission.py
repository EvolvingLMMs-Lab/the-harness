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
        self.assertIn("code waiting for the host to run its test between programs: skills/waits",
                      active.report(rows, 60, None, "own_test"))
        self.assertIn("code waiting for an independent fixture: skills/waits", active.report(rows, 60, None))
        self.assertIn("code waiting for nothing: the host admits no code here: skills/waits",
                      active.report(rows, 60, None, "off"))


PROPOSE = ("<python>\nr = library.propose('skill', 'double', " + repr(CODE) + ", test={test!r})\n"
           "print('PROPOSED', r['ok'], r.get('queued'), 'double' in globals())\n</python>")
USE = "<python>\nprint('HAS', 'double' in globals())\nprint('USED', double(21) if 'double' in globals() else None)\n</python>"


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
        while conversation.status not in ("FINISHED", "ERROR") and time.monotonic() < deadline:
            time.sleep(0.05)
        status = conversation.status
        self.said = [part.get("text", "") if isinstance(part, dict) else str(part)
                     for message in conversation.messages if message["role"] == "user"
                     for part in (message["content"] if isinstance(message["content"], list) else [message["content"]])]
        conversation.close()
        if run in self.app._threads:
            self.app._threads[run].join(30)     # the episode's end folds its uses into the library
        path = self.app.conversations_dir / Path(run).name / "events.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(status, "FINISHED", records[-6:])
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
        propose = ("<python>\nprint(library.propose('skill', 'flaky', " + repr(code) + ", test='assert flaky(1) == 1')['ok'])\n</python>")
        fail = ("<python>\nfor _ in range(3):\n    try:\n        flaky(-1)\n    except AssertionError:\n        print('FAILED')\n</python>")
        records, outputs = self.run_to_end([propose, fail, "<finish>done</finish>"])
        self.assertEqual(outputs[1].count("FAILED"), 3)
        demoted, = self.library_records(records, "demoted")
        self.assertEqual((demoted["key"], demoted["ok"], demoted["failed"]), ("skills/flaky.py", 0, 3))
        row = self.entry()[("skills/flaky.py", True)]
        self.assertEqual((row["evidence"], row["demoted"], row["admitted_by"]), ("proposed", True, None))
        # The next run that learns does not load it and does not run its test again.
        records, outputs = self.run_to_end(["<python>\nprint('HAS', 'flaky' in globals())\n</python>",
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


if __name__ == "__main__":
    unittest.main()
