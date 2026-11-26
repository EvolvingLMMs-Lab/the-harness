"""What the pages read and write besides the chats: usage over a stretch of days, the calendar's
entries changed and put back, the settings an identity has of its own (one name everywhere,
section.key), each setting described for a person in two languages, and a node of the tree
named by its path."""
from datetime import date, timedelta
import json
import time
from unittest import TestCase

import helpers  # noqa: F401  (source paths)

from harness import settings
from harness.problems import Problem
from harness.spending import Account

from test_agent_frontends import Base, run


class UsageTests(Base):
    def ledger(self, identity):
        """Calls of three kinds over three days: priced, under a plan, without a price."""
        folder = identity.directory / "usage"
        folder.mkdir(parents=True, exist_ok=True)
        today = date.today()
        rows = {0: [{"cost_usd": 0.02, "priced": True, "basis": "reported", "model": "a/b", "seconds": 1.5,
                     "source": {"kind": "chat", "id": "main", "whose": "owner"}},
                    {"cost_usd": 0.0, "priced": False, "basis": "plan", "plan_usd": 0.4, "model": "default",
                     "source": {"kind": "chat", "id": "main", "whose": "owner"}},
                    {"cost_usd": 0.01, "priced": True, "basis": "reported", "model": "a/b",
                     "source": {"kind": "task", "id": "run-7", "title": "sort the photos"}}],
                2: [{"cost_usd": 0.0, "priced": False, "basis": "local", "model": "llama",
                     "source": {"kind": "learning", "id": "main", "whose": "own"}}],
                9: [{"cost_usd": 0.5, "priced": True, "basis": "estimated", "model": "a/b",
                     "source": {"kind": "chat", "id": "gone-chat"}}]}
        for back, calls in rows.items():
            day = (today - timedelta(days=back)).isoformat()
            (folder / f"{day}.jsonl").write_text("".join(json.dumps({"time": time.time() - back * 86400, **call}) + "\n"
                                                         for call in calls), encoding="utf-8")

    def test_a_stretch_is_split_by_day_by_conversation_and_by_what_else_it_was_for(self):
        from harness.sdk import Agent

        life = self.life()
        self.ledger(life.identity)
        week = Agent().usage("week")
        self.assertEqual((week["range"], week["cost_usd"], week["plan_usd"]), ("week", 0.03, 0.4))
        self.assertEqual(week["calls"], {"total": 4, "priced": 2, "plan": 1, "unpriced": 1})
        self.assertEqual((len(week["days"]), week["days"][-1]["calls"], week["days"][-1]["plan_calls"],
                          week["days"][-3]["unpriced_calls"], week["days"][0]["calls"]), (7, 3, 1, 1, 0))
        self.assertEqual([(row["chat"], row["title"], row["calls"], row["plan_usd"]) for row in week["by_chat"]],
                         [("main", "Main conversation", 2, 0.4)])
        self.assertEqual([(row["kind"], row["title"], row["cost_usd"]) for row in week["by_task"]],
                         [("task", "sort the photos", 0.01), ("learning", "Main conversation", 0.0)])
        self.assertEqual(week["today"]["daily_budget"], 2.0)
        # The month reaches the older day; a chat that is gone is said to be.
        month = Agent().usage("month")
        self.assertEqual((month["calls"]["total"], round(month["cost_usd"], 2), len(month["days"])), (5, 0.53, 30))
        self.assertEqual([(row["chat"], row["there"]) for row in month["by_chat"]], [("gone-chat", False), ("main", True)])
        self.assertEqual(Agent().usage()["calls"]["total"], 3)
        self.assertEqual(self.host.get("/api/agent/usage?identity=default&range=week")["cost_usd"], 0.03)

    def test_nothing_spent_is_empty_lists_and_a_wrong_range_says_which_there_are(self):
        account = Account(self.folder.name + "/none")
        found = account.span("month")
        self.assertEqual((found["calls"]["total"], found["days"], found["by_source"], found["by_model"]), (0, [], [], []))
        with self.assertRaisesRegex(ValueError, "today, week, month"):
            account.span("year")
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            account.span(start="yesterday")


class CalendarTests(Base):
    def test_an_entry_is_changed_removed_and_put_back(self):
        from harness.sdk import Agent
        from harness_agent.frontends import calendar_main

        life = self.life()
        agent = Agent()
        added = agent.calendar_add("Call Lin", "2030-03-04T15:00", until="2030-03-04T15:30")
        entry = added["result"]["id"]
        # Dragged to another day and made longer; its title and kind edited.
        changed = agent.calendar_update(entry, at="2030-03-05T10:00", until="2030-03-05T11:30", title="Call Lin and Bo",
                                        kind="goal")["result"]
        self.assertEqual((changed["title"], changed["kind"], changed["until"] - changed["at"]),
                         ("Call Lin and Bo", "goal", 5400))
        shown = agent.calendar("2030-03-05T00:00", "2030-03-06T00:00")["entries"]
        self.assertEqual([(row["id"], row["end"] - row["start"], row["has_end"]) for row in shown], [(entry, 5400, True)])
        # A change that does not check changes nothing.
        with self.assertRaises(Problem) as refused:
            agent.calendar_update(entry, title="Half applied", until="2030-03-05T09:00")
        self.assertEqual(refused.exception.code, "calendar_time")
        self.assertEqual(life.calendar._find(entry)["title"], "Call Lin and Bo")
        self.assertEqual(agent.calendar_update(entry, until=None)["result"]["until"], None)
        agent.calendar_remove(entry)
        self.assertEqual(agent.calendar("2030-03-05T00:00", "2030-03-06T00:00")["entries"], [])
        back = agent.calendar_restore()["result"]
        self.assertEqual((back["id"], back["title"]), (entry, "Call Lin and Bo"))
        with self.assertRaises(Problem) as nothing:
            agent.calendar_restore()
        self.assertEqual(nothing.exception.code, "calendar_gone")
        status, out, err = run(calendar_main, "update", entry, "--title", "Call everyone", "--at", "2030-03-06T09:00")
        self.assertEqual(status, 0, err)
        self.assertIn("Call everyone", out)
        status, out, _ = run(calendar_main, "remove", entry)
        status, out, _ = run(calendar_main, "restore", entry)
        self.assertIn("back on the calendar: Call everyone", out)

    def test_an_entry_put_in_the_past_is_missed_and_wakes_nothing(self):
        import time as clock

        life = self.life()
        now = clock.time()
        woken = []
        life.wake = lambda chat, why, **more: woken.append(why)
        # Added in the past; moved into the past; and one that comes due as usual.
        past = life.calendar.add("Yesterday's call", now - 86400)
        moved = life.calendar.add("Was tomorrow", now + 86400)
        life.calendar.update(moved["id"], at=now - 3600)
        soon = life.calendar.add("In a moment", now + 0.2)
        daily = life.calendar.add("Every morning", now - 3 * 86400 - 60, repeat="daily")
        clock.sleep(0.3)
        life._calendar_due(clock.time())
        self.assertEqual(woken, ["on the calendar: In a moment"])
        listed = {row["id"]: row for row in life.calendar.week(now - 2 * 86400, now + 86400)["entries"] if row.get("planned")}
        self.assertEqual((listed[past["id"]]["outcome"], listed[moved["id"]]["missed"], listed[soon["id"]]["missed"]),
                         ("missed", True, False))
        # Of a repeating entry the times before it was put there are missed; the next one comes due.
        self.assertTrue(all(row["missed"] for row in life.calendar.week(now - 4 * 86400, now)["entries"]
                            if row["id"] == daily["id"]))
        life._calendar_due(now + 86400)
        self.assertEqual(woken[-1], "on the calendar: Every morning")
        # Moved back into the future, it is no longer missed.
        life.calendar.update(past["id"], at=now + 7200)
        self.assertNotIn("missed", life.calendar._find(past["id"]))
        # Searched by its words, without reading a year: a repeating entry is one row.
        found = self.host.get("/api/agent/calendar?identity=default&q=MORNING")["entries"]
        self.assertEqual([(row["id"], row["repeat"]) for row in found], [(daily["id"], "daily")])
        self.assertEqual(self.host.get("/api/agent/calendar?identity=default&q=nothing-like-this")["entries"], [])

    def test_what_it_planned_itself_and_the_owner_removed_is_remembered_until_it_is_put_back(self):
        life = self.life()
        row = life.calendar.add("Practise the form", "2030-03-04T09:00", by="agent", kind="plan")
        life.calendar.remove(row["id"])
        self.assertIn("calendar: Practise the form", life.identity.memory()["entries"])
        life.calendar.restore(row["id"])
        self.assertNotIn("calendar: Practise the form", life.identity.memory()["entries"])


class TakeTests(Base):
    def test_a_backup_sent_as_a_file_is_restored_and_a_refusal_says_what_to_do(self):
        import base64

        from harness_agent import state, take

        life = self.life()
        other = state.create("travel", display="Travel")
        folder = __import__("pathlib").Path(self.folder.name)
        take.backup(other, folder / "travel.harness-backup", "correct horse")
        blob = base64.b64encode((folder / "travel.harness-backup").read_bytes()).decode()

        def restore(**more):
            return self.host.post("/api/agent/take", {"action": "restore", "name": "travel.harness-backup", "data": blob,
                                                      "passphrase": "correct horse", **more})

        for more, code in (({}, "identity_exists"), ({"passphrase": "wrong", "replace": True}, "backup_passphrase"),
                           ({"data": base64.b64encode(b"some text").decode()}, "not_backup"), ({"data": "%%"}, "backup_data")):
            with self.assertRaises(Problem) as refused:
                restore(**more)
            self.assertEqual(refused.exception.code, code, more)
            self.assertTrue(refused.exception.fix)
        self.assertTrue((other.directory / "identity.json").is_file())   # a refusal touched nothing
        state.delete("travel")
        done = restore()
        self.assertEqual((done["identity"], done["name"]), ("travel", "Travel"))
        self.assertIn("travel", state.identities())
        with self.assertRaises(Problem) as low:
            self.host.post("/api/agent/usage", {"identity": "default", "raise_today": 1})
        self.assertEqual(low.exception.code, "budget_not_raised")
        self.assertIn("above $2.00", low.exception.fix)


class SettingTests(Base):
    def post(self, **body):
        return self.host.post("/api/agent/settings", {"identity": "default", **body})

    def test_an_identitys_own_value_has_one_name_however_a_frontend_writes_it(self):
        from harness.paths import data
        from harness.sdk import Agent

        life = self.life()
        # The whole name as the key; the section and the key; and the section given twice
        # (what the page sent, which used to end as "no setting agent.agent.daily_budget"
        # and then change the global value).
        self.assertEqual(self.post(key="agent.daily_budget", value=3.5)["own"], {"agent.daily_budget": 3.5})
        self.post(section="agent", key="reserve", value=0.25)
        found = self.post(section="agent", key="agent.proactive", value="learn_only")
        self.assertEqual(found["own"], {"agent.daily_budget": 3.5, "agent.reserve": 0.25, "agent.proactive": "learn_only"})
        self.assertEqual((found["values"]["agent.daily_budget"], found["values"]["agent.stale_hours"]), (3.5, 6.0))
        self.assertEqual(settings.Settings(data()).get()["agent"]["daily_budget"], 2.0)   # the global one is untouched
        self.assertEqual(life.identity.account().day()["daily_budget"], 3.5)
        self.assertEqual(self.post(key="learning.mode", value="review_first")["values"]["learning.mode"], "review_first")
        self.assertEqual(life.learning.mode(), "review_first")
        self.assertEqual(self.post(key="learning.admission", value="by_environment")["own"]["learning.admission"],
                         "by_environment")
        # null: the global value again. Python reads and writes the same.
        self.assertNotIn("agent.daily_budget", self.post(key="agent.daily_budget", value=None)["own"])
        self.assertEqual(Agent().set("agent.keep_days", 30)["values"]["agent.keep_days"], 30)
        self.assertEqual(Agent().settings()["own"]["agent.keep_days"], 30)
        for body, code in ((dict(key="general.theme", value="dark"), "global_setting"),
                           (dict(key="agent.proactive", value="sometimes"), "setting_value"),
                           (dict(key="agent.nothing", value=1), "no_setting"), (dict(key="budget", value=1), "no_setting"),
                           (dict(key="spaces.nowhere.proactive", value="do"), "no_place")):
            with self.assertRaises(Problem) as refused:
                self.post(**body)
            self.assertEqual(refused.exception.code, code, body)

    def test_every_setting_is_described_for_a_person_in_two_languages(self):
        self.life()
        schema = self.host.get("/api/agent/settings?identity=default")["schema"]
        row = schema["agent.proactive"]
        self.assertEqual((row["title"], row["type"], row["scope"]), ({"en": "Acting on its own", "zh": "它自己做事"},
                                                                    "choice", "identity"))
        self.assertEqual((row["choices"], row["labels"]["learn_only"], row["options"][1]),
                         (["on", "learn_only", "off"], {"en": "Only to learn", "zh": "只为学习"},
                          {"value": "learn_only", "en": "Only to learn", "zh": "只为学习"}))
        self.assertTrue(row["about"]["zh"].startswith("on："))
        self.assertEqual(row["about"], row["description"])
        described = settings.described()
        for section, keys in settings._CORE_SCHEMA.items():
            for key in keys:
                found = described[section][key]
                self.assertNotEqual(found["title"]["zh"], found["title"]["en"] if section != "general" else None,
                                    f"{section}.{key} has no Chinese title")
                if found["type"] == "choice":
                    self.assertEqual(found["choices"], list(keys[key].bounds))
                    self.assertTrue(all(found["labels"][value]["zh"] and found["labels"][value]["en"]
                                        for value in found["choices"]))
        # A setting of a package that says nothing more is called by its key, a choice by its value.
        plain = settings.describe("kit", "arm_speed", settings.Setting("fast", "choice", ("fast", "slow_start"), "how fast"))
        self.assertEqual((plain["title"]["en"], plain["labels"]["slow_start"], plain["about"]["zh"]),
                         ("Arm speed", {"en": "slow start", "zh": "slow start"}, "how fast"))
        with self.assertRaisesRegex(ValueError, r"did you mean learning.mode\?"):
            settings.split("learning.mod")

    def test_every_setting_of_every_package_here_has_its_words_in_both_languages(self):
        described = settings.described()
        self.assertGreater(len(described["computer"]), 15)
        for section, keys in described.items():
            for key, found in keys.items():
                name = f"{section}.{key}"
                self.assertTrue(settings.SCHEMA[section][key].title, f"{name} is called by its key only")
                self.assertTrue(found["title"]["zh"] and found["about"]["zh"], name)
                self.assertNotEqual(found["about"]["zh"], found["about"]["en"], f"{name} has no Chinese description")
                if found["type"] == "choice":
                    given = settings.SCHEMA[section][key].labels or {}
                    self.assertEqual(set(given), set(found["choices"]), f"{name}: a label for every choice")
        # What no frontend shows a person: keys that do nothing any more, or only carry what an
        # earlier version kept. Tuning few people need is marked, not hidden.
        hidden = sorted(f"{section}.{key}" for section, keys in described.items() for key, found in keys.items()
                        if not found["shown"])
        self.assertEqual(hidden, ["model.think_interval", "model.think_while_acting", "personal.about",
                                  "personal.instructions"])
        self.assertTrue(described["computer"]["vm_accel"]["advanced"])
        self.assertFalse(described["computer"]["mode"]["advanced"])

    def test_a_node_of_the_tree_is_named_by_the_path_a_page_browses(self):
        life = self.life()
        life.tree.add("desk", {"fact": "working_in", "has": "desktop"}, {"nothing": True}, about="working at the desktop")
        life.tree.add("lowbat", {"fact": "battery", "below": 20}, {"stop": True}, under="desk", about="battery low")
        level = self.host.post("/api/agent/tree", {"identity": "default", "action": "disable", "path": "desk/lowbat"})
        self.assertEqual((level["path"], [(node["name"], node["enabled"]) for node in level["nodes"]]),
                         (["desk"], [("lowbat", False)]))
        level = self.host.post("/api/agent/tree", {"identity": "default", "action": "enable", "name": "lowbat",
                                                   "path": "desk"})
        self.assertEqual([(node["name"], node["enabled"]) for node in level["nodes"]], [("lowbat", True)])
        level = self.host.post("/api/agent/tree", {"identity": "default", "action": "remove", "path": "desk/lowbat"})
        self.assertEqual((level["path"], level["nodes"]), (["desk"], []))


class RetentionTests(Base):
    def test_records_older_than_keep_days_go_and_what_came_from_them_shows_expired(self):
        life = self.life()
        old = life.chats.record("main", "user", text="long ago")
        path = life.chats.folder("main") / "events.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in lines]
        for row in rows:
            if row["seq"] == old["seq"]:
                row["time"] -= 100 * 86400
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        life.identity.set_setting("keep_days", 90)
        life._prune()
        kept = life.chats.read("main")
        self.assertNotIn("long ago", [row.get("text") for row in kept])
        self.assertTrue(life.chats.expired("main", old["time"] - 100 * 86400))
        self.assertFalse(life.chats.expired("main", time.time()))
        self.assertTrue(life.chats.expired("a-chat-that-is-gone", time.time()))
        # Numbers go on where they were.
        self.assertGreater(life.chats.record("main", "user", text="now")["seq"], max(row["seq"] for row in rows))


class ModelTests(Base):
    def test_a_chat_can_have_a_model_of_its_own(self):
        from harness_agent.life import Life
        from harness_agent.state import Identity
        from test_agent_life import NoTasks, Recorder

        asked = []
        mine, theirs = Recorder([{"action": "reply", "text": "from the identity's model"}]), \
            Recorder([{"action": "reply", "text": "from the chat's model"}])

        def model(name=None):
            asked.append(name)
            return theirs if name else mine

        life = Life(Identity("default"), model=model, tasks=lambda row: NoTasks())
        life.start()
        self.lives.append(life)
        chat = life.chats.new("other model")
        life.chats.update(chat, model="entry-7", effort="high")
        self.assertEqual(life.say(chat, "hello", wait=True)["answer"], "from the chat's model")
        self.assertEqual(life.say("main", "hello", wait=True)["answer"], "from the identity's model")
        self.assertIn("entry-7", asked)
        row = next(row for row in life.chats.listing() if row["chat"] == chat)
        self.assertEqual((row["model"], row["effort"]), ("entry-7", "high"))
