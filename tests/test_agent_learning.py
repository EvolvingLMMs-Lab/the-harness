"""Learning by default: a background review after a turn turns a fix into a reusable skill that
passed its own test; 5 uses with 4 done make it effective; undo stops it loading; an outside
SKILL.md installs and is read when used; a learned reaction hangs under its branch; dreaming
archives what went unused."""
import json
import os
import tempfile
import time
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)

from test_agent_life import NoTasks, Recorder, wait_for

CODE = "def rerun_failed(report):\n    return [line.split()[0] for line in report.splitlines() if 'FAILED' in line]\n"
TEST = "assert rerun_failed('a.py::t FAILED\\nb.py::u PASSED') == ['a.py::t']\n"


class LearningTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = mock.patch.dict(os.environ, {"HARNESS_HOME": self.folder.name, "HARNESS_DATA": self.folder.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.folder.cleanup()

    def life(self, chat, review):
        from harness_agent.life import Life
        from harness_agent.state import Identity

        life = Life(Identity("default"), model=lambda: chat, tasks=lambda row: NoTasks())
        life.review_model = lambda: review
        life.start()
        return life

    def test_after_a_fix_review_learns_a_skill_that_passed_its_own_test(self):
        from harness_agent import learning

        chat = Recorder([{"action": "reply", "text": "Fixed: reran only the failing test, then fixed parser.py"}])
        review = Recorder([{"propose": "skill", "name": "rerun_failed", "description": "on a CI failure, rerun only "
                            "the failing tests first", "body": "Collect the failing tests from the report.",
                            "code": CODE, "test": TEST}])
        life = self.life(chat, review)
        life.say("main", "CI failed on test_parser; fix it", wait=True)
        with mock.patch.object(learning, "REVIEW_QUIET", 0):
            learned = wait_for(lambda: [r for r in life.chats.read("main") if r["event"] == "learned"], 30)
        self.assertEqual((learned[0]["name"], learned[0]["evidence"]), ("rerun_failed", "own test passed"))
        row = next(r for r in life.learning.skills() if r["name"] == "rerun_failed")
        self.assertEqual(row["evidence"], "own_test")
        self.assertTrue((life.identity.directory / "skills" / "rerun_failed" / "SKILL.md").exists())
        self.assertIn("rerun_failed", life.learning.notes("main"))
        # Five uses, four done: effective.
        learner = life.learning.learner()
        revision = learner.index()["skills/rerun_failed.py"]["revision"]
        learner.record_uses("skills/rerun_failed.py", [(True, None)] * 4 + [(False, "x")], revision=revision)
        self.assertEqual(life.learning.promote(), ["rerun_failed"])
        self.assertEqual(next(r for r in life.learning.skills() if r["name"] == "rerun_failed")["evidence"], "effective")
        # Undo: no longer loaded.
        life.learning.undo("rerun_failed")
        self.assertFalse((life.identity.library / "skills" / "rerun_failed.py").exists())
        self.assertNotIn("rerun_failed", life.learning.notes("main"))
        life.close()

    def test_a_skill_whose_test_fails_is_not_learned(self):
        life = self.life(Recorder([]), Recorder([]))
        result = life.learning.learn_skill("main", {"name": "broken", "description": "x", "code": CODE,
                                                    "test": "assert False\n"})
        self.assertIn("failed", result)
        self.assertFalse((life.identity.library / "skills" / "broken.py").exists())
        life.close()

    def test_an_outside_skill_md_installs_as_proposed_and_is_read_when_used(self):
        source = os.path.join(self.folder.name, "weekly")
        os.makedirs(source)
        with open(os.path.join(source, "SKILL.md"), "w", encoding="utf-8") as stream:
            stream.write("---\nname: weekly-report\ndescription: Draft the weekly report from the template\n---\n\n"
                         "Open the template, fill in this week's items, keep it under a page.\n")
        chat = Recorder([{"action": "read_skill", "name": "weekly-report"}, {"action": "reply", "text": "drafted"}])
        life = self.life(chat, Recorder([]))
        self.assertEqual(life.learning.install(source)["evidence"], "proposed")
        row = next(r for r in life.learning.skills() if r["name"] == "weekly_report")
        self.assertTrue(row["instructions_only"])
        life.say("main", "draft the weekly report", wait=True)
        result = [r for r in life.chats.read("main") if r["event"] == "outcome" and r.get("verb") == "read_skill"]
        self.assertIn("keep it under a page", json.dumps(result[0]["result"]))
        life.close()

    def test_a_learned_reaction_hangs_under_its_branch(self):
        life = self.life(Recorder([]), Recorder([]))
        life.tree.add("desktop", {"fact": "working_in", "has": "desktop"}, None, about="working on the desktop")
        life.learning.take("main", {"propose": "reaction", "name": "owner took the mouse",
                                    "about": "input refused -> wait for the owner to leave",
                                    "when": {"outcome": ["refused"], "verb": "desktop.input"}, "do": {"nothing": True},
                                    "under": "desktop"})
        node = life.tree.node("owner took the mouse")
        self.assertEqual((node["under"], node["source"], node["evidence"]), ("desktop", "learned", "proposed"))
        life.close()

    def test_dreaming_archives_what_went_unused_for_30_days(self):
        from harness.runtime.learning.learner import candidate

        life = self.life(Recorder([]), Recorder([]))
        learner = life.learning.learner()
        learner.admit(candidate("skill", "old_way", CODE, TEST), "provisional")
        index = learner.index()
        index["skills/old_way.py"]["admitted_at"] = time.time() - 40 * 86400
        learner._save_index(index)
        os.utime(life.identity.library / "skills" / "old_way.py", (time.time() - 40 * 86400,) * 2)
        self.assertEqual(life.learning.archive(time.time()), ["old_way"])
        self.assertTrue(next(r for r in life.learning.skills() if r["name"] == "old_way")["archived"])
        life.learning.restore("old_way")
        self.assertTrue((life.identity.library / "skills" / "old_way.py").exists())
        life.close()
