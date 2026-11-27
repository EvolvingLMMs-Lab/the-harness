"""Crash-consistency for atomic_write (fsync before replace) and graceful recovery
when a chat meta.json or skill origin.json was zero-filled by a sudden reboot."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
from harness.core import atomic_write
from harness_agent.chats import Chats, MAIN
from harness_agent.learning import Learning
from harness_agent.state import Identity


class AtomicWriteAndRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = mock.patch.dict(os.environ, {
            "HARNESS_HOME": str(self.root / "home"),
            "HARNESS_DATA": str(self.root / "data"),
        })
        env.start()
        self.addCleanup(env.stop)

    def test_atomic_write_fsyncs_before_os_replace(self):
        target = self.root / "meta.json"
        order = []
        real_fsync = os.fsync
        real_replace = os.replace

        def track_fsync(fd):
            order.append("fsync")
            return real_fsync(fd)

        def track_replace(src, dst):
            order.append("replace")
            return real_replace(src, dst)

        with mock.patch("harness.core.os.fsync", side_effect=track_fsync), \
                mock.patch("harness.core.os.replace", side_effect=track_replace):
            atomic_write(target, '{"ok": true}\n')

        self.assertEqual(order, ["fsync", "replace"])
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"ok": True})

    def test_zero_filled_chat_meta_recovers_without_breaking_listing(self):
        ident = Identity("default")
        chats = Chats(ident)
        chat_id = chats.new("Original title")
        chats.record(chat_id, "user", text="Check repo status and branches", from_owner=True)
        # Simulate NTFS crash zero-fill of one chat's meta.json (same length, all null bytes).
        meta_path = chats.folder(chat_id) / "meta.json"
        meta_path.write_bytes(b"\x00" * 199)

        listed = chats.listing()
        by_id = {row["chat"]: row for row in listed}
        self.assertIn(MAIN, by_id)
        self.assertIn(chat_id, by_id)
        self.assertEqual(by_id[chat_id]["title"], "Check repo status and branches")
        self.assertEqual(by_id[chat_id]["kind"], "new")

        # Main chat with zero-filled meta.json also recovers cleanly on ensure().
        (chats.folder(MAIN) / "meta.json").write_bytes(b"\x00" * 120)
        reopened = Chats(ident)
        self.assertEqual(reopened.meta(MAIN)["kind"], "main")

    def test_zero_filled_skill_origin_does_not_crash_skills_listing(self):
        ident = Identity("default")
        skill_dir = ident.directory / "skills" / "audit_repo"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text("---\nname: audit_repo\ndescription: Audit repo\n---\nBody\n",
                                            encoding="utf-8")
        (skill_dir / "origin.json").write_bytes(b"\x00" * 84)

        learning = Learning(mock.Mock(identity=ident, clock=lambda: 1700000000.0))
        rows = learning.skills()
        names = [row["name"] for row in rows]
        self.assertIn("audit_repo", names)


if __name__ == "__main__":
    unittest.main()
