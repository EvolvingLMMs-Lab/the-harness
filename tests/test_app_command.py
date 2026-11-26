"""The `harness` command in a terminal (packages/app/harness_app/shell.py): which one a terminal
runs and whether it is this install's, and the desktop app's own on the PATH. The user's PATH
and the registry's environment are never touched: the folders are temporary, the registry is
faked, and the one test that writes the registry writes a key of its own."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401  (source paths)

sys.path.insert(0, str(helpers.ROOT / "packages" / "app"))

from harness import __version__  # noqa: E402
from harness_app import shell  # noqa: E402

WINDOWS = sys.platform.startswith("win")
NAME = "harness.exe" if WINDOWS else "harness"


class Folders(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def install(self, name, content):
        """A harness command file in the folder `name`, with those bytes."""
        file = self.root / name / NAME
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
        file.chmod(0o755)
        return file

    def terminal(self, *folders, own=()):
        """command() for a terminal whose PATH is those folders, this install's files being `own`."""
        with mock.patch.object(shell, "terminal_path", return_value=[str(self.root / name) for name in folders]), \
                mock.patch.object(shell, "own_commands", return_value=list(own)), \
                mock.patch.object(shell, "_version", return_value="0.80.0") as asked:
            found = shell.command()
        return found, asked


class WhichHarnessTests(Folders):
    def test_this_installs_command_first_is_mine(self):
        mine = self.install("app", b"this install")
        self.install("old", b"another install")
        found, asked = self.terminal("empty", "app", "old", own=[mine])
        self.assertEqual((found["path"], found["mine"], found["version"], found["fix"]), (str(mine), True, __version__, ""))
        asked.assert_not_called()  # nothing is run to learn this install's own version

    def test_another_install_first_is_named_with_its_version_and_what_to_do(self):
        mine = self.install("app", b"this install")
        other = self.install("old", b"another install")
        found, _ = self.terminal("old", "app", own=[mine])
        self.assertEqual((found["path"], found["mine"], found["version"], found["own"]), (str(other), False, "0.80.0", str(mine)))
        self.assertTrue(found["on_path"])  # there, but not the one a terminal takes
        for said in (str(other), "0.80.0", __version__, "uninstall the-harness", str(mine)):
            self.assertIn(said, found["fix"])

    def test_a_copy_or_a_link_of_this_installs_command_is_mine(self):
        """uv and pipx put a copy or a link of the console script into their own bin folder."""
        mine = self.install("env", b"console script of this install")
        self.install("bin", b"console script of this install")
        found, _ = self.terminal("bin", own=[mine])
        self.assertTrue(found["mine"])
        self.install("bin", b"console script of another one")
        found, _ = self.terminal("bin", own=[mine])
        self.assertFalse(found["mine"])

    def test_no_harness_on_the_path_says_how_to_get_one(self):
        mine = self.install("app", b"this install")
        found, _ = self.terminal("empty", own=[mine])
        self.assertEqual((found["path"], found["mine"], found["own"], found["on_path"]), (None, False, str(mine), False))
        self.assertIn(str(mine.parent), found["fix"])
        found, _ = self.terminal("empty")  # a source checkout: python -m harness
        self.assertEqual(found["own"], None)
        self.assertIn("python -m harness", found["fix"])

    def test_another_install_is_asked_its_version_without_this_installs_python_variables(self):
        """The host runs with a PYTHONPATH of this install: under it the other harness would
        import this install's code and answer with this version."""
        other = self.install("old", b"another install")
        done = mock.Mock(returncode=0, stdout="harness 0.80.0\n")
        shell._versions.clear()
        with mock.patch.dict(os.environ, {"PYTHONPATH": "this install", "PYTHONHOME": "x", "HARNESS_DATA": "kept"}), \
                mock.patch.object(shell.subprocess, "run", return_value=done) as ran:
            self.assertEqual(shell._version(other), "0.80.0")
            self.assertEqual(shell._version(other), "0.80.0")  # asked once: the answer stands a minute
        self.assertEqual(ran.call_count, 1)
        self.assertEqual(ran.call_args.args[0], [str(other), "--version"])
        env = ran.call_args.kwargs["env"]
        self.assertFalse([name for name in env if name.upper().startswith("PYTHON")])
        self.assertEqual(env["HARNESS_DATA"], "kept")
        shell._versions.clear()
        with mock.patch.object(shell.subprocess, "run", side_effect=OSError("cannot run")):
            self.assertIsNone(shell._version(other))
        shell._versions.clear()

    @unittest.skipUnless(WINDOWS, "the order of executable extensions is Windows's")
    def test_in_one_folder_the_systems_extension_order_decides(self):
        exe = self.install("both", b"exe")
        (self.root / "both" / "harness.cmd").write_text("@echo off\n", encoding="ascii")
        with mock.patch.dict(os.environ, {"PATHEXT": ".COM;.EXE;.BAT;.CMD"}):
            self.assertEqual(shell.commands([str(self.root / "both")]), [exe])
        with mock.patch.dict(os.environ, {"PATHEXT": ".CMD;.EXE"}):
            self.assertEqual([file.name for file in shell.commands([str(self.root / "both")])], ["harness.cmd"])


class UserPathTests(unittest.TestCase):
    """Windows: the user's PATH in the registry, faked: (value as written, type)."""

    def setUp(self):
        self.kept = ["", shell._EXPANDED_TEXT]
        self.told = []
        for patch in (mock.patch.object(shell, "_read_path", side_effect=lambda machine=False: tuple(self.kept)),
                      mock.patch.object(shell, "_write_path", side_effect=lambda value, kind: self.kept.__setitem__(slice(None), [value, kind])),
                      mock.patch.object(shell, "_broadcast", side_effect=lambda: self.told.append(True)),
                      mock.patch.object(shell.os.path, "normcase", side_effect=str.lower)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_folder_is_appended_once_and_what_is_there_stays_as_written(self):
        self.kept[:] = [r"%USERPROFILE%\bin;C:\Tools", shell._TEXT]
        self.assertTrue(shell.path_add(r"C:\Apps\The Harness\runtime\bin"))
        self.assertEqual(self.kept, [r"%USERPROFILE%\bin;C:\Tools;C:\Apps\The Harness\runtime\bin", shell._TEXT])
        self.assertEqual(len(self.told), 1)  # running programs are told once
        # there already, however it is spelled: nothing is written, nothing is told
        for spelled in (r"C:\Apps\The Harness\runtime\bin", r"c:\apps\the harness\runtime\bin" + "\\", r'"C:\Apps\The Harness\runtime\bin"'):
            self.assertFalse(shell.path_add(spelled))
        self.assertEqual(len(self.told), 1)

    def test_an_empty_path_and_one_ending_in_a_separator(self):
        self.assertTrue(shell.path_add(r"C:\A\bin"))
        self.assertEqual(self.kept, [r"C:\A\bin", shell._EXPANDED_TEXT])
        self.kept[:] = ["C:\\Tools;", shell._EXPANDED_TEXT]
        shell.path_add(r"C:\A\bin")
        self.assertEqual(self.kept[0], "C:\\Tools;C:\\A\\bin")

    def test_only_the_folder_is_taken_out(self):
        self.kept[:] = [r"%USERPROFILE%\bin;C:\A\bin;C:\Tools;c:\a\BIN" + "\\", shell._EXPANDED_TEXT]
        self.assertTrue(shell.path_remove(r"C:\A\bin"))
        self.assertEqual(self.kept, [r"%USERPROFILE%\bin;C:\Tools", shell._EXPANDED_TEXT])
        self.assertFalse(shell.path_remove(r"C:\A\bin"))
        self.assertEqual(len(self.told), 1)


@unittest.skipUnless(WINDOWS, "the registry is Windows's")
class RegistryTests(unittest.TestCase):
    def test_the_path_value_is_written_and_read_back_in_a_key_of_the_tests_own(self):
        import winreg

        key = rf"Software\TheHarnessTests\{os.getpid()}"
        self.addCleanup(lambda: [winreg.DeleteKey(winreg.HKEY_CURRENT_USER, each)
                                 for each in (key, r"Software\TheHarnessTests")])
        with mock.patch.object(shell, "_USER_ENV", key), mock.patch.object(shell, "_broadcast"):
            self.assertEqual(shell._read_path(), ("", shell._EXPANDED_TEXT))
            self.assertTrue(shell.path_add(r"%LOCALAPPDATA%\The Harness\runtime\bin"))
            self.assertTrue(shell.path_add(r"C:\Tools"))
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as opened:
                self.assertEqual(winreg.QueryValueEx(opened, "Path"),
                                 (r"%LOCALAPPDATA%\The Harness\runtime\bin;C:\Tools", winreg.REG_EXPAND_SZ))
            self.assertFalse(shell.path_add(os.path.expandvars(r"%LOCALAPPDATA%\The Harness\runtime\bin")))
            self.assertTrue(shell.path_remove(os.path.expandvars(r"%LOCALAPPDATA%\The Harness\runtime\bin")))
            self.assertEqual(shell._read_path(), (r"C:\Tools", winreg.REG_EXPAND_SZ))


class AppCommandTests(Folders):
    """`shell.py command on|off|status`, as the installers run it through the shell's --path."""

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = shell.main(["command", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_on_windows_the_launchers_folder_goes_on_the_users_path_and_off_again(self):
        mine = self.install("app/runtime/bin", b"launcher")
        calls = []
        with mock.patch.object(shell, "_windows", return_value=True), mock.patch.object(shell, "launcher", return_value=mine), \
                mock.patch.object(shell, "path_add", side_effect=lambda folder: calls.append(("add", folder))), \
                mock.patch.object(shell, "path_remove", side_effect=lambda folder: calls.append(("remove", folder))), \
                mock.patch.object(shell, "command", return_value={"path": str(mine), "mine": True, "version": "1", "own": str(mine),
                                                                  "this": "1", "fix": ""}):
            self.assertEqual(self.run_main("on")[0], 0)
            self.assertEqual(self.run_main("off")[0], 0)
        self.assertEqual(calls, [("add", str(mine.parent)), ("remove", str(mine.parent))])

    def test_the_report_names_another_harness_for_the_installers_finish_page(self):
        report = self.root / "report.txt"
        other = {"path": r"C:\Users\名字\.local\bin\harness.exe", "mine": False, "version": "0.80.0", "own": "x", "this": "1",
                 "fix": "remove it"}
        with mock.patch.object(shell, "command", return_value=other):
            code, out, _ = self.run_main("status", "--report", str(report))
        self.assertEqual(code, 0)
        self.assertEqual(report.read_bytes().decode("utf-16-le").splitlines(), [other["path"], "0.80.0"])
        self.assertIn("remove it", out)
        mine = {**other, "mine": True, "fix": ""}
        with mock.patch.object(shell, "command", return_value=mine):
            code, out, _ = self.run_main("status", "--report", str(report), "--json")
        self.assertEqual(report.read_bytes().decode("utf-16-le").splitlines(), ["", ""])
        self.assertTrue(json.loads(out)["mine"])

    def test_without_the_apps_launcher_there_is_nothing_to_put_on_the_path(self):
        with mock.patch.object(shell, "launcher", return_value=None):
            code, _, err = self.run_main("on")
        self.assertEqual(code, 1)
        self.assertIn("no harness command of the desktop app", err)

    @unittest.skipIf(WINDOWS, "links need a privilege on Windows; the link is macOS's")
    def test_on_macos_the_command_is_a_link_that_never_replaces_anothers_file(self):
        mine = self.install("The Harness.app/Contents/Resources/runtime/bin", b"launcher")
        link = self.root / "local" / "bin" / "harness"
        with mock.patch.object(shell, "LINK", link), mock.patch.object(shell.sys, "platform", "darwin"), \
                mock.patch.object(shell, "launcher", return_value=mine), mock.patch.object(shell, "command", return_value={}):
            shell.command_on()
            self.assertTrue(link.is_symlink() and os.path.samefile(link, mine))
            shell.command_on()  # again: nothing to do
            shell.command_off()
            self.assertFalse(link.exists() or link.is_symlink())
            link.write_text("another program", encoding="utf-8")
            with self.assertRaises(ValueError):
                shell.command_on()
            shell.command_off()  # not the app's link: left alone
            self.assertEqual(link.read_text(encoding="utf-8"), "another program")


if __name__ == "__main__":
    unittest.main()
