"""The npm launcher preserves a child's exit status, including POSIX signals."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest


NODE = os.environ.get("HARNESS_TEST_NODE") or shutil.which("node")
LAUNCHER = Path(__file__).resolve().parents[1] / "npm/bin/harness.js"


@unittest.skipUnless(os.name == "posix" and NODE, "POSIX signals and Node.js are required")
class LauncherExitTests(unittest.TestCase):
    def launch(self, body, *, parent_signal=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready = root / "ready"
            interpreter = root / "python"
            interpreter.write_text(
                f"#!{sys.executable}\nimport os, signal, sys, time\n"
                "if '-c' in sys.argv:\n    print('3.12')\n    sys.exit(0)\n"
                + body + "\n", encoding="utf-8")
            interpreter.chmod(0o755)
            env = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
            env.update(HARNESS_PYTHON=str(interpreter), AUDIT_READY=str(ready))
            child = subprocess.Popen([NODE, str(LAUNCHER)], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                if parent_signal is not None:
                    import time

                    deadline = time.monotonic() + 5
                    while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(ready.exists(), "the interpreter never started")
                    child.send_signal(parent_signal)
                output, error = child.communicate(timeout=5)
                return child.returncode, output, error
            finally:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=5)

    def test_child_signal_is_not_reported_as_success(self):
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            with self.subTest(signal=sig):
                code, _, _ = self.launch(f"signal.signal({int(sig)}, signal.SIG_DFL)\nos.kill(os.getpid(), {int(sig)})")
                self.assertEqual(code, -sig)

    def test_parent_termination_reaches_child_and_keeps_signal_status(self):
        code, _, _ = self.launch("open(os.environ['AUDIT_READY'], 'w').close()\ntime.sleep(30)",
                                 parent_signal=signal.SIGTERM)
        self.assertEqual(code, -signal.SIGTERM)

    def test_numeric_exit_status_is_preserved(self):
        code, _, _ = self.launch("sys.exit(37)")
        self.assertEqual(code, 37)


if __name__ == "__main__":
    unittest.main()
