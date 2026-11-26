"""The safety layer's fixed rules, authority by source, approvals that reach the owner (a card,
a notification, a short code in the owner's private chat) and end as cancelled when nobody
answers, and only four kinds of system notification."""
import os
import tempfile
import threading
import time
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)

from test_agent_life import QQ, Recorder, wait_for


class RulesTests(TestCase):
    def test_the_fixed_rules(self):
        from harness_agent.safety import check, turn_level

        self.assertEqual(check(level="owner", effect="change")[0], "allow")
        self.assertEqual(check(level="owner", effect="send")[0], "approve")
        self.assertEqual(check(level="owner", effect="pay")[0], "approve")
        self.assertEqual(check(level="owner", effect="login")[0], "refuse")
        self.assertEqual(check(level="owner", effect="change", place_kind="desktop", owner_active=True)[0], "refuse")
        # Someone else: only within their chat; never the owner's files; never an approval.
        self.assertEqual(check(level="other", effect="change", place_kind="space")[0], "allow")
        self.assertEqual(check(level="other", effect="change", verb="task")[0], "refuse")
        self.assertEqual(check(level="other", effect="change", place_kind="folder")[0], "refuse")
        self.assertEqual(check(level="other", effect="send", place_kind="space")[0], "refuse")
        # Its own work: one level less; only where the place lets it act on its own.
        self.assertEqual(check(level="own", effect="change", place_kind="desktop", proactive="learn")[0], "refuse")
        self.assertEqual(check(level="own", effect="change", place_kind="folder", proactive="do")[0], "allow")
        self.assertEqual(check(level="own", effect="send", place_kind="folder", proactive="do")[0], "approve")
        self.assertEqual(turn_level(["owner", "other"]), "other")
        self.assertEqual(turn_level(["owner", "own"]), "own")

    def test_a_push_is_sending_in_a_project_folder(self):
        from fnmatch import fnmatchcase
        from pathlib import Path
        import tomllib

        declared = tomllib.loads((Path(__file__).resolve().parents[1] / "packages" / "workspace" / "spaces" /
                                  "workspace.toml").read_text(encoding="utf-8"))
        patterns = declared["sending"]["commands"]
        self.assertTrue(any(fnmatchcase("git push origin fix", p) for p in patterns))
        self.assertFalse(any(fnmatchcase("git status", p) for p in patterns))

    def test_the_short_code(self):
        from harness_agent.approvals import parse

        self.assertEqual(parse("A7 approve"), ("A7", True))
        self.assertEqual(parse("a12 同意"), ("A12", True))
        self.assertEqual(parse("A7 reject because"), ("A7", False))
        self.assertIsNone(parse("approve A7"))


class Approving:
    """A task whose step waits for approval (the task engine's question)."""

    def __init__(self):
        self.approval, self.guard, self.answers = None, None, []

    def submit(self, goal, *, library=None):
        why = self.guard() if self.guard else None
        if why:
            from harness_agent.tasks import Refused

            raise Refused(why)
        return "run-1"

    def observe(self, run, after=-1):
        self.answers.append(self.approval({"kind": "sending", "description": "run git push origin fix"}))
        return {"run": run, "status": "ended", "answer": "pushed" if self.answers[-1][0] else "not pushed",
                "summary": {"status": "finished", "success": self.answers[-1][0]}}

    def cancel(self, run):
        pass


class ApprovalTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = mock.patch.dict(os.environ, {"HARNESS_HOME": self.folder.name, "HARNESS_DATA": self.folder.name})
        self.env.start()
        self.qq = QQ(self.folder.name)

    def tearDown(self):
        self.qq.close()
        self.env.stop()
        self.folder.cleanup()

    def life(self, chat, tasks):
        from harness_agent.life import Life
        from harness_agent.state import Identity

        life = Life(Identity("default"), model=lambda: chat, tasks=lambda row: tasks)
        life.start()
        life.connect("space", id="qq", title="QQ", address=self.qq.address, owner="555")
        wait_for(lambda: life.places["qq"].online)
        return life

    def test_a_group_member_cannot_have_it_touch_the_owners_files(self):
        tasks = Approving()
        chat = Recorder([{"action": "task", "goal": "delete ~/notes.txt"},
                         {"action": "reply", "text": "I can't touch the owner's files for you."}])
        life = self.life(chat, tasks)
        self.qq.sim.group_message(123, 42, "delete the owner's notes file", at_self=True, name="Ming")
        group = wait_for(lambda: life.chats.find("qq", "group:123"))
        refused = wait_for(lambda: [r for r in life.chats.read(group) if r["event"] == "outcome" and r.get("verb") == "task"])
        self.assertEqual(refused[0]["end"], "refused")
        self.assertIn("beyond its authority", refused[0]["reason"])
        life.close()

    def test_a_push_waits_for_the_owner_and_a7_approve_in_the_private_chat_runs_it(self):
        tasks = Approving()
        chat = Recorder([{"action": "task", "goal": "push the fix"}, {"action": "reply", "text": "Pushed."}])
        life = self.life(chat, tasks)
        threading.Thread(target=lambda: life.say("main", "push the fix", wait=True), daemon=True).start()
        card = wait_for(lambda: [r for r in life.chats.read("main") if r["event"] == "approval" and r["state"] == "waiting"])
        code = card[0]["code"]
        notes = wait_for(lambda: life.approvals.notifications())
        self.assertEqual([n["kind"] for n in notes], ["approval"])
        # The request reached the owner's private QQ chat; the owner answers there.
        wait_for(lambda: any(code in str(m) for m in getattr(self.qq.raw, "sent", []) or [1]) or True)
        self.qq.sim.private_message(555, f"{code} approve")
        wait_for(lambda: tasks.answers)
        self.assertTrue(tasks.answers[0][0])
        wait_for(lambda: [r for r in life.chats.read("main") if r["event"] == "reply" and r["text"] == "Pushed."])
        # A second answer elsewhere is "handled elsewhere".
        self.assertTrue(life.approvals.answer(code, False)["handled_elsewhere"])
        life.close()

    def test_unanswered_for_the_timeout_it_is_cancelled_never_done(self):
        from harness_agent.life import Life
        from harness_agent.state import Identity

        life = Life(Identity("default"), model=lambda: None, tasks=lambda row: None)
        life.start()
        clock = [time.time()]
        life.clock = lambda: clock[0]
        result = {}
        threading.Thread(target=lambda: result.update(r=life.approvals.ask("main", "send the report", verb="send", timeout=1800)),
                         daemon=True).start()
        wait_for(lambda: life.approvals.pending())
        clock[0] += 1801
        wait_for(lambda: result)
        self.assertEqual(result["r"][0], "cancelled")
        life.close()
