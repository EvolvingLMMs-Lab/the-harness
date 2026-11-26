"""Spending: what a call costs (reported, estimated from prices, local, unpriced), an
identity's daily budget and call cap checked before every model call, a call already made
finishing over the limit, a raise for today only; at the limit a conversation's turn ends
while its program goes on, and the agent's dialogue stops calling the model."""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)
sys.path.insert(0, str(helpers.ROOT / "packages" / "agent"))
from harness import spending
from harness.runtime.decision.model import ChatModel, ChatReply, ScriptedChat
from harness.runtime.decision.thoughts import Thought
from harness.spending import Account, SpendingLimit
from harness_agent import state
from harness_agent.session import Session


class Counting(ScriptedChat):
    def __init__(self, replies, usage=None, provider=None):
        super().__init__(replies)
        self.provider = provider  # openrouter: its calls have a price
        self.asked, self.usage = 0, usage or {}

    def complete(self, system, messages, **options):
        self.asked += 1
        reply = super().complete(system, messages)
        return ChatReply(reply.text, usage=dict(self.usage))


class CostTests(TestCase):
    def test_reported_estimated_local_and_unpriced(self):
        remote = SimpleNamespace(model="m", base_url="https://api.example.com/v1", prices={})
        self.assertEqual(spending.cost(remote, {"cost_usd": 0.25})["basis"], "reported")
        priced = SimpleNamespace(model="m", base_url="https://api.example.com/v1",
                                 prices={"input": 0.5, "output": 2.0})
        estimate = spending.cost(priced, {"input_tokens": 1_000_000, "output_tokens": 500_000})
        self.assertEqual((estimate["cost_usd"], estimate["basis"], estimate["priced"]), (1.5, "estimated", True))
        for url in ("http://localhost:11434/v1", "http://127.0.0.1:8000/v1", "http://192.168.1.20:8000/v1"):
            local = spending.cost(SimpleNamespace(model="m", base_url=url), {"input_tokens": 99})
            self.assertEqual((local["cost_usd"], local["priced"], local["basis"]), (0.0, False, "local"), url)
        self.assertEqual(spending.cost(remote, {})["cost_usd"], None)
        self.assertEqual(spending.cost(remote, {})["basis"], "unpriced")

    def test_prices_come_from_the_model_entry(self):
        from harness import model_list, providers
        row = model_list.entry({"provider": "deepseek", "model": "deepseek-chat", "prices": {"input": 0.27, "output": 1.1}})
        self.assertEqual(row["prices"], {"input": 0.27, "output": 1.1})
        with self.assertRaises(ValueError):
            model_list.entry({"provider": "deepseek", "model": "x", "prices": {"input": -1}})
        role = providers.model_role(row)
        self.assertEqual(role["prices"], {"input": 0.27, "output": 1.1})
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}):
            self.assertEqual(ChatModel(role).prices, {"input": 0.27, "output": 1.1})


class AccountTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.account = Account(Path(temp.name) / "usage")
        self.paid = SimpleNamespace(model="paid", base_url=None)
        self.local = SimpleNamespace(model="local", base_url="http://127.0.0.1:8000/v1")

    def test_budget_checked_before_a_call_and_a_made_call_charged_over_it(self):
        self.account.set_limits(1.0, 500)
        self.account.check()
        self.account.charge(self.paid, {"cost_usd": 0.75}, {"kind": "chat", "id": "s1"})
        self.account.check()  # $0.75 of $1: the next call may start...
        self.account.charge(self.paid, {"cost_usd": 0.75}, {"kind": "task", "id": "r1"})  # ...and it is kept
        day = self.account.day()
        self.assertEqual((day["cost_usd"], day["calls"], day["left_usd"]), (1.5, 2, 0.0))
        self.assertEqual({row["kind"] for row in day["by_source"]}, {"chat", "task"})
        with self.assertRaisesRegex(SpendingLimit, r"budget of \$1.00 is used up"):
            self.account.check()

    def test_raising_today_changes_today_only(self):
        self.account.set_limits(1.0, 500)
        self.account.charge(self.paid, {"cost_usd": 1.0})
        self.assertIsNotNone(self.account.refusal())
        with self.assertRaises(ValueError):
            self.account.raise_today(0.5)
        self.account.raise_today(3.0)
        self.assertIsNone(self.account.refusal())
        self.assertEqual((self.account.limits()["daily_budget"], self.account.limits()["raised"]), (3.0, True))
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.assertEqual(self.account.limits(tomorrow)["daily_budget"], 1.0)
        with mock.patch("harness.spending.today", return_value=tomorrow):
            self.assertIsNone(self.account.refusal())  # a new day starts at $0
            self.assertEqual(self.account.day()["cost_usd"], 0.0)

    def test_local_models_cost_nothing_and_are_capped_by_calls(self):
        self.account.set_limits(0.0, 2)  # no money at all: a local model still works
        self.paid.provider = "openrouter"
        self.assertRegex(self.account.refusal(self.paid), "budget of")
        self.account.charge(self.local, {"input_tokens": 10})
        self.assertIsNone(self.account.refusal(self.local))
        self.account.charge(self.local, {"input_tokens": 10})
        self.assertRegex(self.account.refusal(self.local), "2 model calls without a price are used up")
        self.assertEqual(self.account.day()["cost_usd"], 0.0)
        self.assertIn("2 unpriced calls (limit reached)", spending.line(self.account.day()))

    def test_a_thought_is_refused_without_calling_the_model(self):
        self.account.set_limits(1.0, 500)
        chat = Counting(["one", "two"], usage={"cost_usd": 1.2}, provider="openrouter")
        first = Thought("main", "start", chat, "", [], timeout=10, account=self.account, source={"kind": "task"})
        self.assertEqual(first.complete().text, "one")
        second = Thought("main", "start", chat, "", [], timeout=10, account=self.account)
        with self.assertRaises(SpendingLimit):
            second.complete()
        self.assertEqual(chat.asked, 1)
        self.assertEqual(self.account.day()["cost_usd"], 1.2)


class ConversationTests(TestCase):
    """A real conversation of the session host, charged to an identity's account."""

    def test_at_the_limit_the_turn_ends_and_the_program_goes_on(self):
        from harness import settings
        from harness.host.tasks import TaskHost, TaskServer
        program = ("<python>\nuntil(None)\nimport time\nfor tick in range(20):\n    print('tick', tick, flush=True)\n"
                   "    time.sleep(0.25)\n</python>")
        chat = Counting([program, "never asked"])
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(os.environ, {settings.KEY: "test-no-network", "HARNESS_HOME": str(Path(root) / "home")}):
            account = Account(Path(root) / "home" / "agents" / "work" / "usage")
            account.set_limits(2.0, 1)  # one call without a price today
            app = TaskHost(Path(root) / "host", chat=chat, verifier=ScriptedChat([]))
            app.settings.update({"learning": {"mode": "frozen"}, "limits": {"agent_depth": 0}})
            server = TaskServer(("127.0.0.1", 0), app, token="test")
            try:
                run = app.start(server, "Count to eight", workspace="none",
                                runtime={"identity": "work", "account": str(account.directory)})
                task = server.conversations[run]
                path = task.directory / "events.jsonl"

                def records():
                    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] \
                        if path.exists() else []
                deadline = time.monotonic() + 60
                while not any(row["event"] == "turn_result" for row in records()) and time.monotonic() < deadline:
                    time.sleep(0.05)
                ended = next(row for row in records() if row["event"] == "turn_result")
                while time.monotonic() < deadline and not any(row["event"] == "cell" for row in records()):
                    time.sleep(0.05)
                later = records()
                spent = account.day()
                meta = json.loads((task.directory / "meta.json").read_text(encoding="utf-8"))
                with self.assertRaisesRegex(ValueError, "under HARNESS_HOME"):
                    app.start(server, "Elsewhere", workspace="none", runtime={"account": str(Path(root) / "x")})
            finally:
                for conversation in server.conversations.values():
                    conversation.close()
                for thread in list(app._threads.values()):
                    thread.join(15)
                app.close()
                server.server_close()
        self.assertEqual(ended["reason"], "spending")
        self.assertEqual(chat.asked, 1)  # the model was not asked again
        self.assertTrue(any(row["event"] == "spending_limit" for row in later))
        cell = next(row for row in later if row["event"] == "cell")
        self.assertEqual(cell["result"]["status"], "ok")
        self.assertIn("tick 19", cell["result"]["stdout"])
        # The turn ended while the program ran; the program went on to its end after it.
        self.assertGreater(cell["seq"], ended["seq"])
        self.assertGreater(cell["time"], ended["time"] + 2)
        self.assertEqual(meta["identity"], "work")
        self.assertEqual(spent["calls"], 1)
        self.assertEqual(spent["by_source"][0]["kind"], "task")


class DialogueTests(TestCase):
    def test_the_dialogue_stops_calling_the_model_at_the_limit(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(os.environ, {"HARNESS_DATA": str(Path(root) / "data")}):
            identity = state.create("work", root=Path(root) / "agents")
            identity.set_setting("daily_budget", 0.5)
            self.assertEqual(identity.settings()["daily_budget"], 0.5)
            chat = Counting([json.dumps({"action": "reply", "text": "hi"})] * 3, usage={"cost_usd": 0.6},
                            provider="openrouter")
            session = Session(identity, chat, tasks=None)
            self.assertEqual(session.turn("hello"), "hi")  # the call that crosses the limit finishes
            with self.assertRaisesRegex(SpendingLimit, r"budget of \$0.50 is used up"):
                session.turn("again")
            self.assertEqual(chat.asked, 1)
            events = [json.loads(line) for line in (session.directory / "events.jsonl").read_text(
                encoding="utf-8").splitlines()]
            self.assertEqual([row["event"] for row in events if row["event"] in ("user", "spending_limit")],
                             ["user", "user", "spending_limit"])
            account = identity.account()
            self.assertEqual(account.day()["by_source"], [{"kind": "chat", "id": session.id, "whose": "owner", "cost_usd": 0.6,
                                                           "calls": 1}])
            account.raise_today(2.0)
            self.assertEqual(Session(identity, chat, tasks=None, session=session.id).turn("now?"), "hi")
            identity.set_setting("daily_budget", None)
            self.assertEqual(identity.settings()["daily_budget"], 2.0)  # the global default again

    def test_a_local_model_is_capped_by_calls(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(os.environ, {"HARNESS_DATA": str(Path(root) / "data")}):
            identity = state.create("work", root=Path(root) / "agents")
            identity.set_setting("daily_calls", 2)
            chat = Counting([json.dumps({"action": "reply", "text": "ok"})] * 3)
            chat.base_url = "http://localhost:11434/v1"
            session = Session(identity, chat, tasks=None)
            session.turn("one")
            session.turn("two")
            with self.assertRaisesRegex(SpendingLimit, "2 model calls without a price"):
                session.turn("three")
            self.assertEqual((chat.asked, identity.account().day()["cost_usd"]), (2, 0.0))
