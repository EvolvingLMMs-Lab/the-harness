"""What an agent learned, shared as a package (harness share) and installed from one
(harness install): what goes, the working copy an install makes, and when a later install
keeps it."""

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "src")]

from test_packages import Temporary  # noqa: E402
from harness.packages import archive, sources  # noqa: E402
from harness.packages.libraries import destination  # noqa: E402
from harness.runtime.learning.learner import Learner, candidate, libraries  # noqa: E402
from harness.runtime.learning.library import Library  # noqa: E402

CODE = "def pick():\n    return 1\n"
TEST = "assert pick() == 1\n"


class SharedLibraryTests(Temporary):
    def run_cli(self, *argv):
        from harness.cli import main

        out, err = io.StringIO(), io.StringIO()
        cwd = os.getcwd()
        try:
            os.chdir(self.work)
            with redirect_stdout(out), redirect_stderr(err), mock.patch("sys.stdin", io.StringIO("")):
                code = main(list(argv))
        finally:
            os.chdir(cwd)
        return code, out.getvalue(), err.getvalue()

    def learned(self, name="my_app") -> Path:
        """A library as runs leave it: a tested skill and a reactive entry with their proofs, a
        note, a memory entry, a waiting candidate, and the run folders in its index."""
        folder = self.root / "learned" / name
        learner = Learner(folder, {"learn": "on"}, create=True)
        run = str(self.root / "runs" / "ep1")
        for entry in (candidate("skill", "pick", CODE, TEST, run=run),
                      candidate("reactive", "guard", "set_reflex('guard', lambda view: False)\n", run=run)):
            proof = {"revision": entry.revision().revision, "conditions": {"method": "own_test"}}
            learner.admit(entry, "provisional", proof=proof, test_run={"ok": True, "run": run})
        learner.admit(candidate("note", "save", "Ctrl+S saves."), "proposed")
        learner.store_memory({"id": "memory/desk.md", "name": "desk", "text": "a photo of my desk"})
        learner.admit(candidate("skill", "later", CODE, TEST), "proposed", pending=True)
        return folder

    def test_share_to_a_folder_and_install_a_copy_that_learns(self):
        library = self.learned()
        code, out, err = self.run_cli("share", str(library), str(self.root / "site"), "--yes")
        self.assertEqual(code, 0, err)
        packed = self.root / "site" / "my-app.tar.gz"
        self.assertIn(f"harness install {packed.resolve()}", out)
        with tarfile.open(packed) as tar:
            names = tar.getnames()
            index = tar.extractfile("my-app/libraries/my-app/index.json").read().decode()
        self.assertIn("my-app/libraries/my-app/skills/pick.py", names)
        self.assertIn("my-app/libraries/my-app/reactive/guard.py", names)
        self.assertFalse([name for name in names if "/memory/" in name or "/candidates/" in name], names)
        self.assertNotIn(str(self.root), index)
        self.assertIn('"ep1"', index)

        code, out, err = self.run_cli("install", str(packed), "--yes")
        self.assertEqual(code, 0, err)
        copy = Path(os.environ["HARNESS_HOME"]).resolve() / "libraries" / "my-app"
        self.assertIn(f"library my-app: copied, {copy}", out)
        shared = archive.unpack(packed, self.root / "unpacked") / "libraries" / "my-app"
        self.assertEqual(Library(copy).version(), Library(shared).version())
        loaded = {item.key for item in Library(copy).capture().entries}
        self.assertEqual(loaded, {"skills/pick.py", "reactive/guard.py", "notes/save.md"})
        self.assertEqual([(row["name"], row["package"]) for row in libraries()], [("my-app", "my-app")])
        # The copy is writable: runs keep learning in it.
        Learner(copy, {"learn": "on"}).admit(candidate("note", "more", "Tab moves on."), "proposed")
        self.assertIn("notes/more.md", {item.key for item in Library(copy).capture().entries})

    def test_a_later_install_replaces_the_copy_only_while_no_run_learned_in_it(self):
        library = self.learned()
        site = self.root / "site"
        self.assertEqual(self.run_cli("share", str(library), str(site), "--yes")[0], 0)
        self.assertEqual(self.run_cli("install", str(site / "my-app.tar.gz"), "--yes")[0], 0)
        Learner(library, {"learn": "on"}).admit(candidate("note", "undo", "Ctrl+Z undoes."), "proposed")
        code, _, err = self.run_cli("share", str(library), str(site), "--yes")
        self.assertEqual(code, 0, err)
        code, out, err = self.run_cli("install", str(site / "my-app.tar.gz"), "--yes")
        self.assertIn("my-app 0.1.1", out)
        self.assertIn("library my-app: updated", out)
        copy = Path(os.environ["HARNESS_HOME"]).resolve() / "libraries" / "my-app"
        Learner(copy, {"learn": "on"}).admit(candidate("note", "mine", "My own lesson."), "proposed")
        Learner(library, {"learn": "on"}).admit(candidate("note", "redo", "Ctrl+Y redoes."), "proposed")
        self.assertEqual(self.run_cli("share", str(library), str(site), "--yes")[0], 0)
        code, out, err = self.run_cli("install", str(site / "my-app.tar.gz"), "--yes")
        self.assertIn("library my-app: kept", out + err)
        self.assertTrue((copy / "notes" / "mine.md").is_file())

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_share_to_a_git_remote_and_install_from_it(self):
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
        seed = self.root / "seed"
        subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
        (seed / "README.md").write_text("Our agents.\n", encoding="utf-8")
        for command in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start"],
                        ["push", "-q", str(remote), "main"]):
            subprocess.run(["git", *command], cwd=seed, check=True)
        url = remote.resolve().as_uri()
        identity = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                    "GIT_COMMITTER_EMAIL": "t@t"}
        with mock.patch.dict(os.environ, identity):
            code, out, err = self.run_cli("share", str(self.learned()), f"git:{url}#my-app", "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn(f"harness install git:{url}#my-app", out)
        code, out, err = self.run_cli("install", f"git:{url}#my-app", "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("library my-app: copied", out)

    def test_where_it_goes(self):
        self.assertEqual(sources.parse("https://github.com/alice/mc-agent").url, "https://github.com/alice/mc-agent")
        self.assertEqual(destination("github:alice/agents#mc")["url"], "https://github.com/alice/agents.git")
        self.assertEqual(destination("alice@alice.dev:/var/www/agents")["kind"], "scp")
        self.assertEqual(destination(str(self.root / "site"))["kind"], "file")
        with self.assertRaises(ValueError):
            destination("https://alice.dev/agents")


if __name__ == "__main__":
    unittest.main()
