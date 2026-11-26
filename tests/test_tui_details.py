"""The transcript viewer (Ctrl+O): the key that opened it closes it again, as q, Esc and
Ctrl+C do; it shows every step in full (a program's code and its whole output, which the
chat itself only names in one line), the last turns until Ctrl+E shows them all."""
import asyncio
import unittest

import helpers  # noqa: F401
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from harness.tui import views
from test_tui_recovery import chat as bare_chat


class TranscriptTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_reader_opens_and_closes_twice_with_control_o(self):
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            for close in ('\x0f', 'q', '\x1b', '\x03'):
                task = asyncio.create_task(views.read('Transcript', lambda: 'a detail', close=('app:toggleTranscript',)))
                await asyncio.sleep(.05)
                self.assertFalse(task.done())
                pipe.send_text(close)
                await asyncio.wait_for(task, 2)

    async def test_control_e_asks_for_everything(self):
        shown = {'all': False}
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            task = asyncio.create_task(views.read('Transcript', lambda: 'everything' if shown['all'] else 'the last turns',
                                                  toggle=lambda: shown.update(all=not shown['all'])))
            await asyncio.sleep(.05)
            pipe.send_text('\x05')
            await asyncio.sleep(.05)
            self.assertTrue(shown['all'])
            pipe.send_text('q')
            await asyncio.wait_for(task, 2)

    def test_a_program_is_one_line_in_the_chat_and_whole_in_the_transcript(self):
        chat = bare_chat()
        printed = []
        chat._print = lambda *lines: printed.extend(str(getattr(line, 'plain', line)) for line in lines)
        tail = 'x' * 300
        for record in ({'event': 'user_message', 'text': 'count', 'time': 10.0},
                       {'event': 'model_reply', 'call': 0, 'time': 11.0, 'text': '',
                        'presentation': {'kind': 'python', 'thought': '', 'body': 'print("CODE_MARKER")'}},
                       {'event': 'cell', 'time': 12.0, 'result': {'status': 'ok', 'seconds': 1.0,
                                                                  'stdout': '\n'.join([tail] * 30 + ['STDOUT_TAIL'])}}):
            chat.show(record)
        in_chat = '\n'.join(printed)
        self.assertIn('Program 1', in_chat)
        self.assertIn('ctrl+o to expand', in_chat)
        self.assertNotIn('STDOUT_TAIL', in_chat)
        text = chat.transcript_text(True)
        self.assertIn('CODE_MARKER', text)
        self.assertIn('STDOUT_TAIL', text)
        self.assertGreaterEqual(text.count('x'), 300 * 30)

    def test_the_transcript_opens_on_the_last_turns(self):
        chat = bare_chat()
        chat._print = lambda *lines: None
        for number in range(6):
            chat.show({'event': 'user_message', 'text': f'question {number}', 'time': float(number)})
            chat.show({'event': 'agent_message', 'text': f'answer {number}', 'time': number + 0.5})
        last = chat.transcript_text(False)
        self.assertNotIn('question 0', last)
        self.assertIn('question 5', last)
        self.assertIn('question 0', chat.transcript_text(True))


if __name__ == '__main__':
    unittest.main()
