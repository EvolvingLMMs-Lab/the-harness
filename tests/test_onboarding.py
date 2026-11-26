"""The first run (onboarding.py): what on this computer can be the model, one real call
with the one chosen, and keeping it. An agent signed in here is a source like a key."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import helpers  # noqa: F401
from harness import model_list, onboarding, providers, settings, spending
from harness.problems import Problem
from harness.runtime.decision.model import ChatReply


class Fresh(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        keep = {name: value for name, value in os.environ.items() if name not in providers.KEY_NAMES}
        env = mock.patch.dict(os.environ, keep, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def answering(self, text="ok", error=None):
        """Patch the model so that a try answers `text` (or raises `error`)."""
        def complete(self, system, messages, on_text=None, *, cancellation=None):
            if error is not None:
                raise error
            return ChatReply(text=text)

        return mock.patch.multiple("harness.runtime.decision.model.ChatModel", complete=complete, close=lambda self: None)


class NeededTests(Fresh):
    def test_a_new_folder_needs_the_first_run_until_it_was_gone_through(self):
        self.assertTrue(onboarding.needed(self.directory))
        onboarding.done(self.directory)
        self.assertFalse(onboarding.needed(self.directory))

    def test_a_key_in_the_environment_only_still_needs_it(self):
        os.environ["OPENROUTER_API_KEY"] = "from-the-shell"
        self.assertTrue(onboarding.needed(self.directory))
        self.assertFalse(onboarding.kept_ready(self.directory))

    def test_a_model_list_emptied_on_purpose_is_not_set_up_again(self):
        (self.directory / "models.json").write_text("[]", encoding="utf-8")
        self.assertFalse(onboarding.needed(self.directory))


class SourcesTests(Fresh):
    def test_keys_are_listed_by_where_they_are_and_never_shown(self):
        os.environ["OPENROUTER_API_KEY"] = "from-the-shell"
        settings.Credentials(self.directory).keep("OPENAI_API_KEY", "from-the-file")
        with mock.patch("harness.onboarding.agent_sources", return_value=[]), \
                mock.patch("harness.onboarding.local_models", return_value=[]):
            found = onboarding.found(self.directory)
        rows = {row["provider"]: row for row in found["keys"]}
        self.assertEqual((rows["openrouter"]["kept"], rows["openai"]["kept"]), (False, True))
        self.assertNotIn("from-the", json.dumps(found))

    def test_an_installed_agent_is_a_source_with_whether_it_is_signed_in(self):
        ran = SimpleNamespace(returncode=0)
        with mock.patch("shutil.which", side_effect=lambda name: f"/bin/{name}" if name == "claude" else None), \
                mock.patch("subprocess.run", return_value=ran) as run, \
                mock.patch("harness.extensions.modules", return_value=[]):
            found = onboarding.agent_sources()
        self.assertEqual([(row["provider"], row["name"], row["signed_in"]) for row in found],
                         [("acp:claude-acp", "Claude Code", True)])
        self.assertEqual(run.call_args.args[0], ["/bin/claude", "auth", "status"])

    def test_an_agent_that_is_not_installed_is_not_listed(self):
        with mock.patch("shutil.which", return_value=None), mock.patch("harness.extensions.modules", return_value=[]):
            self.assertEqual(onboarding.agent_sources(), [])


class TryAndKeepTests(Fresh):
    def test_a_key_from_the_environment_that_answers_is_kept_in_the_file(self):
        os.environ["OPENROUTER_API_KEY"] = "from-the-shell"
        choice = {"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash"}
        with self.answering("ok"):
            tried = onboarding.tryout(self.directory, choice)
        self.assertEqual(tried["reply"], "ok")
        self.assertNotIn("keys", settings.read(self.directory))  # trying keeps nothing
        onboarding.choose(self.directory, choice)
        self.assertEqual(settings.read(self.directory)["keys"]["OPENROUTER_API_KEY"], "from-the-shell")
        self.assertEqual(model_list.select(self.directory)["model"], "deepseek/deepseek-v4.1-flash")
        self.assertTrue(onboarding.kept_ready(self.directory))

    def test_a_refused_key_says_so_and_nothing_is_kept(self):
        choice = {"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash"}
        with self.answering(error=RuntimeError("Provider HTTP 401: No auth credentials found")), \
                self.assertRaises(Problem) as raised:
            onboarding.tryout(self.directory, choice, key="wrong")
        self.assertEqual(raised.exception.code, "key_refused")
        self.assertIn("refused the key", raised.exception.reason)
        self.assertFalse((self.directory / "models.json").exists())
        self.assertNotEqual(os.environ.get("OPENROUTER_API_KEY"), "wrong")

    def test_a_provider_that_needs_a_key_without_one_is_not_called(self):
        with self.assertRaises(Problem) as raised:
            onboarding.tryout(self.directory, {"provider": "openai", "model": "gpt"})
        self.assertEqual(raised.exception.code, "no_key")

    def test_an_agent_signed_in_here_is_tried_and_kept_without_any_key(self):
        choice = {"provider": "acp:claude-acp", "model": "default"}
        with mock.patch("harness.onboarding.prepare_agent") as prepare, \
                mock.patch("harness.runtime.decision.model.package_transport", return_value=object()), \
                self.answering("ok"):
            onboarding.tryout(self.directory, choice)
        prepare.assert_called_once()
        entry = onboarding.choose(self.directory, choice)
        self.assertEqual(entry["provider"], "acp:claude-acp")
        self.assertEqual(providers.load(self.directory)["provider"], "acp:claude-acp")
        self.assertEqual(model_list.select(self.directory, native=True)["name"], "Claude Code")
        self.assertTrue(onboarding.kept_ready(self.directory))
        self.assertNotIn("keys", settings.read(self.directory))

    def test_an_agent_that_is_not_signed_in_says_how_to_sign_in(self):
        said = onboarding.refused({"provider": "acp:claude-acp", "model": "default"}, "Claude Code",
                                  OSError("Authentication required: please log in"))
        self.assertEqual(said.code, "not_signed_in")
        self.assertIn("run claude and sign in", said.fix)

    def test_the_host_keeps_the_model_only_when_it_answers(self):
        from harness.host.tasks import TaskHost

        os.environ["OPENROUTER_API_KEY"] = "from-the-shell"
        app = TaskHost(self.directory)
        self.addCleanup(app.close)
        body = {"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash"}
        with self.answering(error=RuntimeError("Provider HTTP 402: insufficient credits")):
            answer = app.set_model(body)
        self.assertEqual((answer["ok"], answer["code"]), (False, "no_credit"))
        self.assertTrue(answer["fix"])
        with self.answering("ok"):
            answer = app.set_model(body)
        self.assertTrue(answer["ok"])
        self.assertEqual(settings.read(self.directory)["keys"]["OPENROUTER_API_KEY"], "from-the-shell")


class PlanTests(unittest.TestCase):
    def test_a_call_under_the_users_plan_counts_as_a_call_not_as_dollars(self):
        agent = SimpleNamespace(plan=True, prices=None, base_url=None, model="default")
        self.assertFalse(spending.priced(agent))
        self.assertEqual(spending.cost(agent, {"cost_usd": 0.05}),
                         {"cost_usd": 0.0, "priced": False, "basis": "plan", "plan_usd": 0.05})


if __name__ == "__main__":
    unittest.main()
