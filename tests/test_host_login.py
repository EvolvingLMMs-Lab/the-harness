"""harness host install / uninstall / status: the login item on each system, read back from the
system (the commands are faked; nothing is registered on the computer running the tests)."""
import contextlib
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import helpers  # noqa: F401  (puts the checkout on the path)
from harness.host import login
from harness import settings


class FakeSystem:
    """The system commands: each call recorded, answered by the first rule whose words match."""

    def __init__(self):
        self.calls = []
        self.answers = []

    def answer(self, words, returncode=0, stdout="", stderr=""):
        self.answers.insert(0, (list(words), returncode, stdout, stderr))

    def __call__(self, command):
        self.calls.append(list(command))
        for words, returncode, stdout, stderr in self.answers:
            if command[:len(words)] == words:
                return subprocess.CompletedProcess(command, returncode, stdout, stderr)
        return subprocess.CompletedProcess(command, 0, "", "")

    def ran(self, *words):
        return [call for call in self.calls if call[:len(words)] == list(words)]


class LoginItemTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.fake = FakeSystem()
        login._cache[:] = [0.0, None]
        environment = {"APPDATA": str(self.root / "roaming"), "XDG_CONFIG_HOME": str(self.root / "config"),
                       "USERNAME": "owner", "USERDOMAIN": "PC"}
        for patch in (mock.patch.object(login, "_run", self.fake),
                      mock.patch.object(login.Path, "home", return_value=self.root / "home"),
                      mock.patch.object(login, "_domain", return_value="gui/501"),
                      mock.patch.object(login.getpass, "getuser", return_value="owner"),
                      mock.patch.dict(os.environ, environment),
                      mock.patch.object(login, "command", return_value=["/opt/py/python3", "-m", "harness.host.login",
                                                                       "run"])):
            patch.start()
            self.addCleanup(patch.stop)

    def on(self, name):
        return mock.patch.object(login, "system", return_value=name)

    def test_windows_scheduled_task_at_logon(self):
        with self.on("windows"):
            made = login.install()
            self.assertEqual(made["kind"], "scheduled task")
            create = self.fake.ran("schtasks", "/Create")[0]
            self.assertEqual(create[create.index("/TN") + 1], login.NAME)
            self.fake.answer(["schtasks", "/Query"], 0, '"\\The Harness host","N/A","Ready"\n')
            self.assertEqual(login.status()["on"], True)
            # Turned off in the system: off here too.
            self.fake.answer(["schtasks", "/Query"], 0, '"\\The Harness host","N/A","Disabled"\n')
            self.assertEqual(login.status()["on"], False)
            # Removed in the system: off, and nothing else is consulted.
            self.fake.answer(["schtasks", "/Query"], 1, "", "ERROR: The system cannot find the file specified.")
            self.assertEqual(login.status(), {"system": "windows", "on": False, "kind": None, "where": None})

    def test_windows_task_definition(self):
        xml = login._task_xml(["C:\\Py\\pythonw.exe", "-m", "harness.host.login", "run", "--data", "C:\\My Data"],
                              "C:\\Py\\Lib\\site-packages")
        self.assertIn("<LogonTrigger>", xml)
        self.assertIn("<UserId>PC\\owner</UserId>", xml)
        self.assertIn("<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>", xml)  # never stopped after 72 hours
        self.assertIn("<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>", xml)
        self.assertIn("<Command>C:\\Py\\pythonw.exe</Command>", xml)
        self.assertIn('<Arguments>-m harness.host.login run --data "C:\\My Data"</Arguments>', xml)

    def test_windows_startup_folder_when_the_task_is_refused(self):
        self.fake.answer(["schtasks", "/Create"], 1, "", "ERROR: Access is denied.")
        self.fake.answer(["schtasks", "/Query"], 1, "", "ERROR: not found")
        with self.on("windows"):
            made = login.install()
            self.assertEqual(made["kind"], "startup folder")
            self.assertIn("Access is denied", made["note"])
            file = Path(made["where"])
            self.assertEqual(file.parent.name, "Startup")
            text = file.read_bytes().decode()
            self.assertIn('start "" /opt/py/python3 -m harness.host.login run\r\n', text)
            with mock.patch.object(login, "_startup_approved", return_value=True):
                self.assertEqual(login.status()["kind"], "startup folder")
                self.assertTrue(login.status()["on"])
            with mock.patch.object(login, "_startup_approved", return_value=False):
                self.assertFalse(login.status()["on"])
            self.assertFalse(login.uninstall()["on"])
            self.assertFalse(file.exists())
            self.assertEqual(self.fake.ran("schtasks", "/Delete"), [])

    def test_macos_launch_agent(self):
        with self.on("macos"):
            made = login.install()
            plist = plistlib.loads(Path(made["where"]).read_bytes())
            self.assertEqual(Path(made["where"]).name, "com.lmms-lab.harness.host.plist")
            self.assertEqual(plist["ProgramArguments"], login.command())
            self.assertTrue(plist["RunAtLoad"])
            self.assertEqual(plist["KeepAlive"], {"SuccessfulExit": False})
            self.assertTrue(self.fake.ran("launchctl", "enable", "gui/501/com.lmms-lab.harness.host"))
            self.assertTrue(login.status()["on"])
            self.fake.answer(["launchctl", "print-disabled"], 0,
                             'disabled services = {\n\t"com.lmms-lab.harness.host" => disabled\n}\n')
            self.assertFalse(login.status()["on"])
            self.assertFalse(login.uninstall()["on"])
            self.assertTrue(self.fake.ran("launchctl", "bootout", "gui/501/com.lmms-lab.harness.host"))
            self.assertFalse(Path(made["where"]).exists())

    def test_linux_user_service_and_linger(self):
        self.fake.answer(["loginctl", "show-user"], 0, "no\n")
        with self.on("linux"):
            made = login.install()
            unit = Path(made["where"])
            self.assertEqual(unit, self.root / "config" / "systemd" / "user" / "harness-host.service")
            text = unit.read_text()
            self.assertIn('ExecStart="/opt/py/python3" "-m" "harness.host.login" "run"', text)
            self.assertIn("WantedBy=default.target", text)
            self.assertIn("Restart=on-failure", text)
            self.assertTrue(self.fake.ran("systemctl", "--user", "enable", "harness-host.service"))
            self.assertIs(made["linger"], False)
            self.fake.answer(["systemctl", "--user", "is-enabled"], 0, "enabled\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), mock.patch("harness.host._reachable", return_value=None):
                self.assertEqual(login.main(["status"]), 0)
            self.assertIn("starts at login: yes", out.getvalue())
            self.assertIn("sudo loginctl enable-linger owner", out.getvalue())
            self.fake.answer(["systemctl", "--user", "is-enabled"], 1, "disabled\n")
            self.assertFalse(login.uninstall()["on"])
            self.assertFalse(unit.exists())

    def test_linux_without_user_services(self):
        self.fake.answer(["systemctl", "--user", "enable"], 1, "", "Failed to connect to bus")
        with self.on("linux"):
            with self.assertRaisesRegex(RuntimeError, "Failed to connect to bus"):
                login.install()
            self.assertFalse(login._unit().exists())
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(login.main(["install"]), 1)
            self.assertIn("not available here", err.getvalue())

    def test_autostart_is_the_login_item(self):
        with self.on("linux"):
            self.fake.answer(["systemctl", "--user", "is-enabled"], 1, "not-found\n")
            self.assertFalse(login.autostart())
            self.assertTrue(login.autostart(True))
            self.assertTrue(self.fake.ran("systemctl", "--user", "enable"))
            self.fake.answer(["systemctl", "--user", "is-enabled"], 0, "enabled\n")
            self.assertTrue(login.autostart())
            with self.assertRaises(ValueError):
                login.autostart("yes")


class CommandTests(unittest.TestCase):
    def test_launcher_given_by_the_shell(self):
        with mock.patch.dict(os.environ, {login.COMMAND_ENV: json.dumps(["/apps/The Harness.AppImage", "--host"]),
                                          "HARNESS_DATA": "/srv/agent-data"}):
            words = login.command()
        self.assertEqual(words[:2], ["/apps/The Harness.AppImage", "--host"])
        self.assertEqual(words[2], "--data")
        with mock.patch.dict(os.environ, {login.COMMAND_ENV: '"not a list"'}):
            with self.assertRaises(ValueError):
                login.command()

    def test_default_runs_the_runner_from_the_package_folder(self):
        with mock.patch.dict(os.environ, {}, clear=False) as environment:
            for name in (login.COMMAND_ENV, "HARNESS_DATA", "HARNESS_HOME"):
                environment.pop(name, None)
            words = login.command()
        self.assertEqual(words[1:], ["-m", "harness.host.login", "run"])
        self.assertTrue((Path(login.directory()) / "harness" / "host" / "login.py").is_file())

    def test_run_leaves_a_running_host_alone(self):
        with mock.patch("harness.host.read_address", return_value={"url": "x", "token": "y"}), \
                mock.patch("harness.host._reachable", return_value=object()), \
                mock.patch.object(login.subprocess, "Popen") as popen:
            self.assertEqual(login.run(), 0)
        popen.assert_not_called()


class FakeHost:
    """The host's process as `run` waits for it: it runs for `seconds` waits, then ends."""

    def __init__(self, code, waits=0):
        self.code, self.waits, self.terminated = code, waits, False

    def wait(self, timeout=None):
        if self.waits and not self.terminated:
            self.waits -= 1
            raise subprocess.TimeoutExpired("host", timeout)
        return self.code

    def terminate(self):
        self.terminated = True


class ShellAnswerTests(unittest.TestCase):
    """What the desktop shell reads: it has no terminal, so `page` and `run` say a failure on
    standard output as {error, fix, code, log}."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        for patch in (mock.patch.dict(os.environ, {"HARNESS_DATA": str(self.data), "HARNESS_HOME": str(self.data / "home")}),
                      mock.patch("harness.host._reachable", return_value=None),
                      mock.patch.object(login.signal, "signal")):
            patch.start()
            self.addCleanup(patch.stop)

    def said(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = login.main(argv)
        return code, out.getvalue()

    def run_host(self, child):
        with mock.patch.object(login.subprocess, "Popen", return_value=child):
            return self.said(["run"])

    def test_page_prints_the_page(self):
        with mock.patch.object(login, "page", return_value={"url": "http://127.0.0.1:1", "token": "t",
                                                           "page": "http://127.0.0.1:1/?token=t"}):
            code, out = self.said(["page"])
        self.assertEqual((code, json.loads(out)["page"]), (0, "http://127.0.0.1:1/?token=t"))

    def test_page_says_why_the_host_did_not_start(self):
        from harness.problems import Problem

        failed = Problem("the session host exited (1) while starting, in the package agent: ImportError: no name X",
                         "update the package (harness install --update agent) or remove it", code="host_exited",
                         log=self.data / "logs" / "host.log")
        with mock.patch.object(login, "page", side_effect=failed):
            code, out = self.said(["page"])
        answer = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(answer["code"], "host_exited")
        self.assertIn("ImportError", answer["error"])
        self.assertIn("harness install --update agent", answer["fix"])
        self.assertTrue(answer["log"].endswith("host.log"))
        # any other error is said the same way, in its own words
        with mock.patch.object(login, "page", side_effect=RuntimeError("The session host runs different code")):
            code, out = self.said(["page"])
        self.assertEqual((code, json.loads(out)["error"]), (1, "The session host runs different code"))

    def test_run_says_why_the_host_it_started_never_answered(self):
        from harness.host import failure_file

        record = failure_file(self.data)
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"time": time.time() + 60, "error": "the session host could not start: ValueError: bad port",
                                      "fix": "harness doctor checks this computer", "code": "host_exited"}), encoding="utf-8")
        code, out = self.run_host(FakeHost(1))
        answer = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual((answer["code"], answer["fix"]), ("host_exited", "harness doctor checks this computer"))
        self.assertIn("ValueError: bad port", answer["error"])
        self.assertTrue(answer["log"].endswith("host.log"))

    def test_run_tells_a_host_that_stopped_later_from_a_failed_start(self):
        with mock.patch("harness.host.read_address", return_value={"started": time.time() + 60}):
            code, out = self.run_host(FakeHost(3, waits=1))
        self.assertEqual((code, json.loads(out)["code"]), (3, "host_stopped"))

    def test_run_says_nothing_of_a_host_that_was_stopped_or_ended_well(self):
        self.assertEqual(self.run_host(FakeHost(0)), (0, ""))
        # another host answers by now (two were started at once): that one serves
        with mock.patch("harness.host._reachable", side_effect=[None, object()]):
            self.assertEqual(self.run_host(FakeHost(1)), (1, ""))


class SettingTests(unittest.TestCase):
    def test_agent_autostart_reads_and_switches_the_system(self):
        if "autostart" not in settings.SCHEMA.get("agent", {}):
            self.skipTest("the agent package is not on this path")
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(login, "autostart", return_value=False) as autostart:
            kept = settings.Settings(Path(folder))
            self.assertIs(kept.get()["agent"]["autostart"], False)
            kept.update({"agent": {"autostart": True}})
            autostart.assert_any_call(True)
            # Never kept in config.toml: the login item is the only record.
            self.assertNotIn("autostart", (settings.read(Path(folder)).get("agent") or {}))
            with self.assertRaises(ValueError):
                kept.update({"agent": {"autostart": "on"}})


if __name__ == "__main__":
    unittest.main()


class LauncherFolderTests(unittest.TestCase):
    def test_the_shells_launcher_runs_in_the_home_folder(self):
        """An AppImage's mount is gone after a restart: the login item must not run inside it."""
        from pathlib import Path
        from harness.host import login

        with mock.patch.dict(os.environ, {login.COMMAND_ENV: '["/tmp/.mount_x/usr/bin/the-harness", "--host"]'}):
            self.assertEqual(login.directory(), str(Path.home()))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(login.COMMAND_ENV, None)
            self.assertNotEqual(login.directory(), str(Path.home()))


class SystemSettingTests(unittest.TestCase):
    def test_a_system_that_cannot_be_asked_does_not_break_the_settings(self):
        """Reading agent.autostart from the system failed on a real machine (no output from
        schtasks): every other setting, the installs and the host must still work."""
        from harness.host import login

        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(login, "_run", return_value=subprocess.CompletedProcess([], 0, None, None)), \
                mock.patch.object(login, "system", return_value="windows"):
            self.assertIn(login.autostart(), (True, False))
            from harness.settings import Settings

            with mock.patch.object(login, "status", side_effect=RuntimeError("cannot ask")):
                values = Settings(Path(folder)).get()
            self.assertIn("general", values)
