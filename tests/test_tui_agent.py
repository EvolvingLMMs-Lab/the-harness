"""The terminal chat on an identity's chats: its conversation is the identity's main
conversation through the host (say, then the record polled), notices about its other chats are
"—" lines that are never written into the main conversation's record, approvals are answered
through the host, and /calendar, /library (the tree browsed like folders) and /usage draw what
the routes give; harness host and harness library tree in the core command line."""
import asyncio
import contextlib
import io
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import helpers  # noqa: F401
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from harness.host.client import RemoteError
from harness.tui import agent as life_view
from harness.tui import views
from test_agent_frontends import Base
from test_agent_life import wait_for
from test_tui_recovery import chat as bare_chat


class Routes:
    """The test host as the session host answers over HTTP: a route its agent package does
    not have is refused with "no such route" (the chat then goes on without it)."""

    def __init__(self, host):
        self.host = host

    def __getattr__(self, name):
        return getattr(self.host, name)

    def get(self, path):
        try:
            return self.host.get(path)
        except KeyError:
            raise RemoteError("no such route") from None

    def post(self, path, body, timeout=None):
        try:
            return self.host.post(path, body, timeout)
        except KeyError:
            raise RemoteError("no such route") from None


class Following:
    """An AgentChat's records, read on a thread of their own until stopped."""

    def __init__(self, conversation):
        self.records, self.stop = [], threading.Event()
        self.thread = threading.Thread(target=self._read, args=(conversation,), daemon=True)
        self.thread.start()

    def _read(self, conversation):
        for record in conversation.records(self.stop):
            self.records.append(record)

    def close(self):
        self.stop.set()
        self.thread.join(5)


class AgentChatTests(Base):
    def setUp(self):
        super().setUp()
        mock.patch.object(life_view, "LOOK", 0.1).start()
        mock.patch.object(life_view, "POLL", 0.05).start()
        self.followers = []

    def tearDown(self):
        for following in self.followers:
            following.close()  # before the lives close and their folder goes
        super().tearDown()

    def follow(self, life):
        conversation = life_view.AgentChat(Routes(self.host), {"id": life.identity.id, "name": life.identity.name})
        following = Following(conversation)
        self.followers.append(following)
        return conversation, following

    def test_the_chat_is_the_main_conversation_and_others_are_notices_only(self):
        life = self.life([{"action": "reply", "text": "Hello, owner."}])
        conversation, following = self.follow(life)
        wait_for(lambda: conversation.life)
        conversation.send("hi")
        reply = wait_for(lambda: [r for r in following.records if r.get("event") == "reply"])
        self.assertEqual(reply[0]["text"], "Hello, owner.")
        self.assertTrue(any(r.get("event") == "user" and r["text"] == "hi" for r in following.records))
        # Something happens in another chat of the identity: a notice, printed only.
        life.chats.ensure("place-qq-group-1", kind="place", title="QQ · Weekend hike", place="qq")
        time.sleep(0.2)
        life.chats.record("place-qq-group-1", "outcome", verb="qq.send", end="refused",
                          reason="only the owner may have it touch files")
        found = wait_for(lambda: [r for r in following.records if r.get("event") == "notice"])
        line = life_view.lines(found[-1])[0]
        self.assertEqual(line[0], "— QQ · Weekend hike: qq.send refused (only the owner may have it touch files)")
        self.assertEqual([r for r in life.chats.read("main") if r["event"] in ("notice", "agent_state")], [])
        posted = [call[1] for call in self.host.calls if call[0] == "POST"]
        self.assertEqual(set(posted), {"/api/agent/opened", "/api/agent/say"})

    def test_an_approval_is_answered_through_the_host(self):
        life = self.life()
        conversation, following = self.follow(life)
        answer = {}
        threading.Thread(target=lambda: answer.update(state=life.approvals.ask("main", "git push origin main",
                                                                                 verb="send")), daemon=True).start()
        card = wait_for(lambda: [r for r in following.records if r.get("event") == "approval"
                                 and r.get("state") == "waiting"])[0]
        self.assertIn(card["code"], conversation.pending)
        # The terminal chat asks; Enter on "Yes" answers it through the host.
        found = bare_chat(conversation=conversation, identity={"id": "default", "name": "default"})
        printed = []
        found._print = lambda *lines: printed.extend(lines)
        found._agent_show(card)
        self.assertEqual(found.ask["request_id"], card["code"])
        self.assertEqual([o[1] for o in found.ask["options"]], ["Yes", "No"])
        self.assertIn("git push origin main", found.ask["what"])
        self.assertIn('a step of the kind "send"', found.ask["why"])
        found._answer(0)
        function, *args = found.sent[-1]
        function(*args)
        wait_for(lambda: answer.get("state"))
        self.assertEqual(answer["state"][0], "approved")
        with self.assertRaises(ValueError):
            conversation.confirm(True)  # nothing waits any more

    def test_the_chat_prints_records_and_skips_its_own_echo(self):
        conversation = SimpleNamespace(pending={}, title="Main conversation", life={})
        found = bare_chat(conversation=conversation, echoed="hello", identity={"id": "default", "name": "default"})
        printed = []
        found._print = lambda *lines: printed.extend(str(getattr(line, "plain", line)) for line in lines)
        found._agent_show({"event": "user", "text": "hello", "agent_chat": "main"})
        self.assertEqual(printed, [])
        found._agent_show({"event": "turn_started", "agent_chat": "main"})
        self.assertEqual(found.status, "RUNNING")
        found._agent_show({"event": "outcome", "verb": "git push", "end": "done", "agent_chat": "main"})
        found._agent_show({"event": "learned", "kind": "memory", "name": "pull requests in English",
                           "agent_chat": "main"})
        found._agent_show({"event": "notice", "text": "QQ · Weekend hike 14 new · /sessions", "agent_chat": "main"})
        self.assertEqual(printed, ["  ✓ git push done", "＋ noted  pull requests in English · private",
                                   "— QQ · Weekend hike 14 new · /sessions"])


class RenderTests(unittest.TestCase):
    def test_the_week_has_days_and_what_is_next(self):
        now = time.time()
        week = {"entries": [
            {"id": "log-0", "title": "spreadsheet", "start": now - 3600, "end": now - 3000, "kind": "turn", "who": "own",
             "outcome": "refused", "refused": True, "note": "it chose to wait"},
            {"id": "log-1", "title": "asleep", "start": now - 7200, "end": now - 3700, "kind": "asleep", "who": "tree"},
            {"id": "c1", "title": "weekly report", "start": now + 86400, "end": now + 88200, "kind": "task",
             "by": "owner", "planned": True}]}
        rows, headers, entries = life_view.calendar_rows(week)
        self.assertEqual([rows[i] for i in headers][-1], "next")
        self.assertRegex(rows[entries.index(week["entries"][0])], r"⊘ +own +spreadsheet +.*safety refused")
        self.assertRegex(rows[entries.index(week["entries"][1])], r"☾ +asleep")
        self.assertRegex(rows[-1], r"· +yours +weekly report")

    def test_the_tree_level_shows_branches_as_folders_and_the_lit_path(self):
        rows = life_view.tree_rows({"path": [], "nodes": [
            {"name": "named", "about": "named or aimed at it → wake it", "evidence": "builtin", "children": 0},
            {"name": "desktop", "about": "working on the desktop", "children": 5, "lit": True}]})
        self.assertRegex(rows[0], r"^  1\.   named or aimed at it → wake it +built in$")
        self.assertRegex(rows[1], r"^• 2\. ▸ working on the desktop +5 nodes$")

    def test_usage_by_chat_and_by_task(self):
        out = life_view.usage_lines({"today": {"date": "2026-11-25", "cost_usd": 1.86, "daily_budget": 2.0,
                                               "reserve": 0.5, "own_usd": 0.71, "by_source": [
                                                   {"kind": "chat", "id": "place-x", "cost_usd": 0.92, "calls": 4},
                                                   {"kind": "task", "id": "run-1", "cost_usd": 0.33, "calls": 2}]},
                                     "week": [{"date": "2026-11-25", "cost_usd": 1.86, "calls": 6}]},
                                    {"place-x": "project · the-harness"})
        text = [line for line, _ in out]
        self.assertIn("$1.86 / $2.00", text[2])
        self.assertIn("by chat", text)
        self.assertIn("by task", text)
        self.assertTrue(any(line.startswith("project · the-harness") and "$0.92" in line for line in text))
        self.assertIn("this week", text)

    def test_spending_in_the_status_line(self):
        self.assertEqual(life_view.spend({"spent_today": 0.71, "budget": 2}), "$0.71 today / $2.00")


class BrowseTests(unittest.IsolatedAsyncioTestCase):
    async def browse(self, typed, **options):
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            answer = asyncio.ensure_future(views.browse("Library", ["skills", "a", "b", "tree", "c"], **options))
            await asyncio.sleep(0.1)
            pipe.send_text(typed)
            return await asyncio.wait_for(answer, 5)

    async def test_group_names_are_not_picked_and_keys_come_back(self):
        self.assertEqual(await self.browse("\x1b[B\x1b[B\r", headers=[0, 3]), ("enter", 4))
        self.assertEqual(await self.browse("u", headers=[0, 3], keys="u"), ("u", 1))
        self.assertEqual(await self.browse("\x7f", headers=[0, 3], back=True), ("left", None))


class CoreCommandTests(unittest.TestCase):
    def test_harness_host_shows_the_identities_it_holds(self):
        from harness import cli

        class Host:
            url = "http://127.0.0.1:8780"

            def info(self):
                return {"pid": 4120, "version": "0.87.0", "started": time.time() - 60}

            def get(self, path):
                if path == "/api/agent/identities":
                    return [{"id": "default", "name": "Yu"}, {"id": "work", "name": "Work assistant"}]
                if path.startswith("/api/agent/life"):
                    return {"places": [1, 2, 3] if "default" in path else [1, 2], "busy": ["main"] if "default" in path else []}
                return {"chats": [{}, {}, {}]}

        lines = cli.host_lines(Host())
        self.assertIn("pid 4120", lines[0])
        self.assertEqual(lines[1], "  identities  default Yu (3 places) · work Work assistant (2 places)")
        self.assertEqual(lines[2], "  chats       6 · 1 working")
        out = io.StringIO()
        with mock.patch("harness.host.Host.connect", return_value=None), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["host"]), 0)
        self.assertIn("no session host runs", out.getvalue())

    def test_harness_library_tree_is_the_identitys(self):
        from harness import cli

        given = []
        with mock.patch("harness.extensions.require", return_value=lambda words: given.append(words) or 0), \
                mock.patch("harness.packages.activate"):
            self.assertEqual(cli.main(["library", "tree", "desktop/spreadsheet", "--identity", "work"]), 0)
        self.assertEqual(given, [["tree", "desktop/spreadsheet", "--identity", "work"]])


if __name__ == "__main__":
    unittest.main()
