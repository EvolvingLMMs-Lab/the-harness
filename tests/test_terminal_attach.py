"""A real local PTY exercises the native attach boundary without model calls."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(os.name == "posix", "POSIX terminal frontend")
class TerminalAttachTest(unittest.TestCase):
    def test_native_output_input_and_detach_restore_terminal(self):
        import pty
        import termios

        with tempfile.TemporaryDirectory() as directory:
            received = Path(directory) / "input.jsonl"
            script = '''
import json, sys, time
from harness.tui.pty import attach
class Conversation:
    run = 'test'
    def records(self, after, stop):
        assert after == 4
        yield {"event": "terminal_output", "text": "\\x1b[2J\\x1b[HNative interface\\r\\n"}
        while not stop.wait(.05):
            pass
    def terminal_input(self, text):
        with open(sys.argv[1], 'a') as f:
            f.write(json.dumps(text) + '\\n')
class Host:
    def get(self, path):
        return [{"seq": 4, "event": "terminal_output", "text": "\\x1b]11;?\\x07\\x1b[6nEarlier output\\r\\n"}]
attach(Conversation(), Host())
'''
            master, slave = pty.openpty()
            original = termios.tcgetattr(slave)
            process = subprocess.Popen([sys.executable, "-c", script, str(received)], stdin=slave, stdout=slave, stderr=slave)
            output = b""
            try:
                deadline = time.monotonic() + 10
                while b"Native interface" not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]:
                        output += os.read(master, 65536)
                self.assertIn(b"\x1b[2J\x1b[HNative interface", output)
                self.assertIn(b"Earlier output", output)
                self.assertNotIn(b"\x1b]11;?", output)
                self.assertNotIn(b"\x1b[6n", output)
                os.write(master, "你好".encode() + b"\r\x03")
                deadline = time.monotonic() + 5
                while not received.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                os.write(master, b"\x1d")
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertEqual("".join(json.loads(line) for line in received.read_text().splitlines()), "你好\r\x03")
                restored = termios.tcgetattr(slave)
                if sys.platform == "darwin":
                    # Darwin sets this pending-input marker when canonical input is
                    # restored, even after a plain setraw/tcsetattr round trip.
                    restored[3] &= ~termios.PENDIN
                    original[3] &= ~termios.PENDIN
                self.assertEqual(restored, original)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)
                os.close(slave)


if __name__ == "__main__":
    unittest.main()
