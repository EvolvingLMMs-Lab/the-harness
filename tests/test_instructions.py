"""Instruction files (instructions.py): which are read, in what order, within what size, and what
the model gets."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness import instructions


class InstructionFilesTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.data = self.base / "data"
        self.data.mkdir()
        patcher = mock.patch.dict(os.environ, {"HARNESS_DATA": str(self.data)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = self.base / "repo"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / "pkg" / "sub").mkdir(parents=True)

    def write(self, path, text):
        path.write_text(text, encoding="utf-8")

    def test_files_from_the_user_and_the_root_down_to_the_folder(self):
        self.write(self.data / "AGENTS.md", "user rule\n@more.md\n")
        self.write(self.data / "more.md", "imported user rule")
        self.write(self.base / "AGENTS.md", "above the root: never read")
        self.write(self.repo / "AGENTS.md", "root rule\n<!-- for people -->\n`@not-an-import.md`\n")
        self.write(self.repo / "CLAUDE.md", "not read: AGENTS.md comes first")
        self.write(self.repo / "pkg" / "CLAUDE.md", "pkg rule")
        self.write(self.repo / "pkg" / "CLAUDE.local.md", "my local pkg rule")
        loaded = instructions.load(self.repo / "pkg", {})
        self.assertEqual([item.label for item in loaded.files][2:], ["AGENTS.md", "pkg/CLAUDE.md", "pkg/CLAUDE.local.md"])
        text = instructions.block(loaded)
        self.assertTrue(text.startswith(f"# AGENTS.md instructions for {self.repo / 'pkg'}\n\n<INSTRUCTIONS>\n"))
        for part in ("user rule", "imported user rule", "--- project-doc ---", "(from AGENTS.md)\nroot rule",
                     "pkg rule", "my local pkg rule", "`@not-an-import.md`"):
            self.assertIn(part, text)
        for absent in ("above the root", "AGENTS.md comes first", "for people"):
            self.assertNotIn(absent, text)
        self.assertLess(text.index("user rule"), text.index("root rule"))
        self.assertLess(text.index("root rule"), text.index("pkg rule"))

    def test_budget_cuts_and_tells_how_to_read_the_rest(self):
        self.write(self.repo / "AGENTS.md", "x" * 100)
        self.write(self.repo / "pkg" / "AGENTS.md", "never reached")
        loaded = instructions.load(self.repo / "pkg", {"max_bytes": 60})
        self.assertEqual([item.label for item in loaded.files], ["AGENTS.md"])
        self.assertTrue(loaded.files[0].cut)
        self.assertIn("Read it with read_file", loaded.files[0].text)
        self.assertEqual(len(loaded.warnings), 2)

    def test_settings_and_files_below_the_folder(self):
        self.write(self.data / "AGENTS.md", "user rule")
        self.write(self.repo / "AGENTS.md", "root rule")
        self.write(self.repo / "pkg" / "sub" / "AGENTS.md", "sub rule")
        self.assertEqual([item.label for item in instructions.load(self.repo, {"load": "user"}).files],
                         [f"~/{(self.data / 'AGENTS.md').relative_to(Path.home()).as_posix()}"]
                         if self.data.is_relative_to(Path.home()) else [(self.data / "AGENTS.md").as_posix()])
        self.assertEqual(instructions.load(self.repo, {"load": "off"}).files, [])
        self.assertNotIn("sub rule", instructions.block(instructions.load(self.repo, {})))
        told = set()
        found = instructions.nested(self.repo, "pkg/sub/main.py", {}, told)
        self.assertEqual([item.text for item in found], ["sub rule"])
        self.assertEqual(instructions.nested(self.repo, "pkg/sub/other.py", {}, told), [])
