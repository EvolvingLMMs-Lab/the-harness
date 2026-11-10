"""Client of tool servers that speak the Model Context Protocol (MCP).

McpSession is the session every transport shares (initialize, request ids, tools/list,
tools/call, error answers); a transport only sends a message. McpClient is streamable
HTTP: messages are JSON-RPC 2.0 POSTed to the server's endpoint, and the answer comes as
JSON or as a text/event-stream whose data lines carry it. The mcp skill (skills/mcp)
lists explicitly configured tools and relays calls to the task host. The host owns
both HTTP and stdio transports; controller programs never launch servers or receive
connection credentials. No optional app or agent is required.
"""

from contextlib import contextmanager
import json
from pathlib import Path
import threading

from ..core.http import open_url, read_sse
from ..core.spans import span


PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    """An MCP server answered with an error, or a tool reported that it failed."""


class SessionGone(Exception):
    """The server no longer knows the session: HTTP 404 to a request with a session id, or
    a stdio server that exited and was started again."""


class McpSession:
    """The client side of one MCP session, whatever carries its messages: it starts on
    first use (initialize, then the initialized notification), numbers the requests and
    turns an error answer into McpError. A transport provides only send()."""

    def __init__(self):
        self._ready = False
        self._next_id = 0
        self._lock = threading.Lock()
        self._requests = threading.RLock()

    def send(self, message):
        """Send one JSON-RPC message; the server's answer to it (a dict), None for a
        notification."""
        raise NotImplementedError

    def request(self, method, params=None):
        """Send one JSON-RPC request and return its result. When the server no longer knows
        the session (it restarted, say after the broker stopped it idle), a new one starts
        with initialize, as the protocol requires, and the request is sent again."""
        with self._requests:
            try:
                return self._request(method, params)
            except SessionGone:
                self._ready = False
                if method == "tools/call":
                    raise McpError("The tool call's outcome is unknown; it was not sent again") from None
                return self._request(method, params)

    def _request(self, method, params):
        if not self._ready and method != "initialize":
            self._request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                         "clientInfo": {"name": "the-harness", "version": "1"}})
            self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self._ready = True
        with self._lock:
            self._next_id += 1
            message = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params
        reply = self.send(message)
        if "error" in reply:
            raise McpError(f"{reply['error'].get('code')}: {reply['error'].get('message')}")
        return reply.get("result", {})

    def tools(self):
        """The server's tools: [{"name", "description", "inputSchema", ...}], every page."""
        tools, cursor = [], None
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += list(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_result(self, name, arguments=None):
        """The complete MCP CallToolResult, including error content and all modalities."""
        with span("service", "mcp", tool=name):
            return self.request("tools/call", {"name": name, "arguments": dict(arguments or {})})

    def call(self, name, arguments=None):
        """Convenience projection for existing service clients; tasks use call_result()."""
        result = self.call_result(name, arguments)
        if result.get("isError"):
            raise McpError(f"tool {name}: {_text(result) or 'failed'}")
        if result.get("structuredContent") is not None:
            return result["structuredContent"]
        return _text(result)

    def stop(self):
        """End what the session started (nothing, over HTTP)."""


class McpClient(McpSession):
    """One MCP server over streamable HTTP; the server's Mcp-Session-Id goes back on every
    request after initialize."""

    def __init__(self, url, timeout=60.0, on_demand=None, headers=None):
        super().__init__()
        self.url = url
        # Sent with every request (a token the server wants).
        self.headers = dict(headers or {})
        self.timeout = float(timeout)
        # A server placed on demand is started by the deploy's broker before a call.
        self.on_demand = on_demand
        self.session_id = None

    def send(self, message):
        from urllib.error import HTTPError

        from .broker import ensure

        ensure({"on_demand": self.on_demand})
        headers = {**self.headers, "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL_VERSION}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        try:
            with open_url(self.url, message, headers, self.timeout) as response:
                self.session_id = response.headers.get("Mcp-Session-Id") or self.session_id
                if "id" not in message:
                    return None  # a notification: accepted, no answer
                return _response(response, message["id"])
        except HTTPError as error:
            with error:
                detail = error.read().decode("utf-8", errors="replace").strip()[:300]
            if error.code == 404 and self.session_id:
                self.session_id = None
                raise SessionGone() from None
            raise McpError(f"HTTP {error.code} from {self.url}: {detail or error.reason}") from None



class Resources:
    """Host-local resource ownership shared across task MCP clients."""
    def __init__(self):
        self._condition = threading.Condition()
        self._busy = set()

    @contextmanager
    def acquire(self, resource, current):
        with self._condition:
            while resource in self._busy:
                if not current():
                    raise McpError("The calling program stopped before dispatch")
                self._condition.wait(0.05)
            if not current():
                raise McpError("The calling program stopped before dispatch")
            self._busy.add(resource)
        try:
            yield
        finally:
            with self._condition:
                self._busy.remove(resource)
                self._condition.notify_all()


class ToolAccess:
    """Run-scoped transports and explicit user grants; server hints grant no authority."""
    def __init__(self, servers, *, prepare=None, resources=None, directory=None, authorize=None):
        self._servers = dict(servers)
        self._prepare = prepare
        self._authorize = authorize
        self._clients = {}
        self._tools = {}
        self._lock = threading.RLock()
        self._closed = False
        self.resources = resources or Resources()
        self.directory = Path(directory or ".")

    def _index(self):
        names = {}
        if self._closed:
            raise McpError("The task's MCP clients are closed")
        for server, config in self._servers.items():
            if not self._current(server):
                continue
            if server not in self._clients:
                if config.get("command"):
                    from .mcp_stdio import StdioServer
                    self._clients[server] = StdioServer(
                        [config["command"], *config.get("args", [])], config.get("env", {}),
                        self.directory / f"mcp-{server}.log", cwd=config.get("cwd"),
                        timeout=float(config.get("timeout_seconds", 60)))
                else:
                    self._clients[server] = McpClient(config["url"],
                        timeout=float(config.get("timeout_seconds", 60)), on_demand=config.get("on_demand"),
                        headers=config.get("headers"))
            if server not in self._tools:
                try:
                    self._tools[server] = self._clients[server].tools()
                except Exception as error:
                    raise McpError(f"{server}: tool discovery failed: {error}") from error
            for spec in self._tools[server]:
                names.setdefault(spec["name"], []).append((server, spec))
        return {name if len(items) == 1 else f"{server}.{name}": (server, spec)
                for name, items in names.items() for server, spec in items}

    def tools(self):
        with self._lock:
            return [{"name": name, "server": server, "description": spec.get("description", ""),
                     "input_schema": spec.get("inputSchema", {})}
                    for name, (server, spec) in sorted(self._index().items())
                    if (self._allowed(server, spec["name"]) or self._write_allowed(server, spec["name"]))
                    and self._current(server, spec["name"])]

    def _check_current(self, server, name=None):
        if self._authorize is not None:
            self._authorize(self._servers[server], name)

    def _current(self, server, name=None):
        try:
            self._check_current(server, name)
            return True
        except McpError:
            return False

    def _allowed(self, server, name):
        config = self._servers[server]
        if name in config.get("tools_off", ()):
            return False
        grants = config.get("allowed_tools", ())
        return name in config.get("read_only_tools", ()) or name in grants or "*" in grants

    def _write_allowed(self, server, name):
        config = self._servers[server]
        return name not in config.get("tools_off", ()) and self._prepare is not None and config.get("host_write_tool") == name

    def call(self, tool, arguments, *, approve=None, current=lambda: True, dispatched=None):
        if not isinstance(tool, str) or not isinstance(arguments, dict):
            raise McpError("An MCP call requires a tool name and an object")
        with self._lock:
            found = self._index().get(tool)
            if found is None:
                raise McpError("The tool has no verified local policy for this call")
            server, spec = found
            config, name = self._servers[server], spec["name"]
            client = self._clients[server]
        with self.resources.acquire(config.get("resource") or server, lambda: not self._closed and current()):
            self._check_current(server, name)
            if self._write_allowed(server, name) and approve is not None:
                with self._prepare(server, config, name, arguments) as (target, commit):
                    if not approve(name, target) or not current():
                        raise McpError("The user did not authorize this call")
                    self._check_current(server, name)
                    if dispatched:
                        dispatched(server)
                    value = commit()
                    return {"content": [{"type": "text", "text": json.dumps(value)}], "structuredContent": value}
            if not self._allowed(server, name):
                raise McpError("The tool has no verified local policy for this call")
            if not current():
                raise McpError("The calling program stopped before dispatch")
            if dispatched:
                dispatched(server)
            return client.call_result(name, arguments)

    def close(self):
        with self._lock:
            self._closed = True
            clients = list(self._clients.values())
        for client in clients:
            client.stop()


def _text(result):
    return "\n".join(str(item.get("text", "")) for item in result.get("content", [])
                     if isinstance(item, dict) and item.get("type") == "text")


def _response(response, request_id):
    """The answer to request `request_id`: the JSON body, or the message of the event
    stream that answers it."""
    if "text/event-stream" in response.headers.get("Content-Type", ""):
        messages = (data for event, data in read_sse(response) if event)
    else:
        messages = [response.read().decode("utf-8", errors="replace")]
    for text in messages:
        try:
            reply = json.loads(text)
        except ValueError:
            continue
        for item in reply if isinstance(reply, list) else [reply]:
            if isinstance(item, dict) and item.get("id") == request_id:
                return item
    raise McpError("the server's reply has no answer to the request")
