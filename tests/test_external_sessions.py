from pathlib import Path
import sys
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import helpers
from harness.host.sessions import Sessions, history
from harness.host import Host
from harness.host.tasks import TaskHost
from harness.host.server import HostServer

sys.path.insert(0, str(helpers.ROOT / "packages" / "external-agents"))
from harness_external_agents.acp import AcpSession


class ExternalSessionIndexTests(unittest.TestCase):
    def test_external_identity_persists_after_rename_and_host_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            index = directory / "index.jsonl"
            run_dir = directory / "conversation"
            run_dir.mkdir()
            conversation = SimpleNamespace(
                directory=run_dir, instruction="Work on the project", status="IDLE",
                session_metadata={"kind": "acp", "project": "project", "source": "managed"},
                capabilities={"send": True},
            )
            sessions = Sessions(index=index)
            identifier = sessions.add("conversation", conversation, frontend="python")
            conversation.session_metadata["external_id"] = "remote-42"
            sessions.save_metadata("conversation")
            sessions.rename("conversation", "New name")
            live = sessions.describe(identifier)
            self.assertEqual(live["agents"][0]["id"], "main")
            self.assertEqual(live["capabilities"], {"send": True})
            stored, = history(index)
            self.assertEqual(stored["id"], identifier)
            self.assertEqual(stored["project"], "project")
            self.assertEqual(stored["title"], "New name")
            self.assertEqual(stored["metadata"]["external_id"], "remote-42")
            self.assertIsNone(stored["capabilities"])


PEER = """
import json, sys
def send(**message):
    print(json.dumps(dict(jsonrpc="2.0", **message)), flush=True)

def reply(id, **result):
    send(id=id, result=result)

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        reply(message["id"], protocolVersion=1, agentCapabilities={})
    elif method == "session/new":
        reply(message["id"], sessionId="session-1")
    elif method == "session/prompt":
        pending = message["id"]
        text = message["params"]["prompt"][0]["text"]
        send(id="permission-" + str(pending), method="session/request_permission", params={
            "sessionId": "session-1", "toolCall": {"toolCallId": "tool-" + str(pending), "title": text},
            "options": [{"kind": "allow_once", "optionId": "allow"}, {"kind": "reject_once", "optionId": "deny"}],
        })
    elif message.get("result", {}).get("outcome", {}).get("outcome") == "selected":
        send(method="session/update", params={"sessionId": "session-1", "update": {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Done " + text},
        }})
        reply(pending, stopReason="end_turn")
    elif method == "session/cancel":
        reply(pending, stopReason="cancelled")
"""


class AcpClientTests(unittest.TestCase):
    def wait_for(self, condition):
        deadline = time.monotonic() + 5
        while not condition():
            self.assertLess(time.monotonic(), deadline, "timed out waiting for the ACP peer")
            time.sleep(0.01)

    def test_cancel_invalidates_original_approval_before_replacement_turn(self):
        with tempfile.TemporaryDirectory() as temporary, patch("harness_external_agents.acp.home",
                                                               return_value=Path(temporary)):
            directory = Path(temporary)
            session = AcpSession(directory / "trace", "acp:test", directory, [sys.executable, "-u", "-c", PEER])
            try:
                session.start("first", ())
                self.wait_for(lambda: session.approval_id)
                original = session.approval_id
                session.steer("replacement")
                self.wait_for(lambda: session.approval_id not in (None, original))
                with self.assertRaisesRegex(ValueError, "no longer pending"):
                    session.confirm(True, request_id=original)
                session.confirm(True, request_id=session.approval_id)
                self.wait_for(lambda: session.status == "IDLE")
                session.send_message("another")
                self.wait_for(lambda: session.approval_id)
                session.confirm(True, request_id=session.approval_id)
                self.wait_for(lambda: session.status == "IDLE")
                trace = (session.directory / "events.jsonl").read_text(encoding="utf-8")
                self.assertIn("Done replacement", trace)
                self.assertIn("Done another", trace)
                self.assertNotIn("Done first", trace)
            finally:
                session.close()

    def test_host_starts_acp_without_a_harness_model_and_routes_approval(self):
        with tempfile.TemporaryDirectory() as temporary, patch("harness_external_agents.acp.home",
                                                               return_value=Path(temporary)):
            directory = Path(temporary)
            app = object.__new__(TaskHost)
            app.directory, app.conversations_dir = directory, directory / "conversations"
            app.starting, app.focus_chat = {}, None

            def factory(agent, trace, *, cwd, isolation, model, effort):
                return AcpSession(trace, agent, cwd, [sys.executable, "-u", "-c", PEER])

            module = SimpleNamespace(session_adapter=factory)
            with (patch("harness.extensions.modules", return_value=[module]),
                  HostServer(("127.0.0.1", 0), app, token="test-key") as server):
                listener = threading.Thread(target=server.serve_forever, daemon=True)
                listener.start()
                try:
                    host = Host(f"http://127.0.0.1:{server.server_port}", "test-key")
                    remote = host.task("first", agent="acp:test", folder=directory)
                    conversation = server.conversations[remote.run]
                    self.wait_for(lambda: conversation.approval_id)
                    row = host.session(remote.run, lines=0)
                    self.assertEqual((row.kind, row.project), ("acp", str(directory)))
                    host.approve(row.id, request_id=conversation.approval_id)
                    self.wait_for(lambda: conversation.status == "IDLE")
                    remote.close()
                    self.assertFalse(host.session(row.id, lines=0).live)
                finally:
                    for conversation in server.conversations.values():
                        conversation.close()
                    server.shutdown()
                    listener.join(5)
