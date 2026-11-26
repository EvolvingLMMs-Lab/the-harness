"""The online update: the app package's /api/app/update between the page and the desktop shell
(the restart waits while the agent is at work, or interrupts when the owner says so; app.update
reaches the shell), and `harness update` with the terminal chat's notice for a pip install."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)

sys.path.insert(0, str(helpers.ROOT / "packages" / "app"))

from harness import update as core_update  # noqa: E402
from harness.settings import Settings  # noqa: E402
from harness_app import update  # noqa: E402


class FakeServer:
    def __init__(self, directory, busy=(), running=False):
        self.app = SimpleNamespace(directory=Path(directory), settings=Settings(directory))
        self.life = SimpleNamespace(alive=True, busy=set(busy))
        self.background = {"agent": SimpleNamespace(lives={"default": self.life})}
        self._running = running

    def running(self):
        return self._running


class AppUpdateTests(TestCase):
    def setUp(self):
        update.reset()
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.server = FakeServer(self.folder.name)

    def tearDown(self):
        update.reset()
        self.folder.cleanup()

    def shell(self, phase="ready", version="9.9.9"):
        return update.update(self.server, {"action": "shell", "state": {"phase": phase, "version": version, "os": "linux"}})

    def set_mode(self, mode):
        path = Path(self.folder.name) / "config.toml"
        path.write_text(f'[app]\nupdate = "{mode}"\n', encoding="utf-8")

    def test_each_mode_reaches_the_shell(self):
        self.assertEqual(self.shell()["mode"], "default")
        for mode in ("start", "manual", "none", "default"):
            self.set_mode(mode)
            self.assertEqual(self.shell()["mode"], mode)
        self.set_mode("sometimes")
        self.assertEqual(self.shell()["mode"], "default")

    def test_check_is_passed_to_the_shell_once(self):
        self.shell(phase="latest")
        view = update.update(self.server, {"action": "check"})
        self.assertEqual(view["installer"], "desktop")
        self.assertEqual(self.shell(phase="latest")["requests"], ["check"])
        self.assertEqual(self.shell(phase="latest")["requests"], [])

    def test_restart_needs_a_ready_update(self):
        self.shell(phase="downloading")
        with self.assertRaises(ValueError):
            update.update(self.server, {"action": "restart", "chat": "c1"})

    def test_restart_happens_at_once_when_nothing_is_at_work(self):
        self.shell()
        view = update.update(self.server, {"action": "restart", "chat": "c1", "view": "settings:about"})
        self.assertEqual(view["busy"], [])
        self.assertEqual(self.shell()["restart"], {"chat": "c1", "view": "settings:about", "interrupt": False})
        self.assertIsNone(self.shell()["restart"])  # handed over once

    def test_restart_waits_while_the_agent_is_at_work(self):
        self.shell()
        self.server.life.busy = {"main"}
        view = update.update(self.server, {"action": "restart", "chat": "main"})
        self.assertEqual(view["busy"], [{"identity": "default", "chat": "main"}])
        self.assertIsNone(self.shell()["restart"])
        self.assertIsNotNone(update.update(self.server, {})["restart"])  # the page shows it waits
        self.server.life.busy = set()
        self.server._running = True  # a task's session still runs
        self.assertIsNone(self.shell()["restart"])
        self.server._running = False
        self.assertEqual(self.shell()["restart"]["chat"], "main")

    def test_the_owner_may_interrupt_or_cancel(self):
        self.shell()
        self.server.life.busy = {"main"}
        update.update(self.server, {"action": "restart", "chat": "main"})
        update.update(self.server, {"action": "cancel"})
        self.assertIsNone(self.shell()["restart"])
        update.update(self.server, {"action": "restart", "chat": "main", "interrupt": True})
        self.assertEqual(self.shell()["restart"], {"chat": "main", "interrupt": True, "view": None})

    def test_the_tray_restarts_onto_the_chat_the_page_showed(self):
        self.shell()
        update.update(self.server, {"chat": "c7"})  # the page's poll
        update.update(self.server, {"action": "restart"})  # the tray names no chat
        self.assertEqual(self.shell()["restart"]["chat"], "c7")

    def test_dismissing_is_kept_per_version(self):
        self.shell()
        view = update.update(self.server, {"action": "dismiss", "version": "9.9.9"})
        self.assertEqual(view["dismissed"], "9.9.9")
        self.assertEqual(update.update(self.server, {})["dismissed"], "9.9.9")

    def test_without_the_shell_it_is_a_pip_install(self):
        with mock.patch.object(core_update, "latest", return_value={"version": "99.0.0", "checked": 1}):
            view = update.update(self.server, {"action": "check"})
        self.assertEqual(view["installer"], "pip")
        self.assertTrue(view["pip"]["newer"])
        self.assertEqual(view["pip"]["command"], "harness update")
        self.assertIsNone(view["shell"])

    def test_the_app_update_setting_is_declared(self):
        from harness.settings import SCHEMA, check

        with mock.patch("harness.paths.find", return_value=[helpers.ROOT / "packages" / "app" / "settings.toml"]):
            spec = SCHEMA["app"]["update"]
            self.assertEqual(spec.default, "default")
            self.assertEqual(spec.bounds, ("default", "start", "manual", "none"))
            self.assertEqual(check("app", "update", "manual"), "manual")
            with self.assertRaises(ValueError):
                check("app", "update", "always")


class PipUpdateTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = mock.patch.dict(os.environ, {"HARNESS_DATA": self.folder.name})
        self.env.start()
        os.environ.pop(core_update.ENV, None)

    def tearDown(self):
        self.env.stop()
        self.folder.cleanup()

    def test_versions_compare_as_releases(self):
        self.assertTrue(core_update.newer("0.88.0", "0.87.9"))
        self.assertTrue(core_update.newer("0.87.10", "0.87.9"))
        self.assertTrue(core_update.newer("1.0.0", "1.0.0rc1"))
        self.assertFalse(core_update.newer("0.87.0", "0.87.0"))
        self.assertFalse(core_update.newer("", "0.87.0"))

    def test_pypi_is_asked_at_most_once_a_day(self):
        answer = io.BytesIO(json.dumps({"info": {"version": "99.0.0"}}).encode())
        with mock.patch.object(core_update, "urlopen", return_value=answer) as asked:
            self.assertEqual(core_update.latest()["version"], "99.0.0")
            self.assertEqual(core_update.latest()["version"], "99.0.0")
        self.assertEqual(asked.call_count, 1)
        self.assertIn("99.0.0 is available", core_update.notice())
        self.assertIn("harness update", core_update.notice())

    def test_the_terminal_does_not_ask_in_tests_or_when_off(self):
        with mock.patch.dict(os.environ, {core_update.ENV: "1"}):
            os.environ.pop("PYTEST_CURRENT_TEST", None)
            self.assertTrue(core_update.enabled())
            Path(self.folder.name, "config.toml").write_text('[app]\nupdate = "none"\n', encoding="utf-8")
            self.assertFalse(core_update.enabled())
        with mock.patch.dict(os.environ, {core_update.ENV: "0"}):
            said = []
            with mock.patch.object(core_update, "urlopen") as asked:
                core_update.check_in_background(said.append)
            asked.assert_not_called()
            self.assertEqual(said, [])

    def test_the_desktop_apps_copy_is_not_updated_by_pip(self):
        with mock.patch.object(core_update, "bundled", return_value=True), \
                mock.patch.object(core_update.subprocess, "run") as run, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(core_update.main([]), 1)
        run.assert_not_called()
        self.assertIn("desktop app", err.getvalue())

    def test_update_upgrades_with_pip_then_the_packages(self):
        done = SimpleNamespace(returncode=0, stdout="99.0.0\n")
        with mock.patch.object(core_update, "bundled", return_value=False), \
                mock.patch.object(core_update.subprocess, "run", return_value=done) as run, \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(core_update.main([]), 0)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][1:], ["-m", "pip", "install", "--upgrade", "--disable-pip-version-check",
                                           "the-harness"])
        self.assertEqual(commands[-1][1:], ["-m", "harness", "install", "--update"])
        self.assertIn("→ 99.0.0", out.getvalue())

    def test_harness_update_is_a_core_command(self):
        from harness.cli import core_commands

        self.assertIn("update", core_commands())
