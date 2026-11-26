"""A conversation's lines show no dollars and the core's settings set no dollar limit: only
OpenRouter reports what a call cost, so a total read $0 on every other provider. Records keep
cost_usd. The one place with dollars is an agent identity's spending (spending.py), which
counts calls without a price apart instead of as $0."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import helpers  # noqa: F401  (source paths)
from harness import settings, transcript
from harness.host.sessions import spent
from test_tui_recovery import chat as bare_chat

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
        chat = self.chat()
        line = "".join(text for _, text in chat._status())
        self.assertIn("deepseek/deepseek-v4.1-flash", line)
        self.assertNotIn("$", line)

    def test_status_line_shows_the_identitys_spending_today(self):
        import tempfile
        from harness.spending import Account
        with tempfile.TemporaryDirectory() as folder:
            account = Account(folder)
            account.charge(SimpleNamespace(model="m"), {"cost_usd": 0.4567})
            account.charge(SimpleNamespace(model="local", base_url="http://127.0.0.1:8000/v1"), {})
            chat = self.chat()
            chat.identity = {"id": "work", "name": "工作", "account": folder}
            line = "".join(text for _, text in chat._status())
        self.assertIn("工作 (work) · today $0.46 · 1 unpriced calls", line)

    def test_usage_command_shows_and_raises_today(self):
        import tempfile
        from harness.spending import Account
        with tempfile.TemporaryDirectory() as folder:
            account = Account(folder)
            account.set_limits(1.0, 500)
            account.charge(SimpleNamespace(model="m"), {"cost_usd": 1.25}, {"kind": "task", "id": "r1", "title": "fix CI"})
            chat = self.chat()
            chat.identity = {"id": "work", "name": "work", "account": folder}
            printed = []
            chat._print = lambda *lines: printed.extend(str(line) for line in lines)
            chat.do_usage("")
            self.assertIn("$1.25 of $1.00", printed[0])
            self.assertTrue(any("Limit reached" in line for line in printed))
            self.assertTrue(any("fix CI" in line for line in printed))
            chat.do_usage("raise 3")
            self.assertIn("$1.25 of $3.00 (raised for today)", printed[-2] if "task" in printed[-1] else printed[-1])
            self.assertIsNone(account.refusal())
            chat.identity = None
            notes = []
            chat.note = lambda text, style="dim": notes.append(text)
            chat.do_usage("")
            self.assertIn("per agent identity", notes[0])

    def chat(self):
        chat = bare_chat(status="IDLE", model="deepseek/deepseek-v4.1-flash")
        chat.app = SimpleNamespace(invalidate=Mock(),
                                   output=SimpleNamespace(get_size=lambda: SimpleNamespace(columns=160)))
        chat.show(REPLY)
        chat.show(REPORT)
        return chat

    def test_no_dollar_limit_setting(self):
        self.assertNotIn("max_cost_usd", settings.defaults()["limits"])
        with self.assertRaises(ValueError):
            settings.check("limits", "max_cost_usd", 1.0)


if __name__ == "__main__":
    unittest.main()
