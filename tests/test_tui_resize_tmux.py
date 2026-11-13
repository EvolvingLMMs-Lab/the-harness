"""A real terminal (tmux) resized under the chat, without opening a window or calling a model: the
live region leaves no rows behind and the chat stays in the scrollback."""
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


@unittest.skipUnless(os.name == "posix" and shutil.which("tmux"), "a POSIX system with tmux is required")
class TmuxResizeTests(unittest.TestCase):
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

            try:
                call("new-session", "-d", "-s", "test", "-x", "100", "-y", "32",
                     shlex.join([sys.executable, str(script)]))
                wait_for(lambda s: "what should it do?" in s)
                draft = "BEGIN_" + "这是窗口缩放时保留的中文草稿。" * 10 + "_END"
                call("send-keys", "-t", "test", "-l", draft)
                wait_for(lambda s: "_END" in s)
                for width, height in ((60, 24), (100, 32), (80, 24), (60, 24), (100, 32)):
                    call("resize-window", "-t", "test", "-x", str(width), "-y", str(height))
                    # Settled: the live region drawn once at the new size, nothing left of the old one.
                    wait_for(lambda s: "BEGIN_" in s and "_END" in s and len(separators(s)) == 2)
                    time.sleep(.3)
                    screen = call("capture-pane", "-p", "-t", "test")
                    with self.subTest(width=width, height=height):
                        self.assertEqual(len(separators(screen)), 2, screen)
                        self.assertIn("TRANSCRIPT_17", call("capture-pane", "-p", "-S", "-200", "-t", "test"))
                        self.assertIn("BEGIN_", screen)
                        self.assertIn("_END", screen)
                call("send-keys", "-t", "test", "Enter")
                deadline = time.monotonic() + 3
                while not submitted.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(json.loads(submitted.read_text()), draft)
            finally:
                subprocess.run([*base, "kill-server"], env=env, capture_output=True)


if __name__ == "__main__":
    unittest.main()
