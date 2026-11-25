"""The core speaks the Agent Space Protocol (harness.space): the participant against the SDK's
test space, and the translation layer around a real worker over HTTP."""

import sys
import threading
import time
import unittest
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
        self.assertEqual(got[0]["data"], {"content": "look at me", "source": "counter"})

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


if __name__ == "__main__":
    unittest.main()
