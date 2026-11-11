"""Another environment is taken into a conversation only as the user's settings allow, is
recorded whether or not it asked, and sub-agents stay off until someone switches them on."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import helpers  # noqa: F401
from harness.core.contracts import Observation
from harness.host.tasks import AttachPlace, TaskHost, TaskServer
from harness.runtime.decision.model import ScriptedChat
from harness.runtime.task.environments import Environments, Place, Refused
from harness.settings import Settings, check


class FakeWorker:
    endpoint = None
    timeout = 5.0
    host_controls = frozenset()

    def __init__(self, kind="desktop", physical=False):
        self.kind, self.physical, self.calls = kind, physical, []

    def tools(self):
        return []

    def reset(self, task, seed):
        return Observation("episode-1", 0, "", {"step": 0})

    def call(self, name, **arguments):
        self.calls.append((name, arguments))
        return {"kind": self.kind, "physical": self.physical} if name == "profile" else {}


class FakePlace(Place):
    def __init__(self, level="ask_once_session", skips=False, fail=None):
        self.given, self.skips, self.fail = level, skips, fail
        self.begun, self.released, self.worker = [], [], FakeWorker()

    def kinds(self):
        return {"desktop": {"label": "Your desktop"}, "browser": {"label": "Background browser"},
                "project": {"label": "Project folder", "folder": True}}

    def level(self, kind, runtime):
        return self.given, self.skips

    def begin(self, conversation, kind, folder, cancelled):
        if self.fail:
            raise self.fail
        self.begun.append((kind, folder))
        return {"env": self.worker, "embodiment": "desktop", "task": "free", "skills": ["desktop"],
                "prompt": "click(x, y) clicks.", "release": lambda: self.released.append(kind)}

    def agents(self):
        return {"mode": "off", "depth": 1, "prompt": "delegate(task) starts one."}


class FakeConversation:
    """What Environments needs of a conversation: its kind, who can be asked, its trace."""

    def __init__(self, answers=(), interactive=True, primary="none"):
        self.workspace_kind, self.interactive, self.seed = primary, interactive, 0
        self.config = SimpleNamespace(runtime={})
        self.identity, self._closing = {"session": "s", "agent": "main"}, False
        self.records, self.asked, self.answers = [], [], list(answers)
        self.trace = SimpleNamespace(emit=lambda event, **detail: self.records.append({"event": event, **detail}))
        self.prompt, self._skills, self.agents = "", ["environments"], object()

    def _ask_user(self, kind, target, **detail):
        self.asked.append({"kind": kind, "target": target, **detail})
        return self.answers.pop(0)

    @contextmanager
    def _span(self, lane, name, **detail):
        self.records.append({"event": "span", "lane": lane, "name": name, **detail})
        yield {}

    def _prompt_added(self, text):
        self.prompt += text

    def _prompt_removed(self, text):
        self.prompt = self.prompt.replace(text, "")

    def _skill_added(self, name):
        self._skills.append(name)
        return True

    def events(self, name):
        return [record for record in self.records if record["event"] == name]


class AttachPermissionTests(unittest.TestCase):
    def attach(self, level, *, answers=((True, ""),), skips=False, interactive=True, kind="desktop", **use):
        conversation = FakeConversation(answers, interactive)
        place = FakePlace(level, skips)
        return conversation, place, Environments(conversation, place)

    def test_default_level_asks_once_per_conversation_and_kind_with_the_models_reason(self):
        conversation, place, environments = self.attach("ask_once_session", answers=[(True, ""), (True, "")])
        answer = environments.use("desktop", "to see the rendered page")
        self.assertEqual(answer["session"]["episode_id"], "episode-1")
        self.assertEqual(conversation.asked, [{"kind": "environment", "target": "use Your desktop",
                                               "why": "to see the rendered page", "environment": "desktop"}])
        record, = conversation.events("environment_attached")
        self.assertEqual((record["kind"], record["why"], record["asked"], record["level"]),
                         ("desktop", "to see the rendered page", True, "ask_once_session"))
        self.assertIn("Environment `desktop`", conversation.prompt)
        self.assertIn("desktop.NAME(...)", conversation.prompt)
        # Released and taken again in the same conversation: not asked a second time.
        self.assertTrue(environments.release("desktop"))
        self.assertEqual(place.released, ["desktop"])
        self.assertEqual(conversation.prompt, "")
        environments.use("desktop", "to look again")
        self.assertEqual(len(conversation.asked), 1)
        # Another kind is another question.
        environments.use("browser", "to read the docs page")
        self.assertEqual([row["environment"] for row in conversation.asked], ["desktop", "browser"])

    def test_ask_each_asks_every_time(self):
        conversation, _, environments = self.attach("ask_each", answers=[(True, ""), (True, "")])
        environments.use("desktop", "first look")
        environments.release("desktop")
        environments.use("desktop", "second look")
        self.assertEqual(len(conversation.asked), 2)

    def test_allow_does_not_ask_and_is_still_recorded(self):
        conversation, place, environments = self.attach("allow", answers=[])
        environments.use("desktop", "to see the page")
        self.assertEqual(conversation.asked, [])
        record, = conversation.events("environment_attached")
        self.assertEqual((record["asked"], record["why"], record["skipped_confirmation"]),
                         (False, "to see the page", False))
        self.assertEqual([row["name"] for row in conversation.events("span")], ["use desktop"])

    def test_skipped_confirmations_do_not_ask_but_show_and_record_the_reason(self):
        conversation, place, environments = self.attach("ask_each", answers=[], skips=True)
        environments.use("desktop", "to see the page")
        self.assertEqual(conversation.asked, [])
        self.assertEqual(place.begun, [("desktop", None)])
        record, = conversation.events("environment_attached")
        self.assertEqual((record["asked"], record["skipped_confirmation"], record["why"]),
                         (False, True, "to see the page"))

    def test_never_refuses_even_when_confirmations_are_skipped(self):
        for skips in (False, True):
            with self.subTest(skips=skips):
                conversation, place, environments = self.attach("never", answers=[], skips=skips)
                with self.assertRaisesRegex(Refused, "never allow"):
                    environments.use("desktop", "to see the page")
                self.assertEqual((conversation.asked, place.begun), ([], []))
                record, = conversation.events("environment_refused")
                self.assertEqual((record["kind"], record["why"]), ("desktop", "to see the page"))
                self.assertEqual(conversation.events("environment_attached"), [])

    def test_nobody_to_ask_refuses_with_the_reason_and_never_allows_silently(self):
        for level in ("ask_each", "ask_once_session"):
            with self.subTest(level=level):
                conversation, place, environments = self.attach(level, answers=[], interactive=False)
                with self.assertRaisesRegex(Refused, "nobody can be asked"):
                    environments.use("desktop", "to see the page")
                self.assertEqual((conversation.asked, place.begun), ([], []))
        # Where the settings allow it, a run without a user still takes it.
        conversation, place, environments = self.attach("allow", answers=[], interactive=False)
        environments.use("desktop", "to see the page")
        self.assertEqual(place.begun, [("desktop", None)])

    def test_a_refusal_by_the_user_reaches_the_program_with_their_reason(self):
        conversation, place, environments = self.attach("ask_once_session", answers=[(False, "not my screen"),
                                                                                    (True, "")])
        answer = environments.handle({"action": "use", "environment": "desktop", "why": "to see the page"})
        self.assertIn("not my screen", answer["error"])
        self.assertIn("what you could not confirm", answer["error"])
        self.assertEqual(place.begun, [])
        # A no is not remembered as a yes: the next request asks again.
        self.assertIn("value", environments.handle({"action": "use", "environment": "desktop", "why": "again"}))
        self.assertEqual(len(conversation.asked), 2)

    def test_requests_that_cannot_be_put_to_the_user_are_refused_first(self):
        conversation, place, environments = self.attach("allow", answers=[])
        for kind, why, words in (("submarine", "x", "no installed package"), ("project", "x", "which folder"),
                                 ("desktop", "", "say why")):
            with self.subTest(kind=kind), self.assertRaisesRegex(Refused, words):
                environments.use(kind, why)
        conversation.workspace_kind = "desktop"
        with self.assertRaisesRegex(Refused, "already works in desktop"):
            environments.use("desktop", "to see it")
        self.assertEqual(place.begun, [])

    def test_a_workspace_that_cannot_start_is_given_back_and_refused(self):
        conversation = FakeConversation()
        place = FakePlace("allow")
        place.worker.kind = "workspace"  # not the kind it was taken as
        environments = Environments(conversation, place)
        with self.assertRaisesRegex(Refused, "could not be prepared"):
            environments.use("desktop", "to see the page")
        self.assertEqual(place.released, ["desktop"])
        self.assertEqual(environments.attached, {})

    def test_real_input_stays_under_the_physical_policy_of_the_run(self):
        conversation = FakeConversation()
        conversation.config.runtime = {"physical": {"level": "ask_each", "rules": [{"level": "never", "app": "bank"}]}}
        place = FakePlace("allow")
        place.worker.physical = True
        Environments(conversation, place).use("desktop", "to see the page")
        name, arguments = next(call for call in place.worker.calls if call[0] == "physical")
        self.assertEqual((arguments["op"], arguments["level"], arguments["rules"], arguments["interactive"]),
                         ("identify", "ask_each", [{"level": "never", "app": "bank"}], True))

    def test_everything_goes_back_when_the_conversation_ends(self):
        conversation, place, environments = self.attach("allow", answers=[])
        environments.use("desktop", "a")
        environments.use("browser", "b")
        environments.close()
        self.assertEqual(sorted(place.released), ["browser", "desktop"])
        self.assertEqual(len(conversation.events("environment_released")), 2)


class AttachSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings(Path(self.tmp.name))
        self.place = AttachPlace(SimpleNamespace(settings=self.settings), None, "run")

    def test_shipped_default_asks_for_every_kind(self):
        for kind in ("desktop", "apps", "browser", "project", "display"):
            self.assertEqual(self.place.level(kind, {}), ("ask_once_session", False))

    def test_a_rule_for_a_kind_wins_over_the_level(self):
        self.settings.update({"environments": {"attach": "allow",
                                               "rules": [{"level": "never", "kind": "desktop"}]}})
        self.assertEqual(self.place.level("desktop", {})[0], "never")
        self.assertEqual(self.place.level("browser", {})[0], "allow")

    def test_skipping_follows_the_users_own_physical_input_switch(self):
        # The schema's default for physical.level is never the user's choice to skip.
        self.assertFalse(self.place.level("desktop", {})[1])
        self.assertTrue(self.place.level("desktop", {"physical": {"level": "allow"}})[1])
        self.assertFalse(self.place.level("desktop", {"physical": {"level": "ask_each"}})[1])
        self.settings.update({"physical": {"level": "allow"}})
        self.assertTrue(self.place.level("desktop", {})[1])
        # This run's own level wins over the saved one.
        self.assertFalse(self.place.level("desktop", {"physical": {"level": "ask_each"}})[1])
        self.settings.update({"environments": {"rules": [{"level": "never", "kind": "desktop"}]}})
        self.assertEqual(self.place.level("desktop", {}), ("never", True))

    def test_rules_are_checked(self):
        self.assertEqual(check("environments", "rules", [{"level": "allow", "kind": "browser"}]),
                         [{"level": "allow", "kind": "browser"}])
        for bad in ([{"level": "sometimes", "kind": "desktop"}], [{"kind": "desktop"}],
                    [{"level": "allow", "kind": "desktop"}, {"level": "never", "kind": "desktop"}],
                    [{"level": "allow", "kind": "none"}], "desktop"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                check("environments", "rules", bad)
        with self.assertRaises(ValueError):
            check("environments", "attach", "ask_once_app")


class Recording(ScriptedChat):
    def __init__(self, replies):
        super().__init__(replies)
        self.requests = []

    def complete(self, system, messages):
        self.requests.append((system, messages))
        return super().complete(system, messages)


class HostCase(unittest.TestCase):
    def host(self, replies):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "data"
        self.root.mkdir()
        self.project = Path(self.tmp.name) / "project"
        self.project.mkdir()
        (self.project / "a.txt").write_text("hello", encoding="utf-8")
        patch = mock.patch.dict(os.environ, {"HARNESS_DATA": str(self.root), "OPENROUTER_API_KEY": "test-no-network"})
        patch.start()
        self.addCleanup(patch.stop)
        # These scripts give one reply per program: a program holds the turn until it is over
        # (one that asks the user takes as long as the answer).
        grace = mock.patch("harness.runtime.decision.loop.TURN_GRACE_SECONDS", 120.0)
        grace.start()
        self.addCleanup(grace.stop)
        self.chat = Recording(replies)
        self.app = TaskHost(self.root, chat=self.chat)
        self.addCleanup(self.app.close)
        self.server = TaskServer(("127.0.0.1", 0), self.app, token="test")
        self.addCleanup(self.server.server_close)

    def run_to_end(self, run, answers=(), seconds=90, each=None):
        conversation = self.server.conversations[run]
        answers = list(answers)
        asked = []
        for _ in range(int(seconds / 0.05)):
            if conversation.status in ("FINISHED", "ERROR"):
                break
            if conversation.status == "WAITING_FOR_CONFIRMATION" and conversation.approval_id:
                asked.append(dict(conversation._physical))
                accept, reason = answers.pop(0)
                conversation.confirm(accept, reason, request_id=conversation.approval_id)
            if each is not None:
                each(conversation)
            time.sleep(0.05)
        self.assertEqual(conversation.status, "FINISHED", conversation.summary)
        return conversation, asked

    def records(self, run):
        path = self.app.conversations_dir / Path(run).name / "events.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def outputs(self, run):
        return [record["result"] for record in self.records(run) if record["event"] == "cell"]


class AttachedEnvironmentTests(HostCase):
    """A second environment's session in the conversation's own kernel, on a real worker."""

    def test_project_folder_joins_a_conversation_and_goes_back(self):
        self.host([])
        take = (f"<python>\nuse_environment('project', 'to read the file you named', folder={str(self.project)!r})\n"
                "print('READ', project.read_file('a.txt')['text'])\n"
                "project.write_file('b.txt', 'made here')\n"
                "print('STATE', get_state())\n</python>")
        back = ("<python>\nprint('AGAIN', project.read_file('b.txt')['text'])\n"
                "print('BACK', release_environment('project'))\n"
                "print('GONE', 'project' not in globals())\n</python>")
        self.chat.replies = [take, back, "<finish>done</finish>"]
        run = self.app.start(self.server, "read a.txt", workspace="none")
        conversation, asked = self.run_to_end(run, answers=[(True, "")])
        first, second = self.outputs(run)
        self.assertEqual((first["status"], second["status"]), ("ok", "ok"), (first, second))
        self.assertIn("READ hello", first["stdout"])
        self.assertIn("AGAIN made here", second["stdout"])
        self.assertIn("BACK True", second["stdout"])
        self.assertIn("GONE True", second["stdout"])
        self.assertEqual((self.project / "b.txt").read_text(encoding="utf-8"), "made here")
        # The user was asked once, with the model's reason and the folder.
        self.assertEqual(len(asked), 1)
        self.assertEqual((asked[0]["sensitive"], asked[0]["why"], asked[0]["folder"]),
                         ("environment", "to read the file you named", str(self.project)))
        records = self.records(run)
        attached = next(record for record in records if record["event"] == "environment_attached")
        self.assertEqual((attached["kind"], attached["why"], attached["asked"]),
                         ("project", "to read the file you named", True))
        self.assertTrue(any(record["event"] == "environment_released" for record in records))
        self.assertTrue(any(record["event"] == "span_start" and record.get("name") == "use project"
                            for record in records))
        # Its prompt section is there only while it is attached; the primary's calls are plain.
        prompts = [system for system, _ in self.chat.requests]
        self.assertNotIn("Environment `project`", prompts[0])
        self.assertIn("Environment `project`", prompts[1])
        self.assertIn("run_command", prompts[1])
        self.assertNotIn("Environment `project`", prompts[2])
        # The model is told the attached environment's state beside the conversation's own.
        told = self.chat.requests[1][1][-1]["content"][0]["text"]
        self.assertIn("project state:", told)
        # Its workspace counted against the pool while attached and is free again.
        for provider in self.app.workspaces.providers():
            self.assertEqual(provider.status().get("workspaces"), [])

    def test_a_refusal_lets_the_conversation_go_on(self):
        program = ("<python>\ntry:\n    use_environment('browser', 'to check the page')\n"
                   "except ValueError as error:\n    print('REFUSED', error)\n"
                   "print('HAS', 'browser' in globals())\n</python>")
        self.host([program, "<finish>could not confirm the page</finish>"])
        run = self.app.start(self.server, "check it", workspace="none")
        conversation, asked = self.run_to_end(run, answers=[(False, "no browsing today")])
        result, = self.outputs(run)
        self.assertEqual(result["status"], "ok")
        self.assertIn("REFUSED", result["stdout"])
        self.assertIn("no browsing today", result["stdout"])
        self.assertIn("HAS False", result["stdout"])
        self.assertEqual(conversation.result, "could not confirm the page")
        refused = next(record for record in self.records(run) if record["event"] == "environment_refused")
        self.assertEqual((refused["kind"], refused["why"]), ("browser", "to check the page"))


class SubAgentsOffByDefaultTests(HostCase):
    def test_new_conversations_load_no_sub_agent_calls_or_prompt(self):
        self.host([])
        values = self.app.settings.get()
        self.assertEqual(values["session"]["agents"], "off")
        self.assertGreater(values["limits"]["agent_depth"], 0)
        skills = self.app.skills_on(values, "none")["enable"]
        self.assertNotIn("agents", skills)
        self.assertIn("environments", skills)
        prompt = self.app.config(None, "none").system_prompt
        self.assertNotIn("delegate(", prompt)
        self.assertIn("use_environment(", prompt)
        self.assertIn("request_agents(", prompt)

    def test_setting_or_the_conversations_own_switch_loads_them(self):
        self.host([])
        self.assertIn("agents", self.app.skills_on(None, "none", agents=True)["enable"])
        self.app.settings.update({"session": {"agents": "on"}})
        self.assertIn("agents", self.app.skills_on(None, "none")["enable"])
        prompt = self.app.config(None, "none").system_prompt
        self.assertIn("delegate(", prompt)
        self.assertNotIn("request_agents(", prompt)
        # The depth limit still switches them off altogether.
        self.app.settings.update({"limits": {"agent_depth": 0}})
        self.assertNotIn("agents", self.app.skills_on(None, "none")["enable"])

    def test_user_switches_them_on_in_a_running_conversation(self):
        look = "<python>\nprint('HAS', 'delegate' in globals())\n</python>"
        self.host([look, look, "<finish>ok</finish>"])
        chat, server = self.chat, self.server
        complete = chat.complete

        def switching(system, messages):
            # The user flips the switch while the model writes its second program.
            if len(chat.requests) == 1:
                next(iter(server.conversations.values())).enable_agents()
            return complete(system, messages)

        chat.complete = switching
        run = self.app.start(self.server, "do it", workspace="none")
        self.run_to_end(run)
        first, second = self.outputs(run)
        self.assertIn("HAS False", first["stdout"])
        self.assertIn("HAS True", second["stdout"])
        enabled = next(record for record in self.records(run) if record["event"] == "agents_enabled")
        self.assertEqual((enabled["enabled"], enabled["asked_by"]), (True, "user"))
        self.assertNotIn("delegate(", self.chat.requests[0][0])
        self.assertIn("delegate(", self.chat.requests[-1][0])

    def test_model_asks_and_the_user_agrees(self):
        ask = ("<python>\nprint('BEFORE', 'delegate' in globals())\n"
               "print('ON', request_agents('the three reports can be written at the same time'))\n"
               "print('AFTER', callable(delegate))\n</python>")
        self.host([ask, "<finish>ok</finish>"])
        run = self.app.start(self.server, "write three reports", workspace="none")
        conversation, asked = self.run_to_end(run, answers=[(True, "")])
        result, = self.outputs(run)
        self.assertEqual(result["status"], "ok", result)
        for words in ("BEFORE False", "ON True", "AFTER True"):
            self.assertIn(words, result["stdout"])
        self.assertEqual((asked[0]["sensitive"], asked[0]["why"]),
                         ("agents", "the three reports can be written at the same time"))
        self.assertIn("delegate(", self.chat.requests[1][0])

    def test_model_asks_and_the_user_refuses(self):
        ask = ("<python>\ntry:\n    request_agents('to go faster')\nexcept ValueError as error:\n"
               "    print('NO', error)\nprint('HAS', 'delegate' in globals())\n</python>")
        self.host([ask, "<finish>ok</finish>"])
        run = self.app.start(self.server, "do it", workspace="none")
        conversation, asked = self.run_to_end(run, answers=[(False, "one agent is enough")])
        result, = self.outputs(run)
        self.assertIn("one agent is enough", result["stdout"])
        self.assertIn("HAS False", result["stdout"])


if __name__ == "__main__":
    unittest.main()
