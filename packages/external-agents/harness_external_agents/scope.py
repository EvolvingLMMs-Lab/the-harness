"""A short-lived MCP grant for selected read-only tools of a single local project."""

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import time


TOOLS = {"project_info": "Show the selected Harness session's project, base and working directory.",
         "project_diff": "Show the selected Harness session's Git diff."}


class ProjectGrant:
    def __init__(self, session, names):
        project = session.project
        if not project or any(name not in TOOLS for name in names) or ("project_diff" in names and not project.directory):
            raise ValueError("MCP project grants support project_info and Git-backed project_diff")
        self.names = sorted(set(names))
        self.token = secrets.token_urlsafe(32)
        self.expires = time.monotonic() + 1800
        self.revoked = threading.Event()
        token, allowed = self.token, self.names
        grant = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def do_POST(self):
                if (self.path != "/mcp" or self.headers.get("Origin") or grant.revoked.is_set()
                        or time.monotonic() >= grant.expires or session.ended
                        or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)):
                    self.send_error(403)
                    return
                try:
                    count = int(self.headers.get("Content-Length", "0"))
                    if not 0 < count <= 65536:
                        raise ValueError("invalid MCP body size")
                    body = json.loads(self.rfile.read(count))
                    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
                        raise ValueError("invalid MCP request")
                except (ValueError, OSError):
                    self.send_error(400)
                    return
                method, params = body.get("method"), body.get("params") or {}
                if "id" not in body:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                answer = {"jsonrpc": "2.0", "id": body["id"]}
                if method == "initialize":
                    version = params.get("protocolVersion")
                    answer["result"] = {"protocolVersion": version if version in ("2025-06-18", "2025-11-25")
                                        else "2025-11-25", "capabilities": {"tools": {}},
                                        "serverInfo": {"name": "harness-project", "version": "1"}}
                elif method == "ping":
                    answer["result"] = {}
                elif method == "tools/list":
                    answer["result"] = {"tools": [{"name": name, "description": TOOLS[name],
                                                   "inputSchema": {"type": "object", "additionalProperties": False}}
                                                  for name in allowed]}
                elif method == "tools/call" and params.get("name") in allowed and not params.get("arguments"):
                    name = params["name"]
                    try:
                        result = project.metadata() if name == "project_info" else project.diff()
                        session.trace.emit("external_mcp_call", name=name)
                        answer["result"] = {"content": [{"type": "text", "text": json.dumps(result)}]}
                    except (ValueError, OSError):
                        answer["result"] = {"isError": True, "content": [{"type": "text", "text": "Project unavailable"}]}
                else:
                    answer["error"] = {"code": -32601, "message": "Operation outside the project grant"}
                encoded = json.dumps(answer).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="project-mcp", daemon=True)
        self.thread.start()
        self.timer = threading.Timer(1800, self.close)
        self.timer.daemon = True
        self.timer.start()
        self.lock = threading.Lock()

    def options(self):
        return {"name": "harness-project", "type": "http",
                "url": f"http://127.0.0.1:{self.server.server_port}/mcp",
                "headers": [{"name": "Authorization", "value": "Bearer " + self.token}]}

    def close(self):
        with self.lock:
            if self.revoked.is_set():
                return
            self.revoked.set()
            self.timer.cancel()
            self.server.shutdown()
            self.server.server_close()
