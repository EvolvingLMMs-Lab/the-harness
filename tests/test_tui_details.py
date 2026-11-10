"""Details close with the same key and never become permanent chat output."""
import asyncio
import io
from types import SimpleNamespace
import unittest
from unittest import mock
import helpers
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console
from rich.text import Text
from harness.tui.chat import Chat
from harness.tui import views


class DetailsTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_reader_opens_and_closes_twice_with_control_o(self):
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            for _ in range(2):
                task = asyncio.create_task(views.read('Program details', lambda: 'secret detail', close_key='c-o'))
                await asyncio.sleep(.05)
                self.assertFalse(task.done())
                pipe.send_text('\x0f')
                await asyncio.wait_for(task, 2)

    async def test_details_and_live_output_stay_separate(self):
        chat = Chat.__new__(Chat)
        chat.details_open, chat.details_output = False, []
        output = io.StringIO()
        chat.console = Console(file=output, force_terminal=False, width=80)
        chat.app = SimpleNamespace(output=DummyOutput())
        program = {'number': 1, 'code': 'print("DETAIL_MARKER")', 'lexer': 'python',
                   'details': [Text('program output')], 'status': 'ok', 'seconds': 1}

        async def show(coroutine):
            before = output.getvalue()
            chat._print(Text('new assistant answer'))
            self.assertEqual(output.getvalue(), before)
            await coroutine

        async def reader(title, text, **options):
            self.assertIn('DETAIL_MARKER', text())
            program['details'].append(Text('live detail'))
            self.assertIn('live detail', text())
            self.assertEqual(options['close_key'], 'c-o')

        chat._view = show
        with mock.patch('harness.tui.chat.views.read', side_effect=reader):
            await chat._show_details(program)
            await chat._show_details(program)
        self.assertFalse(chat.details_open)
        self.assertEqual(chat.details_output, [])
        self.assertNotIn('DETAIL_MARKER', output.getvalue())
        self.assertEqual(output.getvalue().count('new assistant answer'), 2)


if __name__ == '__main__':
    unittest.main()
