"""A package made for another harness version costs its own environments, not every
conversation, and the user is told which one and how to fix it."""
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import helpers  # noqa: F401
from harness import cli, extensions
from harness.host import Host
from harness.host.client import RemoteError
from harness.host.tasks import TaskHost, TaskServer
from harness.host.workspaces import Workspaces, WorkspaceProvider, incompatible, package_problems


class Lab(WorkspaceProvider):
    def __init__(self, directory, settings):
        pass
    def kinds(self): return ("lab",)
    def kind(self, requested=None, text=None): return "lab"
    def bench(self, kind): return "lab-bench"
    def tree(self, tree, kind): return tree
    def acquire(self, run, kind, **waiting): return None
    def close(self): pass


class Before:
    """A provider as packages wrote it before WorkspaceProvider (computer 0.5.14): no
    describe, accepts, bind or environment."""
    def __init__(self, directory, settings):
        pass
    def kinds(self): return ("browser", "desktop")
    def kind(self, requested=None, text=None): return requested or "browser"
    def bench(self, kind): return "computer"
    def tree(self, tree, kind): return tree
    def acquire(self, run, kind, log, evict=None, cancelled=None): return None
    def of(self, run): return None
    def release(self, run): pass
    def status(self): return {}
    def restart(self): return 0
    def close(self): pass


class Broken(Lab):
    def __init__(self, directory, settings):
        raise OSError("its display is gone")


def package(name, version="0.1.0", host=None):
    return SimpleNamespace(name=name, version=version, provides={"host": [host]} if host else {})


class ProviderFitTests(unittest.TestCase):
    def test_a_provider_from_before_the_contract_does_not_fit(self):
        problem = incompatible(Before)
        self.assertIn("lacks accepts, bind", problem)
        self.assertIn("harness version", problem)
        self.assertEqual(incompatible(Lab), "")

    def test_an_old_package_leaves_out_its_own_environments_only(self):
        hosts = [(package("computer", "0.5.14"), SimpleNamespace(Workspaces=Before)),
                 (package("lab"), SimpleNamespace(Workspaces=Lab))]
        with tempfile.TemporaryDirectory() as directory, mock.patch("harness.extensions.hosts", return_value=hosts), \
                mock.patch("harness.extensions.host_problems", return_value={}):
            workspaces = Workspaces(directory, None)
            with mock.patch("sys.stderr"):
                offered = [row["value"] for row in workspaces.environments()]
            self.assertEqual(offered, ["none", "lab"])
            self.assertEqual(list(workspaces.problems), ["computer"])
            self.assertTrue(workspaces.problems["computer"].endswith(": harness install --update"))
            with self.assertRaises(ValueError) as raised:
                workspaces.provider("browser")
            self.assertIn("computer 0.5.14 was skipped", str(raised.exception))

    def test_a_provider_that_fails_to_start_is_left_out_with_its_reason(self):
        hosts = [(package("display"), SimpleNamespace(Workspaces=Broken)),
                 (package("lab"), SimpleNamespace(Workspaces=Lab))]
        with tempfile.TemporaryDirectory() as directory, mock.patch("harness.extensions.hosts", return_value=hosts), \
                mock.patch("harness.extensions.host_problems", return_value={}):
            workspaces = Workspaces(directory, None)
            with mock.patch("sys.stderr"):
                self.assertEqual(workspaces.kinds(), ("lab", "none"))
            self.assertIn("its display is gone", workspaces.problems["display"])

    def test_doctor_reports_what_the_host_would_leave_out(self):
        hosts = [(package("computer", "0.5.14"), SimpleNamespace(Workspaces=Before))]
        with mock.patch("harness.extensions.hosts", return_value=hosts), \
                mock.patch("harness.extensions.host_problems", return_value={}):
            self.assertIn("computer", package_problems())
            report = {"ok": True, "problems": [], "packages": [{"name": "computer"}]}
            cli._package_problems(report)
        self.assertFalse(report["ok"])
        self.assertTrue(report["problems"][0].endswith(": harness install --update"))
        self.assertIn("computer 0.5.14 was skipped", report["packages"][0]["problem"])


class HostModuleTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        (root / "fit_good_host.py").write_text("class Marker:\n    pass\n", encoding="utf-8")
        (root / "fit_old_host.py").write_text("from harness.sdk import a_name_it_no_longer_has\n", encoding="utf-8")
        sys.path.insert(0, str(root))
        self.addCleanup(sys.path.remove, str(root))
        for name in ("fit_good_host", "fit_old_host"):
            self.addCleanup(sys.modules.pop, name, None)
        extensions._CACHE.clear()
        self.addCleanup(extensions._CACHE.clear)
        self.addCleanup(extensions._PROBLEMS.clear)

    def test_a_host_module_that_does_not_import_is_left_out_with_its_reason(self):
        found = [package("good", host="fit_good_host"), package("old", "0.4.2", host="fit_old_host")]
        for item, path in zip(found, ("good", "old")):
            item.path = path
        with mock.patch("harness.paths.packages", return_value=found):
            loaded = extensions.hosts()
        self.assertEqual([item.name for item, _ in loaded], ["good"])
        problem = extensions.host_problems()["old"]
        self.assertIn("old 0.4.2 was skipped", problem)
        self.assertIn("ImportError", problem)
        self.assertTrue(problem.endswith(": harness install --update"))

    def test_doctor_finds_a_host_module_that_does_not_import_in_a_new_process(self):
        found = [package("old", "0.4.2", host="fit_old_host")]
        found[0].path = "old"
        with mock.patch("harness.paths.packages", return_value=found):
            self.assertIn("ImportError", package_problems()["old"])


class AnswerTests(unittest.TestCase):
    """A request that fails in an unexpected way is answered with what went wrong."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with mock.patch.dict(os.environ, {"HARNESS_DATA": folder.name, "OPENROUTER_API_KEY": "test-no-network"}):
            self.app = TaskHost(Path(folder.name))
        self.addCleanup(self.app.close)
        server = TaskServer(("127.0.0.1", 0), self.app, token="test")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.host = Host(f"http://127.0.0.1:{server.server_port}", "test")

    def test_a_post_that_fails_unexpectedly_says_why(self):
        failure = AttributeError("'Workspaces' object has no attribute 'describe'")
        with mock.patch.object(self.app, "start", side_effect=failure), mock.patch("sys.stderr"):
            with self.assertRaises(RemoteError) as raised:
                self.host.post("/api/tasks", {"text": "hello", "workspace": "none"})
        self.assertIn("AttributeError", str(raised.exception))
        self.assertIn("describe", str(raised.exception))

    def test_a_get_that_fails_unexpectedly_says_why_and_the_host_goes_on(self):
        with mock.patch.object(self.app, "environments", side_effect=TypeError("not iterable")), \
                mock.patch("sys.stderr"):
            with self.assertRaises(RemoteError) as raised:
                self.host.get("/api/app/environments")
        self.assertIn("TypeError: not iterable", str(raised.exception))
        self.assertIn("options", self.host.get("/api/app/environments"))


if __name__ == "__main__":
    unittest.main()
