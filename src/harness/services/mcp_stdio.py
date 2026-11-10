"""Host-owned stdio MCP transport. No optional UI or agent dependency."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from harness.core.procs import service_environment
from .mcp import McpSession, McpError, SessionGone

class StdioServer(McpSession):
    """An MCP server on its standard input and output: newline-delimited JSON-RPC. It
    starts on the first request (and again when it exited); its requests to the client
    (sampling, roots) are answered with an error, its notifications ignored."""

    def __init__(self, command: list[str], env: dict, log: Path, cwd: Path | None = None, timeout=180.0):
        super().__init__()
        self.command, self.env, self.log, self.cwd = command, env, log, cwd
        self.timeout = float(timeout)
        self.process = None
        self._pending = {}
        self._stopped = False
        self._lifecycle = threading.RLock()
        self._write = threading.Lock()

    def _start(self):
        executable = shutil.which(self.command[0]) or self.command[0]
        if not Path(executable).is_file():
            raise McpError(f"{self.command[0]} is not installed on this computer")
        self.log.parent.mkdir(parents=True, exist_ok=True)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        if getattr(self, "_stderr", None) is not None:
            self._stderr.close()
        self._stderr = open(self.log, "ab")
        base = service_environment(log=lambda line: self._stderr.write(f"harness: {line}\n".encode()))
        self._stderr.flush()
        # Its own process group: npx and uvx start the server as a child of theirs, and
        # stop() ends them together.
        self.process = subprocess.Popen([executable, *self.command[1:]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self._stderr, env={**base, **self.env}, cwd=self.cwd,
                                        creationflags=flags, start_new_session=sys.platform != "win32")
        threading.Thread(target=self._read, args=(self.process,), daemon=True, name=f"mcp-{self.command[0]}").start()

    def _read(self, process):
        for line in process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if "method" in message and "id" in message:
                self._write_line({"jsonrpc": "2.0", "id": message["id"],
                                  "error": {"code": -32601, "message": "not supported by the-harness"}}, process)
            elif "id" in message and message["id"] in self._pending:
                slot = self._pending.get(message["id"])
                if slot is None or slot["process"] is not process:
                    continue
                slot["reply"] = message
                slot["done"].set()
        for slot in list(self._pending.values()):
            if slot["process"] is process:
                slot["done"].set()

    def _write_line(self, message, process=None):
        data = (json.dumps(message) + "\n").encode()
        with self._write:
            (process or self.process).stdin.write(data)
            (process or self.process).stdin.flush()

    def _tail(self) -> str:
        try:
            return self.log.read_text(encoding="utf-8", errors="replace").strip()[-400:]
        except OSError:
            return ""

    def send(self, message):
        with self._lifecycle:
            return self._send(message)

    def _send(self, message):
        if self._stopped:
            raise McpError("The MCP transport is closed")
        if self.process is None or self.process.poll() is not None:
            self._start()
            if message.get("method") != "initialize":
                raise SessionGone()  # a new process: the session starts again
        if "id" not in message:
            self._write_line(message)
            return None
        slot = self._pending[message["id"]] = {"done": threading.Event(), "reply": None, "process": self.process}
        try:
            self._write_line(message)
            if not slot["done"].wait(self.timeout):
                raise McpError(f"{message['method']}: no answer within {self.timeout:.0f} s")
        except OSError as error:
            raise McpError(f"the server stopped: {error}; {self._tail()}") from None
        finally:
            self._pending.pop(message["id"], None)
        if slot["reply"] is None:
            raise McpError(f"the server exited ({slot['process'].poll()}): {self._tail()}")
        return slot["reply"]

    def stop(self):
        """End the server and the processes it started (npx's node, uvx's Python)."""
        self._stopped = True
        if self.process is not None and self.process.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.process.pid)], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                import signal

                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except OSError:
                    self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.process is not None:
            self.process.stdin.close()
            self.process.stdout.close()
        if getattr(self, "_stderr", None) is not None:
            self._stderr.close()
            self._stderr = None

