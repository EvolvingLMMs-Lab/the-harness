"""Actual macOS PTY reflow, without opening a terminal window or calling a model."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("tmux"), "macOS and tmux are required")
class MacResizeTests(unittest.TestCase):
    def test_resize_keeps_scrollback_and_complete_wide_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            submitted = root / "submitted.json"
            script = root / "chat.py"
            source = os.environ.get("HARNESS_TEST_SOURCE", str(Path(__file__).resolve().parents[1] / "src"))
            script.write_text(
                "import json,sys\nfrom pathlib import Path\n"
                f"sys.path.insert(0, {source!r})\n"
                "from harness.tui.chat import Chat\n"
                "chat=Chat()\n"
                "for number in range(18): chat.note('TRANSCRIPT_'+str(number))\n"
                f"chat.submit=lambda text: Path({str(submitted)!r}).write_text(json.dumps(text))\n"
                "chat.run()\n", encoding="utf-8")
            socket = "harness-test-" + uuid.uuid4().hex[:10]
            base = ["tmux", "-f", "/dev/null", "-L", socket]
            env = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
            env.update(TERM="xterm-256color", HARNESS_DATA=str(root / "data"), HARNESS_HOME=str(root / "cache"))

            def call(*args):
                return subprocess.check_output([*base, *args], env=env, text=True)

            def wait_for(predicate):
                deadline = time.monotonic() + 8
                last = ""
                while time.monotonic() < deadline:
                    last = call("capture-pane", "-p", "-t", "test")
                    if predicate(last):
                        return last
                    time.sleep(.05)
                self.fail("terminal did not reach expected state:\n" + last)

            def separators(text):
                return [line for line in text.splitlines() if line and set(line) == {"─"}]

            def displayed_draft(screen):
                lines = screen.splitlines()
                rules = [index for index, line in enumerate(lines) if line and set(line) == {"─"}]
                return "".join(line[2:] for line in lines[rules[0] + 1:rules[1]])

            try:
                call("new-session", "-d", "-s", "test", "-x", "100", "-y", "32",
                     shlex.join([sys.executable, str(script)]))
                initial = wait_for(lambda s: "what should it do?" in s)
                self.assertEqual(len(separators(initial)), 2, "initial prompt:\n" + initial)
                for boundary in ("A" * 96 + "中", "A" * 95 + "e\u0301", "A" * 96 + "😀"):
                    with self.subTest(boundary=boundary[-3:]):
                        call("send-keys", "-t", "test", "-l", boundary)
                        screen = wait_for(lambda s: boundary[-1] in s)
                        self.assertEqual(displayed_draft(screen), boundary, screen)
                        self.assertNotIn("\u00a0", screen)
                        call("send-keys", "-t", "test", "C-u")
                        wait_for(lambda s: "what should it do?" in s)
                draft = "BEGIN_" + "这是窗口缩放时保留的中文草稿。" * 10 + "_END"
                call("send-keys", "-t", "test", "-l", draft)
                drafted = wait_for(lambda s: "_END" in s)
                self.assertEqual(len(separators(drafted)), 2, "before the first resize:\n" + drafted)
                self.assertEqual(displayed_draft(drafted), draft, drafted)
                for width, height in ((60, 24), (100, 32), (80, 24), (60, 24), (100, 32)):
                    call("resize-window", "-t", "test", "-x", str(width), "-y", str(height))
                    # _END also occurs in the terminal's temporary reflow of
                    # the old frame. Wait for an actual new-width repaint.
                    screen = wait_for(lambda s: len(separators(s)) == 2
                                      and all(len(rule) == width for rule in separators(s))
                                      and displayed_draft(s) == draft)
                    with self.subTest(width=width, height=height):
                        self.assertEqual(len(separators(screen)), 2, screen)
                        history = call("capture-pane", "-p", "-S", "-200", "-t", "test")
                        for number in range(18):
                            self.assertEqual(history.splitlines().count(f"TRANSCRIPT_{number}"), 1, history)
                        self.assertIn("BEGIN_", screen)
                        self.assertIn("_END", screen)
                        self.assertEqual(displayed_draft(screen), draft, screen)
                        self.assertNotIn("\u00a0", screen)
                call("send-keys", "-t", "test", "Enter")
                deadline = time.monotonic() + 3
                while not submitted.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(json.loads(submitted.read_text()), draft)
                wait_for(lambda s: "what should it do?" in s)
                joined = "ZWJ_👩\u200d💻_END"
                call("send-keys", "-t", "test", "-l", joined)
                screen = wait_for(lambda s: "_END" in s)
                self.assertEqual(displayed_draft(screen), joined, screen)
                self.assertNotIn("\u00a0", screen)
            finally:
                subprocess.run([*base, "kill-server"], env=env, capture_output=True)

    def test_joiner_edits_across_frames_preserve_original_output(self):
        source = os.environ.get("HARNESS_TEST_SOURCE", str(Path(__file__).resolve().parents[1] / "src"))

        def frames(primed):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                painted = root / "painted.json"
                script = root / "chat.py"
                override = "" if primed else (
                    "from harness.tui import renderer\n"
                    "renderer._ReflowOutput.write=lambda self,text:self._output.write(text)\n")
                script.write_text(
                    "import json,sys\nfrom pathlib import Path\n"
                    f"sys.path.insert(0, {source!r})\n" + override +
                    "from harness.tui.chat import Chat\nchat=Chat()\n"
                    f"chat.app.after_render += lambda app: Path({str(painted)!r}).write_text(json.dumps(chat.buffer.text))\n"
                    "chat.run()\n", encoding="utf-8")
                base = ["tmux", "-f", "/dev/null", "-L", "harness-joiner-" + uuid.uuid4().hex[:10]]
                env = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
                env.update(TERM="xterm-256color", HARNESS_DATA=str(root / "data"), HARNESS_HOME=str(root / "cache"))

                def call(*args):
                    return subprocess.check_output([*base, *args], env=env, text=True)

                def wait_painted(text):
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        try:
                            if json.loads(painted.read_text()) == text:
                                return
                        except (FileNotFoundError, json.JSONDecodeError):
                            pass
                        time.sleep(.02)
                    self.fail(f"no completed repaint for {text!r}")

                try:
                    call("new-session", "-d", "-s", "test", "-x", "100", "-y", "32",
                         shlex.join([sys.executable, str(script)]))
                    wait_painted("")
                    result = []
                    for piece, expected in (("👩", "👩"), ("\u200d", "👩\u200d"), ("💻", "👩\u200d💻"),
                                            (None, "👩\u200d"), ("💻", "👩\u200d💻")):
                        if piece is None:
                            call("send-keys", "-t", "test", "BSpace")
                        else:
                            call("send-keys", "-t", "test", "-l", piece)
                        wait_painted(expected)
                        result.append((call("capture-pane", "-p", "-t", "test"),
                                       call("display-message", "-p", "-t", "test", "#{cursor_x},#{cursor_y}")))
                    return result
                finally:
                    subprocess.run([*base, "kill-server"], env=env, capture_output=True)

        # Preserve even the toolkit's existing edit limitations; priming must
        # not add visible blanks or change the original cursor positioning.
        self.assertEqual(frames(primed=True), frames(primed=False))


if __name__ == "__main__":
    unittest.main()
