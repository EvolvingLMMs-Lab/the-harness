"""The conversation controls every frontend draws from: the reply while it is written, the
queue of the owner's messages (edit, remove, clear, send now, hold and resume), stopping the
turn in progress, and the list of chats (rename, pin, archive, delete, search). Through the
host's /api/agent routes, harness.sdk.Agent and harness agent, on one life."""
import json
import threading
import time
from unittest import mock

import helpers  # noqa: F401  (source paths)

from harness.core.http import Preempted
from harness.problems import Problem
from harness.runtime.decision.model import USAGE, ChatReply

from test_agent_frontends import Base, run
from test_agent_life import wait_for


class Streaming:
    """A model that writes each scripted answer a few characters at a time and can be cut
    off, as ChatModel does when it streams. `gate`: writing waits there until it is set."""

    model = "scripted"
    streams_text = True

    def __init__(self, replies, gate=None):
        self.replies = [reply if isinstance(reply, str) else json.dumps(reply) for reply in replies]
        self.calls, self.cut, self.gate = 0, 0, gate

    def complete(self, system, messages, on_text=None, *, cancellation=None):
        text = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        half = len(text) // 2
        for start in range(0, len(text), 5):
            if self.gate is not None and start >= half:
                while not self.gate.is_set():
                    if cancellation.event.wait(0.01):
                        self.cut += 1
                        raise Preempted()
            on_text("text", text[start:start + 5])
        return ChatReply(text=text, usage=dict(USAGE))


class Tasks:
    """A task that runs until it is cancelled."""

    def __init__(self):
        self.cancelled = threading.Event()
        self.submitted = threading.Event()

    def submit(self, goal, *, library=None):
        self.submitted.set()
        return "run-1"

    def observe(self, run, after=-1):
        self.cancelled.wait(20)
        return {"run": run, "after": 3, "status": "ended", "answer": "", "summary": {"status": "cancelled"}}

    def cancel(self, run):
        self.cancelled.set()


class ControlTests(Base):
    def life(self, model, tasks=None):
        from harness_agent.life import Life
        from harness_agent.state import Identity
        from test_agent_frontends import FakeHost

        life = Life(Identity("default"), model=lambda: model, tasks=lambda row: tasks or Tasks())
        life.start()
        self.lives.append(life)
        self.host = FakeHost(life)
        mock.patch("harness_agent.frontends.connect", lambda: self.host).start()
        return life

    def events(self, life, *names):
        return [row for row in life.chats.read("main") if row["event"] in names]

    def test_the_reply_is_shown_while_it_is_written_and_then_is_the_record(self):
        from harness.sdk import Agent

        gate = threading.Event()
        life = self.life(Streaming([{"action": "reply", "text": "The tide comes in at seven tonight."}], gate))
        sent = Agent().say("when is the tide?", wait=False)
        live = wait_for(lambda: (Agent().chat()["live"] or {}).get("text") and Agent().chat()["live"])
        # Half written: the text so far, of the message that is running, and no reply record yet.
        self.assertEqual(live["job"], sent["queued"])
        self.assertTrue("The tide comes in at seven tonight.".startswith(live["text"]))
        self.assertLess(len(live["text"]), len("The tide comes in at seven tonight."))
        self.assertEqual(self.events(life, "reply"), [])
        gate.set()
        done = wait_for(lambda: Agent().chat()["live"] is None and Agent().chat())
        self.assertEqual([row["text"] for row in done["records"] if row["event"] == "reply"],
                         ["The tide comes in at seven tonight."])

    def test_an_action_that_is_no_reply_shows_no_text(self):
        from harness_agent.session import reply_so_far

        self.assertIsNone(reply_so_far('{"action":"task","goal":"tidy the fol'))
        self.assertIsNone(reply_so_far('{"text":"said before its action is kn'))
        self.assertEqual(reply_so_far('{"text":"first","action":"reply"'), "first")
        # The text may stop inside an escape or between the halves of one character.
        whole = json.dumps({"action": "reply", "text": 'a "quote"\nand 你好 😀 end'})
        for size in range(len(whole) + 1):
            text = reply_so_far(whole[:size])
            self.assertTrue(text is None or 'a "quote"\nand 你好 😀 end'.startswith(text), (size, text))
            json.dumps(text, ensure_ascii=False).encode("utf-8")

    def test_queued_messages_are_edited_removed_and_sent_now_and_a_stop_can_hold_them(self):
        from harness.sdk import Agent
        from harness_agent.life import Life
        from harness_agent.state import Identity

        gate = threading.Event()
        model = Streaming([{"action": "reply", "text": "a long enough answer to be stopped in"}], gate)
        life = self.life(model)
        agent = Agent()
        ids = [agent.say(text, wait=False)["queued"] for text in ("one", "two", "three", "four")]
        wait_for(lambda: (agent.queue()["running"] or {}).get("text") == "one")
        queue = agent.queue()
        self.assertEqual((queue["running"]["id"], [row["text"] for row in queue["queued"]], queue["held"]),
                         (ids[0], ["two", "three", "four"], False))
        self.assertEqual([row["text"] for row in agent.queue_edit(ids[1], "two, corrected")["queued"]],
                         ["two, corrected", "three", "four"])
        self.assertEqual([row["id"] for row in agent.queue_remove(ids[2])["queued"]], [ids[1], ids[3]])
        # The one that runs is no longer changed.
        with self.assertRaises(Problem) as refused:
            agent.queue_edit(ids[0], "too late")
        self.assertEqual(refused.exception.code, "started")
        # Stop and hold, while the model writes: the turn ends as interrupted, the others stay.
        wait_for(lambda: (agent.chat()["live"] or {}).get("text"))
        self.assertEqual(agent.stop(hold=True), {"stopped": True, "queued": 2, "held": True})
        wait_for(lambda: agent.queue()["running"] is None)
        time.sleep(0.3)
        self.assertEqual(([row["text"] for row in agent.queue()["queued"]], agent.queue()["held"]),
                         (["two, corrected", "four"], True))
        self.assertEqual(model.cut, 1)
        stopped = self.events(life, "interrupted")
        self.assertEqual((len(stopped), stopped[0]["job"]), (1, ids[0]))
        self.assertEqual(self.events(life, "reply"), [])
        # Held and in order after the host restarts.
        life.close()
        self.lives.remove(life)
        again = Life(Identity("default"), model=lambda: model, tasks=lambda row: Tasks())
        again.start()
        self.lives.append(again)
        self.host.life = again
        self.host.server.background["agent"].life = lambda name: again
        time.sleep(0.3)
        self.assertEqual(([row["text"] for row in agent.queue()["queued"]], agent.queue()["held"]),
                         (["two, corrected", "four"], True))
        # Send the last one now: it goes first, and the queue is no longer held.
        gate.set()
        agent.send_now(ids[3])
        wait_for(lambda: len(self.events(again, "reply")) == 2)
        self.assertEqual([row["text"] for row in self.events(again, "user")], ["one", "four", "two, corrected"])
        self.assertEqual(agent.queue(), {"chat": "main", "held": False, "running": None, "queued": []})
        self.assertEqual(agent.stop(), {"stopped": False, "queued": 0, "held": False})

    def test_stopping_cancels_the_running_task_and_the_next_message_starts(self):
        from harness.sdk import Agent

        tasks = Tasks()
        life = self.life(Streaming([{"action": "task", "goal": "sort the photos"},
                                    {"action": "reply", "text": "ok"}]), tasks)
        agent = Agent()
        agent.say("sort my photos", wait=False)
        self.assertTrue(tasks.submitted.wait(10))
        agent.say("and then say ok", wait=False)
        self.assertEqual(agent.stop()["stopped"], True)
        wait_for(lambda: self.events(life, "reply"))
        self.assertTrue(tasks.cancelled.is_set())
        outcome = next(row for row in self.events(life, "outcome") if row.get("verb") == "task")
        self.assertEqual((outcome["end"], outcome["run"]), ("cancelled", "run-1"))
        order = [row["event"] for row in self.events(life, "user", "interrupted", "reply")]
        self.assertEqual(order, ["user", "interrupted", "user", "reply"])
        # What the model is shown next says that the turn was stopped.
        state = json.loads((life.identity.directory / "sessions" / "main" / "state.json").read_text(encoding="utf-8"))
        self.assertIsNone(state["pending"])
        self.assertTrue(any("stopped before it finished" in str(message["content"]) for message in state["messages"]))

    def test_chats_are_renamed_pinned_archived_searched_and_deleted(self):
        from harness.sdk import Agent
        from harness_agent.cli import main

        life = self.life(Streaming([{"action": "reply", "text": "The ferry leaves at nine."}]))
        agent = Agent()
        agent.say("when does the ferry leave?")
        notes, trip = agent.new_chat("notes"), agent.new_chat("trip")
        agent.rename_chat(trip, "Trip to the island")
        rows = agent.pin_chat(notes)
        self.assertEqual([(row["chat"], row["pinned"]) for row in rows][:2], [("main", False), (notes, True)])
        self.assertEqual([row["chat"] for row in agent.chats(q="ISLAND")], [trip])
        found = agent.chats(q="ferry")
        self.assertEqual((found[0]["chat"], "ferry" in found[0]["match"]), ("main", True))
        agent.archive_chat(trip)
        self.assertNotIn(trip, [row["chat"] for row in agent.chats()])
        self.assertEqual([row["chat"] for row in agent.chats(archived=True)], [trip])
        for refused in (lambda: agent.archive_chat("main"), lambda: agent.delete_chat("main")):
            with self.assertRaises(Problem) as error:
                refused()
            self.assertEqual(error.exception.code, "main_chat")
        agent.delete_chat(trip)
        self.assertEqual(agent.chats(archived=True), [])
        # The same from the command line.
        status, out, _ = run(main, "chats", "rename", notes, "Field notes")
        self.assertEqual((status, out.strip()), (0, f"{notes} is now Field notes"))
        status, out, _ = run(main, "chats")
        self.assertIn("Field notes", out)
        self.assertIn("pinned", out)
        status, out, _ = run(main, "queue")
        self.assertIn("nothing waits and nothing runs", out)
        status, out, _ = run(main, "stop")
        self.assertEqual((status, out.strip()), (0, "nothing was running"))
        self.assertFalse(life.chats.folder(trip).exists())
