"""The terminal shows no dollars and settings set no dollar limit: only OpenRouter reports
what a call cost, so a total read $0 on every other provider. Records keep cost_usd."""
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import helpers  # noqa: F401  (source paths)
from rich.console import Console
from harness import settings, transcript
from harness.core.lanes import Lanes
from harness.host.sessions import spent
from harness.tui.chat import Chat

REPLY = {"event": "model_reply", "call": 0, "text": "Done.", "seconds": 2.0,
         "usage": {"input_tokens": 120, "output_tokens": 30, "cost_usd": 0.0342, "finish_reason": "stop"}}
REPORT = {"event": "agent_report", "agent": "a1", "status": "finished", "result": "ok",
          "model_calls": 3, "cost_usd": 0.25, "seconds": 4.0}


def texts(record):
    return [item["text"] for item in transcript.items(record, {}, timeline=True)]


class CostHiddenTests(unittest.TestCase):
    def test_timeline_lines_have_tokens_and_calls_but_no_dollars(self):
        reply, report = texts(REPLY), texts(REPORT)
        self.assertTrue(any("120 in / 30 out tokens" in text for text in reply))
        self.assertTrue(any("3 calls" in text for text in report))
        self.assertFalse(any("$" in text for text in reply + report), reply + report)

    def test_session_cell_counts_calls_only(self):
        self.assertEqual(spent({"model_calls": 3, "cost_usd": 0.5}), "3 calls")
        self.assertEqual(spent({"model_calls": 1, "cost_usd": 0.01}), "1 call")
        self.assertEqual(spent(None), "")

    def test_status_line_shows_no_spending(self):
        chat = Chat.__new__(Chat)
        chat.lanes, chat.names, chat.said = Lanes(), {}, None
        chat.program = chat.host = chat.conversation = chat.ask = chat.learning = chat.environment = None
        chat.details_open, chat.status, chat.starting = False, "IDLE", None
        chat.model, chat.workspace = "deepseek/deepseek-v4.1-flash", None
        chat.console = Console(file=io.StringIO(), width=120, force_terminal=False)
        chat.app = SimpleNamespace(invalidate=Mock())
        chat.show(REPLY)
        chat.show(REPORT)
        line = "".join(text for _, text in chat._status())
        self.assertIn("deepseek/deepseek-v4.1-flash", line)
        self.assertNotIn("$", line)

    def test_no_dollar_limit_setting(self):
        self.assertNotIn("max_cost_usd", settings.defaults()["limits"])
        with self.assertRaises(ValueError):
            settings.check("limits", "max_cost_usd", 1.0)


if __name__ == "__main__":
    unittest.main()
