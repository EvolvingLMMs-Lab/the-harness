"""Recover invalid environment caches and retry only transient installer failures."""
import json
from importlib import metadata
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from harness.packages import environments
from harness import tui


class EnvironmentRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        patcher = mock.patch.dict(os.environ, {"HARNESS_HOME": str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.env = environments.resolve("test", {"python": "3.11", "requirements": ["example==1"]})

    def test_marker_requires_executable_interpreter_and_repairs_on_first_use(self):
        self.env.directory.mkdir(parents=True)
        marker = self.env.directory / environments.RECORD
        marker.write_text(json.dumps({"hash": self.env.hash}))
        self.assertIsNone(self.env.installed())
        calls = []
        def rebuild(env, out, **kwargs):
            calls.append(env.directory)
            env.python.parent.mkdir(parents=True)
            env.python.write_text("#!/bin/sh\n")
            env.python.chmod(0o755)
        with mock.patch.object(environments, "_install", side_effect=rebuild):
            self.assertIs(environments.on_first_use(self.env, "test", log=lambda _: None), self.env)
            environments.install(self.env, log=lambda _: None)
        self.assertEqual(calls, [self.env.directory])
        self.assertIsNotNone(self.env.installed())
        if os.name != "nt":
            self.env.python.chmod(0o644)
            self.assertIsNone(self.env.installed())
        marker.write_text("[]")
        self.assertIsNone(self.env.installed())

    def fake_run(self, errors, calls):
        def run(argv, **kwargs):
            calls.append([str(item) for item in argv])
            if "venv" in argv:
                self.env.python.parent.mkdir(parents=True, exist_ok=True)
                self.env.python.write_text("#!/bin/sh\n")
                self.env.python.chmod(0o755)
            if "install" in argv:
                error = next(errors)
                kwargs["stdout"].write(error)
                return SimpleNamespace(returncode=bool(error))
            return SimpleNamespace(returncode=0)
        return run

    def run_install(self, failures):
        calls, sleeps, logs = [], [], []
        with mock.patch.object(environments.shutil, "which", return_value="/synthetic/uv"), \
                mock.patch.object(environments.subprocess, "run", side_effect=self.fake_run(iter(failures), calls)), \
                mock.patch.object(environments.time, "sleep", side_effect=sleeps.append):
            try:
                environments.install(self.env, log=logs.append)
            except RuntimeError as error:
                return calls, sleeps, logs, error
        return calls, sleeps, logs, None

    def test_deterministic_and_unknown_install_failures_are_not_retried(self):
        for message in ("No matching distribution found for example==1", "ResolutionImpossible: conflicting dependencies",
                        "Failed building wheel for example", "Permission denied", "unrecognized failure"):
            with self.subTest(message=message):
                calls, sleeps, logs, error = self.run_install([message])
                self.assertEqual(sum("install" in call for call in calls), 1)
                self.assertEqual(sleeps, [])
                self.assertFalse(any("attempt" in line for line in logs))
                self.assertIn(message, str(error))

    def test_transient_failure_reports_retry_and_succeeds(self):
        calls, sleeps, logs, error = self.run_install(["connection reset by peer", ""])
        self.assertIsNone(error)
        self.assertEqual(sum("install" in call for call in calls), 2)
        self.assertEqual(sleeps, [1])
        self.assertTrue(any("attempt 1/3" in line and "connection reset" in line for line in logs))

    def test_transient_retries_are_bounded_and_stop_on_deterministic_failure(self):
        calls, sleeps, logs, error = self.run_install(["request timed out"] * 3)
        self.assertEqual(sum("install" in call for call in calls), 3)
        self.assertEqual(sleeps, [1, 2])
        self.assertIn("request timed out", str(error))
        calls, sleeps, logs, error = self.run_install(["connection reset", "No matching distribution found"])
        self.assertEqual(sum("install" in call for call in calls), 2)
        self.assertEqual(sleeps, [1])

    def test_stale_cache_rebuild_removes_partial_files_and_preserves_source_checkout(self):
        self.env.directory.mkdir(parents=True)
        (self.env.directory / environments.RECORD).write_text(json.dumps({"hash": self.env.hash}))
        (self.env.directory / "partial").write_text("unfinished")
        source = self.root / "user-source"
        source.mkdir()
        (source / "work").write_text("user edits")
        self.env.sources.append(environments.Source("user", source, "unused", "unused", managed=False))
        calls = []
        with mock.patch.object(environments.shutil, "which", return_value="/synthetic/uv"), \
                mock.patch.object(environments.subprocess, "run", side_effect=self.fake_run(iter([""]), calls)):
            environments.on_first_use(self.env, "test", log=lambda _: None)
        self.assertIsNotNone(self.env.installed())
        self.assertFalse((self.env.directory / "partial").exists())
        self.assertEqual((source / "work").read_text(), "user edits")

    def test_frontend_receives_retry_and_failure_details_with_log_path(self):
        calls, logs, sleeps = [], [], []
        with mock.patch.object(environments.shutil, "which", return_value="/synthetic/uv"), \
                mock.patch.object(environments.subprocess, "run", side_effect=self.fake_run(iter(["request timed out"] * 3), calls)), \
                mock.patch.object(environments.time, "sleep", side_effect=sleeps.append):
            with self.assertRaisesRegex(RuntimeError, "request timed out.*see .*install-test.log"):
                environments.on_first_use(self.env, "test", log=logs.append)
        self.assertTrue(any("attempt 1/3" in message for message in logs))
        self.assertTrue(any("attempt 2/3" in message for message in logs))
        self.assertIn("FAILED", (self.root / "logs/install-test.log").read_text())


class TerminalDependencyTests(unittest.TestCase):
    def test_importable_but_incompatible_libraries_do_not_skip_preparation(self):
        before = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), before))
        versions = {item.split("==")[0]: item.split("==")[1] for item in tui.LIBRARIES + tui.PINS}
        calls = []
        def version(name):
            calls.append(name)
            return versions[name] if sys.path[0] == "/managed/site-packages" else "0.0.1"
        env = SimpleNamespace(python="/managed/python", directory="/managed")
        with mock.patch.object(metadata, "version", side_effect=version), \
                mock.patch.object(tui.importlib.util, "find_spec", return_value=object()), \
                mock.patch.object(tui.environments, "on_first_use", return_value=env) as prepare, \
                mock.patch.object(tui.subprocess, "run", return_value=SimpleNamespace(stdout="/managed/site-packages\n")):
            # Other test modules can import these; remove only for this controlled loader test.
            with mock.patch.dict(sys.modules):
                for name in ("prompt_toolkit", "rich", "wcwidth", "markdown_it", "mdurl", "pygments"):
                    sys.modules.pop(name, None)
                tui.load(log=lambda _: None)
            prepare.assert_called_once()
        self.assertEqual(sys.path[0], "/managed/site-packages")
        self.assertLessEqual(len(calls), 7)

    def test_compatible_pins_use_existing_interpreter_without_preparation(self):
        versions = dict(item.split("==") for item in tui.LIBRARIES + tui.PINS)
        with mock.patch.object(metadata, "version", side_effect=versions.__getitem__), \
                mock.patch.object(tui.importlib.util, "find_spec", return_value=object()), \
                mock.patch.object(tui.environments, "on_first_use") as prepare:
            tui.load()
            prepare.assert_not_called()

    def test_loaded_incompatible_modules_report_actionable_restart(self):
        with mock.patch.object(metadata, "version", return_value="0.0.1"), \
                mock.patch.object(tui.importlib.util, "find_spec", return_value=object()), \
                mock.patch.dict(sys.modules, {"prompt_toolkit": object()}), \
                mock.patch.object(tui.environments, "on_first_use") as prepare:
            with self.assertRaisesRegex(RuntimeError, "restart harness.*pip install"):
                tui.load()
            prepare.assert_not_called()
