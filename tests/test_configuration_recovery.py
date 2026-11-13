"""Configuration failures remain recoverable without changing the selected provider."""

import io
from contextlib import redirect_stderr, redirect_stdout
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import helpers  # noqa: F401
from harness import cli, model_list, providers, settings
from harness.runtime.decision.model import ChatModel


class ConfigurationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.update(HARNESS_DATA=str(self.directory), HARNESS_HOME=str(self.directory / "cache"),
                          HARNESS_PACKAGE_ROOTS="")

    def listed(self, *rows):
        (self.directory / "models.json").write_text(json.dumps(rows), encoding="utf-8")

    def test_corrupt_config_reports_path_and_parse_reason_and_blocks_updates(self):
        file = self.directory / "config.toml"
        original = '[model]\nprovider="ollama"\nmodel="old"\n[general]\ntheme="dark\n'
        file.write_text(original, encoding="utf-8")
        for operation in (lambda: settings.read(self.directory),
                          lambda: settings.Settings(self.directory).update({"general": {"theme": "light"}}),
                          lambda: providers.save(self.directory, {"provider": "ollama", "model": "new"}),
                          lambda: settings.Credentials(self.directory).keep("EXAMPLE", "synthetic")):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, r"config\.toml:.*line"):
                operation()
            self.assertEqual(file.read_text(encoding="utf-8"), original)

    def test_config_read_error_is_not_empty_configuration(self):
        file = self.directory / "config.toml"
        file.mkdir()
        with self.assertRaisesRegex(ValueError, r"config\.toml:"):
            settings.read(self.directory)

    def test_invalid_encoding_blocks_config_writes(self):
        file = self.directory / "config.toml"
        original = b'[keys]\nEXAMPLE="\xff"\n'
        file.write_bytes(original)
        with self.assertRaisesRegex(ValueError, r"config\.toml: invalid UTF-8"):
            settings.Settings(self.directory).update({"general": {"theme": "light"}})
        self.assertEqual(file.read_bytes(), original)

    def test_only_a_missing_config_is_empty(self):
        self.assertEqual(settings.read(self.directory), {})
        settings.Settings(self.directory).update({"general": {"theme": "dark"}})
        self.assertEqual(settings.read(self.directory)["general"]["theme"], "dark")

    def test_missing_key_check_does_not_persist_empty_list_and_export_recovers(self):
        with patch("harness.paths.data", return_value=self.directory):
            with self.assertRaises(cli.UsageError):
                cli._ready_model(interactive=False)
            self.assertFalse((self.directory / "models.json").exists())
            os.environ["OPENROUTER_API_KEY"] = "synthetic-key"
            cli._ready_model(interactive=False)
        self.assertEqual(model_list.select(self.directory)["model"], providers.DEFAULT["model"])

    def test_explicit_empty_or_disabled_lists_are_respected_after_export(self):
        os.environ["OPENROUTER_API_KEY"] = "synthetic-key"
        for rows in ([], [{"provider": "ollama", "model": "disabled", "enabled": False}]):
            with self.subTest(rows=rows):
                self.listed(*rows)
                self.assertIsNone(model_list.select(self.directory))
                self.assertFalse(providers.ready(self.directory)["ready"])
                with patch("harness.paths.data", return_value=self.directory), self.assertRaises(cli.UsageError):
                    cli._ready_model(interactive=False)
                self.assertEqual(json.loads((self.directory / "models.json").read_text()), rows)

    def test_explicit_config_conflict_never_selects_another_model(self):
        providers.save(self.directory, {"provider": "ollama", "model": "old"})
        model_list.models(self.directory)
        providers.save(self.directory, {"provider": "ollama", "model": "new"})
        with self.assertRaisesRegex(ValueError, r"config\.toml.*models\.json"):
            model_list.select(self.directory)
        self.assertEqual(model_list.select(self.directory, "old")["model"], "old")
        model_list.models(self.directory, {"action": "save", "provider": "ollama", "model": "new"})
        self.assertEqual(model_list.select(self.directory)["model"], "new")

    def test_disabled_configured_model_does_not_fall_back_to_other_model(self):
        providers.save(self.directory, {"provider": "ollama", "model": "chosen"})
        self.listed({"provider": "ollama", "model": "chosen", "enabled": False},
                    {"provider": "ollama", "model": "other"})
        with self.assertRaisesRegex(ValueError, r"config\.toml.*models\.json"):
            model_list.select(self.directory)

    def test_invalid_explicit_provider_never_falls_back_to_default(self):
        (self.directory / "config.toml").write_text('[model]\nprovider="typo"\nmodel="chosen"\n')
        self.listed({"provider": "ollama", "model": "other"})
        with self.assertRaisesRegex(ValueError, r"config\.toml: model: no provider"):
            model_list.select(self.directory)

    def test_list_only_model_readiness_and_doctor_use_selected_provider(self):
        self.listed({"provider": "ollama", "model": "local"})
        self.assertTrue(providers.ready(self.directory)["ready"])
        with patch("harness.paths.data", return_value=self.directory):
            self.assertTrue(cli._core_report()["ok"])
            cli._ready_model(interactive=False)
        self.listed({"provider": "openai", "model": "remote"})
        with patch("harness.paths.data", return_value=self.directory):
            report = cli._core_report()
            self.assertFalse(report["ok"])
            self.assertIn("OPENAI_API_KEY", " ".join(report["problems"]))
            self.assertNotIn("OPENROUTER_API_KEY", " ".join(report["problems"]))
        os.environ["OPENAI_API_KEY"] = "synthetic-key"
        self.assertTrue(providers.ready(self.directory)["ready"])

    def test_doctor_reports_configuration_conflict(self):
        providers.save(self.directory, {"provider": "ollama", "model": "chosen"})
        self.listed({"provider": "ollama", "model": "other"})
        with patch("harness.paths.data", return_value=self.directory):
            report = cli._core_report()
        self.assertFalse(report["ok"])
        self.assertIn("models.json", " ".join(report["problems"]))

    def test_selection_error_is_not_ready_and_does_not_claim_a_default_identity(self):
        providers.save(self.directory, {"provider": "ollama", "model": "chosen"})
        for rows in ([{"provider": "ollama", "model": "other"}],
                     [{"provider": "ollama", "model": "chosen", "enabled": False},
                      {"provider": "ollama", "model": "other"}]):
            with self.subTest(rows=rows):
                self.listed(*rows)
                with self.assertRaises(model_list.SelectionError):
                    model_list.select(self.directory)
                report = providers.ready(self.directory)
                self.assertFalse(report["ready"])
                self.assertTrue(report["selection_error"])
                self.assertIsNone(report["provider"])
                self.assertIsNone(report["model"])

    def test_terminal_recovery_opens_for_removed_disabled_and_empty_default(self):
        providers.save(self.directory, {"provider": "ollama", "model": "chosen"})
        for rows in ([{"provider": "ollama", "model": "other"}],
                     [{"provider": "ollama", "model": "chosen", "enabled": False},
                      {"provider": "ollama", "model": "other"}], []):
            with self.subTest(rows=rows):
                self.listed(*rows)
                warnings = []

                def display(*, start):
                    warnings.append(start.warning)
                    # The management UI is available; a new task still refuses this default.
                    with self.assertRaises(ValueError):
                        start("hello")

                with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                        patch("harness.tui.chat", side_effect=display) as chat, \
                        patch("harness.providers.setup") as setup, patch("harness.cli._task") as task, \
                        redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main([]), 0)
                chat.assert_called_once()
                setup.assert_not_called()
                task.assert_not_called()
                self.assertIn("/models", warnings[0])

    def test_bare_model_overrides_conflicting_default_and_tui_choice_overrides_flag(self):
        providers.save(self.directory, {"provider": "ollama", "model": "chosen"})
        self.listed({"provider": "ollama", "model": "other"}, {"provider": "ollama", "model": "third"})

        def display(*, start):
            self.assertIsNone(start.warning)
            self.assertEqual(start.model_entry, model_list.select(self.directory, "other")["id"])
            self.assertEqual(start.model_effort, "low")
            self.assertEqual(start.model_name, "other")
            start("first")
            start("second", model_entry="third", reasoning_effort="medium")
            start("third", model_entry="third", reasoning_effort=None)

        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                patch("harness.tui.chat", side_effect=display), \
                patch("harness.cli._ready_model", side_effect=AssertionError("not needed")), \
                patch("harness.cli._task", return_value=(object(), object())) as task:
            self.assertEqual(cli.main(["--model", "other", "--effort", "low"]), 0)
        self.assertEqual(task.call_args_list[0].kwargs["model_entry"], model_list.select(self.directory, "other")["id"])
        self.assertEqual(task.call_args_list[0].kwargs["reasoning_effort"], "low")
        self.assertEqual(task.call_args_list[1].kwargs["model_entry"], model_list.select(self.directory, "third")["id"])
        self.assertEqual(task.call_args_list[1].kwargs["reasoning_effort"], "medium")
        self.assertEqual(task.call_args_list[2].kwargs["model_entry"], model_list.select(self.directory, "third")["id"])
        self.assertIsNone(task.call_args_list[2].kwargs["reasoning_effort"])

    def test_startup_effort_is_bound_to_the_resolved_model_once(self):
        self.listed({"provider": "ollama", "model": "chosen", "name": "CLI choice"},
                    {"provider": "ollama", "model": "other"})
        args = cli.parser(packages=False).parse_args(["--model", "chosen", "--effort", "xhigh"])
        chosen = model_list.select(self.directory, "chosen")
        with patch("harness.model_list.select", wraps=model_list.select) as select:
            start = cli._starter(args)
        select.assert_called_once_with(self.directory.resolve(), "chosen")
        self.assertEqual((start.model_entry, start.model_effort, start.model_name),
                         (chosen["id"], "xhigh", "CLI choice"))
        with patch("harness.cli._task", return_value=(object(), object())) as task:
            start("first", model_entry=chosen["id"], reasoning_effort="high")
            start("second", model_entry="other")
        self.assertEqual(task.call_args_list[0].kwargs["reasoning_effort"], "high")
        self.assertIsNone(task.call_args_list[1].kwargs["reasoning_effort"])

    def test_terminal_rejects_model_flags_that_its_start_mode_cannot_apply(self):
        for mode in (["--continue"], ["--resume", "existing"], ["--agent", "acp:tool"]):
            for choice in (["--model", "chosen"], ["--effort", "high"]):
                with self.subTest(mode=mode, choice=choice), \
                        patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                        patch("harness.cli._continued", return_value=None) as continued, \
                        patch("harness.cli._ready_model"), patch("harness.tui.chat") as chat, \
                        redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(cli.main([*mode, *choice]), 2)
                    self.assertIn("--model", error.getvalue())
                    self.assertIn("--effort", error.getvalue())
                    continued.assert_not_called()
                    chat.assert_not_called()

    def test_script_continuation_refuses_options_for_new_conversations(self):
        for mode in (["--continue"], ["--session", "existing"]):
            for option in (["--model", "chosen"], ["--effort", "high"], ["--agent", "acp:tool"],
                           ["--folder", str(self.directory)], ["--workspace", "none"], ["--learn"],
                           ["--library", str(self.directory)], ["--physical", "never"], ["--vm-image", "test-image"]):
                args = cli.parser(packages=False).parse_args(["run", "hello", *mode, *option])
                with self.subTest(mode=mode, option=option), \
                        patch("harness.cli._continued", side_effect=AssertionError("options must be checked before resuming")) as continued, \
                        patch("harness.cli._starter") as start:
                    with self.assertRaisesRegex(cli.UsageError, "saved.*model"):
                        cli._run_task(args)
                    continued.assert_not_called()
                    start.assert_not_called()

    def test_options_before_a_subcommand_are_not_silently_overwritten(self):
        for prefix in (["--model", "chosen"], ["--effort", "high"], ["--continue"]):
            with self.subTest(prefix=prefix), patch("harness.cli._run_task") as task, \
                    redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.main([*prefix, "run", "hello"]), 2)
                self.assertIn("after", error.getvalue())
                task.assert_not_called()

    def test_picked_model_uses_its_default_effort_instead_of_cli_models_effort(self):
        self.listed({"provider": "ollama", "model": "flag-model"}, {"provider": "ollama", "model": "picked-model"})
        args = cli.parser(packages=False).parse_args(["--model", "flag-model", "--effort", "xhigh"])
        start = cli._starter(args)
        with patch("harness.cli._task", return_value=(object(), object())) as task:
            start("hello", model_entry="picked-model", reasoning_effort=None)
        self.assertEqual(task.call_args.kwargs["model_entry"], model_list.select(self.directory, "picked-model")["id"])
        self.assertIsNone(task.call_args.kwargs["reasoning_effort"])

    def test_effort_only_uses_saved_default_and_keeps_invalid_default_recovery(self):
        providers.save(self.directory, {"provider": "ollama", "model": "chosen"})
        self.listed({"provider": "ollama", "model": "chosen"})
        args = cli.parser(packages=False).parse_args(["--effort", "high"])
        start = cli._starter(args)
        self.assertEqual(start.model_entry, model_list.select(self.directory)["id"])
        self.assertEqual(start.model_effort, "high")
        self.listed({"provider": "ollama", "model": "other"})
        start = cli._starter(args)
        self.assertIsNone(start.model_entry)
        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                patch("harness.tui.chat") as chat:
            self.assertEqual(cli.main(["--effort", "high"]), 0)
        self.assertIn("--effort was not applied", chat.call_args.kwargs["start"].warning)

    def test_invalid_model_list_can_open_terminal_editor_recovery(self):
        (self.directory / "models.json").write_text('[{"provider":')
        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                patch("harness.tui.chat") as chat:
            self.assertEqual(cli.main([]), 0)
        self.assertIn("models.json", chat.call_args.kwargs["start"].warning)
        self.assertIn("/models", chat.call_args.kwargs["start"].warning)

    def test_continue_and_resume_skip_new_model_readiness(self):
        self.listed()
        host, conversation = object(), object()
        for flags in (["--continue"], ["--resume", "existing"]):
            with self.subTest(flags=flags), patch("sys.stdin.isatty", return_value=True), \
                    patch("sys.stdout.isatty", return_value=True), \
                    patch("harness.cli._ready_model", side_effect=AssertionError("not needed")), \
                    patch("harness.cli._continued", return_value=(host, conversation, 0)), \
                    patch("harness.tui.chat") as chat:
                self.assertEqual(cli.main(flags), 0)
                self.assertIs(chat.call_args.args[0], conversation)

    def test_run_continue_and_session_skip_new_model_readiness(self):
        conversation = SimpleNamespace(send_message=lambda _: None,
                                       records=lambda **_: [{"event": "finish", "text": "ok"}], close=lambda: None)
        for flags in (["--continue"], ["--session", "existing"]):
            args = cli.parser(packages=False).parse_args(["run", "hello", *flags])
            with self.subTest(flags=flags), patch("harness.cli._ready_model", side_effect=AssertionError("not needed")), \
                    patch("harness.cli._continued", return_value=(object(), conversation, 0)), \
                    patch("harness.cli._watch_sub_agents", return_value=threading.Event()), redirect_stdout(io.StringIO()):
                self.assertEqual(cli._run_task(args), 0)

    def test_corrupt_configuration_is_explicit_at_cli_boundary_without_a_traceback(self):
        file = self.directory / "config.toml"
        original = '[general]\ntheme="dark\n'
        file.write_text(original)
        for words in (["doctor", "--json"], ["run", "hello"], []):
            out, errors = io.StringIO(), io.StringIO()
            with self.subTest(words=words), redirect_stdout(out), redirect_stderr(errors), \
                    patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True):
                self.assertEqual(cli.main(words), 1)
            message = out.getvalue() + errors.getvalue()
            self.assertIn("config.toml", message)
            self.assertNotIn("Traceback", message)
            self.assertEqual(file.read_text(), original)
            if words == ["doctor", "--json"]:
                self.assertFalse(json.loads(out.getvalue())["ok"])
            else:
                self.assertIn("error", json.loads(errors.getvalue()))

    def test_rpc_refuses_task_continuation_flags_instead_of_ignoring_them(self):
        for flags in (["--continue"], ["--session", "existing"]):
            output, errors = io.StringIO(), io.StringIO()
            with self.subTest(flags=flags), patch("sys.stdin", io.StringIO("")), \
                    patch("harness.cli._ready_model"), redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(cli.main(["run", "rpc", *flags]), 2)
            self.assertIn("starts a new conversation", json.loads(errors.getvalue())["error"])

    def test_custom_can_be_keyless_but_keeps_optional_authentication(self):
        choice = {"provider": "custom", "model": "local", "base_url": "http://127.0.0.1:8000/v1"}
        self.listed(choice)
        self.assertTrue(providers.ready(self.directory)["ready"])
        self.assertEqual(providers.model_role(choice)["api_key_env"], "HARNESS_LLM_API_KEY")
        with patch("harness.paths.data", return_value=self.directory):
            cli._ready_model(interactive=False)
        self.assertFalse(providers.requires_key("custom"))
        self.assertTrue(providers.requires_key("openai"))

    def test_openrouter_proxy_is_used_for_calls_key_checks_and_catalog(self):
        choice = providers.check({"provider": "openrouter", "model": "test", "base_url": "https://proxy.test/v1"})
        providers.save(self.directory, choice)
        os.environ["OPENROUTER_API_KEY"] = "synthetic-key"
        model = ChatModel(providers.model_role(choice))
        self.assertEqual(model.url, "https://proxy.test/v1/chat/completions")
        self.assertEqual(providers.models_url(choice), "https://proxy.test/v1/key")
        with patch("harness.providers.open_url", return_value=io.StringIO('{"data":{}}')) as request:
            self.assertTrue(providers.reach(choice, "synthetic-key")["ok"])
        self.assertEqual(request.call_args.args[0], "https://proxy.test/v1/key")
        with patch("harness.providers.open_url", return_value=io.StringIO('{"data":[{"id":"test"}]}')) as request:
            result = providers.catalog(self.directory, "openrouter")
        self.assertEqual(request.call_args.args[0], "https://proxy.test/v1/models")
        self.assertEqual(result[0]["base_url"], choice["base_url"])
        self.assertEqual(providers.models_url(providers.DEFAULT), "https://openrouter.ai/api/v1/key")
        self.assertEqual(providers.models_url({**choice, "base_url": choice["base_url"] + "/chat/completions"}),
                         "https://proxy.test/v1/key")
        with self.assertRaisesRegex(ValueError, "base URL"):
            providers.models_url({"provider": "custom"})

    def test_onboarding_reuses_environment_key_without_copying_it_to_file(self):
        os.environ["OPENAI_API_KEY"] = "environment-key"
        settings.Credentials(self.directory).keep("OPENAI_API_KEY", "file-key")
        prompts, messages = [], []
        answers = iter(["openai", "test"])
        with patch("harness.providers.reach", return_value={"ok": True}) as reach:
            result = providers.setup(self.directory, read=lambda _: next(answers),
                                     secret=lambda prompt: prompts.append(prompt) or "", write=messages.append)
        self.assertEqual(result["provider"], "openai")
        self.assertEqual(reach.call_args.args[1], "environment-key")
        self.assertEqual(settings.read(self.directory)["keys"]["OPENAI_API_KEY"], "file-key")
        self.assertIn("environment", " ".join(messages + prompts))
        self.assertNotIn("environment-key", " ".join(messages + prompts))

    def test_onboarding_reuses_saved_key_and_accepts_keyless_custom(self):
        settings.Credentials(self.directory).keep("OPENAI_API_KEY", "file-key")
        answers = iter(["openai", "test"])
        with patch("harness.providers.reach", return_value={"ok": True}) as reach:
            providers.setup(self.directory, read=lambda _: next(answers), secret=lambda _: "", write=lambda _: None)
        self.assertEqual(reach.call_args.args[1], "file-key")
        answers = iter(["custom", "local", "http://127.0.0.1:8000/v1"])
        with patch("harness.providers.reach", return_value={"ok": True}) as reach:
            chosen = providers.setup(self.directory, read=lambda _: next(answers), secret=lambda _: "", write=lambda _: None)
        self.assertEqual(chosen["provider"], "custom")
        self.assertIsNone(reach.call_args.args[1])
        self.assertNotIn("HARNESS_LLM_API_KEY", settings.read(self.directory).get("keys", {}))


if __name__ == "__main__":
    unittest.main()
