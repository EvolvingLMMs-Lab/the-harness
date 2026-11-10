"""The command line's own flags."""

import contextlib
import io
import unittest

import helpers  # noqa: F401  (the repository on sys.path)

from harness import __version__  # noqa: E402
from harness.cli import main  # noqa: E402


class VersionTest(unittest.TestCase):
    def test_version_prints_the_core_version_and_exits_cleanly(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            main(["--version"])
        self.assertEqual(stop.exception.code, 0)
        self.assertEqual(out.getvalue(), f"harness {__version__}\n")


if __name__ == "__main__":
    unittest.main()
