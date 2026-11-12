"""What the user types in the terminal chat reaches what they meant: a prefilled value is
typed on from its end, a cancelled start leaves an ended conversation ended, an empty reason
still refuses, program output keeps its lines, and /models opens a list saved with a mistake."""
import asyncio
from contextlib import asynccontextmanager
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import helpers  # noqa: F401
from prompt_toolkit.application import create_app_session
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console
from rich.text import Text

from harness.settings import ChoiceRequired
from harness.tui import views
from harness.tui.chat import Chat


def bare(**fields):
    chat = Chat.__new__(Chat)
    chat.console = Console(file=io.StringIO(), force_terminal=False, width=80)
    chat.app = SimpleNamespace(output=DummyOutput(), invalidate=lambda: None, is_running=False, loop=None)
    chat.notes, chat.sent = [], []
    chat.note = lambda text, *style: chat.notes.append(text)
    chat._print = lambda *lines: None
    chat._background = lambda function, *args: chat.sent.append((function, *args))
    for name, value in fields.items():
        setattr(chat, name, value)
    return chat


class PrefilledTests(unittest.IsolatedAsyncioTestCase):
    async def typed(self, default, keys):
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            answer = asyncio.ensure_future(views.ask("max_steps", default))
            await asyncio.sleep(0.1)
            pipe.send_text(keys)
            return await asyncio.wait_for(answer, 5)

    async def test_typing_goes_on_from_the_end_of_the_value(self):
        self.assertEqual(await self.typed("6", "0\r"), "60")

    async def test_deleting_the_value_replaces_it(self):
        self.assertEqual(await self.typed("60", "\x7f\x7f7\r"), "7")
        self.assertEqual(await self.typed("ask", "\x15browser\r"), "browser")  # Ctrl+U

    async def test_enter_keeps_the_value(self):
        self.assertEqual(await self.typed("ask", "\r"), "ask")


class CancelledStartTests(unittest.IsolatedAsyncioTestCase):
    """A message after a conversation ended starts a new one; when that start is cancelled (Esc
    on the environment choice) or fails, the ended conversation stays ended."""

    CHOICE = {"section": "session", "key": "environment", "per_conversation": True, "options": []}

    def chat(self, start):
        ended = SimpleNamespace(name="ended")
        chat = bare(conversation=ended, status="FINISHED", before_start=None, start=start, pending=[],
                    starting=None, environment=None, agents_on=False, model_entry=None, echoed=None,
                    buffer=Buffer())
        chat.app = SimpleNamespace(loop=asyncio.get_running_loop(), is_running=True, invalidate=lambda: None)
        return chat

    async def settled(self, chat):
        for _ in range(200):
            if chat.status != "starting":
                return
            await asyncio.sleep(0.01)
        self.fail("the start did not end")

    async def test_cancelled_choice_leaves_the_ended_conversation_ended(self):
        start = mock.Mock(side_effect=ChoiceRequired(self.CHOICE))
        chat = self.chat(start)

        async def cancelled(choice, settle=0):
            return None

        chat._choose_environment = cancelled
        chat.send("multiply that by 2")
        await self.settled(chat)
        self.assertEqual(chat.status, "FINISHED")
        self.assertEqual(chat.buffer.text, "multiply that by 2")  # kept to send again...
        self.assertEqual(chat.buffer.document.text_after_cursor, "")  # ...typed on from its end
        chat.send("hello")  # starts a new conversation again, not a message to the ended one
        await self.settled(chat)
        self.assertEqual(start.call_count, 2)
        self.assertEqual(chat.sent, [])

    async def test_failed_start_leaves_the_ended_conversation_ended(self):
        start = mock.Mock(side_effect=RuntimeError("no session host"))
        chat = self.chat(start)
        chat.send("hello")
        await self.settled(chat)
        self.assertEqual(chat.status, "FINISHED")
        self.assertIn("could not start", chat.notes[-1])
        chat.send("hello again")
        await self.settled(chat)
        self.assertEqual(start.call_count, 2)
        self.assertEqual(chat.sent, [])

    async def test_cancelled_first_conversation_is_still_new(self):
        start = mock.Mock(side_effect=ChoiceRequired(self.CHOICE))
        chat = self.chat(start)
        chat.conversation, chat.status = None, None

        async def cancelled(choice, settle=0):
            return None

        chat._choose_environment = cancelled
        chat.send("hello")
        await self.settled(chat)
        self.assertIsNone(chat.status)


class RejectReasonTests(unittest.TestCase):
    def test_enter_on_an_empty_reason_refuses_without_one(self):
        conversation = SimpleNamespace(name="open")
        chat = bare(conversation=conversation,
                    ask={"text": "Use the folder?", "options": [], "at": 0, "reason": True, "request_id": "r1"})
        with mock.patch("harness.tui.chat.command") as command:
            chat.submit("")
        self.assertIsNone(chat.ask)
        function, *args = chat.sent[0]
        function(*args)
        command.assert_called_once_with(conversation, "reject", {"reason": "", "request_id": "r1"})

    def test_a_reason_is_sent_with_the_refusal(self):
        conversation = SimpleNamespace(name="open")
        chat = bare(conversation=conversation,
                    ask={"text": "Use the folder?", "options": [], "at": 0, "reason": True, "request_id": "r1"})
        chat.submit("not that folder")
        self.assertEqual(chat.sent[0][1:], (conversation, "reject", {"reason": "not that folder", "request_id": "r1"}))

    def test_an_empty_line_without_a_question_does_nothing(self):
        chat = bare(conversation=None, ask=None)
        chat.submit("   ")
        self.assertEqual((chat.sent, chat.notes), ([], []))


class ProgramDetailsTests(unittest.TestCase):
    def test_each_output_line_stays_a_line(self):
        chat = bare()
        program = {"number": 1, "code": "for i in range(1, 4): print(i)", "lexer": "python",
                   "details": [Text("1"), Text("2"), Text("3")], "status": "ok", "seconds": 1}
        lines = [line.strip() for line in chat._details_text(program).splitlines()]
        self.assertEqual(lines[-3:], ["1", "2", "3"])


def listed(directory: Path) -> Path:
    """A model list of one model, as the first run leaves it."""
    from harness.model_list import models

    (directory / "config.toml").write_text('[model]\nprovider = "deepseek"\nmodel = "deepseek-flash"\n',
                                           encoding="utf-8")
    models(directory)
    return directory / "models.json"


class ModelListTests(unittest.IsolatedAsyncioTestCase):
    async def edit(self, directory, editor):
        tasks = []
        chat = bare()
        chat.app = SimpleNamespace(create_background_task=tasks.append)

        @asynccontextmanager
        async def terminal():
            yield

        with mock.patch("harness.tui.chat.data", return_value=directory), \
                mock.patch("harness.tui.chat.in_terminal", terminal), \
                mock.patch("harness.tui.chat.subprocess.run", side_effect=editor) as run, \
                mock.patch.dict("os.environ", {"EDITOR": "an-editor"}):
            chat.do_models(None)
            await tasks[0]
        return chat, run

    async def test_a_list_saved_with_a_mistake_opens_to_be_corrected(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            path = listed(directory)
            good = path.read_text(encoding="utf-8")
            path.write_text(good[:-3], encoding="utf-8")  # saved with a mistake

            def corrected(command, check=False):
                Path(command[-1]).write_text(good, encoding="utf-8")
                return SimpleNamespace(returncode=0)

            chat, run = await self.edit(directory, corrected)
        self.assertEqual(run.call_args.args[0], ["an-editor", str(path)])
        self.assertEqual(chat.notes[-1].split(" ·")[0], "1 enabled models")

    async def test_a_mistake_left_in_says_how_to_correct_it(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            path = listed(directory)
            path.write_text(path.read_text(encoding="utf-8")[:-3], encoding="utf-8")
            chat, run = await self.edit(directory, lambda command, check=False: SimpleNamespace(returncode=0))
        run.assert_called_once()
        self.assertIn("/models opens it again", chat.notes[-1])


class LeaveTests(unittest.TestCase):
    def press(self, chat, times):
        handler = chat._keys_bound().get_bindings_for_keys(("c-c",))[-1].handler
        app = SimpleNamespace(exit=mock.Mock())
        for _ in range(times):
            handler(SimpleNamespace(app=app))
        return app.exit

    def test_ctrl_c_twice_leaves_while_the_agent_works(self):
        chat = bare(conversation=SimpleNamespace(pause=lambda: None), status="RUNNING", interrupted=False,
                    buffer=Buffer(), armed={}, ask=None)
        exit = self.press(chat, 2)
        exit.assert_called_once()
        self.assertTrue(chat.interrupted)  # the first press interrupted the agent

    def test_ctrl_c_once_does_not_leave(self):
        chat = bare(conversation=SimpleNamespace(pause=lambda: None), status="RUNNING", interrupted=False,
                    buffer=Buffer(), armed={}, ask=None)
        self.press(chat, 1).assert_not_called()

    def test_a_lost_host_stops_showing_the_conversation_as_working(self):
        chat = bare(status="RUNNING", interrupted=True, ask=None, generation=3)
        chat._lost(3, "(the session host at http://127.0.0.1:1 does not answer)")
        self.assertNotEqual(chat.status, "RUNNING")
        self.assertIn("does not answer", chat.notes[-1])


if __name__ == "__main__":
    unittest.main()
