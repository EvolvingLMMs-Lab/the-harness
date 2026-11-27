"""The command line in the forms people know: a first message, a slip of a command's name,
the short help, print mode, config, status, doctor, logs and completion."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)

from harness import cli


def run(*words, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            mock.patch("sys.stdin", stdin if stdin is not None else io.StringIO("")):
        status = cli.main(list(words))
    return status, out.getvalue(), err.getvalue()


class Base(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = mock.patch.dict(os.environ, {"HARNESS_HOME": self.folder.name, "HARNESS_DATA": self.folder.name})
        self.env.start()
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.env.stop)


class WordsTests(Base):
    def test_a_slip_of_a_commands_name_is_named_and_starts_nothing(self):
        with mock.patch("harness.cli._chat", side_effect=AssertionError("no chat for a slip")):
            for typed, meant in (("udpate", "update"), ("stauts", "status"), ("doctr", "doctor"), ("sesions", "sessions")):
                status, out, err = run(typed)
                self.assertEqual((status, out), (2, ""))
                self.assertEqual(err.strip(), f"the-harness: no command {typed!r}. Did you mean the-harness {meant}?")
        status, _, err = run("host", "stauts")
        self.assertEqual(status, 2)
        self.assertIn("Did you mean the-harness host status?", err)

    def test_words_that_are_no_command_are_the_first_message(self):
        seen = []
        with mock.patch("harness.cli._default", side_effect=lambda args: seen.append(args) or 0):
            for words, message in ((["explain this folder"], "explain this folder"), (["hello"], "hello"),
                                   (["--model", "fast", "what", "is", "here"], "what is here"), ([], "")):
                self.assertEqual(run(*words)[0], 0)
                self.assertEqual(seen[-1].first_message, message)
            self.assertEqual(seen[2].model, "fast")
        # Where the first word that is no option is: an option's value is not it.
        self.assertEqual(cli.first_word(["--model", "x", "doctor"]), 2)
        self.assertEqual(cli.first_word(["-r", "trip", "go on"]), 2)
        self.assertEqual(cli.first_word(["-r", "trip"]), 1)
        self.assertEqual(cli.first_word(["-c", "-p"]), None)

    def test_help_is_short_and_grouped_with_a_line_for_every_command(self):
        status, out, _ = run("--help")
        self.assertEqual(status, 0)
        lines = out.splitlines()
        self.assertLess(len(lines), 70)
        self.assertLess(max(map(len, lines)), 110)
        every_day, connect, tasks = (lines.index(name) for name in ("Every day", "Connect and extend", "Tasks"))
        self.assertTrue(every_day < connect < tasks)
        self.assertIn("  doctor        what is missing on this computer, each with its fix", lines[every_day:connect])
        # A package's command has a line of its own, not its package's summary.
        more = lines[lines.index("From installed packages"):]
        self.assertTrue(any(line.startswith("  program ") and "experiment" in line for line in more))
        self.assertFalse(any("Evaluate the agent" in line for line in more))
        for word in ("-v", "--version"):
            out = io.StringIO()
            with self.assertRaises(SystemExit) as done, contextlib.redirect_stdout(out):
                cli.main([word])
            self.assertEqual(done.exception.code, 0)
            self.assertTrue(out.getvalue().startswith("the-harness "))

    def test_print_mode_takes_the_question_and_what_is_piped_in(self):
        asked = []
        with mock.patch("harness.cli._answer_as_identity", side_effect=lambda args, text: asked.append((args, text)) or 0), \
                mock.patch("harness.extensions.first", return_value=object()), mock.patch("harness.packages.activate"):
            piped = SimpleNamespace(isatty=lambda: False, buffer=io.BytesIO("line one\nline two\n".encode()))
            self.assertEqual(run("-p", "explain", stdin=piped)[0], 0)
            self.assertEqual(asked[-1][1], "explain\n\nline one\nline two")
            self.assertEqual(run("-c", "-p", "and then?", "--output-format", "json")[0], 0)
            self.assertEqual((asked[-1][0].continue_last, asked[-1][0].output_format, asked[-1][1]), (True, "json", "and then?"))
            status, _, err = run("-p")
            self.assertEqual(status, 2)
            self.assertIn("needs a question", err)
        status, _, err = run("--output-format", "json", "hello")
        self.assertEqual(status, 2)
        self.assertIn("--output-format goes with -p", err)


class ConfigTests(Base):
    def test_settings_are_shown_got_set_and_unset_by_their_names(self):
        status, out, _ = run("config", "path")
        self.assertEqual(Path(out.strip()), Path(self.folder.name).resolve() / "config.toml")
        self.assertEqual(run("config", "get", "approvals.ask")[1].strip(), "sensitive")
        status, out, _ = run("config", "set", "approvals.ask", "programs")
        self.assertEqual((status, out.strip()), (0, 'approvals.ask = "programs"  (holds from the next conversation)'))
        self.assertEqual(run("config", "set", "limits.max_steps", "80")[0], 0)
        self.assertEqual(run("config", "set", "general.notifications", "off")[1].strip(), "general.notifications = false")
        shown = run("config", "show", "--json")[1]
        rows = {row["setting"]: row for row in json.loads(shown)}
        self.assertEqual((rows["approvals.ask"]["value"], rows["approvals.ask"]["changed"], rows["limits.max_steps"]["value"],
                          rows["limits.max_minutes"]["changed"], rows["learning.mode"]["scope"]),
                         ("programs", True, 80, False, "identity"))
        status, out, _ = run("config", "show", "approvals")
        self.assertIn('* approvals.ask', out)
        self.assertNotIn("limits.", out)
        # A key that is kept but does nothing any more is not listed, unless all are asked for.
        self.assertNotIn("model.think_interval", run("config", "show")[1])
        self.assertIn("model.think_interval", run("config", "show", "--all")[1])
        self.assertEqual(run("config", "unset", "approvals.ask")[1].split("  ")[0], 'approvals.ask = "sensitive"')
        for words, said in ((("config", "set", "approvals.ask", "maybe"), "harness config set approvals.ask sensitive | programs"),
                            (("config", "get", "approvals.aks"), "did you mean approvals.ask?"),
                            (("config", "set", "limits.max_steps", "many"), "a number is expected")):
            status, _, err = run(*words)
            self.assertNotEqual(status, 0)
            self.assertIn(said, err)
        # A provider's key by its variable's name: kept with the credentials, shown masked.
        with mock.patch.dict(os.environ):
            os.environ.pop("OPENROUTER_API_KEY", None)
            self.assertEqual(run("config", "set", "OPENROUTER_API_KEY", "sk-or-0123456789abcdef")[0], 0)
            self.assertEqual(run("config", "get", "OPENROUTER_API_KEY")[1].strip(), "sk-o...cdef")
            self.assertEqual(run("config", "unset", "OPENROUTER_API_KEY")[0], 0)

    def test_the_two_commands_that_share_a_name_with_a_packages(self):
        called = []
        with mock.patch("harness.cli._package_command", side_effect=lambda name, words: called.append((name, words)) or 0), \
                mock.patch("harness.cli.package_commands", return_value={"config": ("m:f", "eval", ""),
                                                                         "status": ("m:f", "local-models", "")}):
            self.assertEqual(run("config", "my-experiment", "--json")[0], 0)
            self.assertEqual(run("status", "--deploy", "lab")[0], 0)
        self.assertEqual(called, [("config", ["my-experiment", "--json"]), ("status", ["--deploy", "lab"])])
        with mock.patch("harness.cli.package_commands", return_value={}):
            status, _, err = run("config", "shwo")
            self.assertEqual(status, 2)
            self.assertIn("Did you mean harness config show?", err)


class LookTests(Base):
    def test_status_says_where_things_stand_without_starting_anything(self):
        with mock.patch("harness.cli._host_now", return_value=None), \
                mock.patch("harness.host.Host.connect", side_effect=AssertionError("nothing is started for a look")), \
                mock.patch("harness.host.connectors.agents", return_value=[]), \
                mock.patch("harness.host.login.status", return_value={"on": False}):
            status, out, _ = run("status")
            self.assertEqual(status, 0)
            self.assertRegex(out.splitlines()[0], r"^The Harness \d+\.\d+\S* · Python 3")
            self.assertIn("host       not running", out)
            self.assertIn("model      not set up", out)
            self.assertIn("harness setup", out)
            report = json.loads(run("status", "--json")[1])
            self.assertEqual((report["host"], report["model"]["ready"], report["mcp"]), (None, False, []))

    def test_doctor_lists_each_thing_with_its_fix(self):
        checks = [{"name": "python", "ok": True, "detail": "Python 3.12.1", "fix": ""},
                  {"name": "model", "ok": False, "detail": "no model is set up (OPENROUTER_API_KEY is not set)",
                   "fix": "harness setup"}]
        lines = cli.doctor_lines(checks)
        self.assertEqual(lines[:3], ["✓ python         Python 3.12.1",
                                     "✗ model          no model is set up (OPENROUTER_API_KEY is not set)",
                                     "                 → harness setup"])
        self.assertEqual(lines[-1], "1 thing to fix, each with what to do after →.")
        with mock.patch.dict(os.environ):
            os.environ.pop("OPENROUTER_API_KEY", None)
            report = cli._core_report()   # no host is started for the library's report
        self.assertFalse(report["ok"])
        self.assertEqual([row["name"] for row in report["checks"]], ["python", "model"])
        self.assertTrue(report["problems"][0].endswith(": harness setup"))

    def test_logs_are_listed_and_shown_from_their_end(self):
        logs = Path(self.folder.name) / "logs"
        logs.mkdir()
        (logs / "host.log").write_text("".join(f"line {number}\n" for number in range(1, 101)), encoding="utf-8")
        self.assertEqual(run("logs", "-n", "3")[1].split(), ["line", "98", "line", "99", "line", "100"])
        self.assertRegex(run("logs", "list")[1], r"host +\d+\.\d KB")
        status, _, err = run("logs", "nothing")
        self.assertEqual(status, 1)
        self.assertIn("harness logs list", err)

    def test_completion_names_the_commands_and_their_first_words(self):
        for shell in ("bash", "zsh", "fish"):
            status, out, _ = run("completion", shell)
            self.assertEqual(status, 0)
            for word in ("doctor", "sessions", "restart", "unset"):
                self.assertIn(word, out)
