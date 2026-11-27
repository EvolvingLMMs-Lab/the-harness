"""An identity's tree of reactions, always judged, and the model woken on objective conditions:
the three built-in nodes, nodes under a situation, the earlier interrupting the later, the
owner's words becoming a node, intentions coming due, the reserve, asleep and 0:00."""
import json
import os
import tempfile
import time
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)

from harness.runtime.decision.model import ScriptedChat

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

    def test_three_built_in_nodes_can_be_disabled_not_deleted(self):
        from harness_agent.reactions import Tree

        tree = Tree(self.identity)
        self.assertEqual([n["name"] for n in tree.level()["nodes"]], ["named", "failed", "approval"])
        with self.assertRaises(ValueError):
            tree.remove("named")
        tree.enable("named", False)
        event = {"kind": "qq.message", "data": {"text": "hi"}, "addressed": True}
        self.assertIsNone(tree.judge({"event": event, "facts": {}}))
        tree.enable("named", True)
        self.assertEqual(tree.judge({"event": event, "facts": {}})["node"], "named")

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

    def life(self, chat, clock=None):
        from harness_agent.life import Life

        life = Life(self.identity, model=lambda: chat, tasks=lambda row: NoTasks(), clock=clock or time.time)
        life.start()
        return life

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
