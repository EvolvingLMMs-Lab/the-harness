"""What the user types in the terminal chat reaches what they meant: a prefilled value is
typed on from its end, a cancelled start leaves an ended conversation ended, an approval is
answered with or without a note, the model list saved with a mistake opens again, the
command list completes names, aliases and words, Ctrl+C twice leaves, and a lost session
host is shown as lost."""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import helpers  # noqa: F401
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from harness.settings import ChoiceRequired
from harness.tui import views
from harness.tui.chat import Completions


from test_tui_recovery import chat as bare


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
        chat = bare(conversation=ended, status="FINISHED", start=start)
        chat.app = SimpleNamespace(loop=asyncio.get_running_loop(), is_running=True, invalidate=lambda: None,
                                   output=DummyOutput())
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

        async def cancelled(choice, settle=0, generation=None):
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
        self.assertTrue(any("could not start" in note for note in chat.notes))
        chat.send("hello again")
        await self.settled(chat)
        self.assertEqual(start.call_count, 2)
        self.assertEqual(chat.sent, [])

    async def test_cancelled_first_conversation_is_still_new(self):
        start = mock.Mock(side_effect=ChoiceRequired(self.CHOICE))
        chat = self.chat(start)
        chat.conversation, chat.status = None, None

        async def cancelled(choice, settle=0, generation=None):
            return None

        chat._choose_environment = cancelled
        chat.send("hello")
        await self.settled(chat)
        self.assertIsNone(chat.status)


class ApprovalAnswerTests(unittest.TestCase):
    """An approval: Enter answers with the option chosen, Esc declines, a note typed after Tab
    goes with either answer."""

    def asked(self):
        conversation = SimpleNamespace(name="open")
        chat = bare(conversation=conversation)
        chat._asked({"what": "Use the folder?", "options": [("once", "Yes"), ("session", "Yes, for this chat"),
                                                             (None, "No")], "request_id": "r1"})
        return chat, conversation

    def test_enter_allows_with_the_option_chosen(self):
        chat, conversation = self.asked()
        chat._choose(1)
        chat._answer(chat.ask["at"])
        self.assertIsNone(chat.ask)
        self.assertEqual(chat.sent[0][1:], (conversation, "approve",
                                            {"remember": "session", "reason": "", "request_id": "r1"}))

    def test_escape_declines_without_a_note(self):
        chat, conversation = self.asked()
        chat._decline()
        self.assertEqual(chat.sent[0][1:], (conversation, "deny", {"reason": "", "request_id": "r1"}))

    def test_a_note_goes_with_the_answer(self):
        chat, conversation = self.asked()
        chat._choose(2)
        chat._note_field()
        self.assertTrue(chat.ask["note"])
        chat.submit("not that folder")  # Enter on the note line
        self.assertEqual(chat.sent[0][1:], (conversation, "deny", {"reason": "not that folder", "request_id": "r1"}))

    def test_the_draft_is_put_aside_and_comes_back(self):
        chat = bare(conversation=SimpleNamespace(name="open"))
        chat.buffer.text = "half a thought"
        chat._asked({"what": "Push?", "options": [("once", "Yes"), (None, "No")], "request_id": "r2"})
        self.assertEqual(chat.buffer.text, "")
        chat._answer(0)
        self.assertEqual(chat.buffer.text, "half a thought")

    def test_an_empty_line_without_a_question_does_nothing(self):
        chat = bare(conversation=None, ask=None)
        chat.submit("   ")
        self.assertEqual((chat.sent, chat.notes), ([], []))


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

        environ = {key: value for key, value in os.environ.items() if key != "VISUAL"}
        with mock.patch("harness.tui.commands.data", return_value=directory), \
                mock.patch("harness.tui.chat.in_terminal", terminal), \
                mock.patch("harness.tui.chat.subprocess.run", side_effect=editor) as run, \
                mock.patch.dict("os.environ", {**environ, "EDITOR": "an-editor"}, clear=True):
            await chat._guarded(chat._edit_models)
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
        self.assertIn("/model opens the list again", chat.notes[-1])


class LeaveTests(unittest.TestCase):
    def press(self, chat, times):
        handler = [found for found in chat._bindings().get_bindings_for_keys(("c-c",)) if found.filter()][-1].handler
        app = SimpleNamespace(exit=mock.Mock())
        for _ in range(times):
            handler(SimpleNamespace(app=app))
        return app.exit

    def test_ctrl_c_twice_leaves_while_the_agent_works(self):
        chat = bare(conversation=SimpleNamespace(pause=lambda: None), status="RUNNING")
        exit = self.press(chat, 2)
        exit.assert_called_once()
        self.assertTrue(chat.interrupted)  # the first press interrupted the agent

    def test_ctrl_c_once_does_not_leave(self):
        chat = bare(conversation=SimpleNamespace(pause=lambda: None), status="RUNNING")
        self.press(chat, 1).assert_not_called()

    def test_ctrl_c_clears_the_draft_and_up_brings_it_back(self):
        chat = bare()
        chat.buffer.text = "a draft"
        self.press(chat, 1).assert_not_called()
        self.assertEqual(chat.buffer.text, "")
        chat._up()
        self.assertEqual(chat.buffer.text, "a draft")

    def test_a_lost_host_stops_showing_the_conversation_as_working(self):
        chat = bare(status="RUNNING", interrupted=True, ask=None, generation=3)
        chat._lost(3, "(the session host at http://127.0.0.1:1 does not answer)")
        self.assertNotEqual(chat.status, "RUNNING")
        self.assertIn("does not answer", chat.notes[-1])


class ApproveCompletionTest(unittest.TestCase):
    def completions(self, text):
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document

        return [found.text for found in Completions().get_completions(Document(text), CompleteEvent())]

    def test_approve_offers_what_it_remembers(self):
        self.assertEqual(self.completions("/approve "), ["app", "session", "always"])

    def test_approve_completes_a_started_word(self):
        self.assertEqual(self.completions("/approve se"), ["session"])

    def test_letters_filter_the_commands_by_name_alias_and_word(self):
        self.assertEqual(self.completions("/mod"), ["/model"])
        self.assertEqual(self.completions("/sett"), ["/config"])       # by its alias
        self.assertEqual(self.completions("/quit"), ["/exit"])
        self.assertIn("/terminal-setup", self.completions("/setup"))   # a word inside the name
        self.assertIn("/terminal-setup", self.completions("/terminalsetup"))  # separators ignored

    def test_nothing_matches_says_so_and_is_no_suggestion(self):
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document

        found = list(Completions().get_completions(Document("/zzz"), CompleteEvent()))
        self.assertEqual([row.display_text for row in found], ['No commands match "/zzz"'])

    def test_rpc_words_are_not_commands_of_the_chat(self):
        from harness.terminal import COMMANDS, find

        self.assertEqual(find("continue")[0], "resume")   # the alias wins over the rpc word
        self.assertEqual(find("pause")[0], "stop")
        self.assertEqual(find("reject")[0], "deny")
        self.assertEqual(COMMANDS["continue"].method, "resume")  # harness run rpc still has it
        self.assertEqual({find(word)[0] for word in ("reset", "new")}, {"clear"})
        self.assertIsNone(find("nope"))


if __name__ == "__main__":
    unittest.main()
