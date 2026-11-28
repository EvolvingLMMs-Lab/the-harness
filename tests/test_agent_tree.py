"""An identity's minimal initial behaviour tree (T_0), always judged, and the model woken on
objective conditions: the 23 built-in T_0 nodes, format-1 migration, nodes under a situation,
scoped desktop yield, anti-lobotomy & R11 evidence-gated tree evolution, intentions & calendar
surviving sleep, frozen-library immutability, anti-livelock auto-demotion, and 0:00 wakeup."""
from datetime import datetime, timedelta
import json
import os
import tempfile
import time
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)

from test_agent_life import NoTasks, Recorder, wait_for


class Clock:
    def __init__(self, start=None):
        self.now = start or time.time()

    def __call__(self):
        return self.now


class TreeTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = mock.patch.dict(os.environ, {"HARNESS_HOME": self.folder.name, "HARNESS_DATA": self.folder.name})
        self.env.start()
        from harness_agent.state import Identity

        self.identity = Identity("default")

    def tearDown(self):
        self.env.stop()
        self.folder.cleanup()

    def test_minimal_initial_tree_nodes_can_be_disabled_not_deleted(self):
        from harness_agent.reactions import BUILTIN, Tree

        tree = Tree(self.identity)
        self.assertEqual(len(tree.data["nodes"]), 23)
        self.assertEqual(len(BUILTIN), 23)
        top_names = [n["name"] for n in tree.level()["nodes"]]
        self.assertEqual(top_names, [
            "desktop_yield", "approval_waiting", "channel_login_expired", "sleep_notice",
            "owner_message", "owner_calendar_due", "learned_reactive", "named",
            "action_failed", "midnight_reset", "morning_brief", "awake_own",
        ])
        with self.assertRaises(ValueError):
            tree.remove("named")
        with self.assertRaises(ValueError):
            tree.remove("awake_own")
        tree.enable("named", False)
        event = {"kind": "qq.message", "data": {"text": "hi"}, "addressed": True}
        self.assertIsNone(tree.judge({"event": event, "facts": {}}))
        tree.enable("named", True)
        self.assertEqual(tree.judge({"event": event, "facts": {}})["node"], "named")

    def test_format1_reactions_migrate_cleanly_to_format2_t0(self):
        from harness_agent.reactions import FORMAT, Tree

        legacy = {
            "format": 1,
            "nodes": [
                {"name": "named", "about": "named", "when": {"event": "*", "match": {"addressed": True}},
                 "do": {"wake": True}, "source": "builtin", "evidence": "builtin", "enabled": False,
                 "under": None, "uses": 4, "done": 3},
                {"name": "failed", "about": "failed", "when": {"outcome": ["failed", "unknown"]},
                 "do": {"wake": True}, "source": "builtin", "evidence": "builtin", "enabled": True,
                 "under": None, "uses": 2, "done": 2},
                {"name": "approval", "about": "approval", "when": {"event": "approval.waiting"},
                 "do": {"remind": "wait"}, "source": "builtin", "evidence": "builtin", "enabled": True,
                 "under": None, "uses": 1, "done": 1},
                {"name": "custom_rule", "about": "custom", "when": {"fact": "battery", "below": 15},
                 "do": {"remind": "plug"}, "source": "owner", "evidence": "owner", "enabled": True,
                 "under": None, "uses": 0, "done": 0},
            ],
        }
        (self.identity.directory / "reactions.json").write_text(json.dumps(legacy), encoding="utf-8")
        tree = Tree(self.identity)
        self.assertEqual(tree.data["format"], FORMAT)
        self.assertFalse(tree.node("named")["enabled"])
        self.assertEqual(tree.node("action_failed")["uses"], 2)
        self.assertEqual(tree.node("approval_waiting")["uses"], 1)
        self.assertIsNotNone(tree.node("custom_rule"))
        self.assertIsNotNone(tree.node("learned_reactive"))
        self.assertIsNotNone(tree.node("learned_proactive"))

    def test_match_reads_payload_kind_without_envelope_collision(self):
        from harness_agent.reactions import Tree

        tree = Tree(self.identity)
        facts = {"asleep": False, "pace_ok": True, "proactive_mode": "learn_only", "learning_mode": "on"}
        ev = {"kind": "intention.due", "data": {"id": "i1", "kind": "practice", "what": "drill"}}
        taken = tree.judge({"event": ev, "facts": facts})
        self.assertIsNotNone(taken)
        self.assertEqual(taken["node"], "practice_due")
        act_ev = {"kind": "intention.due", "data": {"id": "i2", "kind": "act", "what": "explore"}}
        self.assertIsNone(tree.judge({"event": act_ev, "facts": facts}))

    def test_a_node_under_a_situation_answers_only_in_it_and_the_path_is_lit(self):
        from harness_agent.reactions import Tree

        tree = Tree(self.identity)
        tree.add("desktop", {"fact": "working_in", "has": "desktop"}, None, about="working on the desktop")
        tree.add("refused input", {"outcome": ["refused"], "verb": "desktop.input"}, {"wake": True}, under="desktop")
        with self.assertRaises(ValueError):  # nodes hang under a situation, not under an event
            tree.add("x", {"fact": "asleep", "is": True}, {"nothing": True}, under="named")
        with self.assertRaises(ValueError):  # a goal is no objective condition
            tree.add("finish the report", {"goal": "report"}, {"wake": True})
        refused = {"kind": "asp.outcome", "end": "refused", "verb": "desktop.input"}
        self.assertIsNone(tree.judge({"event": refused, "facts": {"working_in": []}}))
        taken = tree.judge({"event": refused, "facts": {"working_in": ["desktop"]}})
        self.assertEqual((taken["node"], taken["path"]), ("refused input", ["desktop", "refused input"]))
        level = tree.level()
        self.assertEqual(next(n for n in level["nodes"] if n["name"] == "desktop")["children"], 1)
        self.assertTrue(next(n for n in level["nodes"] if n["name"] == "desktop")["lit"])
        self.assertEqual([n["name"] for n in tree.level(["desktop"])["nodes"]], ["refused input"])

    def test_the_earlier_node_takes_over(self):
        from harness_agent.reactions import Tree

        tree = Tree(self.identity)
        tree.add("low battery", {"fact": "battery", "below": 20}, {"stop": True, "remind": "plug in"}, before="named")
        held = set()
        view = {"facts": {"battery": 15}}
        self.assertEqual(tree.judge_situation(view, held)["node"], "low battery")
        self.assertIsNone(tree.judge_situation(view, held))        # once each time it comes
        self.assertIsNone(tree.judge_situation({"facts": {"battery": 50}}, held))
        self.assertEqual(tree.judge_situation(view, held)["node"], "low battery")
        event = {"kind": "qq.message", "addressed": True, "data": {}}
        self.assertEqual(tree.judge({"event": event, "facts": {"battery": 15}})["node"], "named")

    def test_tree_evolve_enforces_anti_lobotomy_non_shadowing_and_r11_evidence_gate(self):
        from harness_agent.reactions import Tree

        tree = Tree(self.identity)
        places = {"repo": {"kind": "folder"}, "group": {"kind": "space"}}
        skills = {
            "draft": {"evidence": "proposed", "archived": False},
            "tested": {"evidence": "own_test", "archived": False},
            "eff": {"evidence": "effective", "archived": False},
        }
        # 'other' authority is always refused
        with self.assertRaises(ValueError):
            tree.evolve(authority="other", op="add", name="hijack",
                        when={"event": "chat.message", "place": "group"}, do={"nothing": True}, under="learned_reactive")
        # 'own' cannot delete/disable/edit core builtin nodes or use unconstrained wildcard or protected events
        for kwargs in (
            {"op": "remove", "name": "owner_message"},
            {"op": "disable", "name": "dreaming"},
            {"op": "edit", "name": "awake_own", "when": {"fact": "asleep", "is": True}},
            {"op": "add", "name": "swallow", "under": "learned_reactive", "when": {"event": "*"}, "do": {"nothing": True}},
            {"op": "add", "name": "steal", "under": "learned_reactive", "when": {"event": "owner.message"}, "do": {"nothing": True}},
            {"op": "add", "name": "untested_local", "under": "learned_reactive",
             "when": {"event": "folder.changed", "place": "repo"}, "do": {"skill": "draft"}},
            {"op": "add", "name": "non_eff_ext", "under": "learned_reactive",
             "when": {"event": "chat.message", "place": "group"}, "do": {"skill": "tested"}},
        ):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                tree.evolve(authority="own", skills=skills, places=places, **kwargs)

        # Valid full CRUD cycle for own authority inside extension slots
        added = tree.evolve(authority="own", op="add", name="auto_faq", under="learned_reactive",
                            when={"event": "chat.message", "place": "group", "match": {"faq": True}},
                            do={"skill": "eff"}, skills=skills, places=places)
        self.assertEqual((added["under"], added["source"]), ("learned_reactive", "learned"))
        tree.evolve(authority="own", op="edit", name="auto_faq",
                    when={"event": "chat.message", "place": "group", "match": {"faq": True, "addressed": True}},
                    skills=skills, places=places)
        tree.evolve(authority="own", op="disable", name="auto_faq", skills=skills, places=places)
        self.assertFalse(tree.node("auto_faq")["enabled"])
        tree.evolve(authority="own", op="enable", name="auto_faq", skills=skills, places=places)
        self.assertTrue(tree.node("auto_faq")["enabled"])
        tree.evolve(authority="own", op="move", name="auto_faq", under="learned_proactive", skills=skills, places=places)
        self.assertEqual(tree.node("auto_faq")["under"], "learned_proactive")
        tree.evolve(authority="own", op="remove", name="auto_faq", skills=skills, places=places)
        self.assertIsNone(tree.node("auto_faq"))

    def test_failing_learned_node_auto_demotes_and_audit_promotes_effective(self):
        from harness_agent.reactions import Tree

        tree = Tree(self.identity)
        tree.evolve(authority="own", op="add", name="flaky", under="learned_reactive",
                    when={"event": "folder.changed", "place": "repo"}, do={"nothing": True})
        tree.evolve(authority="own", op="add", name="solid", under="learned_reactive",
                    when={"event": "pr.opened", "place": "repo"}, do={"nothing": True})
        self.assertFalse(tree.counted("flaky", False))
        self.assertFalse(tree.counted("flaky", False))
        self.assertTrue(tree.counted("flaky", False))  # 3 failures -> auto-demoted!
        self.assertFalse(tree.node("flaky")["enabled"])
        self.assertEqual(tree.node("flaky")["evidence"], "proposed")
        for _ in range(5):
            tree.counted("solid", True)
        audited = tree.audit()
        self.assertEqual(audited["promoted"], ["solid"])
        self.assertEqual(tree.node("solid")["evidence"], "effective")

    def life(self, chat, clock=None):
        from harness_agent.life import Life

        life = Life(self.identity, model=lambda: chat, tasks=lambda row: NoTasks(), clock=clock or time.time)
        life.start()
        return life

    def test_desktop_yield_stops_only_desktop_and_keeps_parallel_folder_running(self):
        life = self.life(Recorder([]))
        proj = os.path.join(self.folder.name, "proj")
        os.makedirs(proj)
        life.connect("desktop", id="desktop", title="Desktop")
        life.connect("folder", id="proj", title="Proj", folder=proj)
        life.busy.update({"place-desktop", "place-proj"})
        stopped = []
        with mock.patch.object(life, "stop", side_effect=lambda chat, why="": stopped.append(chat)):
            life.facts["owner_active"] = True
            for taken in life.tree.judge_situations(life._view(), life.held):
                life._answer("main", taken)
        self.assertEqual(stopped, ["place-desktop"])
        life.close()

    def test_the_owner_says_a_reaction_and_it_becomes_a_node_at_once(self):
        when = {"fact": "battery", "below": 20}
        chat = Recorder([{"action": "reaction", "name": "low battery", "about": "battery below 20% -> stop, remind me",
                          "when": when, "do": {"stop": True, "remind": "Plug me in"}, "under": None},
                         {"action": "reply", "text": "Done: I will stop and remind you."}])
        life = self.life(chat)
        life.say("main", "When the battery is below 20%, stop what you are doing and remind me to plug in", wait=True)
        node = life.tree.node("low battery")
        self.assertEqual((node["source"], node["evidence"]), ("owner", "owner"))
        life.facts["battery"] = 12
        wait_for(lambda: [r for r in life.chats.read("main") if r["event"] == "reminder"])
        life.close()

    def test_an_intention_wakes_it_when_due_and_only_the_tree_runs_until_then(self):
        self.identity.set_setting("proactive", "on")
        clock = Clock()
        chat = Recorder([{"action": "intend", "what": "look at the PR again", "in_minutes": 60},
                         {"action": "reply", "text": "I will look again in an hour"},
                         {"action": "done", "note": "looked"}])
        life = self.life(chat, clock)
        life.say("main", "keep an eye on the PR", wait=True)
        self.assertEqual(len(chat.seen), 2)
        time.sleep(1.5)
        self.assertEqual(len(chat.seen), 2)          # nothing to think about: not woken
        clock.now += 3601
        wait_for(lambda: [r for r in life.chats.read("main") if r["event"] == "done"])
        woken = [r for r in life.chats.read("main") if r["event"] == "woken"]
        self.assertIn("intention due: look at the PR again", woken[-1]["why"])
        life.close()

    def test_intention_survives_sleep_and_cancel_op_removes_it(self):
        from harness import spending

        self.identity.set_setting("daily_budget", 2.0)
        self.identity.set_setting("reserve", 0.5)
        self.identity.set_setting("proactive", "on")
        clock = Clock(time.time())
        chat = Recorder([{"action": "done", "note": "followed up after reset"}])
        life = self.life(chat, clock)
        # Cancel op works
        added = life.intend("main", {"what": "temp", "in_minutes": 5})["intended"]
        self.assertEqual(life.intend("main", {"op": "cancel", "id": added["id"]}), {"cancelled": added["id"]})
        # Exhaust own budget -> asleep
        account = self.identity.account()
        account.charge(type("M", (), {"prices": {"input": 0.8e6, "output": 0}, "model": "m"})(),
                       {"input_tokens": 2, "output_tokens": 0}, {"kind": "chat", "id": "x", "whose": "own"})
        wait_for(lambda: life.status()["asleep"])
        # Intention comes due while asleep -> preserved, NOT lost!
        life.intend("main", {"what": "tuesday idea", "in_minutes": 1})
        clock.now += 120
        time.sleep(1.5)
        self.assertEqual(len(life.intentions), 1)
        self.assertEqual(chat.seen, [])
        # Next day 00:00 -> reset wakes and consumes the preserved intention!
        clock.now += 86400
        with mock.patch.object(spending, "today", lambda: time.strftime("%Y-%m-%d", time.localtime(clock.now))):
            wait_for(lambda: [r for r in life.chats.read("main") if r["event"] == "done"])
        self.assertEqual(life.intentions, [])
        life.close()

    def test_owner_calendar_fires_when_asleep_and_proactive_off(self):
        self.identity.set_setting("daily_budget", 2.0)
        self.identity.set_setting("reserve", 0.5)
        self.identity.set_setting("proactive", "off")
        clock = Clock(time.time())
        chat = Recorder([{"action": "reply", "text": "owner reminder delivered"}])
        life = self.life(chat, clock)
        account = self.identity.account()
        account.charge(type("M", (), {"prices": {"input": 0.8e6, "output": 0}, "model": "m"})(),
                       {"input_tokens": 2, "output_tokens": 0}, {"kind": "chat", "id": "x", "whose": "own"})
        wait_for(lambda: life.status()["asleep"])
        life.calendar.add("pay rent", datetime.fromtimestamp(clock.now + 60), kind="reminder", by="owner")
        clock.now += 120
        wait_for(lambda: [r for r in life.chats.read("main") if r["event"] == "reply"])
        life.close()

    def test_frozen_learning_mode_prevents_dream_mutations(self):
        from harness.runtime.learning.learner import candidate

        life = self.life(Recorder([]))
        life.identity.set_setting("mode", "frozen", "learning")
        learner = life.learning.learner()
        learner.admit(candidate("skill", "keep_me", "def keep_me(): return 1\n", "assert keep_me() == 1\n"), "provisional")
        index = learner.index()
        index["skills/keep_me.py"]["admitted_at"] = time.time() - 40 * 86400
        learner._save_index(index)
        os.utime(life.identity.library / "skills" / "keep_me.py", (time.time() - 40 * 86400,) * 2)
        res = life.learning.dream()
        self.assertTrue(res.get("frozen"))
        self.assertTrue((life.identity.library / "skills" / "keep_me.py").exists())
        life.close()

    def test_asleep_its_own_matters_wait_the_owner_is_answered_and_0_00_wakes_it(self):
        from harness import spending

        self.identity.set_setting("daily_budget", 2.0)
        self.identity.set_setting("reserve", 0.5)
        self.identity.set_setting("proactive", "on")
        clock = Clock(time.time())
        chat = Recorder([{"action": "reply", "text": "still here for you"}, {"action": "done", "note": "caught up"}])
        life = self.life(chat, clock)
        account = self.identity.account()
        # Its own part of the budget is spent: $1.60 of $2 with $0.50 kept for the owner.
        account.charge(type("M", (), {"prices": {"input": 0.8e6, "output": 0}, "model": "m"})(),
                       {"input_tokens": 2, "output_tokens": 0}, {"kind": "chat", "id": "x", "whose": "own"})
        time.sleep(1.5)
        self.assertTrue(life.status()["asleep"])
        life.tell("qq", {"type": "folder.changed", "data": {"addressed": True, "text": "please look"}, "source": "outside"})
        chat_id = wait_for(lambda: [r for r in life.chats.listing() if r["kind"] == "place"])[0]["chat"]
        wait_for(lambda: [r for r in life.chats.read(chat_id) if r["event"] == "deferred"])
        self.assertEqual(chat.seen, [])
        self.assertEqual(life.say("main", "are you there?", wait=True)["answer"], "still here for you")
        # 0:00
        clock.now += 86400
        with mock.patch.object(spending, "today", lambda: time.strftime("%Y-%m-%d", time.localtime(clock.now))):
            wait_for(lambda: [r for r in life.chats.read(chat_id) if r["event"] == "done"])
        self.assertTrue([r for r in life.chats.read("main") if r["event"] == "awake"])
        life.close()
