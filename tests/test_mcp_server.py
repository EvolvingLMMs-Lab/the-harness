"""The mcp-server package (packages/mcp-server): The Harness as an MCP server, over a fake
session host, on its HTTP transport (driven by the harness's own MCP client) and on stdio."""

import base64
import io
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "packages" / "mcp-server")]

from harness.services.mcp import McpClient, McpError  # noqa: E402
from harness_mcp_server import server as mcp  # noqa: E402


SCREEN = b"\xff\xd8\xff\xe0fake jpeg\xff\xd9"


class FakeSession:
    def __init__(self, row):
        self.row = row
        for key in ("id", "title", "status", "waiting"):
            setattr(self, key, row.get(key))

    def agents(self):
        return list(self.row.get("agents") or [])


class FakeConversation:
    def __init__(self, host, run):
        self.host, self.run = host, run

    def send_message(self, text):
        self.host.messages.append((self.run, text))

    def close(self):
        self.host.stop_session(self.run)

    def records(self, after=-1, stop=None):
        yield from self.host._entry(self.run)["records"][after + 1:]

    def describe(self):
        return self.host._row(self.host._entry(self.run))


class FakeHost:
    """The session host's client with the same calls; what a session does is set by its task:
    "answer" answers at once, "approve" waits for an approval, "many" writes 120 records,
    anything else keeps working."""

    def __init__(self):
        self.entries = {}
        self.posts, self.messages, self.stopped, self.fetched = [], [], [], []

    def _start(self, text):
        number = len(self.entries) + 1
        session, run = f"s{number:03d}abcdef", f"ui/run-{number}"
        records = [{"event": "state", "status": "RUNNING", "time": 1.0}]
        status, waiting = "RUNNING", None
        if "answer" in text:
            records += [{"event": "model_reply", "text": "Done.\n<finish>It is 4.</finish>", "time": 2.0},
                        {"event": "state", "status": "IDLE", "time": 3.0}]
            status, waiting = "IDLE", "message"
        elif "approve" in text:
            records += [{"event": "confirmation_request", "code": "click(10, 10)", "time": 2.0},
                        {"event": "state", "status": "WAITING_FOR_CONFIRMATION", "time": 3.0}]
            status, waiting = "WAITING_FOR_CONFIRMATION", "approval"
        elif "many" in text:
            records += [{"event": "observation", "time": 2.0 + index, "step": index,
                         "image": "data:image/jpeg;base64," + "A" * 4000,
                         "detail": {"frame": "data:image/png;base64,QUJD", "note": "seen"}}
                        for index in range(119)]
        for seq, record in enumerate(records):
            record["seq"] = seq
        self.entries[session] = {"id": session, "run": run, "title": text[:40], "status": status,
                                 "waiting": waiting, "records": records}
        return run

    def _entry(self, identifier):
        identifier = str(identifier)
        for entry in self.entries.values():
            if identifier in (entry["id"], entry["run"]):
                return entry
        found = [entry for entry in self.entries.values() if entry["id"].startswith(identifier)]
        if len(identifier) >= 3 and len(found) == 1:
            return found[0]
        raise RuntimeError(f"this server runs no session {identifier}")

    def _row(self, entry, lines=0):
        progress = [f"line {index}" for index in range(30)]
        agent = {"id": "main", "run": entry["run"], "status": entry["status"], "waiting": entry["waiting"],
                 "depth": 0, "lines": progress[-lines:] if lines > 0 else []}
        return {"id": entry["id"], "run": entry["run"], "title": entry["title"], "status": entry["status"],
                "waiting": entry["waiting"], "frontend": "app", "created": 1.0, "agents": [agent]}

    def get(self, path):
        url = urlparse(path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        if url.path == "/api/events":
            after = int(query.get("after", -1))
            return [record for record in self._entry(query["run"])["records"] if record["seq"] > after]
        if url.path == "/api/app/packages":
            return {"packages": [{"name": "app", "version": "0.2.0"}], "skills": [], "auto_install": "ask"}
        if url.path == "/api/app/packages/search":
            return {"results": [{"name": "browser", "summary": "a browser", "query": query.get("q")}]}
        if url.path == "/api/libraries":
            return {"libraries": [{"name": "desktop", "entries": 2}], "root": "somewhere"}
        if url.path == "/api/library":
            return {"name": query["name"], "version": 3, "columns": ["name"], "entries": [{"name": "open_app"}]}
        raise RuntimeError(f"no route {path}")

    def post(self, path, payload, timeout=None):
        self.posts.append((path, payload))
        if path == "/api/tasks":
            return {"run": self._start(payload["text"])}
        if path == "/api/app/packages/install":
            return {"installed": [{"name": payload["source"], "version": "0.1.0", "path": "elsewhere"}],
                    "problems": [], "packages": []}
        raise RuntimeError(f"no route {path}")

    def task(self, text, workspace="auto", confirmation=None, runtime=None, timeout=600):
        """As Host.task: POST /api/app/conversations, the conversation it started."""
        return FakeConversation(self, self.post("/api/tasks", {"text": text, "workspace": workspace})["run"])

    def fetch(self, path):
        self.fetched.append(path)
        return SCREEN

    def sessions(self, all=False, limit=50):
        return [FakeSession(self._row(entry)) for entry in self.entries.values()][:limit]

    def session(self, identifier, lines=40):
        return FakeSession(self._row(self._entry(identifier), lines))

    def conversation(self, run):
        self._entry(run)
        return FakeConversation(self, run)

    def stop_session(self, identifier, agent=None):
        entry = self._entry(identifier)
        entry["status"], entry["waiting"] = "FINISHED", None
        self.stopped.append(entry["id"])
        return ["main"]


class HttpTransportTest(unittest.TestCase):
    def setUp(self):
        self.host = FakeHost()
        self.server = mcp.McpServer(host=self.host, poll=0.05, log=lambda message: None)
        self.httpd = mcp.http_server(self.server, 0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/mcp"
        self.client = McpClient(self.url, timeout=20)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def raw(self, message, headers=None):
        request = Request(self.url, data=json.dumps(message).encode(), method="POST",
                          headers={"Content-Type": "application/json", **(headers or {})})
        with urlopen(request, timeout=10) as response:
            data = response.read()
            return response.status, dict(response.headers), json.loads(data) if data else None

    def call_raw(self, name, arguments):
        return self.client.request("tools/call", {"name": name, "arguments": arguments})

    def test_initialize_gives_a_session_id(self):
        status, headers, answer = self.raw({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                            "params": {"protocolVersion": "2025-03-26", "capabilities": {}}})
        self.assertEqual(status, 200)
        self.assertTrue(headers.get("Mcp-Session-Id"))
        result = answer["result"]
        self.assertEqual(result["protocolVersion"], "2025-03-26")
        self.assertEqual(result["serverInfo"]["name"], "the-harness")
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertTrue(result["instructions"])
        # A notification is accepted with an empty answer.
        status, _, answer = self.raw({"jsonrpc": "2.0", "method": "notifications/initialized"},
                                   {"Mcp-Session-Id": headers["Mcp-Session-Id"]})
        self.assertEqual((status, answer), (202, None))
        # A session the server does not know is refused.
        with self.assertRaises(HTTPError) as caught:
            self.raw({"jsonrpc": "2.0", "id": 2, "method": "ping"}, {"Mcp-Session-Id": "unknown"})
        caught.exception.close()
        self.assertEqual(caught.exception.code, 404)

    def test_tools_are_listed_with_schemas_and_none_approves(self):
        tools = {tool["name"]: tool for tool in self.client.tools()}
        self.assertEqual(set(tools), {"run_task", "list_sessions", "start_session", "send_message", "stop_session",
                                      "get_session", "observe_screen", "read_events", "list_packages",
                                      "install_package", "list_library"})
        for tool in tools.values():
            self.assertTrue(tool["description"])
            self.assertEqual(tool["inputSchema"]["type"], "object")
        self.assertEqual(tools["run_task"]["inputSchema"]["required"], ["task"])
        self.assertEqual(tools["run_task"]["inputSchema"]["properties"]["wait_seconds"]["maximum"], 120)
        self.assertFalse([name for name in tools if "approv" in name or "confirm" in name])

    def test_run_task_returns_the_answer(self):
        result = self.client.call("run_task", {"task": "answer: what is 2 + 2?", "wait_seconds": 10})
        self.assertEqual(result["answer"], "It is 4.")
        self.assertEqual(result["session"], "s001abcdef")
        self.assertEqual(result["run"], "ui/run-1")
        self.assertEqual(self.host.posts[0], ("/api/tasks",
                                              {"text": "answer: what is 2 + 2?", "workspace": "auto"}))
        # Answered, the session ends, as harness run "task" ends it.
        self.assertEqual(self.host.stopped, ["s001abcdef"])
        self.assertEqual(result["status"], "FINISHED")
        self.assertEqual(len(result["progress"]), mcp.PROGRESS_LINES)

    def test_run_task_does_not_block_past_wait_seconds(self):
        started = time.monotonic()
        result = self.client.call("run_task", {"task": "a long task", "workspace": "browser", "wait_seconds": 1})
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 3)
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertEqual(result["status"], "RUNNING")
        self.assertNotIn("answer", result)
        self.assertTrue(result["session"])
        self.assertTrue(result["progress"])
        self.assertIn("get_session", result["note"])
        self.assertEqual(self.host.posts[0][1]["workspace"], "browser")
        self.assertEqual(self.host.stopped, [])
        # Polled later.
        later = self.client.call("get_session", {"session": result["session"], "lines": 5})
        self.assertEqual(later["status"], "RUNNING")
        self.assertEqual(later["progress"], [f"line {index}" for index in range(25, 30)])

    def test_waiting_session_says_who_approves(self):
        started = time.monotonic()
        result = self.client.call("run_task", {"task": "approve a click", "wait_seconds": 30})
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(result["status"], "WAITING_FOR_CONFIRMATION")
        self.assertEqual(result["waiting"], "approval")
        self.assertIn(f"/sessions picks session {result['session']}", result["note"])
        self.assertIn("/approve", result["note"])
        self.assertIn("cannot approve", result["note"])
        shown = self.client.call("get_session", {"session": result["session"]})
        self.assertEqual(shown["waiting"], "approval")
        self.assertIn("harness frontend", shown["note"])
        with self.assertRaises(McpError):
            self.client.call("approve", {"session": result["session"]})

    def test_sessions_messages_and_stop(self):
        started = self.client.call("start_session", {"task": "a long task"})
        self.assertEqual(started["status"], "RUNNING")
        listed = self.client.call("list_sessions", {"all": True})
        self.assertEqual([row["session"] for row in listed["sessions"]], [started["session"]])
        self.client.call("send_message", {"session": started["session"], "text": "also look at the second tab"})
        self.assertEqual(self.host.messages, [(started["session"], "also look at the second tab")])
        stopped = self.client.call("stop_session", {"session": started["session"]})
        self.assertEqual(stopped["stopped"], ["main"])
        self.assertEqual(self.client.call("get_session", {"session": started["session"]})["status"], "FINISHED")
        missing = self.call_raw("get_session", {"session": "nothing"})
        self.assertTrue(missing["isError"])

    def test_observe_screen_gives_an_image(self):
        session = self.client.call("start_session", {"task": "a long task"})["session"]
        result = self.call_raw("observe_screen", {"session": session})
        self.assertFalse(result["isError"])
        image = result["content"][0]
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["mimeType"], "image/jpeg")
        self.assertEqual(base64.b64decode(image["data"]), SCREEN)
        self.assertEqual(self.host.fetched, ["/api/app/screen?run=ui%2Frun-1"])

    def test_read_events_pages_without_images(self):
        session = self.client.call("start_session", {"task": "many records"})["session"]
        seen, after, pages = [], -1, 0
        while True:
            page = self.client.call("read_events", {"session": session, "after": after})
            pages += 1
            seen += page["events"]
            after = page["next_after"]
            if not page["more"]:
                break
        self.assertEqual(pages, 3)
        self.assertEqual([event["seq"] for event in seen], list(range(120)))
        self.assertEqual(after, 119)
        text = json.dumps(seen)
        self.assertNotIn("base64", text)
        self.assertEqual(seen[1]["event"], "observation")
        self.assertIn("time", seen[1])
        self.assertNotIn("image", seen[1])
        self.assertIn("<image>", seen[1]["detail"])
        small = self.client.call("read_events", {"session": session, "after": 10, "limit": 5})
        self.assertEqual([event["seq"] for event in small["events"]], [11, 12, 13, 14, 15])
        self.assertEqual(small["next_after"], 15)

    def test_install_package_passes_only_the_name(self):
        result = self.client.call("install_package", {"name": "browser"})
        self.assertEqual(result["installed"], [{"name": "browser", "version": "0.1.0"}])
        self.assertEqual(self.host.posts, [("/api/app/packages/install", {"source": "browser"})])
        for name in ("https://example.com/package.zip", "../folder", "C:/packages/x", "git+https://x/y"):
            refused = self.call_raw("install_package", {"name": name})
            self.assertTrue(refused["isError"], name)
        self.assertEqual(len(self.host.posts), 1)

    def test_packages_and_library(self):
        self.assertEqual(self.client.call("list_packages", {})["packages"], [{"name": "app", "version": "0.2.0"}])
        self.assertEqual(self.client.call("list_packages", {"query": "web"})["results"][0]["query"], "web")
        self.assertEqual(self.client.call("list_library", {}), {"libraries": [{"name": "desktop", "entries": 2}]})
        self.assertEqual(self.client.call("list_library", {"name": "desktop"})["entries"], [{"name": "open_app"}])

    def test_foreign_origin_is_refused(self):
        with self.assertRaises(HTTPError) as caught:
            self.raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"Origin": "http://evil.example"})
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)
        status, _, answer = self.raw({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                     {"Origin": "http://localhost:5173"})
        self.assertEqual((status, answer["result"]), (200, {}))

    def test_unknown_method_and_get(self):
        _, _, answer = self.raw({"jsonrpc": "2.0", "id": 7, "method": "resources/nothing"})
        self.assertEqual(answer["error"]["code"], -32601)
        self.assertEqual(answer["id"], 7)
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.url, method="GET"), timeout=10)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 405)

    def test_batch(self):
        _, _, answer = self.raw([{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                 {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                 {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        self.assertEqual([item["id"] for item in answer], [1, 2])


class StdioTransportTest(unittest.TestCase):
    def test_messages_on_pipes(self):
        host = FakeHost()
        server = mcp.McpServer(host=host, poll=0.05, log=lambda message: None)
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
                 {"jsonrpc": "2.0", "method": "notifications/initialized"},
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                 {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "run_task", "arguments": {"task": "answer it", "wait_seconds": 5}}},
                 {"jsonrpc": "2.0", "id": 4, "method": "nothing/here"},
                 {"jsonrpc": "2.0", "id": 5, "method": "ping"},
                 {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "approve", "arguments": {}}}]
        stdin = io.StringIO("\n".join(json.dumps(line) for line in lines) + "\nnot json\n\n")
        stdout = io.StringIO()
        mcp.serve_stdio(server, stdin, stdout)
        answers = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(stdout.getvalue().count("\n"), len(answers))
        by_id = {answer["id"]: answer for answer in answers}
        self.assertEqual(sorted(by_id, key=str), sorted([1, 2, 3, 4, 5, 6, None], key=str))
        self.assertEqual(answers[0]["id"], 1)
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(len(by_id[2]["result"]["tools"]), len(mcp.TOOLS))
        self.assertEqual(by_id[3]["result"]["structuredContent"]["answer"], "It is 4.")
        self.assertEqual(by_id[4]["error"]["code"], -32601)
        self.assertEqual(by_id[5]["result"], {})
        self.assertEqual(by_id[6]["error"]["code"], -32602)
        self.assertEqual(by_id[None]["error"]["code"], -32700)


class LazyHostTest(unittest.TestCase):
    def test_host_is_connected_on_the_first_tool_call(self):
        made = []

        def connect():
            made.append(FakeHost())
            return made[-1]

        server = mcp.McpServer(connect=connect, log=lambda message: None)
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(made, [])
        answer = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                "params": {"name": "list_sessions", "arguments": {}}})
        self.assertEqual(answer["result"]["structuredContent"], {"sessions": []})
        server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                       "params": {"name": "list_sessions", "arguments": {}}})
        self.assertEqual(len(made), 1)


if __name__ == "__main__":
    unittest.main()
