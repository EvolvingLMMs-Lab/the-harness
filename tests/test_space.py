"""The core speaks the Agent Space Protocol (harness.space): the participant against the SDK's
test space, and the translation layer around a real worker over HTTP."""

import json
import os
import sys
import threading
import time
import unittest
import unittest.mock
import uuid

from agent_space import End

from harness.core.contracts import Observation
from harness.core.codec import EpisodeCursor
from harness.core.worker import WORKER_METHODS, BenchWorker, create_server
from harness.space.environment import ActionFailed, SpaceEnvironment


class Decision:
    def __init__(self, verdict, reasons=()):
        self.verdict, self.reasons = verdict, list(reasons)

    def to_dict(self):
        return {"verdict": self.verdict, "reasons": self.reasons}


class Counter(BenchWorker):
    """A worker whose ticks count: what each tick did is visible in its state."""

    name = "counter"
    methods = (*WORKER_METHODS, "poke", "reject")
    VIEWS = ()

    def __init__(self):
        self._cursor = EpisodeCursor()
        self.executed = 0
        self.new_outcome()

    def reset(self, task, seed):
        self._cursor.start(uuid.uuid4().hex)
        self.new_outcome()
        return Observation(self._cursor.episode_id, 0, f"count ({task}, {seed})", self._state(), {})

    def _state(self):
        return {"step": self._cursor.step, "count": self.executed}

    def _ended(self):
        return False

    def _evaluate(self):
        return {"success": self.executed > 0, "reward": float(self.executed), "process_score": None,
                "steps": self._cursor.step}

    def _screenshot(self):
        return {}

    def _call_profile(self):
        return {"name": self.name, "kind": "none", "tells": True, "max_hz": 5}

    def _call_tick(self, episode_id, step, command, action_id=None):
        self.tick_begins(episode_id, step)
        if command == "blocked":
            return self.tick_refused(Decision("BLOCK", ["not here"]))

        def act():
            if command == "explode":
                raise OSError("the input went out and the device fell silent")
            self.executed += 1

        self.acted(act)
        return self.tick_executed(Decision("PASS"), episode_id, action_id=action_id)

    def _call_poke(self, episode_id, text="poked"):
        self._check_episode(episode_id)
        self.tell(text, "counter")
        return {"told": text}

    def _call_reject(self, episode_id):
        raise PermissionError("not for you")


class Worker:
    def __enter__(self):
        self.environment = Counter()
        self.server = create_server(self.environment, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_address[1]}"
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


class TranslationLayer(unittest.TestCase):
    def setUp(self):
        self.worker = Worker().__enter__()
        self.env = SpaceEnvironment.for_worker(self.worker.endpoint, timeout=30)

    def tearDown(self):
        self.env.close()
        self.worker.__exit__()

    def test_a_run_through_the_space(self):
        env = self.env
        self.assertEqual(env.tools(), [])
        self.assertEqual(env.name, "counter")
        observation = env.reset("free", 3)
        self.assertEqual(observation.instruction, "count (free, 3)")
        self.assertEqual(env.call("profile")["kind"], "none")
        receipt = env.call("tick", episode_id=observation.episode_id, step=0, command="go", action_id="x1")
        self.assertTrue(receipt["executed"])
        self.assertEqual(receipt["state"], {"step": 1, "count": 1})
        self.assertEqual(env.call("state", episode_id=observation.episode_id), {"step": 1, "count": 1})
        self.assertEqual(env.call("observe", episode_id=observation.episode_id), {"state": {"step": 1, "count": 1}, "images": {}})
        self.assertIs(env.outcomes[-1].end, End.DONE)
        token = env.call("claim_outcome", episode_id=observation.episode_id)["token"]
        self.assertEqual(env.call("outcome", token=token)["reward"], 1.0)

    def test_one_action_id_sent_three_times_executes_once(self):
        env = self.env
        observation = env.reset("free", 0)
        p = env.participant
        answers = [p.act("none.tick", None, {"episode_id": observation.episode_id, "step": 0, "command": "go"},
                         id="same-id", timeout=30) for _ in range(3)]
        self.assertEqual({a.end for a in answers}, {End.DONE})
        self.assertEqual(len({a.seq for a in answers}), 1)
        self.assertEqual(self.worker.environment.executed, 1)
        entries = p.record(start=1)["entries"]
        self.assertEqual(sum(1 for e in entries if e["type"] == "asp.outcome" and e["data"]["id"] == "same-id"), 1)

    def test_outcomes_say_what_happened(self):
        env = self.env
        episode = env.reset("free", 0).episode_id
        # The shield stopped it: refused, and the caller reads the envelope as the worker gave it.
        refused = env.call("tick", episode_id=episode, step=0, command="blocked")
        self.assertFalse(refused["executed"])
        self.assertIs(env.outcomes[-1].end, End.REFUSED)
        self.assertEqual(env.outcomes[-1].reason.code, "harness.shield")
        # A stale step: refused with stale, nothing executed.
        with self.assertRaises(ActionFailed) as stale:
            env.call("tick", episode_id=episode, step=7, command="go")
        self.assertIs(stale.exception.outcome.end, End.REFUSED)
        self.assertEqual(stale.exception.outcome.reason.code, "stale")
        self.assertIn("Stale or missing observation", str(stale.exception))
        with self.assertRaises(ActionFailed) as forbidden:
            env.call("reject", episode_id=episode)
        self.assertEqual(forbidden.exception.outcome.reason.code, "forbidden")
        # The input may have reached the device: unknown, and the episode cannot go on.
        with self.assertRaises(ActionFailed) as unknown:
            env.call("tick", episode_id=episode, step=0, command="explode")
        self.assertIs(unknown.exception.outcome.end, End.UNKNOWN)
        self.assertEqual(unknown.exception.outcome.reason.code, "harness.acted")
        self.assertEqual(self.worker.environment.executed, 0)

    def test_basis_picks_the_step_a_participant_saw(self):
        env = self.env
        env.reset("free", 0)
        p = env.participant
        seen = p.observe([], timeout=30)
        first = p.act("none.tick", None, {"command": "go"}, basis=seen["seq"], timeout=30)
        self.assertIs(first.end, End.DONE)
        again = p.act("none.tick", None, {"command": "go"}, basis=seen["seq"], timeout=30)
        self.assertIs(again.end, End.REFUSED)
        self.assertEqual(again.reason.code, "stale")
        fresh = p.act("none.tick", None, {"command": "go"}, basis=first.seq, timeout=30)
        self.assertIs(fresh.end, End.DONE)
        self.assertEqual(self.worker.environment.executed, 2)

    def test_what_the_worker_tells_is_pushed_as_an_event(self):
        env = self.env
        episode = env.reset("free", 0).episode_id
        got = []
        env.participant.on("event", lambda entry: got.append(entry))
        env.participant.subscribe(kinds=["none.told"], timeout=30)
        env.call("poke", episode_id=episode, text="look at me")
        deadline = time.monotonic() + 10
        while not got and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(got[0]["type"], "none.told")
        self.assertEqual(got[0]["data"], {"content": "look at me", "source": "counter", "addressed": True})

    def test_programs_enter_as_members_and_get_no_score(self):
        env = self.env
        episode = env.reset("free", 0).episode_id
        member = env.member()
        try:
            self.assertEqual(member.joined["role"], "member")
            self.assertEqual(member.call("state", episode_id=episode), {"step": 0, "count": 0})
            with self.assertRaises(ActionFailed) as score:
                member.call("outcome", token="x")
            self.assertEqual(score.exception.outcome.reason.code, "forbidden")
        finally:
            member.close()


class AnySpace(unittest.TestCase):
    def test_the_participant_enters_the_sdks_test_space(self):
        env = SpaceEnvironment.connect(f'"{sys.executable}" -m agent_space.testing test-space --listen stdio', timeout=30)
        try:
            self.assertIn("test.toggle", env.verbs())
            self.assertEqual(env.act("test.toggle", object="lamp:1"), {"on": True})
            with self.assertRaises(ActionFailed) as refused:
                env.act("test.add", {"n": "two"}, object="counter:1")
            self.assertIs(refused.exception.outcome.end, End.REFUSED)
            self.assertEqual(refused.exception.outcome.reason.code, "malformed")
        finally:
            env.close()

    def test_its_verbs_become_functions_and_lines_the_model_reads(self):
        from harness.space.vocabulary import describe, functions

        env = SpaceEnvironment.connect(f'"{sys.executable}" -m agent_space.testing test-space --listen stdio', timeout=30)
        try:
            vocabulary = env.vocabulary()
            told = describe(vocabulary, env.space)
            self.assertIn("test.toggle(object: test.lamp) [change]", told)
            self.assertIn("test.add(object: test.counter, n: integer (minimum 1)) [change]", told)
            made = functions(env, vocabulary)
            self.assertEqual(made["test"].toggle("lamp:1"), {"on": True})
            with self.assertRaises(made["ActionFailed"]) as failed:
                made["test"].add("counter:1", n=0)
            self.assertEqual((failed.exception.outcome.end, failed.exception.outcome.reason.code),
                             (End.REFUSED, "malformed"))
            self.assertIn("lamp:1", [t["id"] for t in made["observe"]()["structure"]["things"]])
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()


class EventsAndReactions(unittest.TestCase):
    """What a space pushes reaches the agent's record and its tree of reflexes first; the model
    hears only of what no node answers and is addressed to it (test_units.Episode: the screen
    worker behind the translation layer, a scripted model)."""

    def test_a_pushed_event_fires_the_node_conditioned_on_it_and_the_model_is_not_woken(self):
        from test_units import Episode, program

        asked = "\n".join([
            "def heard(event):",
            "    facts.set('heard', event.detail['data']['content'])",
            "set_reflex('alarm', 'desktop.told', heard)",
            "print('listening')"])
        with Episode([program(asked), "<wait>3<check>pass</check></wait>", "<finish>done</finish>"],
                     tells=True) as episode:
            episode.start()
            self.assertTrue(episode.until(lambda: episode.records("wait")))
            self.assertTrue(episode.environment.tell("The alarm rang."))
            self.assertTrue(episode.until(lambda: any(r.get("kind") == "desktop.told" for r in episode.records("space_event"))))
            summary = episode.end()
            requests = episode.chat.requests
            entered = episode.records("space_entered")
            facts = [row for row in episode.records("fact") if row.get("name") == "heard"]
            units = [row for row in episode.records("unit_end") if row.get("name") == "alarm"]
        self.assertEqual(summary["status"], "finished")
        self.assertEqual((entered[0]["asp"], entered[0]["kind"]), (0, "desktop"))
        self.assertEqual(facts[-1]["value"], '"The alarm rang."')
        self.assertEqual((units[0]["status"], units[0]["quiet"]), ("ok", True))
        # The node answered it: the model was not told.
        self.assertFalse(any("The alarm rang." in str(request) for request in requests))

    def test_an_event_no_node_answers_and_addressed_to_the_agent_wakes_the_model(self):
        from test_units import Episode, program, texts

        with Episode([program("print('nothing runs')"), "<wait>20<check>pass</check></wait>", "<finish>done</finish>"],
                     tells=True) as episode:
            episode.start()
            self.assertTrue(episode.until(lambda: episode.records("wait")))
            self.assertTrue(episode.environment.tell("The alarm rang."))
            summary = episode.end()
            last = episode.chat.requests[-1][-1]
            recorded = episode.records("space_event")
        self.assertEqual(summary["status"], "finished")
        self.assertIn("Message from the environment", texts(last))
        self.assertEqual((recorded[0]["kind"], recorded[0]["asp"]), ("desktop.told", 0))
        self.assertIsInstance(recorded[0]["space_seq"], int)


class ActingFromTheVocabulary(unittest.TestCase):
    """A space with no skills of its own (the SDK's test space, entered by its address): the
    model is told its verbs, and its programs act with them."""

    def setUp(self):
        import subprocess

        self.space = subprocess.Popen([sys.executable, "-m", "agent_space.testing", "test-space", "--listen",
                                       "ws://127.0.0.1:0"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      text=True)
        line = self.space.stdout.readline()
        self.address = line.strip().split(" at ")[-1]

    def tearDown(self):
        self.space.kill()
        self.space.wait(10)

    def test_the_verbs_are_told_and_a_program_acts_with_them(self):
        import tempfile
        from pathlib import Path

        from harness.config.agent import TaskConfig
        from harness.runtime.task.run import TaskRun
        from test_units import Recording, program

        asked = "\n".join([
            "seen = observe()",
            "lamp = [t for t in seen['structure']['things'] if t['id'] == 'lamp:1'][0]",
            "print('before', lamp.get('on'))",
            "print('toggled', test.toggle('lamp:1'))",
            "try:",
            "    test.paint('lamp:1', color='red')",
            "except ActionFailed as error:",
            "    print('refused', error.outcome.end.value, error.outcome.reason.code)"])
        class Told(Recording):
            def complete(self, system, messages):
                self.systems = [*getattr(self, "systems", []), system]
                return super().complete(system, messages)

        chat = Told([program(asked), "<finish>done</finish>"])
        with tempfile.TemporaryDirectory() as root:
            config = TaskConfig(path=Path("."), environment={"space": self.address, "endpoint": self.address},
                                main={"model": "scripted"}, system_prompt="You act by writing programs.",
                                runtime={"verifier": False, "isolation": False, "skills": ["conversation"],
                                         "purpose": "optional", "reflex_method": "optional"},
                                task="free", seeds=[0], max_model_calls=6, max_wall_seconds=120, embodiment="space")
            run = TaskRun(config, 0, Path(root) / "seed-0", chat=chat)
            summary = run.run()
            records = [json.loads(line) for line in (Path(root) / "seed-0" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        system = chat.systems[0]
        self.assertIn("test.toggle(object: test.lamp)", system)
        self.assertIn("ActionFailed", system)
        cell = next(row for row in records if row["event"] == "cell")["result"]
        self.assertEqual(summary["status"], "finished", summary)
        self.assertIn("toggled {'on': True}", cell["stdout"])
        self.assertIn("refused refused forbidden", cell["stdout"])
        self.assertEqual(next(row for row in records if row["event"] == "space_entered")["kind"], None)


class Declared(unittest.TestCase):
    """A package declares its worker's space (spaces/<name>.toml): the project folder's verbs,
    effect classes and basis policy, and a verb made of a tick that lasts as long as the command
    it runs."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        self.folder = tempfile.TemporaryDirectory()
        (Path(self.folder.name) / "notes.txt").write_text("hello", encoding="utf-8")
        options = Path(self.folder.name).parent / f"options-{uuid.uuid4().hex}.toml"
        options.write_text(f"folder = {json.dumps(self.folder.name)}\n", encoding="utf-8")
        self.addCleanup(options.unlink)
        declaration = root / "packages" / "workspace" / "spaces" / "workspace.toml"
        command = (f'"{sys.executable}" -m harness.space.translate --factory harness_workspace.worker:create_environment '
                   f'--options "{options}" --declaration "{declaration}" --listen stdio')
        self.patch = unittest.mock.patch.dict("os.environ", {"PYTHONPATH": os.pathsep.join(
            [str(root / "packages" / "workspace"), os.environ.get("PYTHONPATH", "")])})
        self.patch.start()
        self.env = SpaceEnvironment.connect(command, timeout=60)

    def tearDown(self):
        self.env.close()
        self.patch.stop()
        self.folder.cleanup()

    def test_the_declared_vocabulary_and_a_command_followed_to_its_end(self):
        env, p = self.env, self.env.participant
        verbs = env.verbs()
        self.assertEqual((verbs["workspace.read"]["effect"], verbs["workspace.run"]["effect"]), ("read", "change"))
        self.assertEqual(verbs["workspace.tick"]["stale"], "refuse")
        self.assertTrue(env.capabilities["participants"]["outside"])
        read = env.act("workspace.read", {"path": "notes.txt"})
        self.assertIn("hello", json.dumps(read))
        done = env.act("workspace.run", {"command": [sys.executable, "-c", "print('ran'); raise SystemExit(3)"]})
        self.assertEqual((done["status"], done["exit_code"] if "exit_code" in done else done.get("returncode")), ("exited", 3))
        # A command that would run for a minute, cancelled: the command is stopped and the
        # action ends cancelled, once.
        pending = p.act_async("workspace.run", None, {"command": [sys.executable, "-c", "import time; time.sleep(60)"]},
                              id="long-1")
        time.sleep(1.5)
        p.cancel("long-1")
        cancelled = pending.result(30)
        self.assertIs(cancelled.end, End.CANCELLED)


class OutcomesThatWake(unittest.TestCase):
    def test_an_unknown_outcome_of_a_reflexs_action_wakes_the_model(self):
        from test_units import Episode, program

        asked = "\n".join([
            "def go(event):",
            "    type_text(1)",
            "set_reflex('on_told', 'desktop.told', go)",
            "print('set')"])
        with Episode([program(asked), "<wait>20<check>pass</check></wait>", "<finish>done</finish>"],
                     tells=True) as episode:
            episode.start()
            self.assertTrue(episode.until(lambda: episode.records("wait")))
            episode.environment.jammed = True
            self.assertTrue(episode.environment.tell("Type one key."))
            summary = episode.end()
            requests = episode.chat.requests
            outcomes = episode.records("space_outcome")
        self.assertEqual(summary["status"], "finished")
        self.assertEqual((outcomes[0]["end"], outcomes[0]["reason"]["code"]), ("unknown", "harness.acted"))
        # Nobody waited for the reflex's action: its unknown outcome woke the model.
        self.assertTrue(any("harness.outcome_unknown" in json.dumps(request) for request in requests[1:]))


class QQChannel(unittest.TestCase):
    """The qq package's space with the OneBot 11 simulator, and a conversation in it (scripted
    replies): a group message that does not name the account does not wake the model; an @
    does, and its reply reaches the chat."""

    def setUp(self):
        import asyncio
        import tempfile
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "qq"))
        from harness_qq import space as qq
        from harness_qq.simulator import Simulator

        self.folder = tempfile.TemporaryDirectory()
        config = Path(self.folder.name) / "qq.json"
        config.write_text(json.dumps({"identity": "default", "groups": {"123": "mention"}}), encoding="utf-8")
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        holder = {}

        async def start():
            holder["sim"] = Simulator()
            await holder["sim"].start()
            holder["space"] = qq.QQSpace(holder["sim"].address, settings=qq.Settings(config))
            ready = asyncio.Event()
            self.loop.create_task(holder["space"].serve("ws://127.0.0.1:0", lambda a: (holder.update(address=a), ready.set())))
            await ready.wait()
            for _ in range(100):
                if holder["space"].online:
                    break
                await asyncio.sleep(0.05)

        asyncio.run_coroutine_threadsafe(start(), self.loop).result(20)
        self.sim, self.address = holder["sim"], holder["address"]
        self.qq = holder["space"]

    def tearDown(self):
        import asyncio

        asyncio.run_coroutine_threadsafe(self.qq.space.close(), self.loop).result(10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.folder.cleanup()

    def test_an_unmentioned_message_lets_the_model_wait_and_an_at_wakes_it(self):
        import tempfile
        from pathlib import Path

        from harness.config.agent import TaskConfig
        from harness.runtime.task.run import TaskRun
        from test_units import Recording, program

        reply = "\n".join(["until(None)", "seen = observe()",
                           "named = [t for t in seen['structure']['things'] if t.get('text') == 'what is 2 + 3?']",
                           "print(qq.reply(named[0]['id'], text='5'))"])
        chat = Recording([program("until(None)\nprint('listening')"), "<wait>6<check>pass</check></wait>",
                          "<wait>30<check>pass</check></wait>", program(reply), "<finish>answered</finish>"])
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
            config = TaskConfig(path=Path("."), environment={"space": self.address, "endpoint": self.address},
                                main={"model": "scripted"}, system_prompt="You act by writing programs.",
                                runtime={"verifier": False, "isolation": False, "skills": ["conversation"],
                                         "purpose": "optional", "reflex_method": "optional"},
                                task="free", seeds=[0], max_model_calls=10, max_wall_seconds=120, embodiment="space")
            directory = Path(root) / "seed-0"
            run = TaskRun(config, 0, directory, chat=chat)
            thread = threading.Thread(target=run.run, daemon=True)
            thread.start()

            def records(kind):
                path = directory / "events.jsonl"
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
                return [row for row in rows if row["event"] == kind]

            def until(ready, seconds=30.0):
                end = time.monotonic() + seconds
                while time.monotonic() < end and not ready():
                    time.sleep(0.05)
                return ready()

            self.assertTrue(until(lambda: len(records("wait")) == 1))
            self.loop.call_soon_threadsafe(lambda: self.sim.group_message(123, 7, "anyone up for lunch?"))
            self.assertTrue(until(lambda: len(records("wait")) == 2, 20))
            self.loop.call_soon_threadsafe(lambda: self.sim.group_message(123, 8, "what is 2 + 3?", at_self=True))
            thread.join(60)
            run.close()
            ends = [row["why"] for row in records("wait_end")]
            escalated = [((row.get("reported") or {}).get("detail") or {}).get("data", {}).get("text")
                         for row in records("escalation")]
            recorded = [(row["data"]["text"], row["data"]["addressed"]) for row in records("space_event")
                        if row.get("kind") == "qq.message"]
        # The unmentioned message was recorded and let the wait run out; the @ ended the next one.
        self.assertEqual(recorded, [("anyone up for lunch?", False), ("what is 2 + 3?", True)])
        self.assertEqual(ends, ["time", "event"])
        self.assertEqual(escalated, ["what is 2 + 3?"])
        self.assertEqual(self.sim.sent[-1]["message"], [{"type": "reply", "data": {"id": str(self.sim._message_id - 1)}},
                                                      {"type": "text", "data": {"text": "5"}}])
