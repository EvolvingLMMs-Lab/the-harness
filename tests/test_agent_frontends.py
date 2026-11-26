"""The four frontends do the same thing: harness calendar / channels / library, harness.sdk.Agent
and the terminal chat (/calendar, /channels, /library, /usage, /sessions on the identity's
chats) all read and change one life through the host's /api/agent routes. A host in this
process serves the agent package's route handlers to them; a QQ account is the qq package's
space over the OneBot simulator."""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest import TestCase, mock
from urllib.parse import parse_qs, urlsplit

import helpers  # noqa: F401  (source paths)

from test_agent_life import NoTasks, Recorder, finish_loop, wait_for

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "qq"))


class FakeHost:
    """The session host's /api/agent routes, served in this process by the agent package's
    handlers (JSON both ways, as over HTTP); every call is kept."""

    url = "http://127.0.0.1:0"

    def __init__(self, life):
        self.life = life
        self.server = SimpleNamespace(background={"agent": SimpleNamespace(life=lambda name: life,
                                                                           lives={life.identity.id: life})})
        self.calls = []

    def _route(self, path):
        from harness_agent.host import api

        parts = urlsplit(path)
        return api[parts.path.rsplit("/", 1)[1]], parts

    def get(self, path):
        handler, parts = self._route(path)
        self.calls.append(("GET", parts.path, parts.query))
        return json.loads(json.dumps(handler(self.server, parse_qs(parts.query))))

    def post(self, path, body, timeout=None):
        handler, parts = self._route(path)
        self.calls.append(("POST", parts.path, body))
        return json.loads(json.dumps(handler(self.server, json.loads(json.dumps(body)))))


def run(main, *words):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = main(list(words))
    return status, out.getvalue(), err.getvalue()


class Base(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = mock.patch.dict(os.environ, {"HARNESS_HOME": self.folder.name, "HARNESS_DATA": self.folder.name})
        self.env.start()
        self.lives = []

    def tearDown(self):
        for life in self.lives:
            life.close()
        mock.patch.stopall()
        self.env.stop()
        self.folder.cleanup()

    def life(self, replies=()):
        from harness_agent.life import Life
        from harness_agent.state import Identity

        life = Life(Identity("default"), model=lambda: Recorder(list(replies)), tasks=lambda row: NoTasks())
        life.start()
        self.lives.append(life)
        self.host = FakeHost(life)
        mock.patch("harness_agent.frontends.connect", lambda: self.host).start()
        return life


class FrontendTests(Base):
    def test_calendar_is_the_same_in_the_command_line_and_python(self):
        from harness_agent.frontends import calendar_main
        from harness_agent.sdk import Agent

        life = self.life()
        at = time.strftime("%Y-%m-%dT%H:%M", time.localtime(time.time() + 3600))
        status, out, _ = run(calendar_main, "add", "weekly report", "--at", at, "--kind", "goal")
        self.assertEqual(status, 0)
        self.assertIn("weekly report", out)
        entry = life.calendar.entries[0]
        self.assertEqual((entry["by"], entry["kind"]), ("owner", "goal"))
        # What it did is on the same week: a turn of its own that the safety layer refused.
        life.calendar.log(kind="turn", who="own", title="tidy the spreadsheet", outcome="refused", refused=True,
                          start=time.time() - 600, end=time.time() - 300)
        life.calendar.log(kind="asleep", title="asleep", who="tree", start=time.time() - 7200, end=time.time() - 3600)
        status, out, _ = run(calendar_main, "list")
        self.assertIn("weekly report", out)
        self.assertIn(f"[{entry['id']}]", out)
        self.assertRegex(out, r"⊘ +own +tidy the spreadsheet")
        self.assertIn("asleep", out)
        self.assertIn("kept for you", out)
        week = Agent().calendar()
        self.assertEqual({e["title"] for e in week["entries"]}, {"weekly report", "tidy the spreadsheet", "asleep"})
        later = time.strftime("%Y-%m-%dT%H:%M", time.localtime(time.time() + 7200))
        Agent().calendar_move(entry["id"], later)
        self.assertEqual(time.strftime("%Y-%m-%dT%H:%M", time.localtime(life.calendar.entries[0]["at"])), later)
        status, out, _ = run(calendar_main, "pause")
        self.assertEqual(status, 0)
        self.assertTrue(life.paused_own)
        self.assertTrue(Agent().calendar()["paused_own"])
        Agent().pause_own(False)
        self.assertFalse(life.paused_own)
        status, out, _ = run(calendar_main, "remove", entry["id"])
        self.assertEqual(life.calendar.entries, [])
        status, _, err = run(calendar_main, "remove", "nothing")
        self.assertEqual(status, 2)
        self.assertIn("no calendar entry", err)

    def test_the_tree_is_browsed_one_level_at_a_time_like_folders(self):
        from harness_agent.frontends import library_main
        from harness_agent.sdk import Agent

        life = self.life()
        life.tree.add("desktop", {"fact": "working_in", "has": "desktop"}, None, about="working on the desktop")
        life.tree.add("spreadsheet", {"fact": "owner_active", "is": False}, None, under="desktop",
                      about="in a spreadsheet")
        life.tree.add("edit mode", {"fact": "battery", "below": 20}, {"nothing": True}, under="spreadsheet",
                      about="a cell left in edit mode → press Esc", source="owner")
        status, out, _ = run(library_main, "tree")
        self.assertEqual(status, 0)
        self.assertIn("tree › root", out)
        self.assertIn("built in", out)  # the three built-in nodes
        self.assertRegex(out, r"▸ working on the desktop +2 nodes")
        status, out, _ = run(library_main, "tree", "desktop/spreadsheet")
        self.assertIn("tree › root › working on the desktop › in a spreadsheet", out)
        self.assertIn("a cell left in edit mode", out)
        self.assertIn("added by owner", out)
        level = Agent().reactions("desktop")
        self.assertEqual(level["path"], ["desktop"])
        self.assertEqual([(n["name"], n["children"]) for n in level["nodes"]], [("spreadsheet", 1)])
        self.assertEqual(Agent().reactions(["desktop", "spreadsheet"])["nodes"][0]["name"], "edit mode")
        status, _, err = run(library_main, "tree", "nowhere")
        self.assertNotEqual(status, 0)
        self.assertIn("no node", err)

    def test_skills_and_memory_with_scope_and_source(self):
        from harness_agent.frontends import library_main
        from harness_agent.sdk import Agent

        life = self.life()
        identity = life.identity
        identity.remember("pr-english", "Pull requests are always in English", source="main",
                          expected=identity.memory()["revision"])
        identity.remember("meeting", "This group meets at 7:30", source="qq", scope="chat", chat="place-qq-group-1",
                          expected=identity.memory()["revision"])
        status, out, _ = run(library_main, "memory")
        self.assertEqual(status, 0)
        self.assertRegex(out, r"Pull requests are always in English +private")
        self.assertRegex(out, r"This group meets at 7:30 +this chat +place-qq-group-1")
        self.assertEqual(set(Agent().memory()["entries"]), {"pr-english", "meeting"})
        status, out, _ = run(library_main, "skills")
        self.assertIn("no skills yet", out)
        learned = Agent().learned()
        self.assertEqual((learned["skills"], set(learned["memory"])), ([], {"pr-english", "meeting"}))

    def test_chats_and_usage_come_from_the_host(self):
        from harness_agent.sdk import Agent

        life = self.life([{"action": "reply", "text": "hello"}])
        life.say("main", "hi", wait=True)
        chats = Agent().chats()
        self.assertEqual(chats[0]["chat"], "main")
        usage = Agent().usage(week=True)
        self.assertIn("by_source", usage["today"])
        self.assertEqual(len(usage["week"]), 7)
        self.assertTrue(any(call[1] == "/api/agent/chats" for call in self.host.calls))


class QQAccount:
    """The OneBot simulator and the qq package's space on a loop of their own, keeping its
    settings in `config` (the channel's file in the identity folder)."""

    def __init__(self, config):
        from harness_qq import space as qq
        from harness_qq.simulator import Simulator

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        holder = {}

        async def start():
            holder["sim"] = Simulator()
            await holder["sim"].start()
            holder["space"] = qq.QQSpace(holder["sim"].address, settings=qq.Settings(config))
            ready = asyncio.Event()
            self.loop.create_task(holder["space"].serve("ws://127.0.0.1:0",
                                                        lambda a: (holder.update(address=a), ready.set())))
            await ready.wait()
            for _ in range(100):
                if holder["space"].online:
                    break
                await asyncio.sleep(0.05)

        asyncio.run_coroutine_threadsafe(start(), self.loop).result(20)
        self.sim, self.address, self.space = holder["sim"], holder["address"], holder["space"]

    def private(self, user, text):
        self.loop.call_soon_threadsafe(lambda: self.sim.private_message(user, text))

    def close(self):
        finish_loop(self.loop, self.thread, self.space.space.close, self.sim.close)


class ChannelTests(Base):
    def test_a_channel_is_added_with_identity_and_policy_first_then_groups_owner_and_pairing(self):
        from harness_agent.frontends import channels_main
        from harness_agent.sdk import Agent
        from harness_agent.state import Identity

        config = Identity("default").directory / "channels" / "qq.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"identity": "default", "dm": "pairing"}), encoding="utf-8")
        account = QQAccount(config)
        self.addCleanup(account.close)
        life = self.life()
        # The policy first; the account logs in through its OneBot implementation (here, at once).
        status, out, _ = run(channels_main, "add", "qq", "--dm", "pairing", "--groups", "mention",
                             "--address", account.address, "--no-wait")
        self.assertEqual(status, 0, out)
        wait_for(lambda: life.places["qq"].online)
        row = wait_for(lambda: next((r for r in Agent().channels() if r["online"]), None))
        self.assertEqual((row["account"], row["dm"], row["entered"]), ("qq", "pairing", {}))
        # The groups the account is in, joined none by default; the owner ticks one.
        listed = self.host.get("/api/agent/channels?identity=default&account=qq")["channels"][0]["groups"]
        self.assertEqual({g["id"] for g in listed}, {"123", "456"})
        Agent().channel_groups("qq", ["456"])
        self.assertEqual(Agent().channels()[0]["entered"], {"456": "mention"})
        # Binding the owner: a one-time code shown in the main conversation, sent from their own account.
        code = Agent().channel_owner_code("qq")
        self.assertTrue([r for r in life.chats.read("main") if r["event"] == "channel" and r.get("owner_code") == code])
        account.private(555, code)
        wait_for(lambda: Agent().channels()[0]["owner"] == "555")
        # A stranger gets a pairing code; the owner approves it on the command line.
        account.private(777, "hello?")
        request = wait_for(lambda: (Agent().channels()[0]["pending"] or [None])[0])
        self.assertEqual(request["user"], "777")
        status, out, _ = run(channels_main, "pair")
        self.assertIn(request["code"], out)
        status, out, err = run(channels_main, "pair", "approve", "qq", request["code"])
        self.assertEqual(status, 0, err)
        self.assertIn("paired qq 777", out)
        self.assertEqual(Agent().channels()[0]["paired"], ["777"])
        status, out, _ = run(channels_main, "list")
        self.assertRegex(out, r"qq +online +pairing +1 entered")
        self.assertIn("bound QQ 555", out)
        status, out, _ = run(channels_main, "remove", "qq")
        self.assertEqual((status, Agent().channels()), (0, []))
        self.assertNotIn("qq", life.places)

    def test_owner_verbs_need_a_connected_channel(self):
        from harness_agent.frontends import channels_main

        self.life()
        status, _, err = run(channels_main, "pair", "approve", "qq", "ABC")
        self.assertEqual(status, 2)
        self.assertIn("no channel 'qq'", err)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            channels_main(["add", "irc", "--no-wait"])  # only the channels there are
