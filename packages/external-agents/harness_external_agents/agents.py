"""Other harnesses' agents as sub-agents: Claude Code and Codex run headless on a task, and
each tool call they make passes the harness's gate first.

An agent's program calls delegate(task, agent="claude-code") (or "codex"); the session's
Agents (the harness's runtime/task/delegation.py) makes one of these and runs it as a sub-agent of
that agent. It runs the CLI in its own directory with the task:

Claude Code uses only its structured file tools and a PreToolUse hook. Codex starts
a turn without a local execution environment and calls this adapter's workspace tools
over JSON-RPC. Both use a fresh workspace separate from the trace, and use the same
gate before reading or changing its files. Shells and external tools have no bounded
file or effect contract here, so they are unavailable. Sensitive effects require one
answer per call. Without a user, sensitive calls are refused.

What the CLI does goes to the sub-agent's own trace, which the timeline shows as its lane:
the agent's text as model replies, each tool use as a span of the lane "program", its final
answer as finish. What it spends is charged to the agent that started it as it is spent
(charge(calls, cost)), and the sub-agent stops when it reaches its budget (model calls,
dollars where the CLI reports them, seconds) or when it is cancelled. A CLI that is not
installed is an error that says how to install it. Where the CLI is found:
HARNESS_CLAUDE_CODE_COMMAND / HARNESS_CODEX_COMMAND (a command line), else `claude` /
`codex` on PATH.
"""

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from harness.sdk import Trace, approval, events

WAITING = "WAITING_FOR_CONFIRMATION"


def _reserved(part: str) -> bool:
    if os.name != "nt":
        return False
    is_reserved = getattr(os.path, "isreserved", None)
    return is_reserved(part) if is_reserved else Path(part).is_reserved()


# Protect common credential stores even if a task supplied one inside the workspace.
def _credentials(path: Path) -> bool:
    names = {part.casefold() for part in path.parts}
    return bool(names & {".ssh", ".aws", ".gnupg", ".netrc", ".npmrc", ".pypirc",
                         ".git-credentials", "credentials", "credentials.json", "id_rsa",
                         "id_ed25519"} or path.name.casefold().startswith(".env")
                or path.suffix.casefold() in {".pem", ".key", ".p12", ".pfx"})


class ExternalAgent:
    """A sub-agent run by another harness's CLI (see the module docstring). A kind sets `kind`,
    `program`, `install` (how to get the CLI), argv() and read(event), and may set talks
    (it writes to the CLI's stdin), environment(), opened() and finished()."""

    kind = ""
    program = ""
    install = ""
    talks = False
    followups = False

    def __init__(self, task: str, directory, *, budget: dict, model: str | None = None, charge=None,
                 interactive: bool = False, confirmation: str = "never", multi_turn: bool = False):
        if multi_turn and not self.followups:
            raise ValueError("this delegate does not support follow-ups")
        self.multi_turn = multi_turn
        self.task, self.model, self.budget = task, model, dict(budget)
        self.directory = Path(directory).resolve()
        self.trace = Trace(self.directory, events.EVENTS)
        self.workspace = self.directory / "workspace"
        self.workspace.mkdir(exist_ok=False)
        self._charge = charge
        self.interactive, self.confirmation = interactive, confirmation
        self.status, self.summary, self.result, self.question = "IDLE", None, None, None
        self.agents_usage = {"started": 0, "model_calls": 0, "cost_usd": 0.0}
        self.identity = self.workspace_kind = None
        self.instruction = task
        self._closing = self._ended = False
        self._process = None
        self._charged = (0, 0.0)
        self._spans = {}
        self._lock = threading.Lock()
        self._files = threading.Lock()
        # The call that waits for the user (one at a time) and their answer.
        self._question = threading.Lock()
        self._asking = threading.Condition()
        self._asked = self._answer = None
        self._turn_lock = threading.Lock()

    # What Agents asks of a sub-agent.

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._run, name=f"{self.kind}-agent", daemon=True)
        thread.start()
        return thread

    def send_message(self, text: str, sender: str = "user") -> None:
        with self._turn_lock:
            if (not self.multi_turn or sender != "parent" or self._closing or self._ended or self.status != "IDLE"
                    or self.result is None or self._process is None or self._process.poll() is not None):
                raise ValueError(f"{self.kind} is not ready for a follow-up from its parent")
            if self.summary["model_calls"] >= self.budget.get("calls", float("inf")) or self._over_budget():
                raise ValueError("the delegate has no budget left")
            self.result = None
            self.trace.emit("user_message", text=text, sender=sender)
            self._set_status("RUNNING")
            self.next_turn(text)

    def turn_done(self):
        if self.multi_turn and not self._closing and not self._over_budget():
            with self._turn_lock:
                self.trace.emit("agent_message", text=self.result or "")
                self._set_status("IDLE", reason="external_turn")

    def close(self) -> None:
        self._closing = True
        with self._asking:
            self._asking.notify_all()
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()

    def confirm(self, accept: bool, reason: str = "", remember: str | None = None,
                *, request_id: str | None = None) -> None:
        """Answer the call that waits for the user: for that one call only (nothing is
        remembered, whatever `remember` says)."""
        with self._asking:
            if (self._asked is None or self._answer is not None or self._closing
                    or (self._asked.get("sensitive") or request_id is not None)
                    and self._asked["id"] != request_id):
                raise RuntimeError("Nothing waits for confirmation")
            self._answer = (bool(accept), str(reason or ""))
            self._asking.notify_all()

    @property
    def approval_id(self) -> str | None:
        request = self._asked
        return request["id"] if request is not None else None

    @property
    def waiting_for(self) -> str | None:
        """What it waits for the user to approve."""
        request = self._asked
        if request is None:
            return None
        if request.get("sensitive"):
            return f"approval: {approval.say('sensitive.' + request['sensitive'])} ({request['target']})"
        return f"approval: a command ({request['code']})"

    def charge_up(self) -> None:
        """Charge what it spent since the last time to the agent that started it."""
        if self._charge is None or self.summary is None:
            return
        calls, cost = self.summary["model_calls"], self.summary["cost_usd"]
        with self._lock:
            before, self._charged = self._charged, (calls, cost)
        self._charge(calls - before[0], cost - before[1])

    # A kind's own.

    def argv(self, executable: list[str]) -> list[str]:
        raise NotImplementedError

    def read(self, event: dict) -> None:
        """Take one JSON line of the CLI: trace records, usage (self.summary), the result."""
        raise NotImplementedError

    def environment(self) -> dict | None:
        """The CLI's environment (None: this process's)."""
        return None

    def opened(self) -> None:
        """The CLI has started."""

    def finished(self) -> None:
        """The CLI has ended: give back what the run held."""

    # The gate.

    def _path(self, given) -> Path:
        """Resolve a structured file target. The CLI never receives a wider grant."""
        if not isinstance(given, str) or not given.strip():
            raise ValueError("a workspace file path is required")
        root = self.workspace.resolve()
        path = root / given
        relative = path.relative_to(root) if path.is_relative_to(root) else None
        if (not relative or any(part == ".." or ":" in part or part.rstrip(" .") != part
                                or _reserved(part) for part in relative.parts)
                or not path.resolve().is_relative_to(root) or path.resolve() != path):
            raise ValueError("the path is outside the agent's directory or is an alias")
        if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
            raise ValueError("the target must be an ordinary workspace file")
        return path

    def verdict(self, tool: str, path: Path | None = None, *, kind: str | None = None,
                refused: str | None = None) -> tuple[bool, str]:
        target = path.relative_to(self.workspace.resolve()).as_posix() if path is not None else tool
        span = f"{self.kind}-gate-{secrets.token_hex(4)}"
        self.trace.emit("span_start", id=span, lane="program", name="gate", parent=None, detail=tool)
        if self._closing or self._ended or refused:
            allowed, by, reason = False, "shield", refused or "the agent is ending"
        elif kind or path is not None and _credentials(path.relative_to(self.workspace.resolve())):
            kind = kind or "credentials"
            allowed, by, reason = self._ask(approval.request(kind, target, [tool]),
                                            approval.say("sensitive." + kind))
        elif self.confirmation == "always":
            allowed, by, reason = self._ask({"id": f"tool-{secrets.token_hex(4)}", "code": f"{tool}: {target}"},
                                            "the conversation asks before acting")
        else:
            allowed, by, reason = True, "shield", "workspace operation"
        self.trace.emit("span_end", id=span, verdict="allowed" if allowed else "refused", by=by, reason=reason,
                        **({} if allowed else {"error": reason[:300]}))
        return allowed, reason

    def _ask(self, request: dict, why: str) -> tuple[bool, str, str]:
        """Put one call to the user, one at a time: (allowed, by, reason)."""
        sensitive = bool(request.get("sensitive"))
        with self._question:
            if sensitive:
                self.trace.emit("physical_request", **request)
            else:
                self.trace.emit("confirmation_request", **request)
            if not self.interactive:
                accepted, said = False, "nobody is there to ask in this run"
            else:
                with self._asking:
                    self._asked, self._answer = request, None
                self._set_status(WAITING, reason="sensitive" if sensitive else "program", request=request)
                with self._asking:
                    self._asking.wait_for(lambda: self._answer is not None or self._closing or self._ended,
                                          timeout=approval.WORKER_APPROVAL_SECONDS)
                    answer = None if self._closing or self._ended else self._answer
                    self._asked = self._answer = None
                accepted, said = answer or (False, "the agent ended before the user answered")
                if self.status == WAITING:
                    self._set_status("RUNNING")
            if sensitive:
                self.trace.emit("physical_answer", id=request["id"], accepted=accepted, remember="once", reason=said)
            else:
                self.trace.emit("confirmation", accepted=accepted, reason=said)
        if accepted:
            return True, "user" if self.interactive else "policy", f"{why}: {said or 'the user allowed it'}"
        return False, "user" if self.interactive else "shield", f"{why}: not allowed ({said or 'the user said no'})"

    # The run.

    def command(self) -> list[str] | None:
        """The CLI's command line: HARNESS_<KIND>_COMMAND, else the program on PATH; None
        when neither is there."""
        given = os.environ.get(f"HARNESS_{self.kind.upper().replace('-', '_')}_COMMAND")
        if given:
            # (Windows keeps the quotes of a quoted path in its part.)
            return [part.strip('"') for part in shlex.split(given, posix=os.name != "nt")]
        found = shutil.which(self.program)
        return [found] if found else None

    def _set_status(self, status: str, **detail) -> None:
        self.status = status
        self.trace.emit("state", status=status, **detail)

    def _run(self) -> None:
        self.summary = {"status": "running", "model_calls": 0, "cost_usd": 0.0, "output_tokens": 0}
        self.started = time.monotonic()
        self.trace.emit("user_message", text=self.task, sender="parent")
        self._set_status("RUNNING")
        executable = self.command()
        if executable is None:
            return self._end("error", f"the {self.program} CLI is not installed or not on PATH ({self.install})")
        try:
            self._process = subprocess.Popen(self.argv(executable), cwd=self.workspace, env=self.environment(),
                                             stdin=subprocess.PIPE if self.talks or self.multi_turn else subprocess.DEVNULL,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                             encoding="utf-8", errors="replace")
        except OSError as error:
            return self._end("error", f"{self.program} could not start: {error}")
        threading.Thread(target=self._deadline, name=f"{self.kind}-budget", daemon=True).start()
        # Its stderr is read as it comes (a full pipe would stop the CLI); the end of it is kept.
        stderr = []
        reading = threading.Thread(target=lambda: stderr.extend(self._process.stderr), name=f"{self.kind}-stderr",
                                   daemon=True)
        reading.start()
        self.opened()
        for line in self._process.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                self.read(json.loads(line))
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            self.charge_up()
            if self._over_budget():
                self.close()
        code = self._process.wait()
        reading.join(5)
        for pipe in (self._process.stdin, self._process.stdout, self._process.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except OSError:
                pass
        error = "".join(stderr[-50:]).strip()
        if self.summary["status"] == "budget_exhausted":
            self._end("budget_exhausted")
        elif self._closing:
            self._end("closed")
        elif code != 0 or self.result is None:
            self._end("error", self.summary.get("error") or error[-500:]
                      or f"{self.program} ended with exit status {code} and no result")
        else:
            self._end("finished")

    def _over_budget(self) -> bool:
        cost = self.budget.get("cost")
        over = (self.summary["model_calls"] > self.budget.get("calls", float("inf"))
                or cost is not None and self.summary["cost_usd"] > cost)
        if over:
            self.summary["status"] = "budget_exhausted"
        return over

    def _deadline(self) -> None:
        seconds = float(self.budget.get("seconds") or 0)
        process = self._process
        if seconds and process is not None:
            try:
                process.wait(seconds)
            except subprocess.TimeoutExpired:
                self.summary["status"] = "budget_exhausted"
                self.close()

    def _end(self, status: str, error: str | None = None) -> None:
        self._ended = True
        with self._asking:
            self._asking.notify_all()
        self.finished()
        for span in list(self._spans.values()):
            self.trace.emit("span_end", id=span, error="the agent ended first")
        self._spans.clear()
        self.summary.update(status=status, agent_seconds=round(time.monotonic() - self.started, 1),
                            **({"error": error} if error else {}))
        if error:
            self.trace.emit("error", message=error)
        if self.result is not None:
            self.trace.emit("finish", text=self.result)
        (self.directory / "summary.json").write_text(json.dumps(self.summary, indent=1), encoding="utf-8")
        self.charge_up()
        self._set_status("ERROR" if status == "error" else "FINISHED", reason=status)

    # Records of what it does.

    def _reply(self, text: str, usage: dict | None = None) -> None:
        self.trace.emit("model_reply", call=self.summary["model_calls"], text=text, usage=usage or {})

    def _tool(self, identifier: str, name: str, detail: str = "") -> None:
        span = f"{self.kind}-{identifier}"
        self._spans[identifier] = span
        self.trace.emit("span_start", id=span, lane="program", name=name, parent=None,
                        **({"detail": detail[:200]} if detail else {}))

    def _tool_done(self, identifier: str, failed: bool = False) -> None:
        span = self._spans.pop(identifier, None)
        if span is not None:
            self.trace.emit("span_end", id=span, **({"error": "failed"} if failed else {}))


class ClaudeCode(ExternalAgent):
    """Claude Code, headless: `claude -p` with its stream-json events, every tool call through
    its PreToolUse hook (gate.py) to call()."""

    kind = "claude-code"
    program = "claude"
    install = "npm install -g @anthropic-ai/claude-code, then sign in once with `claude`"
    FILE_TOOLS = ("Read",)
    followups = True

    def call(self, tool: str, given, cwd=None) -> tuple[bool, str]:
        """Approve one structured file operation, using the CLI's actual working directory."""
        if tool not in self.FILE_TOOLS:
            return self.verdict(tool, refused="the tool has no bounded workspace operation")
        if self.multi_turn and self.status not in ("RUNNING", WAITING):
            return self.verdict(tool, refused="the delegate is between turns")
        try:
            if cwd is not None and Path(cwd).resolve() != self.workspace.resolve():
                raise ValueError("the tool's working directory is outside the workspace")
            path = self._path(given.get("file_path") if isinstance(given, dict) else None)
        except (ValueError, OSError, RuntimeError):
            return self.verdict(tool, refused="the path is outside the agent's directory or is not a workspace file")
        if _credentials(path.relative_to(self.workspace.resolve())):
            return self.verdict(tool, refused="credential paths are unavailable through the native hook")
        return self.verdict(tool, path)

    def environment(self):
        token = secrets.token_urlsafe(24)
        decide = self.call

        class Gate(BaseHTTPRequestHandler):
            def do_POST(self):
                if not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                    self.send_error(403)
                    return
                try:
                    asked = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                    allowed, reason = decide(str(asked.get("tool_name")), asked.get("tool_input"), asked.get("cwd"))
                except Exception as error:
                    allowed, reason = False, f"the gate failed ({type(error).__name__}: {error}): refused"
                body = json.dumps({"allow": allowed, "reason": reason}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._gate = ThreadingHTTPServer(("127.0.0.1", 0), Gate)
        self._gate.daemon_threads = True
        threading.Thread(target=self._gate.serve_forever, name=f"{self.kind}-gate", daemon=True).start()
        found = str(Path(__file__).resolve().parents[1])
        environment = {key: value for key, value in os.environ.items()
                       if key not in ("CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_SAFE_MODE")}
        return {**environment, "HARNESS_GATE_URL": f"http://127.0.0.1:{self._gate.server_address[1]}/",
                "HARNESS_GATE_TOKEN": token,
                "PYTHONPATH": os.pathsep.join(filter(None, [found, os.environ.get("PYTHONPATH")]))}

    def hook(self) -> dict:
        """The settings that make gate.py Claude Code's PreToolUse hook for every tool, waiting
        as long as the budget's seconds (a user may take a while to answer)."""
        if os.name == "nt":
            # (Claude Code runs a hook in Git Bash, else PowerShell: said explicitly here.)
            run = {"command": f"& '{sys.executable.replace(chr(39), chr(39) * 2)}' -m harness_external_agents.gate",
                   "shell": "powershell"}
        else:
            run = {"command": shlex.join([sys.executable, "-m", "harness_external_agents.gate"])}
        return {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", **run, "timeout": int(self.budget.get("seconds") or 3600) + 60}]}]}}

    def argv(self, executable):
        # The settings go in a file outside its directory (not a result, not its to change).
        handle, self._settings = tempfile.mkstemp(prefix="harness-gate-", suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(self.hook(), file)
        return [*executable, "-p", "--output-format", "stream-json", "--verbose",
                "--permission-mode", "dontAsk", "--setting-sources", "", "--settings", self._settings,
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--no-chrome", "--no-session-persistence",
                "--tools", ",".join(self.FILE_TOOLS), "--disallowedTools", "mcp__*",
                "--max-turns", str(int(self.budget.get("calls") or 30)),
                *(["--model", self.model] if self.model else []),
                *(["--input-format", "stream-json"] if self.multi_turn else ["--", self.task])]

    def opened(self):
        if self.multi_turn:
            self.next_turn(self.task)

    def next_turn(self, text):
        self._process.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": text},
                                              "parent_tool_use_id": None, "session_id": ""}) + "\n")
        self._process.stdin.flush()

    def finished(self):
        gate = getattr(self, "_gate", None)
        if gate is not None:
            gate.shutdown()
            gate.server_close()
        settings = getattr(self, "_settings", None)
        if settings is not None:
            Path(settings).unlink(missing_ok=True)

    def read(self, event):
        kind = event.get("type")
        if kind == "assistant":
            message = event.get("message") or {}
            self.summary["model_calls"] += 1
            usage = message.get("usage") or {}
            self.summary["output_tokens"] += int(usage.get("output_tokens") or 0)
            for block in message.get("content") or []:
                if block.get("type") == "text" and block.get("text"):
                    self._reply(block["text"], usage)
                elif block.get("type") == "tool_use":
                    self._tool(str(block.get("id")), str(block.get("name")))
        elif kind == "user":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    self._tool_done(str(block.get("tool_use_id")), bool(block.get("is_error")))
        elif kind == "result":
            cost = float(event.get("total_cost_usd") or 0.0)
            self.summary["cost_usd"] = self.summary["cost_usd"] + cost if self.multi_turn else cost
            self.summary["model_calls"] = max(self.summary["model_calls"], int(event.get("num_turns") or 0))
            if event.get("is_error"):
                self.summary["error"] = str(event.get("result") or event.get("subtype"))
                if self.multi_turn:
                    self._process.stdin.close()
            else:
                self.result = str(event.get("result") or "")
                self.turn_done()


class Codex(ExternalAgent):
    """Codex app-server with no turn environment and brokered workspace file operations."""

    kind = "codex"
    program = "codex"
    install = "npm install -g @openai/codex, then sign in once with `codex`"
    talks = True
    followups = True
    TOOLS = ("commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "webSearch")
    DISABLED = ("apps", "plugins", "computer_use", "browser_use", "shell_tool", "unified_exec", "multi_agent",
                "multi_agent_v2", "skill_mcp_dependency_install", "skill_search", "standalone_web_search")
    OPERATIONS = {"list_files": "List files in the delegated workspace.",
                  "read_file": "Read a workspace text file.",
                  "write_file": "Create or replace a workspace text file.",
                  "delete_file": "Delete a workspace file after approval."}

    def argv(self, executable):
        return [*executable, *[part for name in self.DISABLED for part in ("--disable", name)],
                "-c", "mcp_servers={}", "-c", 'web_search="disabled"', "app-server"]

    def opened(self):
        self._calls, self._writing = {}, threading.Lock()
        self.thread_id = self.turn_id = None
        self._call("initialize", {"clientInfo": {"name": "the-harness", "version": "1"},
                                  "capabilities": {"experimentalApi": True}})
        self._send({"method": "initialized"})
        tools = []
        for name, description in self.OPERATIONS.items():
            fields = {} if name == "list_files" else {"path": {"type": "string"}}
            if name == "write_file":
                fields["text"] = {"type": "string"}
            tools.append({"type": "function", "name": name, "description": description,
                          "inputSchema": {"type": "object", "properties": fields, "required": list(fields),
                                          "additionalProperties": False}})
        self._call("thread/start", {"cwd": str(self.workspace.resolve()), "approvalPolicy": "never",
                                    "sandbox": "read-only", "environments": [], "ephemeral": True,
                                    "dynamicTools": tools, **({"model": self.model} if self.model else {})})

    def _send(self, message: dict) -> None:
        with self._writing:
            try:
                self._process.stdin.write(json.dumps(message) + "\n")
                self._process.stdin.flush()
            except (OSError, ValueError):
                pass  # it has ended

    def _call(self, method: str, params: dict) -> None:
        identifier = len(self._calls)
        self._calls[identifier] = method
        self._send({"id": identifier, "method": method, "params": params})

    def _done(self) -> None:
        """Its turn ended: closing its stdin ends the app server."""
        with self._writing:
            try:
                self._process.stdin.close()
            except OSError:
                pass

    def next_turn(self, text):
        self.turn_id = None
        self._call("turn/start", {"threadId": self.thread_id, "environments": [],
                                  "input": [{"type": "text", "text": text}]})

    def read(self, event):
        method, params = event.get("method"), event.get("params") or {}
        if method is not None and "id" in event:
            threading.Thread(target=self._answer_request, args=(event,), name="codex-approval", daemon=True).start()
        elif method is None:
            asked = self._calls.get(event.get("id"))
            if "error" in event:
                self.summary["error"] = f"{asked}: {(event.get('error') or {}).get('message')}"
                self._done()
            elif asked == "thread/start":
                result = event["result"]
                thread = result["thread"]
                if (result.get("approvalPolicy") != "never" or (result.get("sandbox") or {}).get("type") != "readOnly"
                        or thread.get("environments") != []):
                    self.summary["error"] = "Codex did not confirm the restricted workspace protocol"
                    self._done()
                    return
                self.thread_id = thread["id"]
                self.next_turn(self.task)
            elif asked == "turn/start":
                self.turn_id = (event.get("result", {}).get("turn") or {}).get("id")
        elif method == "item/started" and (params.get("item") or {}).get("type") in self.TOOLS:
            item = params["item"]
            self._tool(str(item.get("id")), str(item["type"]))
        elif method == "item/completed":
            item = params.get("item") or {}
            if item.get("type") == "agentMessage":
                self.result = str(item.get("text") or "")
                self._reply(self.result)
            elif item.get("type") == "reasoning" and (item.get("summary") or item.get("content")):
                self._reply("\n".join(map(str, item.get("summary") or item.get("content"))))
            else:
                self._tool_done(str(item.get("id")), item.get("status") in ("failed", "declined"))
        elif method == "thread/tokenUsage/updated":
            # One model response each.
            self.summary["model_calls"] += 1
            self.summary["output_tokens"] = int(((params.get("tokenUsage") or {}).get("total") or {}).get(
                "outputTokens") or 0)
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            if self.multi_turn and (not self.turn_id or turn.get("id") != self.turn_id
                                    or params.get("threadId") != self.thread_id):
                return
            self.turn_id = None
            if turn.get("status") != "completed":
                self.summary["error"] = str((turn.get("error") or {}).get("message") or f"the turn {turn.get('status')}")
            if self.multi_turn and turn.get("status") == "completed":
                self.turn_done()
            else:
                self._done()
        elif method == "error" and not params.get("willRetry"):
            self.summary["error"] = str((params.get("error") or {}).get("message"))

    def _workspace_call(self, tool, arguments, *, valid=lambda: True) -> tuple[bool, str]:
        if not isinstance(tool, str) or tool not in self.OPERATIONS or not isinstance(arguments, dict):
            return self.verdict(str(tool), refused="unknown workspace operation")
        try:
            path = None if tool == "list_files" else self._path(arguments.get("path"))
            before = self._file_identity(path) if path is not None else None
            kind = "deleting" if tool == "delete_file" else (
                "irreversible" if tool == "write_file" and before is not None else None)
            allowed, reason = self.verdict(tool, path, kind=kind)
            if not allowed:
                return False, reason
            if not valid():
                return False, "the delegated turn ended before the tool could run"
            if path is None:
                return True, "\n".join(sorted(item.relative_to(self.workspace).as_posix()
                                              for item in self.workspace.rglob("*") if item.is_file()))
            # Re-resolve after an approval. A concurrent operation may have changed the target.
            if self._closing or path != self._path(arguments["path"]) or self._file_identity(path) != before:
                return False, "the target changed while the tool waited"
            if tool == "read_file":
                with path.open(encoding="utf-8") as file:
                    return True, file.read(100_000)
            if tool == "delete_file":
                path.unlink()
            else:
                text = arguments.get("text")
                if type(text) is not str or len(text) > 100_000:
                    return False, "write_file requires bounded text"
                if before is None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with self._path(arguments["path"]).open("x", encoding="utf-8") as file:
                        file.write(text)
                else:
                    with path.open("r+", encoding="utf-8") as file:
                        stat = os.fstat(file.fileno())
                        if (stat.st_dev, stat.st_ino, stat.st_nlink, stat.st_mtime_ns) != before:
                            return False, "the target changed while the tool waited"
                        file.write(text)
                        file.truncate()
            return True, "Done"
        except (KeyError, ValueError, OSError, RuntimeError, TypeError):
            return False, "the workspace operation could not be performed"

    @staticmethod
    def _file_identity(path):
        try:
            stat = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return None
        return stat.st_dev, stat.st_ino, stat.st_nlink, stat.st_mtime_ns

    def _answer_request(self, request: dict) -> None:
        """Only this client's file tools run. Permission requests never widen the boundary."""
        method, params = request["method"], request.get("params") or {}
        if method == "item/tool/call":
            def valid():
                return not self.multi_turn or (self.turn_id is not None and params.get("threadId") == self.thread_id
                                               and params.get("turnId") == self.turn_id)

            with self._files:
                if not valid():
                    allowed, message = False, "the call is outside the active delegated turn"
                else:
                    allowed, message = self._workspace_call(params.get("tool"), params.get("arguments"), valid=valid)
            result = {"success": allowed, "contentItems": [{"type": "inputText", "text": message}]}
        elif method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
            self.verdict(method, refused="native execution and file changes are disabled")
            result = {"decision": "decline"}
        elif method == "item/permissions/requestApproval":
            result = {"permissions": {}, "scope": "turn"}
        elif method == "mcpServer/elicitation/request":
            result = {"action": "decline"}
        elif method == "item/tool/requestUserInput":
            result = {"answers": {}}
        else:
            self._send({"id": request["id"], "error": {"code": -32601, "message": f"{method} is not answered here"}})
            return
        self._send({"id": request["id"], "result": result})
