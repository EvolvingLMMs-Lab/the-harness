"""Hosted terminals receive actual viewport dimensions, without desktop interaction."""
import os
from pathlib import Path
import select
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import helpers  # noqa: F401
from harness.host.client import RemoteConversation
from harness.host.http import Handler
from harness_external_agents.terminal import PosixTerminal, TerminalSession


class ResizeContractTests(unittest.TestCase):
    def test_client_and_host_forward_size_to_declared_terminal_control(self):
        conversation = RemoteConversation("http://local", "unused", "run")
        with patch.object(conversation, "_post") as post:
            conversation.terminal_resize(90, 30)
        post.assert_called_once_with("terminal/resize", columns=90, rows=30)
        handler = SimpleNamespace(_control=Mock(), _json=Mock())
        body = {"run": "run", "columns": 90, "rows": 30}
        Handler.post_conversations_terminal_resize(handler, body)
        handler._control.assert_called_once_with(body, "terminal_resize", "terminal_resize", 90, 30)

    def test_invalid_size_is_rejected_before_touching_terminal(self):
        session = object.__new__(TerminalSession)
        for columns, rows in ((0, 20), (80, -1), (True, 24), (80, 24.5), (32768, 24)):
            with self.subTest(columns=columns, rows=rows), self.assertRaises(ValueError):
                session.terminal_resize(columns, rows)


@unittest.skipUnless(os.name == "posix", "requires a native POSIX PTY")
class NativeResizeTests(unittest.TestCase):
    def test_resize_before_launch_sets_the_first_frame_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = "import os; print('INITIAL', tuple(os.get_terminal_size(0)), flush=True)"
            session = TerminalSession(root / "trace", "terminal:test", root,
                                      [sys.executable, "-u", "-c", code], {})
            self.assertTrue(session.capabilities["terminal_resize"])
            session.terminal_resize(71, 23)
            session.open("", ())
            from harness.core.episodes import read_records

            output = "".join(row.get("text", "") for row in read_records(session.directory)
                             if row.get("event") == "terminal_output")
            self.assertIn("INITIAL (71, 23)", output)

    def test_running_child_observes_new_terminal_size(self):
        with tempfile.TemporaryDirectory() as directory:
            code = "import os; print('SIZE',tuple(os.get_terminal_size(0)),flush=True); input(); print('RESIZED',tuple(os.get_terminal_size(0)),flush=True)"
            terminal = PosixTerminal([sys.executable, "-u", "-c", code], Path(directory), {})
            def until(marker):
                chunks = b""
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if marker in chunks and b"\n" in chunks.split(marker, 1)[1]:
                        break
                    if select.select([terminal.master], [], [], .1)[0]:
                        chunk = terminal.read()
                        if not chunk:
                            break
                        chunks += chunk
                self.assertIn(marker, chunks)
                return chunks
            try:
                self.assertIn(b"(120, 40)", until(b"SIZE"))
                terminal.resize(61, 19)
                terminal.write(b"\n")
                self.assertIn(b"(61, 19)", until(b"RESIZED"))
                self.assertEqual(terminal.wait(), 0)
            finally:
                terminal.close()


if __name__ == "__main__":
    unittest.main()
