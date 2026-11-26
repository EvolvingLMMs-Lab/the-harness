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


CLAUDE = {"models": [{"id": "opus", "name": "Opus 5.5", "description": "For complex work"},
                     {"id": "claude-fable-5-2", "name": "Fable 5.2"},
                     {"id": "claude-haiku-4-5", "name": "Haiku 4.5"}],
          "current": "claude-fable-5-2", "efforts": ["low", "medium", "high"]}


class Fresh(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        keep = {name: value for name, value in os.environ.items() if name not in providers.KEY_NAMES}
        # Nothing of this computer: what the harness installs goes to a folder of the test's.
        env = mock.patch.dict(os.environ, {**keep, "HARNESS_HOME": str(self.directory / "home")}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        # No source is asked what it offers unless a test says what it answers: asking an
        # agent would install and start it, asking a provider would go to the network.
        self.offers(None)

    def offers(self, answer):
        """What every source answers to onboarding.offered from here on (`answer`: a dict, or a
        function of (provider, model); None: it cannot be asked)."""
        def offered(directory, provider, model=None, log=None):
            if answer is None:
                raise ValueError("no source is asked in this test")
            return answer(provider, model) if callable(answer) else answer

        patched = mock.patch("harness.onboarding.offered", offered)
        patched.start()
        self.addCleanup(patched.stop)

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
        self.assertEqual([(row["provider"], row["name"], row["signed_in"]) for row in found if row["installed"]],
                         [("acp:claude-acp", "Claude Code", True)])
        self.assertEqual(run.call_args.args[0], ["/bin/claude", "auth", "status"])

    def test_an_agent_that_is_not_installed_is_listed_after_those_that_are_with_how_to_get_it(self):
        with mock.patch("shutil.which", side_effect=lambda name: f"/bin/{name}" if name == "grok" else None), \
                mock.patch("harness.extensions.modules", return_value=[]):
            found = onboarding.agent_sources()
        # what can be chosen as it is comes first: one whose command line is here, and one that
        # needs none (its adapter installs when it is chosen, and it is signed in to through it)
        self.assertEqual([(row["name"], row["installed"], row["standalone"]) for row in found],
                         [("Grok", True, True), ("Gemini CLI", False, True), ("Claude Code", False, False),
                          ("Codex", False, False)])
        codex = found[3]
        self.assertEqual((codex["install"], codex["sign_in"], codex["signed_in"]),
                         ("npm install -g @openai/codex", "run codex login", None))
        self.assertEqual([onboarding.usable(row) for row in found], [True, True, False, False])
        # Chosen all the same, it says how to get it instead of being started.
        with mock.patch("shutil.which", return_value=None), self.assertRaises(Problem) as raised:
            onboarding.tryout(self.directory, {"provider": "acp:codex-acp", "model": "default"})
        self.assertEqual((raised.exception.code, raised.exception.fix),
                         ("agent_missing", "install Codex (npm install -g @openai/codex), run codex login, "
                                           "then choose it again"))

    def test_an_agent_that_needs_no_command_line_is_made_ready_and_signed_in_to_through_itself(self):
        asked = []

        def sign_in(provider, method=None):
            asked.append((provider, method))
            if method == "broken":
                raise ValueError("the page was closed")
            return {"signed_in": True, "method": method} if method else [
                {"id": "oauth-personal", "name": "Log in with Google", "description": "Log in with your Google account"}]

        hooks = {"model_backend": object(), "agent_ready": lambda provider, log: asked.append(("ready", provider)),
                 "agent_sign_in": sign_in}
        with mock.patch("shutil.which", return_value=None), mock.patch("harness.extensions.require"), \
                mock.patch("harness.extensions.first", side_effect=hooks.get):
            # no gemini on this computer: it is not asked for, its adapter is made ready
            onboarding.prepare_agent("acp:gemini", lambda message: None)
            self.assertEqual(asked, [("ready", "acp:gemini")])
            ways = onboarding.sign_in("acp:gemini")
            self.assertEqual([way["name"] for way in ways], ["Log in with Google"])
            # what it offered before it was signed in to is asked again afterwards
            onboarding._OFFERED[("acp:gemini", "")] = (9e12, {"models": []})
            self.assertEqual(onboarding.sign_in("acp:gemini", "oauth-personal"), {"signed_in": True, "method": "oauth-personal"})
            self.assertNotIn(("acp:gemini", ""), onboarding._OFFERED)
            with self.assertRaises(Problem) as failed:
                onboarding.sign_in("acp:gemini", "broken")
            self.assertEqual(failed.exception.code, "sign_in_failed")
            # a frontend is handed the ways with the failure that said "not signed in", and with no other
            said = onboarding.refused({"provider": "acp:gemini", "model": "default"}, "Gemini CLI",
                                      RuntimeError("ACP request failed (-32000). The agent wants its user signed in "
                                                   "first (authentication required)."))
            self.assertEqual(said.code, "not_signed_in")
            self.assertIn("harness agents login gemini", said.fix)
            self.assertEqual(onboarding.sign_in_offer("acp:gemini", said), {"sign_in": ways})
            self.assertEqual(onboarding.sign_in_offer("acp:gemini", Problem("it has reached its limit", code="plan_limit")), {})
            self.assertEqual(onboarding.sign_in_offer("openrouter", said), {})

    def test_a_package_from_before_agents_were_models_is_said_to_be_old(self):
        with mock.patch("shutil.which", return_value="/bin/claude"), \
                mock.patch("harness.extensions.require"), mock.patch("harness.extensions.first", return_value=None), \
                self.assertRaises(Problem) as raised:
            onboarding.prepare_agent("acp:claude-acp", lambda message: None)
        self.assertEqual(raised.exception.code, "package_old")

    def test_an_agent_of_the_registry_goes_by_the_name_the_registry_gives_it(self):
        choice = {"provider": "acp:opencode", "model": "default", "name": "OpenCode"}
        with mock.patch("harness.onboarding.prepare_agent"), \
                mock.patch("harness.runtime.decision.model.package_transport", return_value=object()), \
                self.answering("ok"):
            onboarding.tryout(self.directory, choice)
        onboarding.choose(self.directory, choice)
        # once connected, its package lists it under that name: the source's name, never the model's
        with mock.patch("harness.onboarding._agent_names", return_value={"acp:opencode": "OpenCode"}):
            chosen = onboarding.chosen(self.directory)
        self.assertEqual((chosen["name"], chosen["model_name"]), ("OpenCode", "its own default"))


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
        # what is kept is a model of that source, by the model's own name with its effort levels
        self.offers(CLAUDE)
        entry = onboarding.choose(self.directory, choice)
        self.assertEqual((entry["provider"], entry["model"], entry["name"], entry["efforts"]),
                         ("acp:claude-acp", "claude-fable-5-2", "Fable 5.2", ["low", "medium", "high"]))
        self.assertEqual(providers.load(self.directory)["model"], "claude-fable-5-2")
        chosen = onboarding.chosen(self.directory)
        self.assertEqual((chosen["name"], chosen["model_name"], chosen["efforts"]),
                         ("Claude Code", "Fable 5.2", ["low", "medium", "high"]))
        self.assertTrue(onboarding.kept_ready(self.directory))
        self.assertNotIn("keys", settings.read(self.directory))

    def test_another_model_of_the_source_is_kept_with_its_own_effort_levels(self):
        # the levels differ by model: a source is asked about the one model
        self.offers(lambda provider, model: {**CLAUDE, "efforts": [] if model == "claude-haiku-4-5" else CLAUDE["efforts"]})
        onboarding.choose(self.directory, {"provider": "acp:claude-acp", "model": "default"})
        entry = onboarding.choose(self.directory, {"provider": "acp:claude-acp", "model": "claude-haiku-4-5"})
        self.assertEqual((entry["name"], entry["efforts"]), ("Haiku 4.5", []))
        self.assertEqual(onboarding.chosen(self.directory)["model_name"], "Haiku 4.5")
        # both stay in the list, under the one source
        self.assertEqual([(row["provider"], row["name"]) for row in model_list.models(self.directory)],
                         [("acp:claude-acp", "Fable 5.2"), ("acp:claude-acp", "Haiku 4.5")])

    def test_a_source_that_cannot_be_asked_keeps_what_it_is_set_to_and_is_never_named_as_the_model(self):
        entry = onboarding.choose(self.directory, {"provider": "acp:claude-acp", "model": "default"})
        self.assertEqual((entry["model"], entry["efforts"]), ("default", []))
        chosen = onboarding.chosen(self.directory)
        self.assertEqual((chosen["name"], chosen["model_name"]), ("Claude Code", "its own default"))
        # an entry kept by an earlier version under its source's name reads the same
        model_list.models(self.directory, {"action": "save", "provider": "acp:claude-acp", "model": "default",
                                           "name": "Claude Code"})
        self.assertEqual(onboarding.chosen(self.directory)["model_name"], "its own default")

    def test_a_providers_model_is_kept_with_the_effort_levels_its_catalog_names(self):
        os.environ["OPENROUTER_API_KEY"] = "from-the-shell"
        self.offers({"models": [{"id": "deepseek/deepseek-v4.1-flash", "name": "DeepSeek V4.1 Flash",
                                 "efforts": ["high", "low"], "images": False}], "current": None, "efforts": ["high", "low"]})
        entry = onboarding.choose(self.directory, {"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash"})
        self.assertEqual((entry["name"], entry["efforts"], entry["images"]), ("DeepSeek V4.1 Flash", ["high", "low"], False))
        chosen = onboarding.chosen(self.directory)
        self.assertEqual((chosen["name"], chosen["model_name"]), ("OpenRouter", "DeepSeek V4.1 Flash"))

    def test_the_host_keeps_a_model_of_a_source_when_it_is_picked(self):
        from harness.host.tasks import TaskHandler, TaskHost

        app = TaskHost(self.directory)
        self.addCleanup(app.close)
        self.offers(CLAUDE)
        said = []
        handler = SimpleNamespace(server=SimpleNamespace(app=app), _json=said.append)
        body = {"action": "use", "provider": "acp:claude-acp", "model": "opus"}
        TaskHandler.post_app_models(handler, body)
        entry = said[-1]["entry"]
        self.assertEqual((entry["model"], entry["name"], entry["model_name"], entry["source"], entry["efforts"]),
                         ("opus", "Opus 5.5", "Opus 5.5", "Claude Code", ["low", "medium", "high"]))
        # asked for again, it is the same entry: nothing is kept twice
        TaskHandler.post_app_models(handler, body)
        self.assertEqual((said[-1]["entry"]["id"], len(said[-1]["models"])), (entry["id"], 1))
        # every model of the list says its source and its own name apart
        TaskHandler.get_app_models(handler, {})
        self.assertEqual([(row["source"], row["model_name"]) for row in said[-1]["models"]], [("Claude Code", "Opus 5.5")])

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
