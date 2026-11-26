"""The full-screen views of the terminal chat on what the host's routes answer: the calendar by
day, week and month with who did what; the usage with plan calls as calls and an empty
stretch said; the connectors in four classes, a channel drawn from its package's declaration
alone; the library's groups; the settings by their titles, pages and choice names; what
deleting an identity takes with it. No channel is named anywhere in the terminal's code."""
import asyncio
from pathlib import Path
import re
import time
import unittest
from unittest import mock

import helpers  # noqa: F401

from harness.tui import agent as life_view
from harness.tui import calendar, connectors, library, settings as tui_settings, usage, views


class Client:
    """An identity's routes answered from a table; what was posted is kept."""

    identity = "default"

    def __init__(self, answers=None):
        self.answers, self.posted, self.asked = answers or {}, [], []

    def get(self, name, **query):
        self.asked.append(query)
        found = self.answers[name]
        return found(query) if callable(found) else found

    def post(self, name, body=None):
        self.posted.append((name, body))
        found = self.answers.get("post:" + name, {})
        return found(body) if callable(found) else found


def answered(*answers):
    """views.choose / ask / confirm that give these answers in turn (None once they run out)."""
    left = list(answers)

    async def answer(*args, **options):
        return left.pop(0) if left else None

    return answer


class CalendarTests(unittest.TestCase):
    NOW = time.mktime((2026, 11, 26, 12, 0, 0, 0, 0, -1))   # a Thursday

    def at(self, day, hour, minute=0):
        return time.mktime((2026, 11, day, hour, minute, 0, 0, 0, -1))

    def test_the_stretches_of_a_day_a_week_and_a_month(self):
        day = calendar.span("day", self.NOW)
        self.assertEqual((time.localtime(day[0])[:4], round((day[1] - day[0]) / 3600)), ((2026, 11, 26, 0), 24))
        week = calendar.span("week", self.NOW)
        self.assertEqual((time.localtime(week[0])[:3], time.localtime(week[1])[:3]), ((2026, 11, 23), (2026, 11, 30)))
        month = calendar.span("month", self.NOW)
        self.assertEqual((time.localtime(month[0])[:3], time.localtime(month[1])[:3]), ((2026, 11, 1), (2026, 12, 1)))
        self.assertEqual(time.localtime(calendar.span("month", calendar.moved("month", self.NOW, 1))[0])[:3], (2026, 12, 1))
        self.assertEqual(time.localtime(calendar.span("week", calendar.moved("week", self.NOW, -1))[0])[:3], (2026, 11, 16))

    def entries(self):
        return [{"id": "log-1", "title": "git push origin main", "start": self.at(26, 9), "end": self.at(26, 9, 5),
                 "kind": "task", "who": "own", "outcome": "refused", "refused": True},
                {"id": "log-2", "title": "battery low", "start": self.at(26, 10), "end": self.at(26, 10), "kind": "reaction",
                 "who": "tree", "outcome": "done", "note": "paused the download"},
                {"id": "log-3", "title": "asleep", "start": self.at(26, 13), "end": self.at(26, 15), "kind": "asleep"},
                {"id": "c1", "title": "weekly report", "start": self.at(27, 9), "end": self.at(27, 9, 30), "kind": "goal",
                 "planned": True, "by": "owner", "has_end": True, "repeat": "weekly"}]

    def test_a_week_has_each_days_name_over_who_did_what_and_how_it_ended(self):
        start, end = calendar.span("week", self.NOW)
        rows, headers, items = calendar.rows(self.entries(), "week", start, end, now=self.NOW)
        self.assertEqual([rows[index] for index in headers], ["Thu 11-26 · today", "Fri 11-27"])
        text = "\n".join(rows)
        self.assertRegex(text, r"09:00 +⊘ +its own +git push origin main +safety refused")
        self.assertRegex(text, r"10:00 +✓ +tree +battery low +paused the download")
        self.assertRegex(text, r"13:00–15:00 +☾ +asleep +asleep +until 15:00")
        self.assertRegex(text, r"09:00–09:30 +· +yours +weekly report +goal · weekly")
        self.assertEqual(items[-1]["id"], "c1")

    def test_a_month_has_a_row_for_every_day(self):
        start, end = calendar.span("month", self.NOW)
        rows, headers, items = calendar.rows(self.entries(), "month", start, end, now=self.NOW)
        self.assertEqual((len(rows), headers), (30, []))
        self.assertRegex(rows[25], r"Thu 11-26 · today +1 done · 1 refused · asleep a while")
        self.assertRegex(rows[26], r"Fri 11-27 +1 planned +weekly report")
        self.assertEqual(items[26][0], "day")

    def test_an_entry_put_in_the_past_is_missed_not_done_refused_or_failed(self):
        missed = {"id": "c9", "title": "call the bank", "start": self.at(25, 9), "end": self.at(25, 9, 30), "kind": "task",
                  "planned": True, "by": "owner", "missed": True, "outcome": "missed"}
        self.assertRegex(calendar.entry_row(missed), r"09:00 +◌ +yours +call the bank +missed: put at a time already past")
        start, end = calendar.span("month", self.NOW)
        rows, _, _ = calendar.rows([missed, *self.entries()], "month", start, end, now=self.NOW)
        self.assertRegex(rows[24], r"Wed 11-25 +1 missed")
        self.assertNotIn("planned", rows[24])
        self.assertIn("never due", calendar.details(missed))

    def test_an_empty_stretch_has_no_rows(self):
        self.assertEqual(calendar.rows([], "week", *calendar.span("week", self.NOW)), ([], [], []))


class CalendarViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_edit_remove_and_undo_go_through_the_calendar_route(self):
        now = time.time()
        entry = {"id": "c1", "title": "weekly report", "start": now + 600, "end": now + 2400, "kind": "task", "planned": True,
                 "by": "owner", "has_end": True}
        client = Client({"calendar": {"entries": [entry], "paused_own": False}, "usage": {"today": {}},
                         "post:calendar": lambda body: {"result": {"id": "c2"}} if body["action"] == "add" else {"result": {}}})
        notes = []
        keys = iter([("c", 1), ("e", 1), ("x", 1), ("z", 1), ("o", 1), ("/", 1), None, None])

        async def browse(title, rows, **options):
            return next(keys)

        with mock.patch.object(views, "browse", side_effect=browse), \
                mock.patch.object(views, "ask", side_effect=answered("standup", "09:30", "new title", "report")), \
                mock.patch.object(views, "choose", side_effect=answered(1, 0)):
            await calendar.calendar_view(client, notes.append)
        bodies = [body for _, body in client.posted]
        self.assertEqual(bodies[0], {"action": "add", "title": "standup", "at": "09:30", "kind": "goal"})
        self.assertEqual(bodies[1], {"action": "update", "id": "c1", "title": "new title"})
        self.assertEqual(bodies[2], {"action": "remove", "id": "c1"})
        self.assertEqual(bodies[3], {"action": "restore", "id": "c1"})   # z puts back what was removed last
        self.assertEqual(bodies[4], {"action": "pause_own"})
        self.assertTrue(any("z in /calendar puts it back" in note for note in notes))
        self.assertIn({"q": "report"}, client.asked)   # / asks the host for the entries with the text


class UsageTests(unittest.TestCase):
    TODAY = {"date": "2026-11-26", "cost_usd": 0.5, "daily_budget": 2.0, "reserve": 0.4, "left_usd": 1.5, "own_usd": 0.1,
             "unpriced_calls": 3, "daily_calls": 200, "raised": False}

    def test_a_stretch_without_a_call_says_so(self):
        text = "\n".join(usage.rows({"today": self.TODAY, "days": [], "start": "2026-11-20", "end": "2026-11-26"}, "Last 7 days"))
        self.assertIn("Today's limit   $0.50 of $2.00", text)
        self.assertIn("$1.50 left", text)
        self.assertIn("No model calls in this stretch yet.", text)
        self.assertNotIn("By day", text)

    def test_the_numbers_of_the_route_by_day_chat_task_and_model(self):
        answer = {"today": self.TODAY, "start": "2026-11-20", "end": "2026-11-26", "cost_usd": 0.03, "plan_usd": 0.4,
                  "seconds": 12.5, "calls": {"total": 4, "priced": 2, "plan": 1, "unpriced": 1},
                  "days": [{"date": "2026-11-25", "cost_usd": 0.01, "calls": 1}, {"date": "2026-11-26", "cost_usd": 0.02, "calls": 3}],
                  "by_chat": [{"chat": "main", "title": "Main conversation", "there": True, "cost_usd": 0.02, "calls": 2},
                              {"chat": "gone", "title": "Old chat", "there": False, "cost_usd": 0.0, "calls": 1}],
                  "by_task": [{"kind": "learning", "id": "review", "title": "", "cost_usd": 0.01, "calls": 1}],
                  "by_model": [{"model": "a-model", "basis": "reported", "cost_usd": 0.03, "calls": 2},
                               {"model": "an agent's plan", "basis": "plan", "cost_usd": 0, "plan_usd": 0.4, "calls": 1}]}
        text = "\n".join(usage.rows(answer, "Last 7 days"))
        self.assertIn("$0.03 · 4 calls (2 with a price · 1 under your own plan · 1 without a price)", text)
        self.assertIn("under your plan: 1 call, not charged here (listed at $0.40)", text)   # a call, never invented dollars
        self.assertRegex(text, r"2026-11-26 +█+ +\$0\.02 +3 calls")
        self.assertRegex(text, r"Old chat \(deleted\)")
        self.assertRegex(text, r"learning: review")
        self.assertRegex(text, r"an agent's plan +█* +\$0\.00 +1 call +under your plan")


CHANNELS = {"identity": "default", "from": {"en": "Channels come from channel packages: harness install NAME."},
            "kinds": [{"kind": "example", "package": "example-chat", "name": {"en": "Example Chat"}, "about": {"en": "a test"},
                       "steps": ["policies", "owner"],
                       "fields": [{"id": "dm", "kind": "choice", "label": {"en": "Strangers' private messages"},
                                   "default": "pairing", "choices": [{"value": "pairing", "en": "Ask me first"},
                                                                     {"value": "open", "en": "Anyone"}]},
                                  {"id": "server", "kind": "text", "label": {"en": "Server address"}, "required": True},
                                  {"id": "quiet", "kind": "bool", "label": {"en": "Quiet at night"}, "default": False},
                                  {"id": "token", "kind": "secret", "label": {"en": "Token"}}],
                       "owner": {"text": {"en": "Send the code to it."}}, "groups": None}],
            "channels": [{"account": "example-1", "kind": "example", "title": "My account", "state": "waiting_login",
                          "values": {"dm": "pairing"}, "owner": None,
                          "pending": [{"code": "K7", "user": "u9", "name": "Sam", "expires": 0}]}]}


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    def test_the_four_classes_each_with_its_rows_and_a_way_to_add(self):
        rows, headers, items = connectors.listing({
            "channels": CHANNELS, "mcp": {"servers": [{"name": "files", "transport": "stdio", "target": "node server.js",
                                                       "enabled": True}]},
            "acp": {"agents": [{"id": "acp:one", "name": "One", "source": "found", "state": "connected", "signed_in": False,
                                "sign_in": "run one login"}]},
            "skills": {"sources": [{"id": "s1", "from": "github:someone/skills", "kind": "git", "skills": [{"name": "tidy"}]}],
                       "shared": [{"name": "common", "entries": 4}]}})
        self.assertEqual([rows[index] for index in headers], ["Channels", "MCP servers", "External agents", "Skill sources"])
        text = "\n".join(rows)
        self.assertRegex(text, r"My account +Example Chat +waits for its login +no owner bound · dm pairing")
        self.assertIn("asks to pair: Sam · code K7", text)
        self.assertRegex(text, r"files +stdio +on +node server.js")
        self.assertRegex(text, r"One +found +connected +not signed in: run one login")
        self.assertRegex(text, r"github:someone/skills +git +1 skills: tidy")
        self.assertRegex(text, r"common +shared library · 4 entries · read only")
        self.assertEqual([item for item in items if item[0] == "add"],
                         [("add", "channels"), ("add", "mcp"), ("add", "acp"), ("add", "skills")])

    def test_nothing_connected_and_a_route_that_fails_still_read(self):
        rows, headers, items = connectors.listing({"channels": {**CHANNELS, "kinds": [], "channels": []},
                                                   "mcp": {"servers": []}, "acp": ValueError("no registry"), "skills": None})
        text = "\n".join(rows)
        self.assertIn("＋ Add a channel (no channel package is installed yet)", text)
        self.assertIn("could not be read: no registry", text)
        self.assertIn("Skill sources · of an agent identity", text)

    async def test_adding_a_channel_asks_what_its_package_declares(self):
        client = Client({"post:channels": {"account": "example-2", "result": {"code": "Q4", "text": {"en": "Send the code to it."}}}})
        asked, read = [], []

        async def ask(title, default="", **options):
            asked.append((title, options.get("secret", False)))
            return {"Server address": "wss://chat.example", "Token": "s3cret"}[title]

        async def reader(title, text, **options):
            read.append((title, text))

        async def wait(title, call):
            return call()

        with mock.patch.object(views, "choose", side_effect=answered(1, 1)), mock.patch.object(views, "ask", side_effect=ask), \
                mock.patch.object(views, "read", side_effect=reader), mock.patch.object(views, "_load", side_effect=wait):
            await connectors._add_channel(None, client, CHANNELS, lambda text: None)
        self.assertEqual(client.posted[0], ("channels", {"action": "add", "kind": "example", "values": {
            "dm": "open", "server": "wss://chat.example", "quiet": True, "token": "s3cret"}}))
        self.assertEqual(asked, [("Server address", False), ("Token", True)])   # the secret is not shown as it is typed
        self.assertEqual(client.posted[1], ("channels", {"action": "owner_code", "account": "example-2"}))
        self.assertIn("Q4", read[-1][1])

    async def test_without_a_channel_package_adding_says_where_channels_come_from(self):
        read = []

        async def reader(title, text, **options):
            read.append(text)

        with mock.patch.object(views, "read", side_effect=reader):
            await connectors._add_channel(None, Client(), {"kinds": [], "from": CHANNELS["from"]}, lambda text: None)
        self.assertEqual(read, ["Channels come from channel packages: harness install NAME."])

    async def test_an_mcp_server_is_added_by_command_or_address(self):
        posted = []
        host = mock.Mock(post=lambda path, body, timeout=None: posted.append((path, body)) or {})

        async def wait(title, call):
            return call()

        with mock.patch.object(views, "_load", side_effect=wait):
            with mock.patch.object(views, "ask", side_effect=answered("files", "python -m server --root .", "API_KEY=k1")):
                await connectors._add_server(host, None, {}, lambda text: None)
            with mock.patch.object(views, "ask", side_effect=answered("remote", "https://mcp.example/mcp", "")):
                await connectors._add_server(host, None, {}, lambda text: None)
        self.assertEqual(posted[0], ("/api/app/mcp", {"action": "add", "name": "files", "command": "python",
                                                      "args": ["-m", "server", "--root", "."], "env": {"API_KEY": "k1"}}))
        self.assertEqual(posted[1], ("/api/app/mcp", {"action": "add", "name": "remote", "url": "https://mcp.example/mcp"}))

    def test_the_terminal_names_no_channel(self):
        names = re.compile(r"\b(qq|onebot|wechat|weixin|telegram|discord|slack|whatsapp|feishu|lark|dingtalk)\b",
                           re.IGNORECASE)
        folder = Path(life_view.__file__).parent
        found = [f"{path.name}:{number}" for path in sorted(folder.glob("*.py"))
                 for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if names.search(line)]
        self.assertEqual(found, [])


class LibraryTests(unittest.TestCase):
    def test_skills_with_evidence_uses_and_origin_then_the_tree_and_memory(self):
        learned = {"skills": [{"name": "tidy-notes", "evidence": "own_test", "uses": 3,
                               "source": {"chat": "main", "time": 0, "expired": True}},
                              {"name": "old-way", "evidence": "effective", "uses": 9, "archived": True, "source": {}}],
                   "memory": {"prs": {"text": "pull requests in English", "scope": "private", "updated": "1"}}}
        rows, headers, items = library.listing(learned, {"nodes": [{"name": "safety", "children": 2}, {"name": "ping"}]})
        self.assertEqual([rows[index] for index in headers], ["skills", "tree of reactions", "memory",
                                                              "shared libraries (read only)"])
        text = "\n".join(rows)
        self.assertRegex(text, r"tidy-notes +own test +3 uses +main · .*\(record expired\)")
        self.assertRegex(text, r"old-way +archived +9 uses")
        self.assertRegex(text, r"▸ root +4 nodes")
        self.assertRegex(text, r"pull requests in English +private")

    def test_a_new_identity_reads_sensibly(self):
        rows, headers, items = library.listing({"skills": [], "memory": {}}, {"nodes": []})
        text = "\n".join(rows)
        self.assertIn("none yet: what it learns to do becomes a skill", text)
        self.assertIn('nothing yet: tell it "remember …"', text)

    def test_the_tree_level_shows_branches_as_folders_and_the_lit_path(self):
        rows = library.tree_rows({"nodes": [{"name": "safety", "about": "safety", "children": 2, "lit": True},
                                            {"name": "ping", "about": "ping -> pong", "evidence": "owner", "enabled": False}]})
        self.assertRegex(rows[0], r"^• 1\. ▸ safety +2 nodes$")
        self.assertRegex(rows[1], r"^  2\.   ping -> pong +added by owner \(disabled\)$")

    def test_what_a_stopped_reply_had_written_stays_and_a_failure_says_its_fix(self):
        stopped = life_view.lines({"event": "interrupted", "reason": "stopped", "text": "Half an answer"})
        self.assertEqual(stopped[0], ("answer", "Half an answer"))
        self.assertIn("Interrupted", stopped[1][0])
        failed = life_view.lines({"event": "error", "error": "the provider refused the key", "fix": "/login adds one",
                                  "code": "key_refused", "kind": "HTTPError"})
        self.assertEqual([text for text, _ in failed], ["the provider refused the key", "  /login adds one"])
        asleep = life_view.lines({"event": "asleep", "code": "spending_limit", "fix": "harness usage raise 5"})
        self.assertEqual(asleep[1][0], "  harness usage raise 5")

    def test_spending_in_the_status_line(self):
        self.assertEqual(life_view.spend({"spent_today": 0.4567, "budget": 2}), "$0.46 today / $2.00")


class SettingsTests(unittest.IsolatedAsyncioTestCase):
    SCHEMA = {"approvals": {"programs": {"name": "approvals.programs", "title": {"en": "What programs may do"},
                                         "about": {"en": "beyond their own folder"}, "type": "choice",
                                         "choices": ["ask_each", "allow"],
                                         "labels": {"ask_each": {"en": "Ask each time"}, "allow": {"en": "Allow"}},
                                         "scope": "global", "default": "ask_each"}},
              "agent": {"daily_budget": {"name": "agent.daily_budget", "title": {"en": "Daily limit"}, "about": {"en": "dollars a day"},
                                         "type": "float", "scope": "identity", "default": 2.0},
                        "proactive": {"name": "agent.proactive", "title": {"en": "Acting on its own"}, "about": {"en": ""},
                                      "type": "bool", "scope": "identity", "default": True}},
              "general": {"theme": {"name": "general.theme", "title": {"en": "Theme"}, "about": {"en": ""}, "type": "choice",
                                    "choices": ["system"], "scope": "global", "default": "system"}}}

    def test_rows_have_titles_pages_and_values_in_words(self):
        rows = tui_settings.settings_rows(self.SCHEMA, {"approvals": {"programs": "allow"}}, {"agent.daily_budget": 5.0})
        self.assertEqual([(row["page"], row["title"], tui_settings.shown(row["description"], row["value"]), row["scope"])
                          for row in rows],
                         [("Permissions and limits", "What programs may do", "Allow", "global"),
                          ("Permissions and limits", "Daily limit", "5.0", "identity"),
                          ("Permissions and limits", "Acting on its own", "on", "identity")])   # the page's looks are left out
        only = tui_settings.settings_rows(self.SCHEMA, {}, None, pages=("General",))
        self.assertEqual(only, [])

    def test_a_setting_sits_on_the_page_the_app_has_it_on(self):
        for name, page in (("agent.autostart", "General"), ("agent.proactive", "Permissions and limits"),
                           ("agent.stale_hours", "Permissions and limits"), ("limits.max_steps", "Permissions and limits"),
                           ("physical.level", "Computer"), ("privacy.level", "Computer"), ("agent.model", "Model"),
                           ("model.reasoning_effort", "Model"), ("learning.mode", "What it learned"),
                           ("packages.registry", "Packages"), ("agent.keep_days", "Data"), ("data.keep_days", "Data"),
                           ("workspace.workers", "Computer")):
            self.assertEqual(tui_settings.page_of(name), page, name)

    def test_what_is_not_shown_is_left_out_and_advanced_ones_come_last_on_their_page(self):
        schema = {"model": {"vision": {"title": {"en": "Vision model"}, "type": "text", "advanced": True, "shown": True},
                            "think_interval": {"title": {"en": "Think interval"}, "type": "int", "shown": False},
                            "reasoning_effort": {"title": {"en": "Reasoning effort"}, "type": "choice", "choices": ["default"],
                                                 "shown": True, "advanced": False}}}
        rows = tui_settings.settings_rows(schema, {})
        self.assertEqual([(row["name"], row["advanced"]) for row in rows],
                         [("model.reasoning_effort", False), ("model.vision", True)])

    def test_every_setting_of_the_core_has_a_title_and_a_page(self):
        rows = tui_settings.settings_rows(tui_settings.described(), {})
        self.assertTrue(rows)
        self.assertTrue(all(row["title"] and row["page"] for row in rows))
        self.assertIn("terminal.editor_mode", [row["name"] for row in rows])

    async def test_an_identitys_setting_is_written_for_the_identity_and_a_choice_by_its_name(self):
        client = Client({"settings": {"values": {"agent.daily_budget": 2.0, "agent.proactive": True},
                                      "schema": {name: description for section in ("agent",)
                                                 for name, description in ((f"{section}.{key}", value)
                                                                           for key, value in self.SCHEMA[section].items())}}})
        store = mock.Mock()
        store.get.return_value = {"approvals": {"programs": "ask_each"}}
        chosen = []

        async def choose(title, rows, **options):
            chosen.append((title, rows))
            return {0: 1, 1: None}.get(len(chosen) - 1) if title == "Settings" else 1

        with mock.patch("harness.settings.Settings", return_value=store), \
                mock.patch.object(tui_settings, "described", return_value={"approvals": self.SCHEMA["approvals"]}), \
                mock.patch.object(views, "choose", side_effect=choose), mock.patch.object(views, "ask", side_effect=answered("3.5")):
            changed = await tui_settings.config_view("unused", client)
        self.assertIn("Permissions and limits › What programs may do", chosen[0][1][0])
        self.assertTrue(chosen[0][1][0].rstrip().endswith("Ask each time"))
        self.assertEqual(client.posted, [("settings", {"key": "agent.daily_budget", "value": 3.5})])
        store.update.assert_not_called()
        self.assertEqual(changed, ["Daily limit (agent.daily_budget) = 3.5"])

    def test_deleting_an_identity_lists_what_goes_with_it(self):
        host = mock.Mock()
        host.get.side_effect = lambda path: {"chats": [{"title": "Main conversation"}, {"title": "Trip"}]} if "chats" in path \
            else {"channels": [{"account": "example-1"}]} if "channels" in path else {"cost_usd": 1.25, "calls": {"total": 40}}
        text = tui_settings._goes_with(host, "work")
        self.assertIn("conversations   2: Main conversation, Trip", text)
        self.assertIn("channels        1: example-1", text)
        self.assertIn("spent           $1.25 in the last 30 days, 40 calls", text)
        self.assertTrue(all("identity=work" in call.args[0] for call in host.get.call_args_list))


class BrowseTests(unittest.IsolatedAsyncioTestCase):
    async def test_named_keys_come_back_with_the_row_and_an_empty_list_says_so(self):
        from prompt_toolkit.application import create_app_session
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            task = asyncio.ensure_future(views.browse("Calendar", ["Thu", "an entry"], headers=[0], keys=["x", "delete"]))
            await asyncio.sleep(0.1)
            pipe.send_text("\x1b[3~")   # Delete
            self.assertEqual(await asyncio.wait_for(task, 3), ("delete", 1))
            real, apps = views.Application, []
            with mock.patch.object(views, "Application", side_effect=lambda *a, **k: apps.append(real(*a, **k)) or apps[-1]):
                task = asyncio.ensure_future(views.browse("Calendar", [], keys=["c"], empty="Nothing on the calendar."))
                await asyncio.sleep(0.1)
                shown = "".join(text for _, text in apps[0].layout.container.children[2].content.text())
                pipe.send_text("c")
                self.assertEqual(await asyncio.wait_for(task, 3), ("c", None))
            self.assertIn("Nothing on the calendar.", shown)


if __name__ == "__main__":
    unittest.main()
