"""The resident life of an identity: a QQ group through the OneBot simulator, the owner's
words from several frontends in one queue, pausing, a restart carrying on from the record,
and old events reaching the model as one summary."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)

from harness.runtime.decision.model import ScriptedChat

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "qq"))


def finish_loop(loop, thread, *closing):
    """Close what runs on a fixture's own event loop, end every task still on it, and close
    the loop. A task left pending is destroyed whenever it is collected, and asyncio writes
    that onto the stderr of whatever test runs then."""
    async def shut():
        for close in closing:
            await close()
        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run_coroutine_threadsafe(shut(), loop).result(10)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(10)
    loop.close()


def wait_for(check, seconds=20.0):
    end = time.time() + seconds
    while time.time() < end:
        found = check()
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError("timed out")


class Recorder(ScriptedChat):
    """Scripted replies; what each call was shown is kept."""

    def __init__(self, replies):
        super().__init__([json.dumps(r) if not isinstance(r, str) else r for r in replies])
        self.seen = []
        self.lock = threading.Lock()

    def complete(self, system, messages, **options):
        with self.lock:
            self.seen.append(messages)
            return super().complete(system, messages, **options)


class NoTasks:
    def submit(self, goal, *, library=None):
        raise AssertionError("no task expected")

    def cancel(self, run):
        pass


class QQ:
    """The OneBot simulator and the qq package's space, on a loop of their own."""

    def __init__(self, folder):
        from harness_qq import space as qq
        from harness_qq.simulator import Simulator

        config = Path(folder) / "qq.json"
        config.write_text(json.dumps({"identity": "default", "groups": {"123": "mention"}, "owner": "555"}),
                          encoding="utf-8")
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
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
        self.raw, self.address, self.space = holder["sim"], holder["address"], holder["space"]
        loop, raw = self.loop, self.raw

        class OnItsLoop:
            """The simulator is driven from its own loop."""
            def __getattr__(self, name):
                return lambda *a, **k: loop.call_soon_threadsafe(lambda: getattr(raw, name)(*a, **k))

        self.sim = OnItsLoop()

    def close(self):
        finish_loop(self.loop, self.thread, self.space.space.close, self.raw.close)


class LifeTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = mock.patch.dict(os.environ, {"HARNESS_HOME": self.folder.name, "HARNESS_DATA": self.folder.name})
        self.env.start()
        self.qq = QQ(self.folder.name)

    def tearDown(self):
        self.qq.close()
        self.env.stop()
        self.folder.cleanup()

    def life(self, chat, connect=True):
        from harness_agent.life import Life
        from harness_agent.state import Identity

        identity = Identity("default")
        life = Life(identity, model=lambda: chat, tasks=lambda row: NoTasks())
        life.start()
        if connect and not any(p.get("kind") == "space" for p in __import__("harness_agent.places", fromlist=["load"]).load(identity)):
            life.connect("space", id="qq", title="QQ", address=self.qq.address, channel="qq")
        wait_for(lambda: life.places["qq"].online)
        return life

    def records(self, life, chat, event=None):
        return [r for r in life.chats.read(chat) if event is None or r["event"] == event]

    def test_a_mention_in_the_group_wakes_it_and_it_answers_there(self):
        chat = Recorder([{"action": "reply", "text": "7:30 at the south gate"}])
        life = self.life(chat)
        self.qq.sim.group_message(123, 42, "anyone around?", name="Ming")
        self.qq.sim.group_message(123, 42, "what time tomorrow?", at_self=True, name="Ming")
        group = wait_for(lambda: life.chats.find("qq", "group:123"))
        done = wait_for(lambda: [r for r in self.records(life, group, "outcome") if r.get("verb") == "qq.reply"])
        self.assertEqual(done[0]["end"], "done")
        # One wake for the mention; the unmentioned message only went into the record.
        self.assertEqual(len(chat.seen), 1)
        events = [r for r in self.records(life, group, "event") if r["kind"] == "qq.message"]
        self.assertEqual([r["addressed"] for r in events], [False, True])
        # The list marks the group's chat; the main conversation stays the owner's private chat.
        row = next(r for r in life.chats.listing() if r["chat"] == group)
        self.assertGreater(row["unread"], 0)
        life.close()

    def test_paused_it_records_and_answers_after_resuming(self):
        chat = Recorder([{"action": "reply", "text": "here now"}])
        life = self.life(chat)
        life.pause()
        self.qq.sim.group_message(123, 42, "hello?", at_self=True)
        group = wait_for(lambda: life.chats.find("qq", "group:123"))
        wait_for(lambda: self.records(life, group, "event"))
        time.sleep(0.5)
        self.assertEqual(chat.seen, [])
        life.resume()
        wait_for(lambda: [r for r in self.records(life, group, "outcome") if r.get("verb") == "qq.reply"])
        self.assertEqual(len(chat.seen), 1)
        life.close()

    def test_the_owner_from_two_frontends_is_one_queue_and_qq_joins_the_main_conversation(self):
        chat = Recorder([{"action": "reply", "text": "one"}, {"action": "reply", "text": "two"},
                         {"action": "reply", "text": "three"}])
        life = self.life(chat)
        first = life.say("main", "from the app")
        second = life.say("main", "from the terminal")
        wait_for(lambda: len(self.records(life, "main", "reply")) == 2)
        self.qq.sim.private_message(555, "from my phone")
        replies = wait_for(lambda: len(self.records(life, "main", "reply")) == 3 and self.records(life, "main", "reply"))
        self.assertEqual([r["text"] for r in replies], ["one", "two", "three"])
        users = self.records(life, "main", "user")
        self.assertEqual([u["text"] for u in users], ["from the app", "from the terminal", "from my phone"])
        self.assertEqual(users[2]["channel"], "qq")
        self.assertNotEqual(first["queued"], second["queued"])
        wait_for(lambda: [r for r in self.records(life, "main", "outcome") if r.get("verb") == "reply"])
        life.close()

    def test_after_a_restart_queued_work_is_done_and_old_events_come_as_one_summary(self):
        from harness_agent.state import Identity

        chat = Recorder([{"action": "done", "note": "nothing worth answering now"}])
        life = self.life(chat)
        life.pause()
        self.qq.sim.group_message(123, 42, "old question", at_self=True)
        group = wait_for(lambda: life.chats.find("qq", "group:123"))
        wait_for(lambda: life.waiting.get(group))
        # Ten hours pass while it is down.
        for event in life.waiting[group]:
            event["time"] -= 10 * 3600
        life._persist()
        life.close()
        state = json.loads((Identity("default").directory / "life-state.json").read_text(encoding="utf-8"))
        self.assertTrue(state["paused"])
        again = self.life(chat, connect=False)
        again.resume()
        wait_for(lambda: self.records(again, group, "done"))
        shown = json.dumps(chat.seen[-1], ensure_ascii=False)
        self.assertIn("older_events_summary", shown)
        self.assertIn("old question", shown)
        again.close()
