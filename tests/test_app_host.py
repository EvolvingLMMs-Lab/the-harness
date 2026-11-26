"""The app package's part of the session host: its pages and typefaces, an identity's persona
files (only those), a place chat's changes, and the overlay's address; `harness app` prints
the address and opens no browser."""
import io
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)
import sys

sys.path.insert(0, str(helpers.ROOT / "packages" / "app"))

from harness_app import cli, host, overlay  # noqa: E402


def server_with(identities, lives=None):
    service = SimpleNamespace(life=lambda identity: (lives or {})[identity])
    return SimpleNamespace(background={"agent": service}, identities=identities)


class AppHostTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.folder.name)
        self.identity = self.root / "agents" / "default"
        self.identity.mkdir(parents=True)
        (self.identity / "SOUL.md").write_text("Keep it short.\n", encoding="utf-8")
        rows = [{"id": "default", "name": "Yu", "folder": str(self.identity), "current": True}]
        self.agent = mock.patch.object(host, "_agent", lambda name: (lambda server, body: rows) if name == "identities" else None)
        self.agent.start()

    def tearDown(self):
        self.agent.stop()
        self.folder.cleanup()

    def test_pages_are_the_app_and_the_overlay(self):
        self.assertEqual(host.pages, {"/": "index.html", "/overlay": "overlay.html"})
        for page in host.pages.values():
            self.assertTrue((host.STATIC / page).is_file())

    def test_the_typefaces_are_plain_static_files(self):
        css = (host.STATIC / "tokens.css").read_text(encoding="utf-8")
        for face in ("inter-400", "jetbrains-mono-400", "space-grotesk-500"):
            self.assertIn(f"/static/app/archive/fonts/{face}.ttf", css)
            self.assertTrue((host.STATIC / "archive" / "fonts" / f"{face}.ttf").is_file())
        self.assertNotIn("font", host.api)

    def test_the_shell_is_found_where_the_windows_installer_puts_it(self):
        from harness_app import shell

        exe = self.root / "The Harness" / "the-harness.exe"
        exe.parent.mkdir()
        exe.write_bytes(b"")
        with mock.patch.object(shell.sys, "platform", "win32"), mock.patch.object(shell.shutil, "which", return_value=None),                 mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            os.environ.pop("HARNESS_APP_SHELL", None)
            self.assertEqual(shell.find(), exe)

    def test_persona_reads_and_writes_only_the_persona_files(self):
        server = server_with([])
        found = host.persona(server, {"identity": "default"})
        self.assertEqual([f["name"] for f in found["files"]], list(host.PERSONA))
        self.assertEqual(found["files"][1]["text"], "Keep it short.\n")
        host.persona(server, {"identity": "default", "file": "USER.md", "text": "Hikes on weekends.\n"})
        self.assertEqual((self.identity / "USER.md").read_text(encoding="utf-8"), "Hikes on weekends.\n")
        with self.assertRaises(ValueError):
            host.persona(server, {"identity": "default", "file": "identity.json", "text": "{}"})
        with self.assertRaises(ValueError):
            host.persona(server, {"identity": "nobody"})

    def test_a_folder_place_shows_its_changes_and_files_and_a_space_shows_none(self):
        project = self.root / "project"
        project.mkdir()
        (project / "parser.py").write_text("def parse(text):\n    raise ValueError\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
            subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True)
        (project / "parser.py").write_text("def parse(text):\n    return []\n", encoding="utf-8")
        metas = {"place-project": {"kind": "place", "place": "project"}, "place-qq": {"kind": "place", "place": "qq"}}
        places = {"project": SimpleNamespace(kind="folder", row={"kind": "folder", "folder": str(project)}),
                  "qq": SimpleNamespace(kind="space", row={"kind": "space", "address": "ws://x"}, folder=str(self.identity))}
        life = SimpleNamespace(chats=SimpleNamespace(meta=lambda chat: metas.get(chat, {"kind": "main"})), places=places)
        server = server_with([], {"default": life})
        found = host.place(server, {"identity": "default", "chat": "place-project"})
        self.assertEqual(found["folder"], "project")
        self.assertIn("+    return []", found["diff"])
        self.assertEqual([f["name"] for f in found["files"]], ["parser.py"])
        self.assertEqual(host.place(server, {"identity": "default", "chat": "place-qq"})["folder"], None)

    def test_the_overlay_address_carries_the_run_and_options(self):
        address = overlay.address("http://127.0.0.1:8780/", "key", "abc/main", overlay.Options(corner="top-left"))
        self.assertTrue(address.startswith("http://127.0.0.1:8780/overlay?token=key&"))
        self.assertIn("corner=top-left", address)
        self.assertIn("run=abc%2Fmain", address)
        self.assertIn("click_through=true", address)

    def test_overlay_without_the_shell_says_where_the_page_is(self):
        with mock.patch.dict(os.environ, {"HARNESS_APP_SHELL": str(self.root / "missing.exe")}):
            with self.assertRaises(ValueError) as caught:
                overlay.launch("http://127.0.0.1:8780", "key")
        self.assertIn("/overlay?token=key", str(caught.exception))

    def test_harness_app_prints_the_address_and_opens_no_browser(self):
        fake = SimpleNamespace(page=lambda: "http://127.0.0.1:8780/?token=key")
        out = io.StringIO()
        with mock.patch("harness.host.Host.connect", return_value=fake), \
                mock.patch.dict(os.environ, {"HARNESS_APP_SHELL": str(self.root / "missing.exe")}), \
                mock.patch("webbrowser.open") as browser, mock.patch("sys.stdout", out), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(cli.app([]), 0)
        self.assertEqual(out.getvalue().strip(), "http://127.0.0.1:8780/?token=key")
        browser.assert_not_called()

    def test_the_package_manifest_loads(self):
        from harness.packages.manifest import load

        package = load(helpers.ROOT / "packages" / "app")
        self.assertEqual(package.provides["host"], ("harness_app.host",))
        self.assertEqual(set(package.provides["commands"]), {"app", "timeline"})
        self.assertIn("pages", package.provides)
