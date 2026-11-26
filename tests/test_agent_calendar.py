"""The calendar: entries the owner and it put there wake it when due (a missed one once, for its
latest time), what happened is on it (who began each turn, the outcome, refusals, asleep), the
owner removing its plan becomes a private memory, and the morning summary."""
import os
import tempfile
import time
from datetime import datetime, timedelta
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)

from test_agent_life import NoTasks, Recorder, wait_for


class CalendarTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = mock.patch.dict(os.environ, {"HARNESS_HOME": self.folder.name, "HARNESS_DATA": self.folder.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.folder.cleanup()

    def life(self, chat, clock=None):
        from harness_agent.life import Life
        from harness_agent.state import Identity

        life = Life(Identity("default"), model=lambda: chat, tasks=lambda row: NoTasks(), clock=clock or time.time)
        life.start()
        return life

    def test_remind_me_every_day_and_a_missed_one_is_taken_up_once(self):
        now = [time.time()]
        chat = Recorder([{"action": "calendar", "title": "stand-up notes", "at": "09:00", "repeat": "daily",
                          "kind": "reminder"},
                         {"action": "reply", "text": "I'll remind you every day at 9."},
                         {"action": "reply", "text": "Time for the stand-up notes."}])
        life = self.life(chat, lambda: now[0])
        life.say("main", "remind me every day at 9 am to write the stand-up notes", wait=True)
        entry = life.calendar.entries[0]
        self.assertEqual((entry["by"], entry["repeat"]), ("owner", "daily"))
        # The computer was off for three days: it is taken up once, for the latest time.
        entry["at"] = now[0] - 3 * 86400 - 60
        now[0] += 1
        wait_for(lambda: [r for r in life.chats.read("main") if r["event"] == "woken"])
        time.sleep(1.5)
        woken = [r for r in life.chats.read("main") if r["event"] == "woken"]
        self.assertEqual(len(woken), 1)
        self.assertIn("on the calendar: stand-up notes", woken[0]["why"])
        life.close()

    def test_the_week_shows_who_did_what_and_its_outcome(self):
        chat = Recorder([{"action": "reply", "text": "hello"}])
        life = self.life(chat)
        life.say("main", "hi", wait=True)
        life.calendar.log(kind="asleep", title="asleep", start=time.time() - 7200, end=time.time() - 3600, who="tree")
        week = life.calendar.week()
        kinds = {(e["kind"], e["who"]) for e in week["entries"]}
        self.assertIn(("turn", "owner"), kinds)
        self.assertIn(("asleep", "tree"), kinds)
        turn = next(e for e in week["entries"] if e["kind"] == "turn")
        self.assertEqual(turn["outcome"], "done")
        life.close()

    def test_the_owner_removing_its_plan_is_remembered(self):
        life = self.life(Recorder([]))
        row = life.calendar.add("tidy the group's links", datetime.now() + timedelta(hours=2), kind="plan", by="agent")
        life.calendar.remove(row["id"], by="owner")
        memory = life.identity.memory()["entries"]
        self.assertTrue(any("tidy the group's links" in e["text"] and e["scope"] == "private" for e in memory.values()))
        life.close()

    def test_the_morning_summary(self):
        now = [datetime.now().replace(hour=7, minute=0).timestamp()]
        life = self.life(Recorder([]), lambda: now[0])
        life.calendar.state.update(morning="the day before", summarized=now[0] - 86400)  # a night lived through
        life.calendar.log(kind="turn", who="own", title="fixed the failing test", start=now[0] - 3600,
                          end=now[0] - 3000, outcome="done")
        wait_for(lambda: [r for r in life.chats.read("main") if r["event"] == "summary"])
        summary = [r for r in life.chats.read("main") if r["event"] == "summary"][0]["text"]
        self.assertIn("fixed the failing test (done)", summary)
        self.assertIn("Waiting for your approval: nothing", summary)
        self.assertTrue((life.identity.directory / "DREAMS.md").exists())
        life.close()
