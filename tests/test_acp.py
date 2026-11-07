"""The acp package: The Harness as an Agent Client Protocol agent (packages/acp), driven
over pipes by a small test client, with a fake session host whose conversations play
scripted trace records."""

import itertools
import json
import os
import queue
import sys
import threading
import unittest

import helpers  # noqa: F401  (the repository on sys.path)

sys.path.insert(0, str(helpers.ROOT / "packages" / "acp"))

from harness_acp.agent import Agent, METHOD_NOT_FOUND, prompt_text  # noqa: E402

TIMEOUT = 5.0


class FakeConversation:
    """A host conversation whose records are what the test (or the fake host) feeds it."""

    def __init__(self, host, run, session="s1", agent="main"):
        self.host = host
        self.run = run
        self.session = session
        self.agent = agent
        self.feed = queue.Queue()
        self.messages = []
        self.closed = threading.Event()

    def play(self, *records):
        for record in records:
            self.feed.put(record)

    def describe(self):
        return {"id": self.session, "agents": [{"id": self.agent, "run": self.run, "status": "RUNNING"}]}

    def records(self, after=-1, stop=None):
        while True:
            if stop is not None and stop.is_set():
                return
            try:
                record = self.feed.get(timeout=0.02)
            except queue.Empty:
                continue
            if record is None:
                return
            yield record

    def send_message(self, text):
        self.messages.append(text)
        script = self.host.on_message.get(len(self.messages))
        if script:
            self.play(*script)

    def close(self):
        self.closed.set()
        self.feed.put(None)


class FakeHost:
    """The session host's client: post starts a conversation that plays `script`;
    approve records the answer and plays `on_approve[accept]`."""

    def __init__(self, script=(), on_approve=None, on_message=None, agents=None):
        self.script = list(script)
        self.on_approve = on_approve or {}
        self.on_message = on_message or {}
        # The session's agents as the host lists them (beyond the main one).
        self.agents = list(agents or [])
        self.posts = []
        self.approvals = []
        self.approved = threading.Event()
        self.conversations = {}
        self.main = None

    def post(self, path, body, timeout=None):
        self.posts.append((path, body))
        run = f"r{len(self.posts)}"
        self.main = self.conversations[run] = FakeConversation(self, run)
        self.main.play(*self.script)
        return {"run": run}

    def task(self, text, workspace="auto", confirmation=None, runtime=None, timeout=600):
        """As Host.task: POST /api/app/conversations, the conversation it started."""
        return self.conversation(self.post("/api/tasks", {"text": text, "workspace": workspace})["run"])

    def conversation(self, identifier):
        if identifier not in self.conversations:
            session, _, agent = identifier.partition("/")
            self.conversations[identifier] = FakeConversation(self, identifier, session, agent or "main")
        return self.conversations[identifier]

    def session(self, identifier, lines=40):
        row = {"id": identifier, "agents": [{"id": "main", "run": self.main.run if self.main else None,
                                             "status": "RUNNING"}, *self.agents]}
        return type("Session", (), {"row": row})()

    def approve(self, identifier, accept=True, reason="", agent=None, remember=None, *, request_id=None):
        self.approvals.append({"session": identifier, "accept": accept, "reason": reason, "agent": agent,
                               "remember": remember, "request_id": request_id})
        self.approved.set()
        self.main.play(*self.on_approve.get(bool(accept), ()))
        return agent


class Client:
    """A test ACP client: runs the agent's stdio loop on pipes, sends requests, collects
    the agent's notifications and answers its permission requests with `permission`."""

    def __init__(self, host, permission="allow_once"):
        self.agent = Agent(host, log=lambda message: None, poll=0.02)
        self.permission = permission
        agent_in, to_agent = os.pipe()
        from_agent, agent_out = os.pipe()
        self.writer = os.fdopen(to_agent, "w", encoding="utf-8", newline="\n")
        self.reader = os.fdopen(from_agent, "r", encoding="utf-8")
        reader = os.fdopen(agent_in, "r", encoding="utf-8")
        writer = os.fdopen(agent_out, "w", encoding="utf-8", newline="\n")

        def serve():
            try:
                self.agent.serve(reader, writer)
            finally:
                writer.close()
                reader.close()

        self.serving = threading.Thread(target=serve, daemon=True)
        self.serving.start()
        self.inbox = queue.Queue()
        self.reading = threading.Thread(target=self._read, daemon=True)
        self.reading.start()
        self.ids = itertools.count(1)
        self.updates = []
        self.permissions = []
        self.responses = {}

    def _read(self):
        for line in self.reader:
            self.inbox.put(json.loads(line))
        self.inbox.put(None)

    def send(self, message):
        self.writer.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        self.writer.flush()

    def start(self, method, params):
        identifier = next(self.ids)
        self.send({"id": identifier, "method": method, "params": params})
        return identifier

    def call(self, method, params):
        return self.wait(self.start(method, params))

    def wait(self, identifier):
        """Read until the response to `identifier`; notifications and requests on the way
        are kept and answered."""
        while identifier not in self.responses:
            self.step()
        return self.responses.pop(identifier)

    def until(self, condition):
        while not condition():
            self.step()

    def step(self):
        message = self.inbox.get(timeout=TIMEOUT)
        if message is None:
            raise AssertionError("the agent closed its output")
        if message.get("method") == "session/update":
            self.updates.append(message["params"])
        elif message.get("method") == "session/request_permission":
            self.permissions.append(message["params"])
            outcome = ({"outcome": "cancelled"} if self.permission is None else
                       {"outcome": "selected", "optionId": self.permission})
            self.send({"id": message["id"], "result": {"outcome": outcome}})
        elif "id" in message and "method" not in message:
            self.responses[message["id"]] = message
        else:
            raise AssertionError(f"unexpected message {message}")

    def kinds(self):
        return [update["update"]["sessionUpdate"] for update in self.updates]

    def close(self):
        self.writer.close()
        self.serving.join(TIMEOUT)
        self.reading.join(TIMEOUT)
        self.reader.close()


def program(span="p1", code="print(1)", stdout="1\n", status="ok"):
    """The records of one program the agent writes and runs."""
    return [{"event": "model_reply", "text": f"<python>{code}</python>",
             "presentation": {"kind": "python", "thought": "Count first.", "body": code}},
            {"event": "span_start", "id": span, "lane": "program", "name": "program 1"},
            {"event": "span_end", "id": span, "status": status},
            {"event": "cell", "code": code, "result": {"status": status, "seconds": 0.2, "stdout": stdout,
                                                       "error": None if status == "ok" else "it failed"}}]


def answer(text="Done.", reason="message"):
    return [{"event": "agent_message", "text": text}, {"event": "state", "status": "IDLE", "reason": reason}]


class AcpTest(unittest.TestCase):
    def client(self, host, **options):
        client = Client(host, **options)
        self.addCleanup(client.close)
        return client

    def session(self, client):
        return client.call("session/new", {"cwd": "/work", "mcpServers": []})["result"]["sessionId"]

    def test_initialize(self):
        client = self.client(FakeHost())
        result = client.call("initialize", {"protocolVersion": 1, "clientCapabilities": {}})["result"]
        self.assertEqual(result["protocolVersion"], 1)
        self.assertEqual(result["authMethods"], [])
        self.assertFalse(result["agentCapabilities"]["loadSession"])
        self.assertEqual(result["agentCapabilities"]["promptCapabilities"],
                         {"image": False, "audio": False, "embeddedContext": False})

    def test_new_session_starts_nothing(self):
        host = FakeHost()
        client = self.client(host)
        first, second = self.session(client), self.session(client)
        self.assertTrue(first and second and first != second)
        self.assertEqual(host.posts, [])

    def test_prompt_streams_message_and_program(self):
        host = FakeHost([{"event": "state", "status": "RUNNING"}, *program(), *answer("There is 1 file.")],
                        on_message={1: [{"event": "state", "status": "RUNNING"}, *answer("Still 1.")]})
        client = self.client(host)
        session = self.session(client)
        response = client.call("session/prompt", {"sessionId": session,
                                                  "prompt": [{"type": "text", "text": "count the files"}]})
        self.assertEqual(response["result"], {"stopReason": "end_turn"})
        self.assertEqual(host.posts, [("/api/tasks", {"text": "count the files", "workspace": "auto"})])
        self.assertEqual(client.kinds(), ["agent_thought_chunk", "tool_call", "tool_call_update", "tool_call_update",
                                          "agent_message_chunk"])
        updates = [item["update"] for item in client.updates]
        self.assertTrue(all(item["sessionId"] == session for item in client.updates))
        call = updates[1]
        self.assertEqual((call["kind"], call["status"], call["rawInput"]), ("execute", "in_progress",
                                                                           {"code": "print(1)"}))
        self.assertEqual(updates[3]["toolCallId"], call["toolCallId"])
        self.assertEqual(updates[3]["status"], "completed")
        self.assertIn("1", updates[3]["content"][0]["content"]["text"])
        self.assertEqual(updates[4]["content"], {"type": "text", "text": "There is 1 file."})
        # A later prompt is a message to the same conversation.
        response = client.call("session/prompt", {"sessionId": session,
                                                  "prompt": [{"type": "text", "text": "and now?"}]})
        self.assertEqual(response["result"], {"stopReason": "end_turn"})
        self.assertEqual(len(host.posts), 1)
        self.assertEqual(host.main.messages, ["and now?"])
        self.assertEqual(client.updates[-1]["update"]["content"]["text"], "Still 1.")

    def test_failed_program_and_error_end(self):
        host = FakeHost([*program(status="error"), {"event": "error", "message": "the model is gone"},
                         {"event": "state", "status": "ERROR"}])
        client = self.client(host)
        session = self.session(client)
        response = client.call("session/prompt", {"sessionId": session, "prompt": [{"type": "text", "text": "go"}]})
        self.assertEqual(response["result"], {"stopReason": "refusal"})
        statuses = [item["update"].get("status") for item in client.updates
                    if item["update"]["sessionUpdate"] == "tool_call_update"]
        self.assertEqual(statuses, ["failed", "failed"])

    def confirmation(self, permission):
        code = "click(10, 20)"
        host = FakeHost([{"event": "model_reply", "text": f"<python>{code}</python>",
                          "presentation": {"kind": "python", "thought": "", "body": code}},
                         {"event": "confirmation_request", "id": "program-1", "code": code},
                         {"event": "state", "status": "WAITING_FOR_CONFIRMATION"}],
                        on_approve={True: [{"event": "confirmation", "accepted": True, "reason": ""},
                                           {"event": "state", "status": "RUNNING"},
                                           *program(code=code)[1:], *answer("Clicked.")],
                                    False: [{"event": "confirmation", "accepted": False, "reason": "no"},
                                            {"event": "state", "status": "RUNNING"}, *answer("I did not click.")]})
        client = self.client(host, permission=permission)
        session = self.session(client)
        response = client.call("session/prompt", {"sessionId": session, "prompt": [{"type": "text", "text": "click"}]})
        self.assertEqual(response["result"], {"stopReason": "end_turn"})
        self.assertEqual(len(client.permissions), 1)
        asked = client.permissions[0]
        self.assertEqual(asked["sessionId"], session)
        self.assertEqual(asked["toolCall"]["kind"], "execute")
        self.assertEqual([option["optionId"] for option in asked["options"]], ["allow_once", "reject_once"])
        self.assertEqual(len(host.approvals), 1)
        return host, client, asked

    def test_permission_allowed(self):
        host, client, asked = self.confirmation("allow_once")
        self.assertEqual(host.approvals[0], {"session": "s1", "accept": True, "reason": "", "agent": "main",
                                             "remember": "once", "request_id": "program-1"})
        # The approved program runs in the tool call the user approved.
        tool = asked["toolCall"]["toolCallId"]
        ran = [item["update"] for item in client.updates if item["update"].get("toolCallId") == tool]
        self.assertEqual([item.get("status") for item in ran], ["pending", "in_progress", "completed", "completed"])
        self.assertEqual(client.updates[-1]["update"]["content"]["text"], "Clicked.")

    def test_permission_rejected(self):
        host, client, asked = self.confirmation("reject_once")
        self.assertFalse(host.approvals[0]["accept"])
        self.assertEqual(host.approvals[0]["remember"], "once")
        tool = asked["toolCall"]["toolCallId"]
        self.assertEqual([item["update"]["status"] for item in client.updates
                          if item["update"].get("toolCallId") == tool], ["pending", "failed"])

    def test_permission_cancelled_by_client_is_no_approval(self):
        host, _, _ = self.confirmation(None)
        self.assertFalse(host.approvals[0]["accept"])

    def test_physical_input_permission(self):
        request = {"id": "q1", "app": "notepad", "window": "Untitled - Notepad", "actions": ["keyboard"],
                   "why": "type the note"}
        host = FakeHost([{"event": "physical_request", **request},
                         {"event": "state", "status": "WAITING_FOR_CONFIRMATION", "reason": "physical",
                          "request": request}],
                        on_approve={False: [{"event": "physical_answer", "id": "q1", "accepted": False},
                                            {"event": "state", "status": "RUNNING"}, *answer("Not typed.")]})
        client = self.client(host, permission="reject_once")
        session = self.session(client)
        response = client.call("session/prompt", {"sessionId": session, "prompt": [{"type": "text", "text": "type"}]})
        self.assertEqual(response["result"], {"stopReason": "end_turn"})
        self.assertEqual(client.permissions[0]["toolCall"]["kind"], "other")
        self.assertIn("Notepad", client.permissions[0]["toolCall"]["title"])
        self.assertEqual(host.approvals, [{"session": "s1", "accept": False, "reason": "the user rejected it in the "
                                           "editor", "agent": "main", "remember": "once", "request_id": "q1"}])

    def test_sub_agent_waiting(self):
        host = FakeHost([{"event": "state", "status": "RUNNING"}],
                        agents=[{"id": "e1", "run": "s1/e1", "status": "WAITING_FOR_CONFIRMATION",
                                 "approval_id": "current"}],
                        on_approve={True: answer("The sub-agent did it.")})
        sub = host.conversation("s1/e1")
        sub.play({"event": "confirmation_request", "id": "stale", "code": "delete()"},
                 {"event": "state", "status": "WAITING_FOR_CONFIRMATION"},
                 {"event": "confirmation_request", "id": "current", "code": "save()"},
                 {"event": "state", "status": "WAITING_FOR_CONFIRMATION"})
        client = self.client(host)
        session = self.session(client)
        response = client.call("session/prompt", {"sessionId": session, "prompt": [{"type": "text", "text": "go"}]})
        self.assertEqual(response["result"], {"stopReason": "end_turn"})
        self.assertIn("e1", client.permissions[0]["toolCall"]["title"])
        self.assertEqual(host.approvals[0]["agent"], "e1")
        self.assertEqual(host.approvals[0]["request_id"], "current")
        self.assertEqual(len(client.permissions), 1)
        self.assertTrue(host.approvals[0]["accept"])

    def test_cancel(self):
        host = FakeHost([{"event": "state", "status": "RUNNING"},
                         {"event": "model_reply", "text": "<python>wait()</python>",
                          "presentation": {"kind": "python", "thought": "", "body": "wait()"}},
                         {"event": "span_start", "id": "p1", "lane": "program", "name": "program 1"}])
        client = self.client(host)
        session = self.session(client)
        identifier = client.start("session/prompt", {"sessionId": session,
                                                     "prompt": [{"type": "text", "text": "wait forever"}]})
        client.until(lambda: "tool_call" in client.kinds())
        client.send({"method": "session/cancel", "params": {"sessionId": session}})
        response = client.wait(identifier)
        self.assertEqual(response["result"], {"stopReason": "cancelled"})
        self.assertTrue(host.main.closed.wait(TIMEOUT))
        # The next prompt starts a new conversation.
        host.script = answer("New start.")
        response = client.call("session/prompt", {"sessionId": session, "prompt": [{"type": "text", "text": "again"}]})
        self.assertEqual(response["result"], {"stopReason": "end_turn"})
        self.assertEqual(len(host.posts), 2)

    def test_unknown_method_and_session(self):
        client = self.client(FakeHost())
        response = client.call("session/load", {"sessionId": "x", "cwd": "/", "mcpServers": []})
        self.assertEqual(response["error"]["code"], METHOD_NOT_FOUND)
        response = client.call("session/prompt", {"sessionId": "nope", "prompt": [{"type": "text", "text": "hi"}]})
        self.assertEqual(response["error"]["code"], -32602)

    def test_prompt_text(self):
        self.assertEqual(prompt_text([{"type": "text", "text": "open"}, {"type": "image", "data": "..."},
                                      {"type": "resource_link", "uri": "file:///a.txt", "name": "a.txt"}]),
                         "open\nfile:///a.txt")


if __name__ == "__main__":
    unittest.main()
