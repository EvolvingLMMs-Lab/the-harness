"""Real Windows console reflow, not a simulated screen or renderer mock.

Run on Windows with prompt_toolkit, rich and pywinpty installed. The child opens
the actual Chat layout without starting a model or touching an existing session.
"""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unittest

import helpers  # noqa: F401


def child(directory):
    import asyncio
    import ctypes
    from ctypes import wintypes
    from prompt_toolkit.application import in_terminal
    from prompt_toolkit.win32_types import COORD
    from harness.tui.chat import Chat

    root = Path(directory)
    chat = Chat()
    app = chat.app
    kernel = ctypes.windll.kernel32
    kernel.GetStdHandle.restype = wintypes.HANDLE
    handle = kernel.GetStdHandle(-11)
    kernel.ReadConsoleOutputCharacterW.argtypes = [
        wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, COORD, ctypes.POINTER(wintypes.DWORD)]

    def snapshot(sequence):
        info = app.output.get_win32_screen_buffer_info()
        rows = []
        for y in range(info.dwSize.Y):
            buf = ctypes.create_unicode_buffer(info.dwSize.X + 1)
            read = wintypes.DWORD()
            if not kernel.ReadConsoleOutputCharacterW(handle, buf, info.dwSize.X, COORD(0, y), ctypes.byref(read)):
                raise ctypes.WinError()
            if buf.value.strip():
                rows.append([y, buf.value.rstrip()])
        value = dict(sequence=sequence, size=[info.dwSize.X, info.dwSize.Y], rows=rows,
                     text=chat.buffer.text, cursor=chat.buffer.cursor_position)
        temporary = root / 'response.tmp'
        temporary.write_text(json.dumps(value), encoding='utf-8')
        temporary.replace(root / 'response.json')

    async def commands():
        sequence = 0
        while True:
            await asyncio.sleep(.05)
            request = root / 'request.json'
            if not request.exists():
                continue
            value = json.loads(request.read_text(encoding='utf-8'))
            if value['sequence'] <= sequence:
                continue
            sequence = value['sequence']
            if 'text' in value:
                chat.buffer.text = value['text']
                chat.buffer.cursor_position = value.get('cursor', len(value['text']))
            if 'ask' in value:
                chat.ask = value['ask']
                app.invalidate()
            if 'print' in value:
                async with in_terminal():
                    print(value['print'], flush=True)
            if value.get('exit'):
                app.exit()
                return
            # Include both the ordinary refresh and resize-poll paths.
            await asyncio.sleep(.65)
            snapshot(sequence)

    async def main():
        await app.run_async(pre_run=lambda: app.create_background_task(commands()))

    asyncio.run(main())


@unittest.skipUnless(sys.platform == 'win32', 'requires real Windows console reflow')
class ResizeTests(unittest.TestCase):
    def setUp(self):
        from winpty import PtyProcess

        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        env = dict(os.environ)
        env['PYTHONPATH'] = os.pathsep.join(sys.path)
        self.process = PtyProcess.spawn([sys.executable, str(Path(__file__).resolve()), '--child', str(self.root)],
                                        dimensions=(30, 120), env=env)
        self.sequence = 0
        self.output = []

        def drain():
            try:
                while self.process.isalive():
                    self.output.append(self.process.read(4096))
            except (EOFError, OSError):
                pass

        self.reader = threading.Thread(target=drain, daemon=True)
        self.reader.start()
        self.addCleanup(self.close)
        self.request()

    def close(self):
        self.process.close(force=True)
        self.reader.join(timeout=2)
        self.directory.cleanup()

    def request(self, **values):
        self.sequence += 1
        temporary = self.root / 'request.tmp'
        temporary.write_text(json.dumps(dict(sequence=self.sequence, **values)), encoding='utf-8')
        temporary.replace(self.root / 'request.json')
        end = time.monotonic() + 10
        while time.monotonic() < end:
            response = self.root / 'response.json'
            if response.exists():
                value = json.loads(response.read_text(encoding='utf-8'))
                if value['sequence'] == self.sequence:
                    return value
            if not self.process.isalive():
                self.fail('terminal child exited: ' + ''.join(self.output))
            time.sleep(.03)
        self.fail('terminal child timed out: ' + ''.join(self.output))

    def check_screen(self, snapshot, text='', marker=None):
        rules = [y for y, line in snapshot['rows'] if line and set(line) == {'─'}]
        self.assertEqual(len(rules), 2, snapshot['rows'])
        self.assertEqual(snapshot['text'], text)
        if text:
            painted = ''.join(line[2:] for y, line in snapshot['rows'] if rules[0] < y < rules[1])
            # The input scrolls to the cursor when wrapped text exceeds its
            # allocated height. Its visible suffix must still be real input.
            self.assertTrue(painted.strip(), snapshot['rows'])
            self.assertTrue(re.sub(r'\s', '', text).endswith(re.sub(r'\s', '', painted)), snapshot['rows'])
        if marker:
            self.assertEqual(sum(marker in line for _, line in snapshot['rows']), 1, snapshot['rows'])

    def test_width_cycles_preserve_input_and_transcript(self):
        marker = 'TRANSCRIPT_MUST_SURVIVE'
        self.check_screen(self.request(**{'print': marker}), marker=marker)
        for text in ['', 'draft ' * 25 + '\nsecond line', '中文输入' * 25 + '\nlast line']:
            self.request(text=text)
            for width in [80, 120, 59, 120, 39, 120]:
                self.process.setwinsize(30, width)
                snapshot = self.request()
                self.assertEqual(snapshot['size'], [width, 30])
                self.check_screen(snapshot, text, marker)
                self.assertEqual(snapshot['cursor'], len(text))

    def test_height_changes_and_resize_burst(self):
        for height in [20, 30, 18, 30]:
            self.process.setwinsize(height, 120)
            self.check_screen(self.request())
        for width in [80, 55, 100, 65, 120] * 3:
            self.process.setwinsize(30, width)
            time.sleep(.04)
        self.check_screen(self.request())
        self.check_screen(self.request(**{'print': 'OUTPUT_AFTER_RESIZE'}), marker='OUTPUT_AFTER_RESIZE')

    def test_wide_characters_above_input(self):
        self.request(ask=dict(text='中文' * 40, options=[['yes', 'yes'], ['no', 'no']], at=0))
        for width in [59, 120, 39, 120]:
            self.process.setwinsize(30, width)
            snapshot = self.request()
            self.check_screen(snapshot)
            # The first prompt row must not be stranded above a new copy.
            self.assertEqual(sum('中文' in line for _, line in snapshot['rows']), 1, snapshot['rows'])


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(sys.argv[2])
    else:
        unittest.main()
