"""New terminal conversations use the TUI and defer task creation until input."""

import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness import cli


class NewChatTests(unittest.TestCase):
    def setUp(self):
        for target, options in (
            ("harness.cli._ready_model", {}),
            ("harness.cli._package_command", {"side_effect": AssertionError("unexpected package frontend")}),
            ("sys.stdin.isatty", {"return_value": True}),
            ("sys.stdout.isatty", {"return_value": True}),
        ):
            patcher = mock.patch(target, **options)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_new_chat_and_alias_wait_for_first_message(self):
        for words in ([], ["chat"]):
            with self.subTest(words=words), mock.patch("harness.cli._task") as task:
                def display(*args, start, **kwargs):
                    self.assertEqual(args, ())
                    self.assertNotIn("conversation", kwargs)
                    task.assert_not_called()
                    self.assertTrue(callable(start))
                    return None

                with mock.patch("harness.tui.chat", side_effect=display):
                    self.assertEqual(cli.main(words), 0)
                task.assert_not_called()

    def test_first_message_keeps_task_options_and_successful_exit(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch("harness.cli._task") as task:
            host, conversation = object(), object()
            task.return_value = host, conversation

            def display(*, start):
                task.assert_not_called()
                self.assertEqual(start("inspect this folder", ["note.txt"]), (host, conversation))
                return conversation  # A conversation is not a CLI exit status.

            with mock.patch("harness.tui.chat", side_effect=display):
                self.assertEqual(cli.main(["--agent", "harness", "--folder", folder,
                                           "--workspace", "apps", "--think", "off"]), 0)
            task.assert_called_once_with("inspect this folder", "apps", runtime={"think_while_acting": "off"},
                                         files=["note.txt"], log=None, agent="harness", folder=Path(folder).resolve(),
                                         model_entry=None, reasoning_effort=None)

    def test_native_first_message_uses_selected_model(self):
        with mock.patch("harness.model_list.select", return_value={"id": "chosen", "provider": "openrouter"}), \
                mock.patch("harness.cli._task", return_value=(object(), object())) as task:
            def display(*, start):
                return start("hello", model_entry="chosen", reasoning_effort="medium")[1]

            with mock.patch("harness.tui.chat", side_effect=display):
                self.assertEqual(cli.main([]), 0)
            self.assertEqual(task.call_args.kwargs["model_entry"], "chosen")
            self.assertEqual(task.call_args.kwargs["reasoning_effort"], "medium")

    def test_redirected_input_or_output_does_not_open_chat(self):
        for stream in ("stdin", "stdout"):
            with self.subTest(stream=stream), mock.patch(f"sys.{stream}.isatty", return_value=False), \
                    mock.patch("sys.stderr", new_callable=io.StringIO) as errors, \
                    mock.patch("harness.tui.chat") as chat:
                self.assertEqual(cli.main(["--agent", "harness"]), 2)
                self.assertIn("needs a terminal", errors.getvalue())
                chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
