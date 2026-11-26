"""A failure is said the same everywhere: its reason, its fix, its log (problems.py); the
session host says why it did not start and leaves a faulty package out instead of ending."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from harness import extensions, problems
from harness.host import DATA_FORMAT, check_data, mark_data, stamp_file
from harness.host.client import RemoteError
from harness.problems import Problem

TRACEBACK = '''{"host": "http://127.0.0.1:1"}
Traceback (most recent call last):
  File "/home/me/.cache/harness/packages/agent/0.1.2-7e6bedcd/harness_agent/host.py", line 12, in <module>
    from harness.sdk import SpendingLimit
ImportError: cannot import name 'SpendingLimit' from 'harness.sdk'
'''


class SaidTests(unittest.TestCase):
    def test_a_problem_travels_through_the_api_with_its_fix_and_log(self):
        sent = Problem("the key was refused", "enter another one: harness model", code="key_refused", log="x.log")
        back = RemoteError.of(json.loads(json.dumps(sent.as_dict())))
        self.assertEqual((back.reason, back.fix, back.code, back.log), (sent.reason, sent.fix, "key_refused", "x.log"))
        self.assertEqual(problems.lines(back), ["the key was refused", "enter another one: harness model", "log: x.log"])

    def test_a_person_reads_lines_and_a_program_reads_json(self):
        error = Problem("no model is set up", "run harness setup")
        self.assertEqual(problems.said(error), "harness: no model is set up\n  run harness setup")
        self.assertEqual(json.loads(problems.said(error, program=True)),
                         {"error": "no model is set up", "code": "error", "fix": "run harness setup"})
        self.assertEqual(json.loads(problems.said(ValueError("bad"), program=True)), {"error": "ValueError: bad"})

    def test_a_log_gives_the_exception_and_the_package_that_raised_it(self):
        found = problems.from_log(TRACEBACK, "host.log", what="the session host exited (1) while starting")
        self.assertIn("in the package agent", found.reason)
        self.assertIn("ImportError: cannot import name 'SpendingLimit'", found.reason)
        self.assertIn("harness install --update agent", found.fix)
        self.assertEqual(found.log, "host.log")

    def test_a_log_without_a_traceback_gives_its_last_line(self):
        found = problems.from_log("starting\nAddress already in use\n", what="it stopped")
        self.assertEqual(found.reason, "it stopped: Address already in use")


class DataTests(unittest.TestCase):
    def test_a_folder_of_a_newer_layout_is_refused_with_what_to_do(self):
        with tempfile.TemporaryDirectory() as folder:
            mark_data(Path(folder))
            check_data(Path(folder))
            stamp_file(Path(folder)).write_text(json.dumps({"format": DATA_FORMAT + 1, "version": "9.0.0"}))
            with self.assertRaises(Problem) as raised:
                check_data(Path(folder))
        self.assertIn("newer The Harness (9.0.0)", raised.exception.reason)
        self.assertIn("harness update", raised.exception.fix)


class LeftOutTests(unittest.TestCase):
    def setUp(self):
        extensions._CACHE.clear()
        self.addCleanup(extensions._CACHE.clear)
        self.addCleanup(extensions._PROBLEMS.clear)

    def test_a_package_for_another_harness_is_not_imported(self):
        unfit = SimpleNamespace(name="later", version="2.0.0", path="later", harness=">=9,<10",
                                provides={"host": ["no_such_module_at_all"]}, runs_here=lambda: True, platforms=())
        with mock.patch("harness.paths.packages", return_value=[unfit]):
            self.assertEqual(extensions.hosts(), [])
        self.assertIn("later 2.0.0 was skipped: it works with harness >=9,<10", extensions.host_problems()["later"])

    def test_a_background_service_that_fails_leaves_the_host_running(self):
        from harness.host.server import HostServer

        def failing(server):
            raise RuntimeError("no display")

        good = SimpleNamespace(start=mock.Mock(), close=mock.Mock())
        found = [(SimpleNamespace(name="bad", version="1.0.0"), SimpleNamespace(background=failing)),
                 (SimpleNamespace(name="good", version="1.0.0"), SimpleNamespace(background=lambda server: good))]
        server = SimpleNamespace(conversations=SimpleNamespace(), _registered=None, background={})
        with mock.patch("harness.extensions.hosts", return_value=found), mock.patch("traceback.print_exc"):
            HostServer.start_background(server)
        self.assertEqual(list(server.background), ["good"])
        good.start.assert_called_once()
        self.assertIn("bad 1.0.0 was skipped: its background service did not start (RuntimeError: no display)",
                      extensions.host_problems()["bad"])


if __name__ == "__main__":
    unittest.main()
