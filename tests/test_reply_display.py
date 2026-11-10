"""Runtime replies reach terminal and shared transcript consumers exactly once."""
import io
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import helpers
from rich.console import Console
from harness import transcript
from harness.core.episodes import read_records
from harness.core.lanes import Lanes
from harness.core.trace import Trace
from harness.runtime.task.run import TaskRun
from harness.tui.chat import Chat


class ReplyDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = TaskRun.__new__(TaskRun)
        self.run.trace = Trace(Path(self.temp.name) / 'trace')
        self.run.summary, self.run.messages = {}, []
        self.run.interactive = True
        self.run._condition = threading.RLock()
        self.run._inbox, self.run._pending_events = [], []
        self.run._revision = 0
        self.run._await_input = Mock()
        self.loop = SimpleNamespace(empties=0, nudged=0, kinds=('python', 'verify', 'finish'),
                                    call=0, thought=None, malformed_from=None,
                                    revision=0, ahead_generation=None)
        self.output = io.StringIO()
        self.chat = Chat.__new__(Chat)
        self.chat.lanes, self.chat.names = Lanes(), {}
        self.chat.said = None
        self.chat.program, self.chat.host = None, None
        self.chat.details_open = False
        self.chat.console = Console(file=self.output, width=120, force_terminal=False)
        self.chat.app = SimpleNamespace(invalidate=Mock())
        self.run.trace.subscribe(self.chat.show)

    def reply(self, text):
        reply = SimpleNamespace(text=text, usage={}, response_id=None, seconds=0, reasoning='')
        kind, parsed = self.run._output(reply, {}, self.loop)
        if kind == 'message':
            self.run._out_message(reply, parsed, self.loop)
        elif kind == 'finish':
            self.run.trace.emit('finish', text=parsed.body)
        self.loop.call += 1
        return kind

    def test_plain_reply_once_in_live_terminal_and_replayed_transcript(self):
        self.assertEqual(self.reply('I can write Python.'), 'message')
        self.assertEqual(self.output.getvalue().count('I can write Python.'), 1)
        records = read_records(self.run.trace.directory)
        rendered = transcript.TextTranscript()
        text = '\n'.join(line for record in records for line in rendered.lines(record))
        self.assertEqual(text.count('I can write Python.'), 1)
        self.assertEqual([r['event'] for r in records], ['model_reply', 'agent_message'])
        self.assertEqual(transcript.answer_of(records[-1]), 'I can write Python.')
        self.run._await_input.assert_called_once()

    def test_same_answer_on_distinct_turns_is_not_swallowed(self):
        for _ in range(2):
            self.reply('Same answer.')
            self.run.trace.emit('user_message', text='Again please.')
        self.assertEqual(self.output.getvalue().count('Same answer.'), 2)

    def test_standalone_and_during_program_messages_remain_visible(self):
        self.reply('Same answer.')
        self.run.trace.emit('agent_message', text='Same answer.')
        self.run.trace.emit('agent_message', text='Same answer.', program='running-program')
        self.assertEqual(self.output.getvalue().count('Same answer.'), 3)

    def test_model_finish_once_after_plain_reply(self):
        self.reply('A clarification.')
        self.assertEqual(self.reply('<finish>Task complete.</finish>'), 'finish')
        self.assertEqual(self.output.getvalue().count('A clarification.'), 1)
        self.assertEqual(self.output.getvalue().count('Task complete.'), 1)

    def test_program_finish_remains_visible(self):
        self.run.trace.emit('finish', text='Program complete.', source='program')
        self.assertEqual(self.output.getvalue().count('Program complete.'), 1)

    def test_unpaired_legacy_model_reply_remains_visible(self):
        self.run.trace.emit('model_reply', text='Legacy answer.')
        self.assertEqual(self.output.getvalue().count('Legacy answer.'), 1)


if __name__ == '__main__':
    unittest.main()
