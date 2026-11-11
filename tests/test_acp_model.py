"""An ACP agent as the model of the Harness agent (packages/external-agents model.py)."""

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import helpers
from harness import model_list, providers
from harness.core.http import Preempted, RequestCancellation
from harness.runtime.decision.model import ChatModel

sys.path.insert(0, str(helpers.ROOT / "packages" / "external-agents"))
from harness_external_agents import host as agents_host
from harness_external_agents.model import HISTORY, NO_IMAGE, ROLE, AcpModel


# An ACP agent that answers each prompt with the number of the turn in its session and what
# it was sent, and writes every request it gets to the file named by ACP_LOG.
AGENT = r"""
import json, os, sys

log = open(os.environ["ACP_LOG"], "a", encoding="utf-8")
features = set(filter(None, os.environ.get("ACP_FEATURES", "").split(",")))
sessions = {}
waiting = {}

def send(**message):
    print(json.dumps(dict(jsonrpc="2.0", **message)), flush=True)

def update(session, **fields):
    send(method="session/update", params={"sessionId": session, "update": fields})

def say(session, text):
    update(session, sessionUpdate="agent_message_chunk", content={"type": "text", "text": text})

for line in sys.stdin:
    message = json.loads(line)
    method, params = message.get("method"), message.get("params") or {}
    log.write(json.dumps(message) + "\n")
    log.flush()
    if method == "initialize":
        capabilities = {"promptCapabilities": {"image": "image" in features},
                        "sessionCapabilities": {"systemPrompt": {"mode": {"override": {}}}} if "system" in features else {}}
        send(id=message["id"], result={"protocolVersion": 1, "agentCapabilities": capabilities})
    elif method == "session/new":
        name = f"s{len(sessions) + 1}"
        sessions[name] = 0
        send(id=message["id"], result={"sessionId": name, "configOptions": [
            {"id": "mode", "category": "mode", "currentValue": "auto",
             "options": [{"value": "auto"}, {"value": "default"}, {"value": "plan"}]},
            {"id": "model", "category": "model", "currentValue": "small",
             "options": [{"value": "small"}, {"value": "large"}]},
            {"id": "effort", "category": "thought_level", "currentValue": "default",
             "options": [{"value": "default"}, {"value": "high"}]}]})
    elif method == "session/set_config_option":
        send(id=message["id"], result={})
    elif method == "session/prompt":
        session = params["sessionId"]
        sessions[session] += 1
        text = "".join(block.get("text", f"<{block['type']}>") for block in params["prompt"])
        if "USE_TOOL" in text:
            waiting[session] = message["id"]
            update(session, sessionUpdate="tool_call", toolCallId="t1", title="Write leak.txt", status="pending")
        elif "ASK" in text:
            waiting[session] = message["id"]
            send(id="permission", method="session/request_permission", params={
                "sessionId": session, "toolCall": {"toolCallId": "t2", "title": "Run rm"},
                "options": [{"kind": "allow_once", "optionId": "allow"}, {"kind": "reject_once", "optionId": "deny"}]})
        elif "HANG" in text:
            waiting[session] = message["id"]
        else:
            update(session, sessionUpdate="agent_thought_chunk", content={"type": "text", "text": "thinking"})
            say(session, f"turn {sessions[session]} of {session}: ")
            say(session, text)
            update(session, sessionUpdate="usage_update", used=10, size=100,
                   cost={"amount": 0.5 * sessions[session], "currency": "USD"})
            send(id=message["id"], result={"stopReason": "end_turn",
                                           "usage": {"inputTokens": 7, "cachedReadTokens": 3, "outputTokens": 2}})
    elif method == "session/cancel":
        session = params["sessionId"]
        if session in waiting:
            send(id=waiting.pop(session), result={"stopReason": "cancelled"})
    elif message.get("id") == "permission":
        session = next(iter(waiting))
        say(session, "permission " + json.dumps(message["result"]["outcome"]))
        send(id=waiting.pop(session), result={"stopReason": "end_turn"})
"""


def request(*messages, system="SYSTEM"):
    return {"messages": [{"role": "system", "content": system}, *messages]}


def user(text):
    return {"role": "user", "content": text}


def assistant(text):
    return {"role": "assistant", "content": text}


class AcpModelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.log = Path(self.temporary.name) / "requests.jsonl"
        self.models = []

    def model(self, features="", **config):
        environment = {**os.environ, "ACP_LOG": str(self.log), "ACP_FEATURES": features}
        model = AcpModel({"agent": "acp:test", **config}, [sys.executable, "-u", "-c", AGENT], environment)
        self.models.append(model)
        self.addCleanup(model.close)
        return model

    def sent(self, method):
        rows = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        return [row["params"] for row in rows if row.get("method") == method]

    @staticmethod
    def text(body):
        return body["choices"][0]["message"]["content"]

    def test_a_longer_history_continues_its_session_and_sends_only_what_is_new(self):
        model = self.model()
        first = model("", {}, request(user("one")), 5)
        self.assertEqual(first["usage"]["session"], "new")
        second = model("", {}, request(user("one"), assistant(self.text(first)), user("two")), 5)
        self.assertEqual((self.text(second), second["usage"]["session"]), ("turn 2 of s1: two", "continued"))
        self.assertEqual(len(self.sent("session/new")), 1)
        self.assertEqual(self.sent("session/prompt")[1]["prompt"], [{"type": "text", "text": "two"}])
        # What the agent reports is the call's usage; its running cost becomes the call's share.
        self.assertEqual((second["usage"]["prompt_tokens"], second["usage"]["completion_tokens"]), (10, 2))
        self.assertEqual((first["usage"]["cost"], second["usage"]["cost"]), (0.5, 0.5))

    def test_a_rewritten_history_gets_a_new_session_with_the_whole_conversation(self):
        model = self.model()
        first = model("", {}, request(user("one")), 5)
        body = model("", {}, request(user("ONE"), assistant(self.text(first)), user("two")), 5)
        self.assertEqual(body["usage"]["session"], "new")
        prompt = "".join(block["text"] for block in self.sent("session/prompt")[1]["prompt"])
        self.assertEqual(prompt, ROLE + "SYSTEM\n\n" + HISTORY + "\n[user]\nONE\n[assistant]\n" + self.text(first)
                         + "\n[user]\ntwo")
        # Another system prompt is another conversation too.
        again = model("", {}, request(user("one"), assistant(self.text(first)), user("two"), system="OTHER"), 5)
        self.assertEqual(again["usage"]["session"], "new")

    def test_requests_at_the_same_time_use_sessions_of_their_own(self):
        model = self.model()
        first = model("", {}, request(user("one")), 5)
        history = [user("one"), assistant(self.text(first))]
        answers = {}
        threads = [threading.Thread(target=lambda name=name: answers.__setitem__(
            name, model("", {}, request(*history, user(name)), 5))) for name in ("left", "right")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(sorted(body["usage"]["session"] for body in answers.values()), ["continued", "new"])
        self.assertTrue(self.text(answers["left"]).endswith("left"))
        self.assertTrue(self.text(answers["right"]).endswith("right"))

    def test_the_system_prompt_is_the_sessions_own_where_the_agent_takes_one(self):
        model = self.model("system")
        model("", {}, request(user("one")), 5)
        new, = self.sent("session/new")
        self.assertEqual(new["systemPrompt"], {"mode": "override", "content": [{"type": "text", "text": "SYSTEM"}]})
        self.assertEqual(self.sent("session/prompt")[0]["prompt"], [{"type": "text", "text": "one"}])
        self.assertEqual(self.sent("initialize")[0]["clientCapabilities"], {})
        self.assertTrue(new["_meta"]["disableBuiltInTools"])
        self.assertEqual(os.listdir(new["cwd"]), [])

    def test_model_effort_and_an_asking_mode_are_set_on_the_session(self):
        model = self.model(model="large", reasoning_effort="high")
        model("", {}, request(user("one")), 5)
        self.assertEqual([(row["configId"], row["value"]) for row in self.sent("session/set_config_option")],
                         [("model", "large"), ("effort", "high"), ("mode", "default")])
        with self.assertRaisesRegex(ValueError, "offers no model 'huge': choose one of small, large"):
            self.model(model="huge")("", {}, request(user("one")), 5)

    def test_a_tool_of_its_own_fails_the_turn_and_permissions_are_refused(self):
        model = self.model()
        with self.assertRaisesRegex(OSError, r"started a tool of its own \(Write leak.txt\)"):
            model("", {}, request(user("USE_TOOL")), 5)
        self.assertEqual(self.sent("session/cancel"), [{"sessionId": "s1"}])
        body = model("", {}, request(user("ASK")), 5)
        self.assertEqual(self.text(body), 'permission {"outcome": "selected", "optionId": "deny"}')
        # The failed turn's session is not used again.
        self.assertEqual(body["id"], "s2")

    def test_a_cancellation_cancels_the_turn(self):
        model = self.model()
        cancellation = RequestCancellation()
        threading.Timer(0.3, cancellation.cancel).start()
        started = time.monotonic()
        with self.assertRaises(Preempted):
            model("", {}, request(user("HANG")), 30, cancellation=cancellation)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.sent("session/cancel"), [{"sessionId": "s1"}])

    def test_a_silent_agent_times_out(self):
        with self.assertRaisesRegex(OSError, "sent nothing for 0.3 s"):
            self.model()("", {}, request(user("HANG")), 0.3)

    def test_images_go_to_an_agent_that_reads_them_only(self):
        picture = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
        content = [{"type": "text", "text": "look"}, picture]
        self.model("image")("", {}, request({"role": "user", "content": content}), 5)
        self.model()("", {}, request({"role": "user", "content": content}), 5)
        seeing, blind = (row["prompt"] for row in self.sent("session/prompt"))
        self.assertEqual(seeing[-1], {"type": "image", "mimeType": "image/png", "data": "AAAA"})
        self.assertEqual(blind[-1], {"type": "text", "text": NO_IMAGE})

    def test_chat_model_completes_through_the_package_backend(self):
        settings = {"argv": [sys.executable, "-u", "-c", AGENT], "env": ["ACP_LOG", "ACP_FEATURES"]}
        pieces = []
        with (patch.dict(os.environ, {"ACP_LOG": str(self.log), "ACP_FEATURES": ""}),
              patch.object(agents_host, "configured", return_value={"acp:test": settings}),
              patch("harness.extensions.modules", return_value=[agents_host])):
            chat = ChatModel({"backend": "acp", "agent": "acp:test", "model": "large"})
            self.addCleanup(chat.transport.close)
            reply = chat.complete("SYSTEM", [{"role": "user", "content": [{"type": "input_text", "text": "one"}]}],
                                  on_text=lambda kind, text: pieces.append((kind, text)))
        self.assertEqual((reply.text, reply.reasoning), ("turn 1 of s1: " + ROLE + "SYSTEM\n\none", "thinking"))
        self.assertEqual(reply.usage, {"input_tokens": 10, "output_tokens": 2, "cost_usd": 0.5,
                                       "finish_reason": "stop", "session": "new"})
        self.assertEqual(pieces[0], ("reasoning", "thinking"))
        self.assertTrue(chat.streams_text)

    def test_without_a_package_the_backend_says_what_to_install(self):
        with patch("harness.extensions.modules", return_value=[SimpleNamespace()]):
            with self.assertRaisesRegex(ValueError, "harness install external-agents"):
                ChatModel({"backend": "acp", "agent": "acp:test", "model": "large"})


class AcpModelEntryTests(unittest.TestCase):
    def test_an_agents_entry_is_a_model_of_the_harness_agent(self):
        entry = {"provider": "acp:claude-acp", "model": "fable", "base_url": None}
        role = providers.model_role(entry, {"reasoning_effort": "high"})
        self.assertEqual(role, {"model": "fable", "backend": "acp", "agent": "acp:claude-acp",
                                "reasoning_effort": "high"})
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = providers.model_file(entry, directory, {})
            self.assertIn('backend = "acp"', path.read_text(encoding="utf-8"))
            (directory / "models.json").write_text(json.dumps([{**entry, "efforts": ["high"]}]), encoding="utf-8")
            # A run that names a workspace, a folder or learning takes it like any model.
            self.assertEqual(model_list.select(directory, "fable", native=True)["provider"], "acp:claude-acp")


if __name__ == "__main__":
    unittest.main()
