"""Every new conversation chooses where it works; nothing is chosen for the user."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import helpers  # noqa: F401
from harness import cli
from harness.host import Host
from harness.host.tasks import TaskHost, TaskServer
from harness.runtime.decision.model import ScriptedChat
from harness.settings import ChoiceRequired, check, read, write


class Recording(ScriptedChat):
    def __init__(self, replies):
        super().__init__(replies)
        self.requests = []

    def complete(self, system, messages):
        self.requests.append((system, messages))
        return super().complete(system, messages)


def finished(conversation, seconds=30):
    """How the conversation's first turn ended (its summary's status), once it is over."""
    for _ in range(int(seconds / 0.05)):
        if conversation.status in ("FINISHED", "ERROR") or conversation.waiting_since is not None:
            break
        time.sleep(0.05)
    return (conversation.summary or {}).get("status")


class EnvironmentChoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "data"
        self.root.mkdir()
        patch = mock.patch.dict(os.environ, {"HARNESS_DATA": str(self.root), "OPENROUTER_API_KEY": "test-no-network"})
        patch.start()
        self.addCleanup(patch.stop)
        self.chat = Recording(["<finish>4</finish>"])
        self.app = TaskHost(self.root, chat=self.chat)
        self.addCleanup(self.app.close)
        self.server = TaskServer(("127.0.0.1", 0), self.app, token="test")
        self.addCleanup(self.server.server_close)

    def choice(self, **given):
        with self.assertRaises(ChoiceRequired) as found:
            self.app.environment(**given)
        return found.exception

    def test_default_asks_and_offers_core_and_package_kinds_in_order(self):
        error = self.choice()
        choice = error.choice
        values = [row["value"] for row in choice["options"]]
        self.assertEqual(values[:3], ["none", "project", "browser"])
        self.assertIn("desktop", values)
        self.assertTrue(choice["per_conversation"])
        self.assertIsNone(choice["selected"])
        # The message names the flag and the Python argument for callers that cannot ask.
        self.assertIn("--workspace", str(error))
        self.assertIn("workspace=", str(error))
        by = {row["value"]: row for row in choice["options"]}
        self.assertTrue(by["project"]["folder"])
        self.assertTrue(by["desktop"]["views"] and by["desktop"]["physical"])
        self.assertFalse(by["none"].get("views"))
        self.assertEqual(read(self.root), {})

    def test_explicit_kind_and_folder_never_ask(self):
        self.assertEqual(self.app.environment("none"), ("none", None))
        self.assertEqual(self.app.environment("browser"), ("browser", None))
        self.assertEqual(self.app.environment(folder=str(self.root)), ("project", str(self.root)))
        with self.assertRaisesRegex(ValueError, "--folder"):
            self.app.environment("project")
        with self.assertRaisesRegex(ValueError, "no installed package provides"):
            self.app.environment("submarine")

    def test_new_installation_installs_the_package_of_a_named_environment(self):
        """With no environment package installed, a named environment or a folder installs
        the registry's package that gives it; the choice offers what can be installed."""
        real = self.app.workspaces.providers
        installed = []
        rows = [{"name": "workspace", "summary": "Operate project files", "provides": {"workspaces": ["project"]}},
                {"name": "computer", "summary": "Control a computer",
                 "provides": {"workspaces": ["apps", "browser", "desktop", "display"]}},
                {"name": "eval", "summary": "Evaluate", "provides": {"commands": ["runs"]}}]

        def ensure(what, name, **_):
            self.assertEqual(what, "workspaces")
            if name == "submarine":
                from harness.packages import MissingPackage
                raise MissingPackage("no package provides the workspace submarine")
            installed.append(name)

        def providers():
            return real() if installed else ()

        with mock.patch.object(self.app.workspaces, "providers", providers),                 mock.patch.object(self.app.packages.registry, "search", lambda query="": rows),                 mock.patch.object(self.app.packages, "installed", lambda: []),                 mock.patch.object(self.app.packages, "ensure", ensure):
            offered = {row["value"]: row for row in self.choice().choice["options"]}
            self.assertEqual(list(offered)[:3], ["none", "project", "browser"])
            self.assertEqual(offered["project"]["package"], "workspace")
            self.assertIn("installs the package computer", offered["desktop"]["about"])
            self.assertEqual(installed, [])  # offering installs nothing
            with self.assertRaisesRegex(ValueError, "no installed package provides workspace 'submarine'; there are none$"):
                self.app.environment("submarine")
            self.assertEqual(self.app.environment(folder=str(self.root)), ("project", str(self.root)))
            self.assertEqual(installed, ["project"])
            # Once installed, the package describes its own environments.
            self.assertNotIn("package", {row["value"]: row for row in self.choice().choice["options"]}["project"])

    def test_nothing_is_offered_for_install_when_automatic_installs_are_off(self):
        rows = [{"name": "submarines", "summary": "Dive", "provides": {"workspaces": ["submarine"]}}]
        # With an environment package installed the registry is not read for the choice.
        with mock.patch.object(self.app.packages.registry, "search", side_effect=AssertionError("read")):
            self.assertNotIn("submarine", [row["value"] for row in self.choice().choice["options"]])
        with mock.patch.object(self.app.workspaces, "providers", lambda: ()),                 mock.patch.object(self.app.packages.registry, "search", lambda query="": rows):
            self.assertIn("submarine", [row["value"] for row in self.choice().choice["options"]])
            with mock.patch.dict(os.environ, {"HARNESS_AUTO_INSTALL": "off"}):
                self.assertNotIn("submarine", [row["value"] for row in self.choice().choice["options"]])
                with self.assertRaisesRegex(ValueError, "no installed package provides"):
                    self.app.environment("submarine")

    def test_setting_grades_ask_last_and_fixed_kind(self):
        settings = self.app.settings
        settings.update({"session": {"environment": "last"}})
        self.choice()  # nothing chosen yet: last has nothing to take, so it asks
        settings.remember("session", "last_environment", "browser")
        self.assertEqual(self.app.environment(), ("browser", None))
        settings.update({"session": {"environment": "none"}})
        self.assertEqual(self.app.environment(), ("none", None))
        settings.update({"session": {"environment": "project"}})
        with self.assertRaisesRegex(ValueError, "--folder"):
            self.app.environment()
        settings.remember("session", "last_folder", str(self.root))
        self.assertEqual(self.app.environment(), ("project", str(self.root)))
        settings.update({"session": {"environment": "submarine"}})
        with self.assertRaisesRegex(ValueError, "session.environment"):
            self.app.environment()
        for bad in ("", "Ask me", "a" * 41):
            with self.assertRaises(ValueError):
                check("session", "environment", bad)

    def test_saved_computer_mode_is_only_the_highlight(self):
        write(self.root, {"computer": {"mode": "desktop"}})
        self.assertEqual(self.choice().choice["selected"], "desktop")
        self.app.settings.remember("session", "last_environment", "none")
        self.assertEqual(self.choice().choice["selected"], "none")
        self.assertEqual(self.app.settings.get()["computer"]["mode"], "desktop")
        # remember() never writes a setting, and what it keeps is not a setting.
        with self.assertRaises(ValueError):
            self.app.settings.remember("session", "environment", "none")
        self.assertNotIn("last_environment", self.app.settings.get()["session"])

    def test_no_environment_runs_without_a_worker_and_sends_no_image(self):
        run = self.app.start(self.server, "what is 2+2", workspace="none")
        conversation = self.server.conversations[run]
        self.assertEqual(finished(conversation), "finished", conversation.summary)
        self.assertEqual(conversation.result, "4")
        # It waits after its answer. Ended, nothing scored it: no evaluator verdict for the frontends to print.
        conversation.close()
        self.app._threads[run].join(30)
        self.assertIsNone(conversation.summary["success"])
        for provider in self.app.workspaces.providers():
            self.assertFalse(getattr(provider.pool, "workers", None))
        system, messages = self.chat.requests[0]
        images = [part for message in messages if isinstance(message["content"], list)
                  for part in message["content"] if part.get("type") == "input_image"]
        self.assertEqual(images, [])
        self.assertIn("no environment", system)
        self.assertNotIn("click(", system)
        self.assertNotIn("run_command(", system)
        meta = json.loads((self.app.conversations_dir / Path(run).name / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["workspace"], "none")
        # The next conversation's choice highlights it.
        self.assertEqual(self.app.environments()["selected"], "none")

    def test_http_reports_the_choice_and_starts_nothing(self):
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.shutdown)
        host = Host(f"http://127.0.0.1:{self.server.server_port}", "test")
        with self.assertRaises(ChoiceRequired) as found:
            host.task("say hello")
        self.assertEqual(found.exception.choice["key"], "environment")
        self.assertIn("--workspace", str(found.exception))
        self.assertEqual(list(self.app.conversations_dir.iterdir()), [])
        offered = host.get("/api/app/environments")
        self.assertEqual(offered["setting"], "ask")
        self.assertEqual(offered["options"][0]["value"], "none")


class FrontendChoiceTests(unittest.IsolatedAsyncioTestCase):
    CHOICE = {"section": "session", "key": "environment", "per_conversation": True, "title": "Where?",
              "selected": "browser", "folder": None,
              "options": [{"value": "none", "label": "No environment"},
                          {"value": "project", "label": "Project folder", "folder": True},
                          {"value": "browser", "label": "Background browser"}]}

    @staticmethod
    def chat():
        async def view(coroutine):
            return await coroutine

        return SimpleNamespace(_view=view, _host=mock.Mock())

    async def test_terminal_chat_highlights_the_last_choice_and_saves_nothing(self):
        from harness.tui.chat import Chat

        chat = self.chat()
        with mock.patch("harness.tui.chat.views.choose", return_value=2) as choose:
            self.assertEqual(await Chat._choose_environment(chat, self.CHOICE), ("browser", None))
        self.assertEqual(choose.call_args.kwargs["current"], 2)
        self.assertEqual(len(choose.call_args.args[1]), 3)
        chat._host.assert_not_called()

    async def test_terminal_chat_without_a_last_choice_preselects_nothing(self):
        from harness.tui.chat import Chat

        with mock.patch("harness.tui.chat.views.choose", side_effect=[0, 1]) as choose:
            picked = await Chat._choose_environment(self.chat(), {**self.CHOICE, "selected": None})
        self.assertEqual(picked, ("none", None))
        self.assertEqual(choose.await_count, 2)

    async def test_terminal_chat_asks_the_folder_of_a_project(self):
        from harness.tui.chat import Chat

        with tempfile.TemporaryDirectory() as folder, \
                mock.patch("harness.tui.chat.views.choose", return_value=1), \
                mock.patch("harness.tui.chat.views.ask", return_value=folder) as ask:
            self.assertEqual(await Chat._choose_environment(self.chat(), self.CHOICE), ("project", folder))
        self.assertTrue(ask.call_args.args[1])  # prefilled

    async def test_a_choice_opened_by_enter_is_not_answered_by_that_enter(self):
        import asyncio

        from prompt_toolkit.application import create_app_session
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        from harness.tui import views

        with create_pipe_input() as keys, create_app_session(input=keys, output=DummyOutput()):
            keys.send_text("\r")  # the key press that sent the message, still on its way
            picking = asyncio.ensure_future(views.choose("Where?", ["none", "project", "browser"], current=2,
                                                         settle=0.4))
            await asyncio.sleep(0.2)
            self.assertFalse(picking.done())
            await asyncio.sleep(0.4)
            keys.send_text("\r")
            self.assertEqual(await asyncio.wait_for(picking, 5), 2)

    async def test_terminal_chat_passes_the_settle_time_and_the_highlight(self):
        from harness.tui.chat import SETTLE, Chat

        with mock.patch("harness.tui.chat.views.choose", return_value=2) as choose:
            await Chat._choose_environment(self.chat(), self.CHOICE, settle=SETTLE)
        self.assertEqual((choose.call_args.kwargs["current"], choose.call_args.kwargs["settle"]), (2, SETTLE))

    def test_cli_enter_takes_the_highlighted_choice(self):
        with mock.patch("builtins.input", side_effect=[""]), mock.patch("sys.stderr", io.StringIO()) as shown:
            self.assertEqual(cli._choose_environment(self.CHOICE), ("browser", None))
        self.assertIn("*3.", shown.getvalue())

    def test_cli_without_a_last_choice_requires_a_number(self):
        with mock.patch("builtins.input", side_effect=["", "1"]), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(cli._choose_environment({**self.CHOICE, "selected": None}), ("none", None))

    def test_noninteractive_run_fails_with_the_flag_and_chooses_nothing(self):
        error = ChoiceRequired({**self.CHOICE, "message": "Choose where this conversation works: --workspace KIND"})
        for flags, tty in ((["--json"], True), ([], False)):
            starter = mock.Mock(side_effect=error)
            with self.subTest(flags=flags), mock.patch("harness.cli._ready_model"), \
                    mock.patch("harness.cli._starter", return_value=starter), \
                    mock.patch("harness.cli._choose_environment") as choose, \
                    mock.patch("sys.stdin.isatty", return_value=tty), \
                    mock.patch("sys.stdout.isatty", return_value=tty), \
                    mock.patch("sys.stderr", io.StringIO()) as errors:
                self.assertEqual(cli.main(["run", "say hello", *flags]), 2)
                self.assertIn("--workspace", errors.getvalue())
                choose.assert_not_called()
                self.assertEqual(starter.call_count, 1)

    def test_interactive_run_retries_with_the_picked_environment(self):
        conversation = mock.Mock()
        conversation.records.return_value = iter([{"event": "finish", "text": "hi"},
                                                  {"event": "state", "status": "FINISHED"}])
        starter = mock.Mock(side_effect=[ChoiceRequired(self.CHOICE), (mock.Mock(), conversation)])
        with mock.patch("harness.cli._ready_model"), mock.patch("harness.cli._starter", return_value=starter), \
                mock.patch("harness.cli._choose_environment", return_value=("none", None)), \
                mock.patch("harness.cli._watch_sub_agents", return_value=threading.Event()), \
                mock.patch("sys.stdin.isatty", return_value=True), mock.patch("sys.stdout.isatty", return_value=True), \
                mock.patch("builtins.print"):
            cli.main(["run", "say hello", "-p"])
        self.assertEqual(starter.call_args.kwargs["workspace"], "none")


if __name__ == "__main__":
    unittest.main()
