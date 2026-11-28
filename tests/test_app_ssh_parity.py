"""End-to-end App API parity tests for SSH projects (probe, browse, tree, file, search,
changes/revert, overview) backed by the real remote bridge script."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import helpers  # noqa: F401
from harness.core import ssh
from harness_agent.life import Life
from harness_agent.state import Identity
from harness_app import host as app_host
from harness_app import overview as overview_mod


def _local_bridge_spawn(target: str, port: int | None) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-u", "-c", "import base64,sys;exec(base64.b64decode(sys.stdin.readline()))"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )


class AppSshParityTests(unittest.TestCase):
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

        self.repo = self.root / "pfs" / "echo_folder" / "weiyang"
        self.repo.mkdir(parents=True, exist_ok=True)
        for args in (
            ["git", "init", "-b", "main"],
            ["git", "config", "user.email", "test@example.com"],
            ["git", "config", "user.name", "Test User"],
        ):
            subprocess.run(args, cwd=str(self.repo), check=True, capture_output=True)
        (self.repo / "main.py").write_text("print('v1')\n", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text("Remote repo rule: use pytest.\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.repo), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(self.repo), check=True, capture_output=True)
        # Dirty change for git parity verification
        (self.repo / "main.py").write_text("print('v2')\n", encoding="utf-8")

        self.ident = Identity("default")
        self.life = Life(self.ident, model=lambda *a, **k: None, tasks=lambda row=None: None)
        self.server = SimpleNamespace(
            background={"agent": SimpleNamespace(life=lambda ident_id=None: self.life)},
            conversations=SimpleNamespace(sessions=lambda: []),
        )
        self.pool = ssh.SshPool(spawn_fn=_local_bridge_spawn)
        self.addCleanup(self.pool.close_all)

    def test_full_ssh_workbench_parity_and_remote_instructions(self):
        with mock.patch.object(ssh, "POOL", self.pool), \
                mock.patch.object(overview_mod, "_cached_prs", return_value=[]):
            # 1. Step 1 Probe & Step 2 Browse arbitrary non-home folder
            probed = app_host.ssh_probe(self.server, {"host": "gpu-node", "identity": "default"})
            self.assertTrue(probed["ok"])
            self.assertIn("home", probed)

            browsed = app_host.ssh_browse(self.server, {"host": "gpu-node", "path": str(self.repo.parent)})
            by_name = {f["name"]: f for f in browsed["folders"]}
            self.assertIn("weiyang", by_name)
            self.assertTrue(by_name["weiyang"]["git"])

            # 2. Connect SSH project at arbitrary remote path & bind chat
            row = self.life.ssh_project("gpu-node", str(self.repo))
            self.assertEqual(row["title"], "weiyang @ gpu-node")
            chat = self.life.chats.new("SSH task")
            self.life.work_in(chat, row["id"])

            # Probe again: recent_folders now includes this opened path
            probed2 = app_host.ssh_probe(self.server, {"host": "gpu-node", "identity": "default"})
            self.assertIn(str(self.repo), probed2["recent_folders"])

            # 3. Overview reports real remote git branch, dirty count, +/- lines, and changes tool available
            snap = app_host.overview(self.server, {"identity": "default", "chat": chat})
            self.assertTrue(snap["workspace"]["ssh"])
            self.assertTrue(snap["workspace"]["is_git"])
            self.assertEqual(snap["workspace"]["branch"], "main")
            self.assertEqual(snap["workspace"]["dirty_count"], 1)
            tools = {t["id"]: t for t in snap["tools"]}
            self.assertTrue(tools["changes"]["available"])
            self.assertEqual(tools["changes"]["badge"], 1)
            self.assertTrue(tools["files"]["available"])

            # 4. File tree, file viewer, @ search
            tree = app_host.place_tree(self.server, {"identity": "default", "chat": chat})
            self.assertTrue(tree["ssh"])
            entries = {e["name"]: e for e in tree["entries"]}
            self.assertEqual(entries["main.py"]["status"], "M")

            fv = app_host.place_file(self.server, {"identity": "default", "chat": chat, "path": "main.py"})
            self.assertIn("v2", fv["text"])

            srch = app_host.place_search(self.server, {"identity": "default", "chat": chat, "q": "main"})
            self.assertEqual([m["path"] for m in srch["matches"]], ["main.py"])

            # 5. Review/Changes diff + single-file revert
            chg = app_host.place_changes(self.server, {"identity": "default", "chat": chat})
            self.assertTrue(chg["ssh"])
            self.assertEqual([f["path"] for f in chg["files"]], ["main.py"])
            self.assertIn("print('v2')", chg["files"][0]["diff"])

            reverted = app_host.place_changes(self.server, {"identity": "default", "chat": chat, "action": "revert", "path": "main.py"})
            self.assertEqual(reverted["files"], [])
            self.assertEqual((self.repo / "main.py").read_text(encoding="utf-8"), "print('v1')\n")

            # 6. Agent notes include remote SSH context & remote AGENTS.md
            notes = self.life.notes(chat)
            self.assertIn("remote SSH project", notes)
            self.assertIn("Remote repo rule: use pytest.", notes)


if __name__ == "__main__":
    unittest.main()
