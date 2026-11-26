"""The terminal chat driven by its keys, as a person presses them: the chat itself over a
pipe, an identity's conversation on a host that serves the conversation-control routes from
memory (the reply while it is written, the queue, stop).

Input: Enter sends and the four newline keys do not, a paste never sends, Up and Down move in
a draft before they walk the history, a cleared draft comes back, Ctrl+D deletes forward or
leaves, Ctrl+R searches, ? opens the keys only on an empty input, / lists and completes
commands and answers an unknown one as Claude Code does, a skill is a command.
While it works: a message is queued and listed, Up takes the queue back, Esc stops the turn,
the reply shows while it is written, an approval is answered with the arrows, a number,
Enter, Esc or a note, Shift+Tab changes the approval level, Alt+P opens the models and keeps
the draft. The user's keybindings file applies without a restart and its mistakes are said."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import helpers  # noqa: F401
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from harness.host.client import RemoteError
from harness.tui import agent as life_view
from harness.tui import keys, views
from harness.tui.chat import Chat

ENTER, ESC, UP, DOWN, TAB = "\r", "\x1b", "\x1b[A", "\x1b[B", "\t"
CTRL_C, CTRL_D, CTRL_J, CTRL_R, CTRL_S, CTRL_UNDERSCORE = "\x03", "\x04", "\n", "\x12", "\x13", "\x1f"


class Host:
    """A session host's /api/agent routes for one identity, in memory: its main chat's
    record, the turn that runs, the queue behind it, and the reply being written."""

    url = "http://127.0.0.1:0"

    def __init__(self, control=True):
        self.records, self.queued, self.running, self.live = [], [], None, None
        self.calls, self.control, self.number = [], control, 0
        self.skills = [{"name": "tidy-notes", "description": "puts the notes of a folder in order"}]

    def record(self, event, **data):
        self.records.append({"seq": len(self.records) + 1, "event": event, "time": time.time(), **data})

    def begin(self, row):
        self.running = {"id": row["id"], "text": row["text"], "since": time.time()}
        self.record("turn_started", job=row["id"])
        self.record("user", text=row["text"])

    def finish(self, text="done"):
        """The turn that runs ends with a reply; the next queued message begins."""
        self.record("reply", text=text)
        self.running, self.live = None, None
        if self.queued:
            self.begin(self.queued.pop(0))

    def get(self, path):
        parts = urlsplit(path)
        name, query = parts.path.rsplit("/", 1)[1], {key: value[0] for key, value in parse_qs(parts.query).items()}
        self.calls.append(("GET", name, query))
        if name == "life":
            return {"busy": ["main"] if self.running else [], "spent_today": 0.12, "budget": 2.0}
        if name == "chats":
            return {"chats": [{"chat": "main", "title": "Main conversation", "updated": 1.0}]}
        if name == "chat":
            return {"records": [row for row in self.records if row["seq"] > int(query.get("after") or 0)],
                    "live": self.live}
        if name == "learned":
            return {"skills": self.skills, "memory": {}}
        if name == "queue" and self.control:
            return self.queue()
        raise RemoteError("no such route")

    def queue(self):
        return {"chat": "main", "held": False, "running": self.running, "queued": list(self.queued)}

    def post(self, path, body, timeout=None):
        name = urlsplit(path).path.rsplit("/", 1)[1]
        self.calls.append(("POST", name, body))
        if name == "say":
            self.number += 1
            row = {"id": f"q{self.number}", "text": body["text"], "queued": time.time()}
            if self.running:
                self.queued.append(row)
            else:
                self.begin(row)
            return {"queued": row["id"], "chat": "main"}
        if name == "opened":
            return {"ok": True}
        if name == "approvals":
            self.record("approval", code=body["code"], state="approved" if body["accept"] else "rejected",
                        reason=body.get("reason"))
            return {"code": body["code"], "state": "approved" if body["accept"] else "rejected", "handled_elsewhere": False}
        if name == "stop" and self.control:
            stopped = self.running is not None
            if stopped:
                self.record("interrupted", reason="stopped")
                self.running, self.live = None, None
                if self.queued:
                    self.begin(self.queued.pop(0))
            return {"stopped": stopped, "queued": len(self.queued), "held": False}
        if name == "queue" and self.control:
            row = next((row for row in self.queued if row["id"] == body.get("id")), None)
            if body["action"] == "clear":
                self.queued.clear()
            elif row is None:
                raise RemoteError("that message has started already")
            elif body["action"] == "remove":
                self.queued.remove(row)
            elif body["action"] == "edit":
                row["text"] = body["text"]
            elif body["action"] == "send_now":
                self.record("interrupted", reason="stopped")
                self.queued.remove(row)
                self.begin(row)
            return self.queue()
        raise RemoteError("no such route")

    def posted(self, name):
        return [body for method, route, body in self.calls if method == "POST" and route == name]


class Driven(unittest.IsolatedAsyncioTestCase):
    """The chat over a pipe, in folders of its own."""

    identity = {"id": "default", "name": "default"}

    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        self.data = Path(self.folder.name)
        environ = mock.patch.dict(os.environ, {"HARNESS_HOME": self.folder.name, "HARNESS_DATA": self.folder.name})
        environ.start()
        self.addCleanup(environ.stop)
        before = os.getcwd()
        os.chdir(self.folder.name)
        self.addCleanup(os.chdir, before)
        for name, seconds in (("POLL", 0.02), ("FAST", 0.02), ("LOOK", 0.05)):
            patched = mock.patch.object(life_view, name, seconds)
            patched.start()
            self.addCleanup(patched.stop)
        bound = set(keys.bound)
        self.addCleanup(lambda: (keys.bound.clear(), keys.bound.update(bound)))
        self.pipe = self.enterContext(create_pipe_input())
        self.enterContext(create_app_session(input=self.pipe, output=DummyOutput()))
        self.host = None

    async def open(self, host=None, identity=True):
        self.host = host
        start = SimpleNamespace(identity=self.identity if identity else None, named=False)
        self.chat = Chat(host=host, start=start if identity else None, input=self.pipe, output=DummyOutput())
        self.printed = []
        self.chat._print = lambda *lines: self.printed.extend(str(getattr(line, "plain", getattr(line, "markup", line)))
                                                             for line in lines)
        if host is None:
            self.sent = []
            self.chat.send = lambda text, files=(), **more: self.sent.append((text, list(files)))
            self.chat._open = lambda: None
        self.running = asyncio.ensure_future(self.chat.app.run_async(pre_run=self.chat._begin))
        await asyncio.sleep(0.05)
        if host is not None:
            await self.until(lambda: self.chat.conversation is not None and self.chat.status != "starting")
        return self.chat

    async def asyncTearDown(self):
        chat = getattr(self, "chat", None)
        if chat is not None:
            chat.stop.set()
            if not self.running.done():
                chat.app.exit()
            await asyncio.wait_for(self.running, 3)

    async def press(self, *texts):
        for text in texts:
            self.pipe.send_text(text)
            await asyncio.sleep(0.06)

    async def until(self, condition, seconds=3.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if condition():
                return
            await asyncio.sleep(0.02)
        self.fail("it did not happen in time")

    def text(self, fragments) -> str:
        return "".join(part[1] for part in fragments)


class InputTests(Driven):
    async def test_enter_sends_and_the_newline_keys_start_a_line(self):
        chat = await self.open()
        await self.press("one", keys.carrier("shift+enter"), "two", CTRL_J, "three", ESC + ENTER, "four\\", ENTER, "five")
        self.assertEqual(chat.buffer.text, "one\ntwo\nthree\nfour\nfive")
        self.assertEqual(self.sent, [])
        await self.press(ENTER)
        self.assertEqual(self.sent, [("one\ntwo\nthree\nfour\nfive", [])])
        self.assertEqual(chat.buffer.text, "")

    async def test_a_paste_of_lines_never_sends_and_a_long_one_is_a_chip(self):
        chat = await self.open()
        await self.press("\x1b[200~first\rsecond\r\x1b[201~")
        self.assertEqual((chat.buffer.text, self.sent), ("first\nsecond\n", []))
        await self.press(CTRL_C)
        long = "\n".join(f"row {number}" for number in range(40))
        await self.press("see ", "\x1b[200~" + long + "\x1b[201~")
        self.assertEqual(chat.buffer.text, "see [Pasted text #1 +39 lines]")
        await self.press(ENTER)
        self.assertEqual(self.sent, [("see " + long, [])])
        await self.press(UP)  # recalled as it was typed, and sent whole again
        self.assertEqual(chat.buffer.text, "see [Pasted text #1 +39 lines]")

    async def test_up_and_down_move_in_the_draft_before_they_walk_the_history(self):
        chat = await self.open()
        await self.press("first message", ENTER, "second message", ENTER, "second message", ENTER)
        await self.press("top", CTRL_J, "bottom")
        await self.press(UP)
        self.assertEqual((chat.buffer.text, chat.buffer.document.cursor_position_row), ("top\nbottom", 0))
        await self.press(UP)   # from the first row: the history, the same message sent twice once
        self.assertEqual(chat.buffer.text, "second message")
        await self.press(UP)
        self.assertEqual(chat.buffer.text, "first message")
        await self.press(DOWN, DOWN)
        self.assertEqual(chat.buffer.text, "top\nbottom")  # past the newest: the draft again
        history = [json.loads(line) for line in (self.data / "history.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(row["text"], row["cwd"]) for row in history],
                         [("first message", os.getcwd()), ("second message", os.getcwd())])

    async def test_ctrl_c_clears_the_draft_up_brings_it_back_and_twice_leaves(self):
        chat = await self.open()
        await self.press("a draft worth keeping", CTRL_C)
        self.assertEqual(chat.buffer.text, "")
        self.assertIn("Press Ctrl-C again to exit", self.text(chat._hint()))
        await asyncio.sleep(0.9)  # past the time a second press would leave
        await self.press(UP)
        self.assertEqual(chat.buffer.text, "a draft worth keeping")
        await self.press(CTRL_C, CTRL_C)
        await asyncio.wait_for(self.running, 2)

    async def test_ctrl_d_deletes_forward_with_text_and_leaves_twice_without(self):
        chat = await self.open()
        await self.press("abc", "\x01", CTRL_D)   # Ctrl+A, then Ctrl+D
        self.assertEqual(chat.buffer.text, "bc")
        self.assertFalse(self.running.done())
        await self.press(CTRL_C, CTRL_D)
        self.assertIn("Press Ctrl-D again to exit", self.text(chat._hint()))
        self.assertFalse(self.running.done())
        await self.press(CTRL_D)
        await asyncio.wait_for(self.running, 2)

    async def test_ctrl_r_searches_and_tab_enter_and_ctrl_c_end_it(self):
        chat = await self.open()
        await self.press("deploy to staging", ENTER, "deploy to production", ENTER, "half typed")
        await self.press(CTRL_R, "deploy")
        self.assertEqual(self.text(chat._searching()), "search prompts: deploy")
        self.assertEqual(chat.buffer.text, "deploy to production")
        await self.press(CTRL_R)   # again: the match before it
        self.assertEqual(chat.buffer.text, "deploy to staging")
        await self.press(TAB)      # taken, and edited on
        self.assertIsNone(chat.search)
        await self.press(" now")
        self.assertEqual(chat.buffer.text, "deploy to staging now")
        await self.press(CTRL_C, CTRL_R, "zzz")
        self.assertEqual(self.text(chat._searching()), "no matching prompt: zzz")
        await self.press(CTRL_C)   # back to what was typed
        self.assertEqual((chat.search, chat.buffer.text), (None, ""))
        await self.press(CTRL_R, "production", ENTER)   # taken and sent
        self.assertEqual(self.sent[-1], ("deploy to production", []))

    async def test_the_question_mark_opens_the_keys_only_on_an_empty_input(self):
        chat = await self.open()
        await self.press("?")
        self.assertTrue(chat.help)
        self.assertEqual(chat.buffer.text, "")
        panel = self.text(chat._keys())
        for expected in ("! for shell mode", "/ for commands", "@ for file paths", "shift+tab to cycle approval levels",
                         "ctrl+o to see the transcript", "ctrl+t to see the timeline", "ctrl+_ to undo",
                         "alt+p to switch model", "ctrl+s to stash prompt", "ctrl+g to edit in $EDITOR",
                         "/keybindings to customize"):
            self.assertIn(expected, panel)
        await self.press(ESC)
        await asyncio.sleep(0.4)
        self.assertFalse(chat.help)
        await self.press("why", "?")
        self.assertEqual((chat.buffer.text, chat.help), ("why?", False))

    async def test_stash_and_undo(self):
        chat = await self.open()
        await self.press("alpha beta", CTRL_UNDERSCORE)
        self.assertEqual(chat.buffer.text, "alpha ")     # what was typed goes a word at a time
        await self.press("gamma", CTRL_S)
        self.assertEqual(chat.buffer.text, "")
        await self.press("something first", ENTER)       # the stash comes back once that is sent
        self.assertEqual(chat.buffer.text, "alpha gamma")

    async def test_the_readline_keys(self):
        chat = await self.open()
        await self.press("run src/utils/foo.ts", ESC + "b", ESC + "b", "X")   # Alt+B twice
        self.assertEqual(chat.buffer.text, "run src/utils/Xfoo.ts")
        await self.press("\x17")                                              # Ctrl+W: back to the whitespace
        self.assertEqual(chat.buffer.text, "run foo.ts")
        await self.press("\x19")                                              # Ctrl+Y pastes it back
        self.assertEqual(chat.buffer.text, "run src/utils/Xfoo.ts")
        await self.press("\x0b", "\x15")                                      # Ctrl+K, Ctrl+U
        self.assertEqual(chat.buffer.text, "")
        await self.press("one two", ESC + "\x7f")                             # Alt+Backspace
        self.assertEqual(chat.buffer.text, "one ")

    async def test_the_command_list_filters_completes_and_answers_an_unknown_command(self):
        chat = await self.open()
        await self.press("/mod")
        await self.until(lambda: chat.buffer.complete_state is not None)
        self.assertEqual([found.text for found in chat.buffer.complete_state.completions], ["/model"])
        await self.press(TAB)
        self.assertEqual(chat.buffer.text, "/model")
        await self.press(CTRL_C, "/nope", ENTER)
        await self.until(lambda: any("Unknown command: /nope" in line for line in self.printed))
        await self.press("/modle", ENTER)
        await self.until(lambda: any("Unknown command: /modle. Did you mean /model?" in line for line in self.printed))
        self.assertEqual(self.sent, [])

    async def test_aliases_run_the_command_they_stand_for(self):
        chat = await self.open()
        with mock.patch.object(Chat, "do_config") as config, mock.patch.object(Chat, "do_usage") as usage:
            await self.press("/settings", ENTER, "/cost week", ENTER)
        config.assert_called_once_with("")
        usage.assert_called_once_with("week")
        await self.press("/quit", ENTER)
        await asyncio.wait_for(self.running, 2)
        self.assertIsNotNone(chat)


class WorkingTests(Driven):
    async def test_a_message_while_it_works_is_queued_listed_and_taken_back_with_up(self):
        host = Host()
        chat = await self.open(host)
        await self.press("first task", ENTER)
        await self.until(lambda: chat.status == "RUNNING")
        self.assertIn("› first task", self.printed)
        await self.press("then this", ENTER, "and this", ENTER)
        await self.until(lambda: len(chat.queue["queued"]) == 2)
        self.assertEqual(self.text(chat._queued()), "› then this\n› and this")
        self.assertNotIn("› then this", self.printed)  # not said yet: it waits its turn
        self.assertIn("Press up to edit queued messages", self.text(chat._hint()))
        await self.press("my draft", "\x01", UP)   # Up from the first row takes the queue back
        await self.until(lambda: not host.queued)
        await self.until(lambda: chat.buffer.text == "then this\nand this\nmy draft")
        self.assertEqual([body["action"] for body in host.posted("queue")], ["remove", "remove"])

    async def test_queued_messages_are_said_when_their_turn_comes(self):
        host = Host()
        chat = await self.open(host)
        await self.press("first task", ENTER)
        await self.until(lambda: chat.status == "RUNNING")
        await self.press("second task", ENTER)
        await self.until(lambda: len(chat.queue["queued"]) == 1)
        host.finish("the first is done")
        await self.until(lambda: "› second task" in self.printed)
        self.assertEqual(chat.queue["queued"], [])
        self.assertEqual(self.printed.count("› first task"), 1)

    async def test_escape_stops_the_turn_and_what_is_queued_goes_next(self):
        host = Host()
        chat = await self.open(host)
        await self.press("a long task", ENTER)
        await self.until(lambda: chat.status == "RUNNING")
        await self.press("next thing", ENTER)
        await self.until(lambda: len(chat.queue["queued"]) == 1)
        await self.press(ESC)
        await self.until(lambda: host.posted("stop"), 4)
        self.assertEqual(host.posted("stop"), [{"identity": "default", "chat": "main", "hold": False}])
        await self.until(lambda: any("Interrupted" in line for line in self.printed))
        await self.until(lambda: "› next thing" in self.printed)   # the queue goes on, as after Esc in Claude Code

    async def test_the_reply_shows_while_it_is_written_with_the_time_it_takes(self):
        host = Host()
        chat = await self.open(host)
        await self.press("write something", ENTER)
        await self.until(lambda: chat.status == "RUNNING")
        working = self.text(chat._working())
        self.assertRegex(working, r"Working… \(\d+s · esc to interrupt\)")
        host.live = {"job": "q1", "text": "", "reasoning": "let me think", "since": time.time() - 75}
        await self.until(lambda: chat.live is not None)
        self.assertRegex(self.text(chat._working()), r"Thinking… \(1m 1\ds · esc to interrupt\)")
        host.live = {"job": "q1", "text": "A **bold** start", "reasoning": "", "since": time.time() - 75}
        await self.until(lambda: chat.live and chat.live["text"])
        self.assertIn("A bold start", "".join(part[1] for part in chat._writing().__pt_formatted_text__()))
        host.finish("A **bold** start, and its end.")
        await self.until(lambda: chat.live is None and chat.status == "IDLE")
        self.assertEqual(sum("its end" in line for line in self.printed), 1)

    async def test_send_now_stops_the_turn_for_what_is_queued(self):
        host = Host()
        chat = await self.open(host)
        await self.press("first", ENTER)
        await self.until(lambda: chat.status == "RUNNING")
        await self.press("urgent", ENTER)
        await self.until(lambda: len(chat.queue["queued"]) == 1)
        await self.press(keys.carrier("ctrl+enter"))
        await self.until(lambda: host.posted("queue"))
        self.assertEqual(host.posted("queue")[0]["action"], "send_now")
        await self.until(lambda: "› urgent" in self.printed)

    async def test_a_host_without_the_control_routes_is_said_not_failed(self):
        host = Host(control=False)
        chat = await self.open(host)
        await self.press("a task", ENTER)
        await self.until(lambda: chat.status == "RUNNING")
        await self.press(ESC)
        await self.until(lambda: any("earlier version" in line for line in self.printed), 4)
        self.assertEqual(chat.status, "RUNNING")

    async def test_a_failed_turn_says_why_and_gives_the_message_back(self):
        host = Host()
        chat = await self.open(host)
        await self.press("do the thing", ENTER)
        await self.until(lambda: chat.status == "RUNNING")
        host.running = None
        host.record("error", error="the provider refused the key", fix="/login adds a key that works", code="key")
        await self.until(lambda: chat.buffer.text == "do the thing")
        self.assertIn("the provider refused the key", self.printed)
        self.assertIn("  /login adds a key that works", self.printed)

    async def test_an_approval_is_answered_with_arrows_a_number_escape_or_a_note(self):
        host = Host()
        chat = await self.open(host)

        async def asked(code):
            host.record("approval", code=code, what="git push origin main", verb="send", state="waiting",
                        expires=time.time() + 1800)
            await self.until(lambda: chat.ask is not None and chat.ask["request_id"] == code)

        await self.press("a draft")
        await asked("A1")
        shown = self.text(chat._asking())
        for expected in ("git push origin main", 'a step of the kind "send"', "1. Yes", "2. No", "tab to add a note"):
            self.assertIn(expected, shown)
        self.assertEqual(chat.buffer.text, "")           # the draft is aside while the question has the keys
        await self.press(DOWN, UP, ENTER)                # the arrows, then Enter on "Yes"
        await self.until(lambda: len(host.posted("approvals")) == 1)
        self.assertEqual(chat.buffer.text, "a draft")
        await asked("A2")
        await self.press("2")                            # the number of "No"
        await self.until(lambda: len(host.posted("approvals")) == 2)
        await asked("A3")
        await self.press(ESC)                            # Esc declines
        await self.until(lambda: len(host.posted("approvals")) == 3, 4)
        await asked("A4")
        await self.press(DOWN, TAB, "push to a branch instead", ENTER)   # a note with the answer
        await self.until(lambda: len(host.posted("approvals")) == 4)
        answers = [(body["code"], body["accept"], body["reason"]) for body in host.posted("approvals")]
        self.assertEqual(answers, [("A1", True, ""), ("A2", False, ""), ("A3", False, ""),
                                   ("A4", False, "push to a branch instead")])

    async def test_skills_are_commands_and_the_status_names_what_it_must(self):
        host = Host()
        chat = await self.open(host)
        await self.until(lambda: chat.skills)
        await self.press("/tidy")
        await self.until(lambda: chat.buffer.complete_state is not None)
        self.assertEqual([found.text for found in chat.buffer.complete_state.completions], ["/tidy-notes"])
        await self.press(TAB, " the inbox", ENTER)
        await self.until(lambda: host.posted("say"))
        self.assertEqual(host.posted("say")[0]["text"], "Use your skill tidy-notes. the inbox")
        host.record("model_reply", role="dialogue", text="{}", usage={"input_tokens": 3000, "output_tokens": 200,
                                                                    "context_window": 32000})
        await self.until(lambda: chat.context is not None)
        chat.model = "provider/some-model-name-v4"
        self.assertEqual(self.text(chat._status()).strip(),
                         "default · $0.12 today / $2.00 · provider/some-model-name-v4")   # in 80 columns
        self.assertEqual(chat._context_part(), "10% context")
        self.assertIn("approvals: ask once per conversation (shift+tab to cycle)", self.text(chat._mode()))
        chat.app.output.get_size = lambda: SimpleNamespace(rows=40, columns=72)   # narrower: the model by its short name
        self.assertEqual(self.text(chat._status()).strip(), "default · $0.12 today / $2.00 · some-model-name-v4")

    async def test_leaving_says_that_it_goes_on_and_how_to_come_back_and_stop_it(self):
        host = Host()
        chat = await self.open(host)
        said = []
        chat.console = SimpleNamespace(print=lambda line: said.append(line.plain))
        chat._farewell()
        self.assertEqual(said[0], "default goes on in the background.")
        self.assertTrue(any("harness" in line and "come back" in line for line in said))
        self.assertTrue(any("harness host stop" in line for line in said))


class SettingsTests(Driven):
    async def test_shift_tab_goes_through_the_approval_levels_and_keeps_the_choice(self):
        from harness.settings import Settings

        chat = await self.open()
        seen = []
        for _ in range(4):
            await self.press("\x1b[Z")
            seen.append(Settings(self.data).get()["approvals"]["programs"])
        self.assertEqual(seen, ["allow", "never", "ask_each", "ask_once_session"])
        self.assertIn("ask once per conversation", self.text(chat._mode()))

    async def test_alt_p_opens_the_models_and_keeps_the_draft(self):
        chat = await self.open()
        opened = []

        async def choose(title, rows, **options):
            opened.append(title)

        async def view(coroutine):
            return await coroutine

        chat._view = view
        with mock.patch.object(views, "choose", side_effect=choose):
            await self.press("half a message", ESC + "p")
            await self.until(lambda: opened)
        self.assertEqual(opened, ["Select model"])
        self.assertEqual(chat.buffer.text, "half a message")

    async def test_the_keybindings_file_applies_without_a_restart_and_its_mistakes_are_said(self):
        chat = await self.open()
        (self.data / "keybindings.json").write_text(json.dumps({"bindings": [{"context": "Chat", "bindings": {
            "f5": "chat:newline", "ctrl+j": None, "ctl+k": "chat:undo"}}]}), encoding="utf-8")
        await self.until(lambda: "f5" in chat.keymap.of("chat:newline"))   # read again by itself
        self.assertTrue(any("keybindings.json" in line and "'ctl'" in line for line in self.printed))
        await self.press("one", "\x1b[15~", "two")                         # F5 is the newline now
        self.assertEqual(chat.buffer.text, "one\ntwo")
        await self.press(CTRL_J)   # unbound: no longer a newline (the byte a terminal sends for it is Enter's)
        self.assertEqual((chat.buffer.text, self.sent), ("", [("one\ntwo", [])]))
        self.assertNotIn("ctrl+j", self.text(chat._keys()))
        (self.data / "keybindings.json").write_text("{ not json", encoding="utf-8")
        await self.until(lambda: any("not valid JSON" in line for line in self.printed))
        self.assertEqual(chat.keymap.key("chat:newline"), "ctrl+j")        # the defaults, and the chat goes on
        self.assertFalse(self.running.done())

    async def test_the_vim_editing_mode_is_a_setting(self):
        from harness.settings import Settings

        chat = await self.open()
        Settings(self.data).update({"terminal": {"editor_mode": "vim"}})
        await self.until(lambda: chat.vim)
        self.assertIn("-- INSERT --", self.text(chat._hint()))
        await self.press("some words", ESC)
        await asyncio.sleep(0.4)
        self.assertIn("-- NORMAL --", self.text(chat._hint()))
        await self.press("0", "d", "w")                     # NORMAL mode: to the start, delete a word
        self.assertEqual(chat.buffer.text, "words")
        await self.press("i", "more ", ENTER)               # INSERT again; Enter still sends
        self.assertEqual(self.sent, [("more words", [])])


if __name__ == "__main__":
    unittest.main()
