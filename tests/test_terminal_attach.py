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
        self.exercise()

    def test_resize_refusal_does_not_turn_normal_attach_into_an_error(self):
        self.exercise(resize_refused=True)

    def exercise(self, resize_refused=False):
        import pty
        import fcntl
        import struct
        import termios

        with tempfile.TemporaryDirectory() as directory:
            received = Path(directory) / "input.jsonl"
            sizes = Path(directory) / "sizes.jsonl"
            script = '''
import json, sys, time
from harness.tui.pty import attach
class Conversation:
    run = 'test'
    agent = {"capabilities": {"terminal_resize": True}}
    def records(self, after, stop):
        assert after == 4
        yield {"event": "terminal_output", "text": "\\x1b[2J\\x1b[HNative interface\\r\\n"}
        while not stop.wait(.05):
            pass
    def terminal_input(self, text):
        with open(sys.argv[1], 'a') as f:
            f.write(json.dumps(text) + '\\n')
    def terminal_resize(self, columns, rows):
        with open(sys.argv[2], 'a') as f:
            f.write(json.dumps([columns, rows]) + '\\n')
        if sys.argv[3] == 'refuse':
            raise RuntimeError('the terminal ended while resizing')
class Host:
    def get(self, path):
        return [{"seq": 4, "event": "terminal_output", "text": "\\x1b]11;?\\x07\\x1b[6nEarlier output\\r\\n"}]
attach(Conversation(), Host())
'''
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            original = termios.tcgetattr(slave)
            process = subprocess.Popen([sys.executable, "-c", script, str(received), str(sizes),
                                        'refuse' if resize_refused else 'resize'], stdin=slave, stdout=slave, stderr=slave)
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
                deadline = time.monotonic() + 3
                while not sizes.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(json.loads(sizes.read_text().splitlines()[0]), [80, 24])
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 19, 61, 0, 0))
                deadline = time.monotonic() + 3
                if not resize_refused:
                    while len(sizes.read_text().splitlines()) < 2 and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertEqual([json.loads(line) for line in sizes.read_text().splitlines()], [[80, 24], [61, 19]])
                os.write(master, "你好".encode() + b"\r\x03")
                deadline = time.monotonic() + 5
                while not received.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                os.write(master, b"\x1d")
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertEqual("".join(json.loads(line) for line in received.read_text().splitlines()), "你好\r\x03")
                if resize_refused:
                    self.assertEqual(len(sizes.read_text().splitlines()), 1)
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
