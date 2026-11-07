"""One bounded natural-language task, including model decisions and agentic control.

Programs, reactive rules and learned policies execute independently of model transport.
The runtime calls the model at decision points, permits steering/clarification during
execution, and settles speculative decisions against their input revisions. Finish and
budget exhaustion end the run. Persistent identity and multi-task conversations are not
part of this lifecycle. Benchmark and interactive task callers use this same engine.
"""

import ast
import base64
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import uuid

from harness.runtime.decision import loop as decisions
from harness.runtime.decision.messages import _inbox_parts
from harness.runtime.execution.results import _taken_over, _cell_usage, _wrap_up
from harness.runtime.safety.approval import CONFIRMATION_POLICIES
from harness.runtime.status import Closed

from harness.bench import bench_names, bench_spec
from harness.core.remote import RemoteEnvironment
from harness.core.media import write_episode_videos
from harness.core import sha256
from harness.core.http import Preempted
from harness.core.trace import Trace, context_summary, provenance, write_json
from harness.embodiments import KINDS as EMBODIMENT_KINDS, embodiment_kind
from harness.runtime.decision.thoughts import Thought, ThoughtCancelled, ThoughtQueue
from harness.runtime.execution.kernel import DEFAULT_BOOTSTRAP, Kernel, KernelDied, kernel_python
from harness.runtime.learning.library import SECTIONS, eligible, executable, library_for
from harness.runtime.task import context as memory_view
from harness.runtime.task.context import WorkingMemory
from harness.runtime.learning.usage import fold_uses
from harness.runtime.decision.messages import EMBODIMENT_TEXT, attachment_parts, cell_feedback, image_parts, prune_images, state_text, window
from harness.runtime.events import EVENTS
from harness.runtime.status import ERROR, FINISHED, IDLE, PAUSED, RUNNING, STATUSES, WAITING_FOR_CONFIRMATION
from harness.runtime.learning.active import sandbox_of
from harness.runtime.decision.protocol import DIRECT_KINDS, KINDS, ProtocolError, announces, looks_like_action, parse_reply

import harness.runtime.learning.views as library_view


class TaskRun:
    """One episode of `config.task` with `seed`, its trace and files under `directory`.
    `chat`, `verifier` and `environment` replace the configured models and worker.
    `interactive`: a user takes part (see the module docstring); `confirmation`: one of
    CONFIRMATION_POLICIES; `instruction`: the user's own instruction in place of the
    task's (the evaluator's outcome still scores the task). `agents` (runtime/task/delegation.py)
    starts the sub-agents its programs ask for; `parent`: the agent that started this one.
    Managed workspaces are acquired by the host before the conversation starts."""

    def __init__(self, config, seed: int, directory, *, chat=None, verifier=None, environment=None,
                 interactive: bool = False, confirmation: str = "never", instruction: str | None = None,
                 agents=None, parent=None, memory=None):
        from copy import copy

        from harness.config.agent import resolve_for
        from harness.runtime.task.delegation import NO_DEEPER, SUB_AGENT_PROMPT

        if confirmation not in CONFIRMATION_POLICIES:
            raise ValueError(f"confirmation must be one of {CONFIRMATION_POLICIES}")
        # The configuration as given: a sub-agent's is a copy of it.
        self.base_config = config
        self.parent = parent
        self.depth = parent.depth + 1 if parent is not None else 0
        self.agents = agents
        roles = {"main": config.main, "verifier": config.verifier}
        self._skills = resolve_for(config.runtime, roles, config.embodiment).enabled
        # Working state belongs to this task; sharing requires an explicit argument.
        self.working_memory = memory if memory is not None else WorkingMemory()
        self._active_library = {}
        self._library_prompt = ""
        self._captured_library = None
        self._activation_queue = {}
        self._activation_interrupt = 0
        self._fixture_attempts = set()
        self._fixture_status = "unchecked"
        self._fixture_descriptions = []
        self._fixture_feedback = {}
        self._reflected_cells = 0
        self._recall_library = []
        self._recall_since = None
        self._admissions = parent._admissions if parent is not None else {}
        self._admission_lock = parent._admission_lock if parent is not None else threading.Lock()
        table = config.runtime.get("library") or {}
        config = copy(config)
        if table and table.get("learn") == "on":
            config.system_prompt = config.base_prompt
        self.ahead = str(config.runtime.get("think_while_acting") or "on")
        if self.ahead not in decisions.THINK_WHILE_ACTING:
            raise ValueError(f"runtime.think_while_acting must be one of {decisions.THINK_WHILE_ACTING}, got {self.ahead!r}")
        thinking = self.thinking_level = str(config.runtime.get("thinking") or "model")
        if thinking not in decisions.THINKING:
            raise ValueError(f"runtime.thinking must be one of {tuple(decisions.THINKING)}, got {thinking!r}")
        if thinking != "model":
            config = copy(config)
            config.main = decisions._thinking(config.main, thinking)
            if thinking in ("none", "low"):
                config.system_prompt += decisions.THINK_BRIEFLY
                config.base_prompt += decisions.THINK_BRIEFLY
        if interactive:
            config = copy(config)
            message_prompt = decisions.MESSAGE_PROMPT
            if parent is None:
                role_prompt = decisions.INTERACTIVE_PROMPT + message_prompt
            else:
                deepest = agents is None or self.depth >= agents.max_depth
                role_prompt = SUB_AGENT_PROMPT + message_prompt + (
                    NO_DEEPER if deepest and "agents" in (config.runtime.get("skills") or []) else "")
            config.system_prompt += role_prompt
            config.base_prompt += role_prompt
        self.config = config
        self.seed = seed
        self.directory = directory
        self.program_directory: Path | None = None
        self.interactive = interactive
        self.confirmation = confirmation
        self.instruction = instruction
        self.chat, self.verifier, self.env = chat, verifier, environment
        self.trace = Trace(directory, EVENTS)
        self.status = IDLE
        self.messages = []
        self.kernel = None
        self.episode = None
        self.summary = None
        self._condition = threading.Condition()
        self._inbox = []
        self._pause = False
        self._closing = False
        self._decision = None
        self._waited = 0.0
        self._cell_running = False
        self._program_span = None
        # Thinking while acting: what the next user message starts with (a used reply's program
        # result), the messages logged and replaced, the calls set aside before they were back.
        self._carry = []
        # What a call made for a message while a program runs needs (_think_on_message).
        self._kinds, self._turns = KINDS, None
        # Programs run beside the running one, by id (_run_beside).
        self._sides = {}
        self._request = None
        self._revision = self._ahead_generation = 0
        self._pending_events = {}
        self._seen_events = set()
        self._reported_events = set()
        self._ahead_due = None
        self._program_completing = False
        self._interruptions = 0
        self._thoughts = ThoughtQueue(self._condition, advance=self._decision_tick,
                                      on_exit=self._came_back, trace=self.trace)
        self._cancelled_origins = set()
        # Set when the episode deadline expires while a program runs.
        self._wall_up = False
        self._logged = 0
        self._replaces = 0
        # What the user said, in order: the instruction, then every message.
        self._said = []
        # The physical-input request waiting for the user's answer.
        self._physical = None
        self._program_approval_id = None
        self._host_tool = None
        self._worker_approvals = {}
        self._worker_slot = threading.BoundedSemaphore(1)
        self.mcp_prepare = None
        self._mcp_slot = threading.BoundedSemaphore(1)
        self._managed_workspace = self._managed_dispatcher = None
        # {session, agent} in a sessions registry (host/sessions.py).
        self.identity = None
        # Sub-agents: their models, this agent's workspace kind, what its sub-agents spent and
        # it charged its parent, and its result and question for its parent.
        self.agent_chat, self.agent_verifier = chat, verifier
        self.workspace_kind = None
        place = EMBODIMENT_KINDS[config.embodiment].place if config.embodiment in EMBODIMENT_KINDS else ""
        if self.agents is None and parent is None and place and "agents" in (config.runtime.get("skills") or []):
            # Its kind gives the sub-agents a place (a game has one body: its sub-agents
            # only look, at a view of this episode, and never act).
            import importlib

            from harness.runtime.task.delegation import Agents

            module, _, name = place.partition(":")
            self.agents = Agents(place=getattr(importlib.import_module(module), name)())
            self.workspace_kind = self.agents.place.kinds[0] if self.agents.place.kinds else None
        self.agents_usage = {"started": 0, "model_calls": 0, "cost_usd": 0.0}
        self._charged = (0, 0.0)
        self._iterations = 0
        self.result = None
        self.question = None
        self.waiting_since = None
        self.trace.context = self._who

    def _who(self) -> dict:
        """What every record of the trace says of whose it is, once it is in a session."""
        identity = self.identity
        if not identity:
            return {}
        parent = (self.parent.identity or {}).get("agent") if self.parent is not None else None
        return {"who": {"session": identity.get("session"), "agent": identity.get("agent"),
                        "parent": identity.get("parent") or parent}}

    # What others call, from any thread.

    def send_message(self, text: str, sender: str = "user", files=()) -> None:
        """A message from the user (or, `sender` "parent", from the agent that started this
        one): recorded now, sent with the model's next call. `files`: paths the user attached
        (read now: messages.attachment_parts)."""
        text, files = str(text).strip(), [str(path) for path in files or ()]
        if not text and not files:
            return
        parts = attachment_parts(files)
        with self._condition:
            if self.status in (FINISHED, ERROR):
                raise RuntimeError("The episode has ended")
            self._inbox.append((sender, text, parts))
            said = " ".join([text] + [f"@{path}" for path in files]).strip()
            self._said.append(said if sender == "user" else f"(from the agent that started you) {said}")
            self.question = None
            self.trace.emit("user_message", text=text, **({"files": files} if files else {}),
                            **({"sender": sender} if sender != "user" else {}))
            self._revision += 1
            if self._managed_dispatcher is not None:
                self._managed_dispatcher.stop()
                self._cancel_managed_worker_approvals("a new user message arrived")
            if self._physical is not None and self._physical["id"] in self._worker_approvals:
                request = self._physical
                self._worker_approvals.pop(request["id"])
                self._physical = None
                self._answer_physical(request, False, "once", "superseded by a user message")
            self._preempt("user message")
            self._condition.notify_all()

    def pause(self) -> None:
        """Pause: a running program stops at its next execution step; the model is not
        called again until resume() or a message."""
        with self._condition:
            if self.status in (FINISHED, ERROR):
                return
            self._pause = True
            self._activation_interrupt += 1
            self._thoughts.cancel_where(lambda item: item.role == "reflection", "paused")
            if self._managed_dispatcher is not None:
                self._managed_dispatcher.stop()
            self._cancel_managed_worker_approvals("paused")
            kernel = self.kernel if self._cell_running else None
            self.invalidate_lookahead()
            self._condition.notify_all()
        if self.agents is not None:
            self.agents.wake()
        self._drop_physical("paused")
        if kernel is not None:
            kernel.pause()

    def resume(self) -> None:
        """Go on after a pause."""
        with self._condition:
            self._pause = False
            self._condition.notify_all()

    def set_model(self, model: str | None = None, reasoning_effort: str | None = None) -> dict:
        """Change the main model (another id of its provider) or its reasoning effort (EFFORTS,
        "" for the provider's default; runtime.thinking still bounds it) from its next call on:
        a model_changed record. Returns the model and effort now."""
        from harness.runtime.decision.model import ChatModel

        main = dict(self.config.main)
        if model:
            main["model"] = str(model).strip()
        if reasoning_effort is not None:
            from harness.runtime.decision.model import valid_effort

            if not valid_effort(reasoning_effort):
                raise ValueError("invalid reasoning effort ID")
            main.pop("reasoning_effort", None)
            if reasoning_effort:
                main["reasoning_effort"] = reasoning_effort
        if self.thinking_level != "model":
            main = decisions._thinking(main, self.thinking_level)
        with self._condition:
            if self.status in (FINISHED, ERROR):
                raise RuntimeError("The episode has ended")
            chat = self.chat
            if chat is not None:
                if not isinstance(chat, ChatModel):
                    raise ValueError("this conversation's model is not one a model id names")
                # Its connection as it is (a provider's transport), with the new role.
                chat = ChatModel(main, transport=chat.transport)
            self.config.main = main
            if chat is not None:
                self.chat = chat
        changed = {"model": main["model"], "reasoning_effort": main.get("reasoning_effort")}
        self.trace.emit("model_changed", **changed)
        return changed

    @property
    def waiting_for(self) -> str | None:
        """What the conversation waits for the user to approve, when it is physical input."""
        request = self._physical
        if request is None:
            return None
        where = request.get("app") or request.get("window") or "a window"
        return f"approval: physical input in {where} ({'/'.join(request.get('actions') or [])})"

    @property
    def approval_id(self):
        with self._condition:
            return self._physical.get("id") if self._physical is not None else self._program_approval_id

    def confirm(self, accept: bool, reason: str = "", remember: str | None = None, *, request_id=None) -> None:
        """Answer a pending approval. A sensitive step requires its exact request ID."""
        from harness.runtime.safety.input import REMEMBER

        with self._condition:
            request = self._physical
            if request_id is not None and request_id != self.approval_id:
                raise RuntimeError("The approval request is no longer pending")
            if request is None:
                if self.status != WAITING_FOR_CONFIRMATION or self._program_approval_id is None or self._decision is not None:
                    raise RuntimeError("No program is waiting for confirmation")
                self._decision = (bool(accept), str(reason or ""))
                self._condition.notify_all()
                return
            if request.get("sensitive") and request_id != request["id"]:
                raise RuntimeError("The sensitive approval requires its exact request id")
            if (remember or "once") not in REMEMBER:
                raise ValueError(f"remember is one of {', '.join(REMEMBER)}")
            host_tool = self._host_tool is not None and request is self._host_tool["request"]
            if host_tool and time.monotonic() >= self._host_tool["deadline"]:
                raise RuntimeError("The approval request expired")
            pending = self._worker_approvals.get(request["id"])
            if pending is not None:
                if not self._worker_approval_current(pending):
                    raise RuntimeError("The worker approval is no longer pending")
                pending["answer"] = (bool(accept), "once" if request.get("sensitive") else remember or "once")
            self._physical = None
            if host_tool:
                self._host_tool["decision"] = bool(accept)
                self._answer_physical(request, accept, "once", reason, host_only=True)
                self._condition.notify_all()
                return
            if pending is not None and pending["workspace"] is not None:
                self._answer_physical(request, accept, "once", reason, host_only=True)
                if not accept:
                    self.cancel_worker_approval(pending, reason=reason or "the approval was refused")
                return
        self._answer_physical(request, accept, remember or "once", reason)

    def close(self) -> None:
        """End the episode: at once while it waits, else at the next step boundary."""
        with self._condition:
            self._closing = True
            if self._request is not None:
                self._preempt("conversation closed")
            if self._managed_dispatcher is not None:
                self._managed_dispatcher.stop()
            self._cancel_managed_worker_approvals("closed")
            kernel = self.kernel if self._cell_running else None
            self._condition.notify_all()
        if self.agents is not None:
            self.agents.wake()
        self._drop_physical("closed")
        if kernel is not None:
            kernel.pause()

    # Physical input the policy asks the user for (runtime/safety/input.py).

    def _register_worker_approval(self, request, tick, *, workspace=None):
        """Record a refusal from a host-authenticated worker call under the condition."""
        from harness.runtime.safety.approval import WORKER_APPROVAL_SECONDS

        now = time.monotonic()
        self._worker_approvals = {key: row for key, row in self._worker_approvals.items()
                                  if row["deadline"] > now and row["revision"] == self._revision}
        pending = {"request": request, "tick": tick, "workspace": workspace, "revision": self._revision,
                   "answer": None, "deadline": now + WORKER_APPROVAL_SECONDS}
        self._worker_approvals[request["id"]] = pending
        return pending

    def _worker_approval_current(self, pending):
        return (self._worker_approvals.get(pending["request"]["id"]) is pending
                and pending["revision"] == self._revision and time.monotonic() < pending["deadline"])

    def _claim_worker_retry(self, pending, action_id, step):
        """Consume consent once and recover the original tick payload under the condition."""
        if not (self._worker_approval_current(pending) and pending["answer"] and pending["answer"][0]
                and pending["request"].get("retry") == "host_tick" and action_id == pending["tick"]["action_id"]):
            return None
        identifier = pending["request"]["id"]
        del self._worker_approvals[identifier]
        return {**pending["tick"], "step": step, "request_id": identifier}

    def offer_managed_worker_approval(self, workspace, reply, tick):
        """Publish the private worker's attributed refusal through the normal host prompt."""
        from harness.runtime.safety.approval import SENSITIVE

        request = reply.get("approval")
        if (reply["executed"] or not isinstance(request, dict) or request.get("retry") != "host_tick"
                or request.get("sensitive") not in SENSITIVE or not isinstance(request.get("id"), str)
                or not request["id"] or not isinstance(request.get("target"), str)
                or not isinstance(request.get("actions"), list)
                or any(request.get(key) != tick[key] for key in ("episode_id", "execution_id", "action_id", "step"))
                or reply["state"]["step"] != tick["step"]):
            return None
        with self._condition:
            if (not self.interactive or self._managed_workspace is not workspace
                    or tick["episode_id"] != self.episode or self._closing or self._pause
                    or self.status != RUNNING or self._physical is not None or self._host_tool is not None
                    or self._managed_dispatcher.stopped()):
                return None
            pending = self._register_worker_approval(request, tick, workspace=workspace)
            self._physical_request(request)
            return pending

    def worker_approval_ready(self, pending):
        with self._condition:
            return not self._worker_approval_current(pending) or pending["answer"] is not None

    def claim_managed_worker_retry(self, pending, episode_id, step):
        with self._condition:
            if (self._managed_workspace is pending["workspace"] and not self._closing and not self._pause
                    and self.status not in (FINISHED, ERROR) and episode_id == self.episode == pending["tick"]["episode_id"]
                    and not self._managed_dispatcher.stopped()):
                if arguments := self._claim_worker_retry(pending, pending["tick"]["action_id"], step):
                    return arguments
            self.cancel_worker_approval(pending, reason="the approval expired or the action was interrupted")

    def _cancel_managed_worker_approvals(self, reason):
        for pending in tuple(self._worker_approvals.values()):
            if pending["workspace"] is not None:
                self.cancel_worker_approval(pending, reason=reason)

    def cancel_worker_approval(self, pending, *, reason):
        with self._condition:
            request = pending["request"]
            if self._worker_approvals.get(request["id"]) is not pending:
                return
            del self._worker_approvals[request["id"]]
            if self._physical is request:
                self._drop_physical(reason)
            threading.Thread(target=pending["workspace"].cancel_approval,
                             args=(request["id"], pending["tick"]), daemon=True).start()

    def _physical_request(self, request: dict) -> None:
        """A running program waits for the user's answer to a physical-input request: in
        an interactive conversation the user is asked; nobody is in an evaluation."""
        if not isinstance(request.get("id"), str):
            return
        with self._condition:
            managed = bool(getattr(self.env, "approval_key", None))
            pending = None
            if managed or request.get("retry") in ("tick", "host_tick"):
                pending = self._worker_approvals.get(request["id"])
                if (pending is None or not self._worker_approval_current(pending) or pending["answer"] is not None
                        or self._pause or self._closing):
                    self._answer_physical(request, False, "once", "worker approval requires a trusted due receipt",
                                          update_status=False)
                    return
                offered = pending["request"]
                request = ({**offered, "scope": request["scope"], "why": str(request.get("why", ""))[:500]}
                           if request.get("scope") and not offered.get("sensitive") else offered)
            detail = ({"action_step": pending["tick"]["step"]}
                      if pending is not None and pending["workspace"] is not None else {})
            self.trace.emit("physical_request", **request, **detail)
            if not self.interactive:
                self._worker_approvals.pop(request["id"], None)
                self._answer_physical(request, False, "once", "nobody is there to ask in this run")
                return
            if self._physical is not None or self._host_tool is not None:
                self._answer_physical(request, False, "once", "another approval is pending", update_status=False)
                return
            self._physical = request
            self._set_status(WAITING_FOR_CONFIRMATION, reason="physical", request=request)

    def _answer_physical(self, request: dict, accept: bool, remember: str, reason: str = "",
                         *, update_status=True, host_only=False) -> None:
        if request.get("sensitive"):
            remember = "once"
        self.trace.emit("physical_answer", id=request.get("id"), accepted=bool(accept), remember=remember,
                        reason=str(reason or ""))
        if self.kernel is not None and not host_only:
            self.kernel.answer(request.get("id"), {"accept": bool(accept), "remember": remember,
                                                   "reason": str(reason or ""), "physical": True})
        with self._condition:
            waiting = update_status and self.status == WAITING_FOR_CONFIRMATION and self._decision is None
        if waiting and self.status not in (FINISHED, ERROR):
            self._set_status(RUNNING)

    def _drop_physical(self, why: str) -> None:
        """Pausing or closing answers no physical-input request: the program stops waiting."""
        with self._condition:
            request, self._physical = self._physical, None
            if self._pause or self._closing:
                self._worker_approvals.clear()
        if request is not None:
            self.trace.emit("physical_answer", id=request.get("id"), accepted=False, remember="once", reason=why)
            if self.status == WAITING_FOR_CONFIRMATION:
                self._set_status(RUNNING)

    def start(self) -> threading.Thread:
        """Run the episode on a thread of its own and return the thread."""
        self._set_status(RUNNING)
        thread = threading.Thread(target=self.run, name=f"conversation-{self.directory.name}", daemon=True)
        thread.start()
        return thread

    # The episode.

    @contextmanager
    def _span(self, lane: str, name: str, **detail):
        """Record the code inside as a span of the timeline (core/spans.py); yields a
        dict whose items go into its end record."""
        identifier = uuid.uuid4().hex[:12]
        self.trace.emit("span_start", id=identifier, lane=lane, name=name, parent=None, **detail)
        if lane == "program":
            self._program_span = identifier
        end = {}
        try:
            yield end
        except BaseException as error:
            end.setdefault("error", f"{type(error).__name__}: {error}"[:300])
            raise
        finally:
            if lane == "program":
                self._program_span = None
            self.trace.emit("span_end", id=identifier, **end)

    def _steps_shown(self) -> bool:
        """Whether the model is told the step count and what is left of the step budget: not
        when the worker keeps them to itself (profile steps_shown false: a practice segment,
        whose time limit the model must not play against)."""
        return (getattr(self, "profile", None) or {}).get("steps_shown", True) is not False

    def _kernel_span(self, record: dict) -> None:
        """A span from the kernel (a skill's execution, a service call), under the
        program that runs."""
        record = dict(record)
        kind = record.pop("op")
        if kind == "worker_request":
            self._queue_host_request(record, worker=True)
            return
        if kind == "side_result":
            self._side_ended(record)
            return
        if kind == "note":
            note = record.pop("kind", None)
            if note == "physical_request" and isinstance(record.get("request"), dict):
                self._physical_request(record["request"])
            elif note == "physical_cancel":
                with self._condition:
                    self._worker_approvals.pop(record.get("id"), None)
                    if self._physical is not None and self._physical["id"] == record.get("id"):
                        self._drop_physical(str(record.get("reason") or "execution ended"))
            elif note == "agents":
                self._agents_request(record)
            elif note == "mcp_request":
                self._queue_host_request(record)
            elif note == "thought_cancel":
                with self._condition:
                    self._cancelled_origins.add(record["id"])
                    self._thoughts.cancel_where(lambda thought: thought.origin == record["id"], "caller stopped")
            elif note in ("library", "thought") and record.get("action") != "test":
                if note == "thought":
                    with self._condition:
                        record["revision"] = self._revision
                handle = self._library_request if note == "library" else self._thought_request
                threading.Thread(target=handle, args=(record,), name=note, daemon=True).start()
            elif note == "library_use":
                record.pop("time", None)
                self.trace.emit("library_use", **record)
            elif note == "cell_finishing":
                with self._condition:
                    if self._cell_running:
                        self._program_completing = True
                        self._condition.notify_all()
            elif note == "escalation":
                self._escalation(record)
            elif note == "memory":
                self._memory_request(record)
            elif note in EVENTS:
                record.pop("time", None)
                self.trace.emit(note, **record)
                if note == "guard" and self.summary is not None:
                    self.summary["guard_triggers"] += 1
                if note == "memory":
                    self.invalidate_lookahead()
            return
        if kind == "span_start" and record.get("parent") is None:
            record["parent"] = self._program_span
        self.trace.emit(kind, **record)

    def _queue_host_request(self, request, *, worker=False):
        identifier = request.get("id")
        if not isinstance(identifier, str) or len(identifier) != 32:
            return
        with self._condition:
            kernel = self.kernel
            if kernel is None or (not worker and not self._cell_running) or self._closing or self._pause:
                if worker and kernel is not None:
                    kernel.answer(identifier, {"worker": True, "error": "The calling program has stopped"})
                return
            slot = self._worker_slot if worker else self._mcp_slot
            if not slot.acquire(blocking=False):
                kernel.answer(identifier, {"worker": worker, "error": "Another request is still running"})
                return
            revision, cell = self._revision, self.summary["cells"]

        def still_current():
            return (self.kernel is kernel and (worker or self._cell_running and self.summary["cells"] == cell)
                    and self._revision == revision and not self._pause and not self._closing)

        threading.Thread(target=self._host_request, args=(kernel, request, still_current, slot),
                         kwargs={"worker": worker}, name="host-request", daemon=True).start()

    def _host_request(self, kernel, request, still_current, slot, *, worker=False):
        """Make a host-owned worker or MCP call without blocking the kernel reader."""
        from harness.services.mcp import ToolAccess

        action = None
        try:
            with self._condition:
                if not still_current():
                    raise PermissionError("The calling program has stopped")
                if not worker and not hasattr(self, "_mcp_access"):
                    self._mcp_access = ToolAccess(self.config.runtime.get("mcp") or {}, prepare=self.mcp_prepare)
                if worker:
                    name, args = request.get("name"), dict(request.get("arguments") or {})
                    env = self.env
                    if not getattr(env, "approval_key", None) or name not in env.host_controls:
                        raise PermissionError("The host does not own this worker control")
                    if args.setdefault("episode_id", self.episode) != self.episode:
                        raise PermissionError("The control belongs to another episode")
                    op = args.get("op")
                    if name == "tick":
                        action = args.get("action_id")
                        args.pop("execution_id", None)
                        if isinstance(action, str) and 0 < len(action) <= 128:
                            args["execution_id"] = action
                    elif name == "sensitive_approval" or (name == "physical" and op == "answer"):
                        identifier = args.get("id")
                        pending = self._worker_approvals.get(identifier)
                        if (pending is None or not self._worker_approval_current(pending) or pending["answer"] is None
                                or pending["workspace"] is not None):
                            raise PermissionError("No current user approval for this worker request")
                        accept, remember = pending["answer"]
                        sensitive = pending["request"].get("retry") == "host_tick"
                        if name == "sensitive_approval":
                            if op != "retry" or not (retry := self._claim_worker_retry(
                                    pending, args.get("action_id"), args["step"])):
                                raise PermissionError("Approval does not match the refused action")
                            args, action = retry, retry["action_id"]
                        elif sensitive:
                            raise PermissionError("A sensitive action requires the original worker retry")
                        else:
                            args = {"op": "answer", "episode_id": self.episode, "id": identifier,
                                    "accept": accept, "remember": remember}
                            del self._worker_approvals[identifier]
                    elif (name not in getattr(env, "program_controls", ()) and name != "use_screen"
                          and not (name == "physical" and op in ("check", "status"))):
                        raise PermissionError("This worker control is reserved to the host")
            if worker:
                if name == "sensitive_approval":
                    value = env.sensitive_approval("retry", approval_key=env.approval_key, **args)
                else:
                    value = env.managed_call(name, approval_key=env.approval_key, **args)
                reply = {"value": value}
                offered = (value.get("approval") if name == "tick" else
                           value.get("request") if name == "physical" and op == "check" else None)
                if isinstance(offered, dict) and (offered.get("retry") != "host_tick" or
                        name == "tick" and "execution_id" in args and
                        (offered.get("episode_id"), offered.get("execution_id"), offered.get("action_id")) ==
                        (self.episode, args["execution_id"], action)):
                    with self._condition:
                        if still_current():
                            self._register_worker_approval(offered, args)
            elif request.get("method") == "list":
                reply = {"value": self._mcp_access.tools()}
            elif request.get("method") == "call":
                reply = {"value": self._mcp_access.call(request.get("tool"), request.get("arguments"),
                             approve=lambda tool, target: self._approve_host_tool(tool, target, still_current))}
            else:
                raise ValueError("Unknown MCP operation")
        except Exception as error:
            reply = {"error": f"{type(error).__name__}: {error}"}
        finally:
            slot.release()
        with self._condition:
            if worker and action and self.kernel is not kernel:
                result = reply.get("value") or {}
                self.trace.emit("late_receipt", action_id=action, executed=result.get("executed"),
                                step=(result.get("state") or {}).get("step"), error=reply.get("error"))
            if still_current() or worker and self.kernel is kernel:
                kernel.answer(request["id"], {"worker": True, **reply} if worker else reply)

    def _approve_host_tool(self, tool, target, still_current):
        """Await and claim a decision for one operation already bound by the host."""
        from harness.runtime.safety import approval

        request = approval.request("irreversible", target, [tool])
        with self._condition:
            if (not self.interactive or not still_current() or self._physical is not None
                    or self._host_tool is not None):
                return False
            deadline = time.monotonic() + approval.WORKER_APPROVAL_SECONDS
            pending = self._host_tool = {"request": request, "decision": None, "deadline": deadline}
            self._physical = request
            self.trace.emit("physical_request", **request)
            self._set_status(WAITING_FOR_CONFIRMATION, reason="physical", request=request)

            ready = self._condition.wait_for(lambda: pending["decision"] is not None or not still_current(),
                                             timeout=approval.WORKER_APPROVAL_SECONDS)
            self._host_tool = None
            if self._physical is request:
                self._drop_physical("the tool approval expired or was interrupted")
            return ready and still_current() and time.monotonic() < deadline and pending["decision"] is True

    def _escalation(self, record):
        with self._condition:
            identifier = record["id"]
            if identifier in self._seen_events:
                return
            self._seen_events.add(identifier)
            self._pending_events[identifier] = record
            self.trace.emit("escalation", **{key: value for key, value in record.items() if key != "event"},
                            reported=record["event"])
            self._revision += 1
            self._preempt("unhandled escalation")
            self._condition.notify_all()

    def heard(self, text: str, *, escalation=False, agent_report=False) -> None:
        """Child reports are execution results; only explicit escalation asks the model."""
        if escalation:
            self._escalation({"id": uuid.uuid4().hex, "event": {"kind": "ESCALATION", "detail": str(text)}})

    def _preempt(self, reason):
        self._ahead_due = None
        thought = self._request
        if thought is not None and thought.outcome is None:
            self._settle(thought, "discarded", reason)
        if reason == "user message":
            self._thoughts.cancel_where(lambda item: item.role in ("verifier", "observer", "vlm", "pointer", "reflection"),
                                        reason)
        elif reason == "unhandled escalation":
            self._thoughts.cancel_where(lambda item: item.role == "observer", reason)

    def invalidate_lookahead(self) -> None:
        with self._condition:
            self._ahead_due = None
            self._ahead_generation += 1
            if self._request is not None and self._request.trigger == "ahead":
                self._settle(self._request, "discarded", "inputs changed")
            self._condition.notify_all()

    def _learner(self):
        """The run's library ([runtime.library]) and what its settings allow, opened once per
        conversation (runtime/learning/learner.py)."""
        if self.__dict__.get("_opened") is None:
            from harness.runtime.learning.learner import Learner

            runtime = self.base_config.runtime
            self._opened = Learner(library_for(runtime, Path("/")).directory, runtime["library"])
        return self._opened

    def _learning(self) -> dict | None:
        """The run's learning settings (runtime/learning/learner.py) when its library learns, else None."""
        table = self.config.runtime.get("library") or {}
        if not table:
            return None
        from harness.runtime.learning.learner import settings

        chosen = settings(table)
        return chosen if chosen["learn"] == "on" else None

    def _learning_rows(self, snapshot=None):
        rows = self._learner().entries(snapshot=snapshot)
        with self._condition:
            active = self._active_library.copy()
        shown = set()
        for row in rows:
            item = active.get(row["file"])
            if executable(row["file"]):
                row["loaded"] = bool(item and not row["waiting"] and item[0].revision == row["revision"])
                if row["loaded"]:
                    shown.add(row["file"])
        for key, (item, row) in active.items():
            if key in shown:
                continue
            info = self._active_row(item, row)
            rows.append({**info, "section": key.split("/", 1)[0], "file": key, "loaded": True,
                         "verified": bool(row.get("proof")), "uses": info["seen"], "success_rate": info["rate"]})
        return rows

    def _learning_progress(self):
        from harness.runtime.learning.active import progress

        return {**progress(self._learning_rows(), self.seconds_left(), self.config.max_wall_seconds or 0.0,
                           self._situations()), "fixture_status": self._fixture_status,
                "fixture_feedback": dict(self._fixture_feedback)}

    def _learning_report(self) -> str:
        from harness.runtime.learning import active

        if not active.is_active(self.config.runtime):
            return ""
        report = active.report(self._learning_rows(), self.seconds_left(), self._situations())
        if self._fixture_descriptions:
            report += "\n" + "\n".join(self._fixture_descriptions)
        elif self._fixture_status == "unavailable":
            report += "\nNo trusted fixture is configured here. Keep observations and leave executable proposals pending."
        if self._fixture_feedback:
            report += "\n" + "\n".join(f"{key}: {why}" for key, why in self._fixture_feedback.items())
        return "\n" + report

    def _trial_at_boundary(self, *, replay=False):
        """Run at most one trial between programs, or recheck pinned entries at startup."""
        from harness.runtime.learning import fixtures
        from harness.runtime.learning.learner import CANDIDATES

        learning = self._learning()
        if not learning or self.parent is not None or (replay and not learning["replay"]):
            return
        with self._condition:
            if self._closing or self._pause or self._cell_running or self._sides or (self._inbox and not replay):
                return
            generation = self._activation_interrupt, self._revision

        def cancelled():
            with self._condition:
                return (self._closing or self._pause or self._cell_running or bool(self._sides)
                        or generation != (self._activation_interrupt, self._revision))

        try:
            inventory = fixtures.configured(self.profile)
        except (OSError, TypeError, ValueError) as error:
            self._fixture_status = "unavailable"
            self.trace.emit("library", action="fixture_unavailable", reason=str(error))
            return
        self._fixture_descriptions = fixtures.describe(inventory)
        self._fixture_status = "configured" if self._fixture_descriptions else "unavailable"
        if not self._fixture_descriptions:
            return
        learner = self._learner()
        trials = {fixture.get("skill"): fixture for fixture in inventory}
        for index_key, row in learner.index().items():
            pending = index_key.startswith(f"{CANDIDATES}/")
            if pending and (replay or row.get("evidence") != "proposed"):
                continue
            if not pending and (not replay or row.get("evidence") != "provisional" or not row.get("proof")):
                continue
            key = index_key.removeprefix(f"{CANDIDATES}/")
            if not executable(key):
                continue
            fixture = trials.get(Path(key).stem)
            expected = row.get("revision")
            if (not fixture or not expected or expected in self._fixture_attempts or cancelled()
                    or self.seconds_left() <= 0):
                continue
            self._fixture_attempts.add(expected)
            budget = fixtures.Budget(self.seconds_left(), cancelled)
            try:
                entry = learner.candidate_from(key, pending=pending)
                if entry is None or pending and entry.revision().revision != expected:
                    continue
                self.trace.emit("library", action="trial_started", key=key, revision=expected)
                began = time.monotonic()
                item, receipt = fixtures.verify(entry, fixture, budget, str(self.directory))
                receipt["seconds"] = round(time.monotonic() - began, 3)
                self.trace.emit("library", action="trial_observed", key=key, **receipt)
                if not pending:
                    proof = row["proof"]
                    if (item.revision != expected or proof["conditions"].get("fixture_sha256") != receipt["fixture_sha256"]
                            or proof["conditions"].get("profile_sha256") != sha256(self.profile)
                            or proof.get("receipt", {}).get("run") == receipt["run"]
                            or proof.get("receipt", {}).get("episode_id") == receipt["episode_id"]):
                        raise ValueError("the replay conditions differ from the verified revision")
                if not receipt["ok"] or not pending:
                    with self._admission_lock, self._condition:
                        budget.remaining()
                        learner.record_trial(key, expected, item, pending=pending,
                                             evidence="replayed" if receipt["ok"] else "failed",
                                             receipt=receipt, check=budget.remaining)
                    if not receipt["ok"]:
                        self._fixture_feedback[key] = "Trusted verification failed: the expected input effect was absent."
                else:
                    proof = {"revision": item.revision, "conditions": {"method": "fixture",
                             "fixture_sha256": receipt["fixture_sha256"], "profile_sha256": sha256(self.profile)},
                             "receipt": receipt}
                    admitted = {**row, "revision": item.revision, "proof": proof, "evidence": "provisional"}

                    def publish():
                        budget.remaining()
                        value = learner.admit(entry, "provisional", proof=proof, test_run=receipt,
                                              bindings=item.bindings, expected=expected, check=budget.remaining)
                        self._library_admitted(learner, value, entry.text, entry.kind, entry.source, entry.origin)
                        self._fixture_feedback.pop(key, None)
                        return value["row"]

                    if learner.wanted(entry, "provisional") and self._library_eligible(
                            item, admitted, learner.layers, learner.settings["load"]):
                        self._activate_library([(item, admitted)], publish=publish, budget=budget)
                    else:
                        with self._admission_lock, self._condition:
                            publish()
            except (OSError, ValueError, RuntimeError, ImportError, SyntaxError, TypeError, KeyError, StopIteration) as error:
                if isinstance(error, KernelDied):
                    raise
                if isinstance(error, (ValueError, SyntaxError)):
                    self._fixture_feedback[key] = f"Still pending: {str(error)[:300]}."
                self.trace.emit("library", action="trial_pending", key=key, revision=expected, reason=str(error))
            if not replay:
                return

    def _startup_library(self, learning):
        library = self._learner().library
        with self._admission_lock:
            if learning:
                self._learner().migrate_experience()
            captured = library.capture()
            if not learning:
                expected = self.config.runtime["library"].get("manifest", {}).get("version")
                if expected and captured.version != expected:
                    raise RuntimeError(f"Library {library.directory} changed after the configuration was loaded "
                                       f"(expected version {expected[:12]}). Evaluation needs a frozen library.")
            if learning and "notes" in library.layers:
                self._recall_since = len(self._admissions.get(library.directory, ()))
        self._captured_library = captured
        self._recall_library = library_view.library_entries(captured)
        return captured

    def queue_library_revision(self, item, proof):
        """A trusted host verifier has admitted this exact revision."""
        if not executable(item.key) or proof.get("revision") != item.revision or not proof.get("conditions"):
            raise ValueError("activation requires proof for the exact executable revision")
        learner = self._learner()
        row = learner.index().get(item.key) or {}
        if row.get("revision") != item.revision or row.get("proof") != proof:
            raise ValueError("the revision and proof must be published together")
        if self._library_eligible(item, row, learner.layers, learner.settings["load"]):
            with self._condition:
                self._activation_queue[item.key] = (item, row)

    def _library_eligible(self, item, row, layers, load):
        conditions = (row.get("proof") or {}).get("conditions") or {}
        if isinstance(conditions, dict) and conditions.get("profile_sha256") not in (None, sha256(self.profile)):
            return False
        return eligible(item, row, layers, load)

    def _activate_library(self, selected, *, startup=False, publish=None, budget=None):
        if not selected:
            return
        def can_switch():
            return startup or (not (self._sides or self._cell_running or self._inbox)
                               and (publish is not None or all(
                                   self._activation_queue.get(item.key, (None,))[0] == item for item, _ in selected)))

        with self._condition:
            if self._pause or self._closing or not can_switch():
                return
            kernel = self.kernel
            interrupt = self._activation_interrupt
        for item, _ in selected:
            item.save(self.directory)
        entries = [(item, startup and row.get("origin", "hand") == "hand") for item, row in selected]
        with self._span("program", "library"):
            prepared = kernel.load_library("prepare", entries, **({"timeout": budget.remaining()} if budget else {}))
        rejected = None
        with self._admission_lock, self._condition:
            cancelled = (self._closing or self._pause or self.kernel is not kernel
                         or self._activation_interrupt != interrupt or not can_switch())
            if not cancelled and prepared["status"] == "ok" and publish is not None:
                try:
                    selected = [(selected[0][0], publish())]
                except (OSError, ValueError, RuntimeError) as error:
                    rejected = str(error)
        if prepared["status"] != "ok" or cancelled or rejected:
            if prepared["status"] == "ok" and self.kernel is kernel:
                kernel.load_library("discard")
            self.trace.emit("library", action="load_failed", status="cancelled" if cancelled else "error",
                            error=rejected or prepared.get("error"), revisions={item.key: item.revision for item, _ in selected})
            if cancelled or rejected:
                return
            if startup and any(not hand for _, hand in entries):
                self._activate_library([(item, row) for item, row in selected
                                        if row.get("origin", "hand") == "hand"], startup=True)
            elif startup:
                raise RuntimeError(f"Library code failed in the kernel: {prepared.get('error')}")
            else:
                with self._condition:
                    for item, _ in selected:
                        if self._activation_queue.get(item.key, (None,))[0] == item:
                            del self._activation_queue[item.key]
            return
        # The boundary check reserved the switch. The kernel reader can drain notes while
        # the commit is acknowledged and the decision loop still owns program scheduling.
        result = kernel.load_library("commit")
        if result["status"] != "ok":
            raise KernelDied(f"Library commit failed: {result.get('error')}")
        with self._condition:
            for item, row in selected:
                self._active_library[item.key] = (item, row)
                queued = self._activation_queue.get(item.key)
                if queued and queued[0].revision == item.revision:
                    del self._activation_queue[item.key]
            self._library_version = sha256(result["active"])
            self.trace.emit("library", action="activated", version=self._library_version,
                            revisions=result["active"],
                            entries=[self._active_row(item, row) for item, row in self._active_library.values()])
            if not startup:
                from copy import copy
                from harness.runtime.learning.library import active_summary

                self.config = copy(self.config)
                prior = self._library_prompt
                updated = active_summary(item for item, _ in self._active_library.values())
                self.config.system_prompt = (self.config.system_prompt.replace(prior, updated, 1)
                                             if prior else self.config.system_prompt + updated)
                self._library_prompt = updated
            self.invalidate_lookahead()

    @staticmethod
    def _active_row(item, row):
        uses = (row.get("uses_by_revision") or {}).get(item.revision) or {}
        row_data = memory_view.entry({"id": item.key, "kind": item.key.split("/", 1)[0],
                                      "name": Path(item.key).stem, "evidence": row.get("evidence", "validated"),
                                      "seen": uses.get("ok", 0) + uses.get("failed", 0), "rate": uses.get("rate")},
                                     "library")
        return {**row_data, "key": item.key, "revision": item.revision, "sha256": item.source_sha256,
                "source": row.get("origin", "hand"), "summary": row.get("summary", ""),
                "text": item.source.decode("utf-8")[:400], "active": True,
                **({"verification": row["proof"]} if row.get("proof") else {})}

    def _startup_holdings(self):
        from harness.runtime.learning import active

        situations = self._situations()
        rows = [{"section": item.key.split("/", 1)[0], "name": Path(item.key).stem,
                 "summary": row.get("summary"), "passed": bool(row.get("proof"))}
                for item, row in self._active_library.values()]
        holdings = active.holdings(rows, situations)
        return f"\n{holdings}\n" if holdings else ""

    def _visible_memory(self):
        if self._recall_since is None:
            return self._recall_library
        reader = self._learner().library
        admitted = self._admissions.get(reader.directory, ())[self._recall_since:]
        return library_view.overlay(self._recall_library, admitted, reader.layers, reader.load)

    def _situations(self):
        with self._admission_lock:
            return next((item["text"] for item in reversed(self._visible_memory())
                         if item["name"] == "situations" and item["where"] is None), None)

    def _library_request(self, request: dict) -> None:
        """Handle program proposals and reads. Only the host can verify or admit code."""
        with self._admission_lock:
            answer = self._handle_library_request(request)
        if request.get("wait", True) and self.kernel is not None:
            self.kernel.answer(request.get("id"), answer)

    def _handle_library_request(self, request: dict) -> dict:
        try:
            learning = self._learning()
            if request.get("action") == "entries":
                return {"value": self._learning_rows(self._captured_library if learning is None else None)}
            if request.get("action") == "attachment":
                pinned = [item for item, _ in self._active_library.values()]
                if self._captured_library is not None:
                    pinned.extend(item for item in self._captured_library.entries if not executable(item.key))
                for item in pinned:
                    for _, data in item.attachments:
                        if hashlib.sha256(data).hexdigest() == request["sha256"]:
                            return {"value": base64.b64encode(data).decode("ascii")}
                raise KeyError("no attachment with that digest in the active snapshot")
            if request.get("action") == "record":
                # Old learned programs may still call this. The traced result is the only tally.
                return {"value": None}
            if learning is None and request.get("action") in ("admit", "grade"):
                raise ValueError("learning is off in this run: the library is frozen")
            learner = self._learner()
            value = learner.handle(request, source=learner.settings["trigger"],
                                   run=str(self.directory) if getattr(self, "directory", None) else None)
            answer = {"value": value}
        except Exception as error:
            answer, value = {"error": f"{type(error).__name__}: {error}"}, None
        action = request.get("action")
        if action == "admit":
            if value is not None:
                self._library_admitted(learner, value, request.get("text", ""), request.get("entry"),
                                       learner.settings["trigger"], "model")
                if value["admitted"] and request.get("entry") == "note":
                    from copy import copy

                    with self._condition:
                        self.config = copy(self.config)
                        self.config.system_prompt += f"\nLearned in this run: {str(request.get('text', '')).strip()}\n"
                        self.invalidate_lookahead()
            else:
                self.trace.emit("library", action="rejected", kind=request.get("entry"), name=request.get("name"),
                                reason=answer["error"])
        elif action == "grade":
            revision = {"sha256": request["sha256"]} if request.get("sha256") else {}
            if value is not None:
                self.trace.emit("library", action="promoted", key=request.get("key"), evidence=value["evidence"],
                                why=request.get("why"), history=value.get("history"), **revision)
            else:
                self.trace.emit("library", action="rejected", key=request.get("key"), reason=answer["error"], **revision)
        return answer

    def _library_admitted(self, learner, value, text, kind, source, origin) -> None:
        holding = library_view.admitted_entry(value, text)
        self.trace.emit("library", action="admitted", **learner.record_of(value), kind=kind,
                        learned=source, origin=origin, holding=holding)
        if value["admitted"] and holding["kind"] == "memory":
            # Keep revisions in order so readers with different floors can keep the last one they selected.
            self._admissions[learner.directory] = (*self._admissions.get(learner.directory, ()), holding)

    def _memory_request(self, request: dict) -> None:
        """A program's request to the run's working memory (skills/memory), answered at once;
        one nobody waits for that fails is a `world` record (refused) with why. A sub-agent in
        a world of its own (not a view of its parent's, not on its worker) keeps its places in
        a space of its own."""
        agent = (getattr(self, "identity", None) or {}).get("agent") or "main"
        try:
            if request.get("action") == "observe":
                request = {**request, "stream": self.episode}
            with self._admission_lock:
                library = self._visible_memory()
                if request.get("kind") == "skill_use":
                    library = library_view.use_entries(self._active_library)

                def persist(item, *, forgotten=False):
                    learner = self._learner()
                    changed = learner.store_memory(item, forgotten=forgotten)
                    self._admissions[learner.directory] = (*self._admissions.get(learner.directory, ()), changed)
                    self.trace.emit("library", action="memory", holding=changed)
                    return changed

                persist_memory = persist if self._recall_since is not None else None
                answer = {"value": self.working_memory.handle(request, record=self._memory_record, source=agent,
                                                              space=self._memory_space(), library=library,
                                                              persist=persist_memory)}
        except Exception as error:
            answer = {"error": f"{type(error).__name__}: {error}"}
            if not request.get("wait", True):
                self.trace.emit("world", action="refused", request=request.get("action"), reason=answer["error"][:300])
        if request.get("wait", True) and self.kernel is not None:
            self.kernel.answer(request.get("id"), answer)

    def _memory_space(self):
        parent = self.parent
        if parent is not None and (self.workspace_kind == "view" or
                                   self.config.environment.get("endpoint") == parent.config.environment.get("endpoint")):
            return parent._memory_space()
        return (self.identity or {}).get("agent") or "main"

    def _memory_record(self, **change) -> None:
        """A change of the working memory, or what a recall found: a `world` record of this
        agent's trace."""
        self.trace.emit("world", **change)

    def _agents_request(self, request: dict) -> None:
        """A program asks for sub-agents (skills/agents): done on a thread of its own (a wait
        takes long; the kernel's notes must go on), answered through the kernel."""

        if request.get("action") == "wait" and request.get("own", True):
            with self._condition:
                request["interrupt_at"] = self._interruptions
                self.invalidate_lookahead()

        def answer():
            if self.agents is None:
                value = {"error": "this conversation cannot start sub-agents"}
            else:
                value = self.agents.handle(self, request)
            if self.kernel is not None:
                self.kernel.answer(request.get("id"), value)

        threading.Thread(target=answer, name=f"agents-{request.get('action')}", daemon=True).start()

    def charge_up(self) -> None:
        """Charge what this sub-agent spent since the last time to its parent (and up)."""
        if self.parent is None or self.summary is None:
            return
        calls, cost = self.summary["model_calls"], self.summary["cost_usd"]
        with self._condition:
            before, self._charged = self._charged, (calls, cost)
        self.parent._charge(calls - before[0], cost - before[1])

    def _charge(self, calls: int, cost: float) -> None:
        """What a sub-agent (of any depth below) spent: counted against this agent's budget,
        its calls as this turn's."""
        if not calls and not cost:
            return
        with self._condition:
            self.agents_usage["model_calls"] += calls
            self.agents_usage["cost_usd"] += cost
            self._iterations += calls
            self._condition.notify_all()
        if self.parent is not None:
            self.parent._charge(calls, cost)

    def _set_status(self, status: str, **detail) -> None:
        if status not in STATUSES:
            raise ValueError(f"unknown conversation status {status!r}")
        with self._condition:
            if status == self.status and not detail:
                return
            self.status = status
            self._condition.notify_all()
        self.trace.emit("state", status=status, **detail)

    def _wait(self, status: str, ready, **detail):
        """Wait in `status` until `ready()` holds (under the lock); Closed when the user
        closes the conversation meanwhile."""
        self._set_status(status, **detail)
        began = time.perf_counter()
        with self._condition:
            while not self._closing and not ready():
                self._condition.wait()
            closing = self._closing
        self._waited += time.perf_counter() - began
        if closing:
            raise Closed()
        self._set_status(RUNNING)

    def _take_inbox(self) -> list[str]:
        with self._condition:
            pending, self._inbox = self._inbox, []
        return pending

    def _checkpoint(self) -> None:
        """Between steps: stop when closing, wait while paused."""
        with self._condition:
            closing, paused = self._closing, self._pause
        if closing:
            raise Closed()
        if paused:
            self._wait(PAUSED, lambda: not self._pause or bool(self._inbox))
            with self._condition:
                self._pause = False
            self._handed_back()

    def _handed_back(self) -> None:
        """After a pause the computer is the agent's again as it is now: what the user did
        meanwhile is not their using it under the agent's hand (the worker's hand_back,
        where its profile says it has one)."""
        episode, profile = getattr(self, "episode", None), getattr(self, "profile", None) or {}
        if self.env is None or episode is None or not profile.get("hand_back"):
            return
        try:
            self.env.call("hand_back", episode_id=episode)
        except (ValueError, RuntimeError, OSError):
            pass

    def _await_input(self) -> None:
        """Wait for missing task input, without starting a new turn or renewing its budget."""
        self.waiting_since = time.time()
        try:
            self._wait(IDLE, lambda: bool(self._inbox) or bool(self._pending_events), reason="message")
        finally:
            self.waiting_since = None
        self.reason = "user"

    def _add_user_messages(self) -> None:
        """Put the user's messages into the next request: into the user message that
        ends the history, or as a new one after a reply."""
        pending = self._take_inbox()
        if not pending:
            return
        parts = _inbox_parts(pending)
        if self.messages[-1]["role"] == "user":
            self._extend_request(parts)
        else:
            self._tell(parts)

    def _tell(self, content) -> None:
        """Add a user message to the history: what the program of the last used reply
        to a call made while it ran reported (self._carry) first, then `content`."""
        carry, self._carry = self._carry, []
        if carry:
            content = carry + ([{"type": "input_text", "text": content}] if isinstance(content, str) else list(content))
        self.messages.append({"role": "user", "content": content})

    def _with_what_was_said(self, request, messages):
        """Interactive: when the window leaves earlier turns out, the first message of the
        request still lists everything the user said (they hold the task)."""
        if not self.interactive or len(request) >= len(messages) or len(self._said) < 2:
            return request
        text = "The user's messages so far, oldest first:\n" + "\n".join(
            f"{number}. {said}" for number, said in enumerate(self._said, 1))
        first = dict(request[0])
        first["content"] = (list(first["content"]) + [{"type": "input_text", "text": text}]
                            if isinstance(first["content"], list) else f"{first['content']}\n{text}")
        return [first] + request[1:]

    def seconds_left(self) -> float:
        """What the episode has left of its wall time (max_wall_seconds): the time it ran,
        less the time it waited for the user, counts; the whole budget before it starts."""
        started = getattr(self, "started", None)
        ran = time.perf_counter() - started - self._waited if started is not None else 0.0
        return float(self.config.max_wall_seconds) - ran

    def _cell_timeout(self, *, policy=False) -> float:
        """The program's declared deadline, bounded by the episode."""
        seconds = self.seconds_left()
        configured = self.config.runtime.get("cell_timeout_seconds")
        if configured is not None and not policy:
            seconds = min(seconds, float(configured))
        return max(0.01, seconds)

    def _program_deadline(self, number, episode_deadline):
        with self._condition:
            if self._cell_running and not self._program_completing and self.summary["cells"] == number:
                if episode_deadline:
                    self._wall_up = True
                    self.kernel.pause()
                else:
                    self._program_timed_out = True
                    self._stop_program_for_decision()

    def _stuck(self, program: str, result: dict) -> None:
        """Interactive: note the same program, or the same unhandled event, three times
        in a row (after OpenHands' stuck detector). Only noted; nothing changes."""
        escalation = result.get("escalation") or {}
        key = (program.strip(), None) if not escalation else (None, (escalation.get("skill"),
                                                                     escalation.get("event", {}).get("kind")))
        self._recent = (getattr(self, "_recent", []) + [key])[-3:]
        if len(self._recent) == 3 and len(set(self._recent)) == 1:
            self.trace.emit("stuck", repeated="program" if key[0] else "event",
                            what=key[0][:200] if key[0] else list(key[1]))
            self._recent = []

    def run(self) -> dict:
        """Run the episode to its end and return its summary (status, evaluator outcome,
        model calls, tokens, cost, times), also written with the trace and manifest under
        the directory. An error ends the episode with status "error" instead of raising."""
        from harness.runtime.decision.model import USAGE, ChatModel
        from harness.config.agent import image_roles, model_services

        config, seed, directory, trace = self.config, self.seed, self.directory, self.trace
        snapshot = config.snapshot()
        extra = ({"interactive": {"confirmation": self.confirmation, "instruction": self.instruction}}
                 if self.interactive else {})
        if self.parent is not None:
            extra["agent"] = {**(self.identity or {}), "depth": self.depth, "workspace": self.workspace_kind,
                              "budget": {"calls": config.max_model_calls, "cost": config.max_cost_usd,
                                         "seconds": config.max_wall_seconds}}
        write_json(directory / "manifest.json", {
            "schema_version": 1, "kind": "program", "config": snapshot,
            "config_sha256": sha256(snapshot), "seed": seed, "provenance": provenance(), **extra,
        })
        runtime = config.runtime
        embodiment = config.embodiment
        told = EMBODIMENT_TEXT[embodiment]
        roles = {"main": config.main, "verifier": config.verifier}
        skills = self._skills
        summary = self.summary = {
            "run": str(directory), "task": config.task, "seed": seed, "status": "error",
            "success": False, "reward": None, "process_score": None, "steps": 0,
            "model_calls": 0, "verifier_calls": 0, "cells": 0, **USAGE, "agent_seconds": 0.0,
            "kernel_seconds": 0.0,
            # Why the high level was called (Sec. 3.2: at the start and when an event
            # reaches it), and what the lower layers resolved without it.
            "decisions": {}, "events_handled": 0, "events_escalated": 0,
            "vision_calls": 0, "vision_cost_usd": 0.0, "guard_triggers": 0}
        self.started = time.perf_counter()
        self._set_status(RUNNING)
        token = None
        try:
            self.chat = self.chat or ChatModel(config.main)
            if runtime.get("verifier", True):
                self.verifier = self.verifier or ChatModel({**config.main, **config.verifier})
            env = self.env = self.env or RemoteEnvironment(
                config.environment["endpoint"], timeout=float(config.environment.get("timeout_seconds", 600)))
            env.tools()
            with self._span("env", "reset", task=config.task, seed=seed):
                observation = env.reset(config.task, seed)
            self.episode = observation.episode_id
            token = env.call("claim_outcome", episode_id=self.episode)["token"]
            # The embodiment profile is part of the frozen configuration (App. A).
            self.profile = {key: value for key, value in env.call("profile").items()
                            if key not in ("task", "step_limit", "fk_check_error_m")}
            # The skills, prompt and session were chosen for one embodiment kind; the worker
            # says which it drives.
            if embodiment_kind(self.profile) != embodiment:
                raise RuntimeError(f"The worker drives a {embodiment_kind(self.profile)} embodiment; this "
                                   f"configuration was resolved for a {embodiment} one")
            if (expected := runtime.get("knowledge")) is not None:
                benchmark = self.profile.get("benchmark")
                # A bench that exposes this worker setting requires it in the profile,
                # including when an older external worker omits it.
                reports_knowledge = ("knowledge" in self.profile or
                                     (benchmark in bench_names() and "knowledge" in bench_spec(benchmark).worker))
                if reports_knowledge and self.profile.get("knowledge") != expected:
                    raise RuntimeError(f"The worker must report knowledge={expected!r}; got "
                                       f"{self.profile.get('knowledge')!r}. Start a matching worker.")
            if self.parent is None:
                self.working_memory.declare(self.profile.get("world"), self._memory_record)
            frame = observation.state.get("memory_frame")
            if frame is not None:
                self._memory_request({"action": "observe", "wait": False, **frame})
            library = self._learner().library if runtime.get("library") else None
            learning = self._learning()
            self._trial_at_boundary(replay=True)
            self._checkpoint()
            startup = self._startup_library(learning) if library is not None else None
            if startup is not None:
                for item in startup.entries:
                    item.save(directory)
                manifest = startup.manifest()
                manifest["revisions"] = {item.key: item.revision for item in startup.entries}
                config.runtime = runtime = {**runtime, "library": {**runtime["library"],
                    "manifest": {**manifest, **({"learns": True} if learning else {})}}}
                trace.emit("library", action="opened", version=startup.version, revision_schema=1, revisions=manifest["revisions"],
                           entries=[item for item in library_view.library_entries(startup, sections=SECTIONS)
                                    if not executable(item["id"])])
            run_manifest = {"schema_version": 1, "kind": "program", "config": snapshot,
                            "config_sha256": sha256(snapshot), "embodiment_profile": self.profile,
                            "embodiment_sha256": sha256(self.profile), "seed": seed,
                            "provenance": provenance(), **extra}
            write_json(directory / "manifest.json", run_manifest)
            # The instruction it was given in place of the task's, for the frontends to show.
            trace.emit("reset", observation=observation.to_dict(),
                       **({"instruction": self.instruction} if self.instruction else {}))
            if self.profile.get("physical"):
                # Whose steps these are, and the run's physical-input policy, for the worker.
                identity, policy = self.identity or {}, dict(runtime.get("physical") or {})
                seen = dict(runtime.get("privacy") or {})
                env.call("physical", op="identify", episode_id=self.episode, session=identity.get("session"),
                         agent=identity.get("agent"), level=policy.get("level"), rules=policy.get("rules") or [],
                         interactive=self.interactive,
                         **({"privacy": {key: seen[key] for key in ("level", "rules") if seen.get(key)}}
                            if seen else {}))
            if self._managed_workspace is not None:
                self._managed_dispatcher = self._managed_workspace.dispatcher(self, self.workspace_kind)
                operations = ", ".join(self._managed_dispatcher.options()["operations"])
                scope = f"\nThis isolated workspace exposes only these synchronous operations: {operations}.\n"
                config.system_prompt += scope
                config.base_prompt += scope
                self.kernel = Kernel(DEFAULT_BOOTSTRAP, {}, managed=self._managed_dispatcher,
                                     managed_launcher=self._managed_workspace.program_command,
                                     log_path=directory / "kernel.log", start_timeout=30)
            else:
                # (The verifier is asked through the conversation, a thought: control.think.)
                services = model_services(runtime, roles)
                image_clients = {role: {key: value for key, value in client.items() if key in ("class", "point_format")}
                                 if client else None for role, client in image_roles(services).items()}
                kernel_services = {key: value for key, value in services.items()
                                   if key not in ("vlm", "pointer", "verifier", "mcp")}
                self.kernel = Kernel(runtime.get("bootstrap", DEFAULT_BOOTSTRAP), {
                    "endpoint": config.environment["endpoint"], "episode_id": self.episode, "embodiment": embodiment,
                    "reactive_budget_ms": runtime.get("reactive_budget_ms", 5.0),
                    "reaction_delay_ms": float(runtime.get("reaction_delay_ms") or 0.0),
                    "observer": dict(runtime.get("observer") or {}),
                    "default_max_seconds": runtime.get("default_max_seconds", 30.0),
                    "host_thoughts": True,
                    **({"host_controls": sorted(env.host_controls), "timeout_seconds": env.timeout}
                       if getattr(env, "approval_key", None) and env.host_controls else {}),
                    "skills": skills,
                    **kernel_services, **image_clients,
                    "memory": self._recall_library,
                    # App. A: programs see only the Python installation and the harness source,
                    # and reach only the services named here (runtime/safety/isolation.py).
                    "isolation": runtime.get("isolation", True),
                    "strategy_first": bool(runtime.get("strategy_first", False)),
                    "policy_progress_seconds": float(runtime.get("policy_progress_seconds") or 0.0),
                    # Skills the user installed in the app, for read_skill (skills/instructions).
                    **({"agent_skills": runtime["agent_skills"]} if runtime.get("agent_skills") else {}),
                    # A game the agent learns itself: none of its handwritten skills is loaded.
                    **({"knowledge": runtime["knowledge"]} if runtime.get("knowledge") else {}),
                    # The library and whether this run learns (skills/learning, runtime/learning/learner.py).
                    **({"library": {"directory": str(library.directory), "settings": learning or {"learn": "off"}}}
                       if library is not None else {}),
                    # The practice sandbox: an active run's only (runtime/learning/active.py, the bench's [sandbox]).
                    **({"sandbox": sandbox_of(runtime)} if sandbox_of(runtime) else {}),
                    # The worker's private files (a game's instance): never a program's.
                    **({"private_paths": self.profile["private_paths"]} if self.profile.get("private_paths") else {}),
                }, python=kernel_python(runtime), cwd=str(self.program_directory) if self.program_directory else None,
                    log_path=directory / "kernel.log",
                    on_span=self._kernel_span)
            if self.profile.get("private_paths"):
                trace.emit("private_paths", paths=list(self.profile["private_paths"]), guarded=self.kernel.private)
            holdings = ""
            if startup is not None:
                self._library_version = startup.version
                index = startup.index
                selected = [(item, index.get(item.key) or {}) for item in startup.entries
                            if executable(item.key) and self._library_eligible(
                                item, index.get(item.key) or {}, startup.layers, startup.load)]
                self._activate_library(selected, startup=True)
                self._library_prompt = startup.api_summary(self._active_library)
                config.system_prompt = config.base_prompt + self._library_prompt + startup.notes()
                holdings = self._startup_holdings()
                snapshot = config.snapshot()
                snapshot["startup_holdings"] = holdings
                snapshot["active_library"] = {key: item.revision for key, (item, _) in self._active_library.items()}
                write_json(directory / "manifest.json", {**run_manifest, "config": snapshot,
                                                         "config_sha256": sha256(snapshot)})
            self.cameras = runtime.get("cameras", list(told["cameras"]))
            instruction = self.instruction or observation.instruction
            from harness.runtime.learning import active

            if active.is_active(runtime):
                # The active trigger: this run learns the environment for the task (runtime/learning/active.py).
                instruction = active.goal(instruction, active.schedule(runtime.get("library"))["minutes"],
                                          runtime.get("skills") or (), sandbox_of(runtime),
                                          legacy_memory="legacy_memory" in EMBODIMENT_KINDS[embodiment].prompt_features)
            self._said.insert(0, instruction)
            opening = f"Instruction: {instruction}\n"
            if config.task_description:
                opening += f"\nTask description:\n{config.task_description}\n\n"
            # What the library holds, from the first call on.
            opening += holdings
            self.messages = [{"role": "user", "content": [
                {"type": "input_text",
                 "text": opening + f"{told['state_label']}: "
                         f"{state_text(observation.state, embodiment, self._steps_shown())}"},
                *image_parts(observation.images, self.cameras)]}]
            summary["status"] = "budget_exhausted"
            self._loop(skills, told)
        except Closed:
            # Finished, closed by the user, or a sub-agent's budget ran out: the benchmark's
            # convention ends it.
            summary["status"] = "closed"
            if self.kernel is not None:
                _wrap_up(self.kernel, trace)
        except KeyboardInterrupt:
            summary["status"] = "interrupted"
            trace.emit("interrupted")
            raise
        except Exception as error:
            summary["status"] = "error"
            summary["error"] = f"{type(error).__name__}: {error}"
            trace.emit("error", message=summary["error"])
        finally:
            self._close_episode(token)
        return summary

    def _loop(self, skills, told) -> None:
        try:
            self._steps(skills, told)
        finally:
            with self._condition:
                if self._request is not None:
                    self._settle(self._request, "unused", "the episode or the turn ended first")
                self._request = None

    def _steps(self, skills, told) -> None:
        """The loop: a thought on the trigger of what happened last (self.reason), then what
        its reply's output does (OUTPUTS), until an output, a budget or the episode ends it."""
        config, trace, summary, runtime = self.config, self.trace, self.summary, self.config.runtime
        self._logged = 0
        direct = runtime.get("mode", "program") == "direct"
        post_calls = runtime.get("post_policy_calls")
        # What the outputs share in this loop. Direct control: the agent's action vocabulary
        # turns each <action> into a program (runtime.actions, "module:function"). turns: history
        # turns sent to the model, lowered after the model server runs out of memory.
        # malformed_from: the first reply without a valid block since the last valid one (such
        # exchanges leave the history once a valid reply comes). nudged: replies in a row sent
        # back for only announcing an action (ANNOUNCED); empties: empty replies in a row asked
        # again (EMPTY_RETRIES). post_calls: the model's calls after the learned policy's first
        # run are bounded (finishing with its own tools cost half the spend for no score), from
        # post_from on; then the policy runs on.
        loop = SimpleNamespace(skills=skills, told=told, direct=direct, kinds=DIRECT_KINDS if direct else KINDS,
                               actions=_object(runtime["actions"]) if direct else None,
                               turns=runtime.get("max_history_turns"), malformed_from=None, nudged=0, empties=0,
                               post_calls=None if post_calls is None else int(post_calls), post_from=None)
        self.reason = "start"
        # Iterations of the loop in this turn (an interactive episode starts one with every
        # message of the user).
        with self._condition:
            self._iterations = 0
        while True:
            self._checkpoint()
            with self._condition:
                selected = tuple(self._activation_queue.values())
            self._activate_library(selected)
            self._trial_at_boundary()
            self._checkpoint()
            learning_report = self._learning_report()
            with self._condition:
                current = self._request
                if current is not None and current.cancelled:
                    if "deadline" in str(current.error):
                        raise current.error
                    if current.program is not None and self._carry:
                        self._tell([])
                    self._request = current = None
                if current is None:
                    if self._iterations >= config.max_model_calls:
                        break
                    if (loop.post_from is not None and loop.post_calls is not None
                            and summary["model_calls"] - loop.post_from >= loop.post_calls and not self._inbox):
                        break_for_policy = True
                    else:
                        break_for_policy = False
                    if self.seconds_left() <= 0:
                        summary["status"] = "wall_time_exhausted"
                        break
                    if not self._ahead_allowed():
                        summary["status"] = "cost_exhausted"
                        break
                    if not break_for_policy:
                        current = self._think("between", loop.turns, learning_report=learning_report)
                else:
                    break_for_policy = False
                if not break_for_policy:
                    self._condition.wait_for(lambda: current.back(0) or self._closing)
                    if self._closing:
                        raise Closed()
                    if current.cancelled:
                        if isinstance(current.error, ThoughtCancelled) and "deadline" in str(current.error):
                            raise current.error
                        continue
                    self._request = None
                    reply, loop.turns = current.wait(), current.turns
                    if current.program is not None:
                        if self._completed_decision(current, loop.kinds):
                            continue
                        used = {"ahead": "used"} if current.trigger == "ahead" else {}
                    else:
                        used = {}
                    self._settle(current, "used")
                    self._pending_events.clear()
                    loop.revision = current.revision
                    loop.assumption = getattr(current, "assumption", None)
                    loop.ahead_generation = current.ahead_generation if current.trigger == "ahead" else None
                    loop.call, loop.thought = current.call, current.id
            if break_for_policy:
                self._policy_to_end()
                break
            output, parsed = self._output(reply, used, loop)
            if getattr(self, decisions.OUTPUTS["between"][output])(reply, parsed, loop) == "end":
                break

    def _completed_decision(self, thought, kinds):
        """A real request outlives program completion. Replan only if its reply depended on it."""
        if thought.trigger == "ahead":
            return False
        if thought.stopped:
            result = thought.program_result
            event = (result.get("escalation") or {}).get("event", {}).get("kind")
            if result["status"] in ("ok", "finished") or event == "USER_MESSAGE":
                return False
        parsed, prose = decisions._running_reply(thought.reply.text, kinds)
        if prose and thought.trigger == "message":
            return False
        if parsed is not None and parsed.kind != "wait" and not decisions._STOP.search(thought.reply.text):
            if parsed.kind not in ("python", "action") or (parsed.kind == "python" and decisions._beside(parsed.body)):
                return False
        self._settle(thought, "waited", "the decision needs the completed program result")
        self._pending_events.clear()
        if self._carry:
            self._extend_request(self._carry)
            self._carry = []
        return True

    def _output(self, reply, used: dict, loop) -> tuple[str, object]:
        """What a reply between programs does (a key of OUTPUTS) and its parsed block (or the
        error that kept it from parsing); the reply joins the trace and the history."""
        summary, trace, messages = self.summary, self.trace, self.messages
        if (not used and not reply.text.strip() and reply.usage.get("finish_reason") != "length"
                and loop.empties < decisions.EMPTY_RETRIES):
            return "empty", None
        loop.empties = 0
        # An empty reply is a format error after EMPTY_RETRIES, never a message.
        plain = (self.interactive and reply.usage.get("finish_reason") != "length"
                 and bool(reply.text.strip()) and not looks_like_action(reply.text))
        # A plain reply that only announces the next step ("I'll open the page ...") is
        # sent back as a format error.
        announced = plain and loop.nudged < decisions.ANNOUNCED_TIMES and announces(reply.text)
        plain = plain and not announced
        loop.nudged = loop.nudged + 1 if announced else 0
        try:
            if reply.usage.get("finish_reason") == "length":
                raise ProtocolError("The reply was truncated; nothing ran")
            parsed = parse_reply(reply.text, loop.kinds)
            parsed.program = (loop.actions(parsed.body, allow_policy="vla" in loop.skills,
                                           allow_skills=bool(self.config.runtime.get("fixed_skills", False)))
                              if parsed.kind == "action" else parsed.body)
            thought_text = decisions._STOP.sub("", parsed.thought or "")
            assumed = decisions._ASSUME.search(thought_text)
            presentation = {"kind": parsed.kind,
                            "thought": (decisions._ASSUME.sub("", thought_text) if assumed else thought_text).strip(),
                            "body": parsed.body,
                            **({"assume": " ".join(assumed[1].split())} if assumed else {})}
            output = {"python": "program", "action": "program"}.get(parsed.kind, parsed.kind)
        except (ProtocolError, ValueError) as failed:
            parsed, output = failed, "message" if plain else "invalid"
            if announced:
                parsed = ProtocolError("The reply said what it would do, without a block")
            presentation = ({"kind": "message", "body": reply.text.strip(), "announced": True} if announced else
                            {"kind": "message" if plain else "invalid", "body": reply.text.strip() if plain else ""})
        self._record_reply(reply, loop.call + 1, thought=loop.thought, presentation=presentation, **used)
        messages.append({"role": "assistant", "content": reply.text})
        if output == "invalid":
            if loop.malformed_from is None and not used:
                # (A used reply's exchange stays: its message holds its program's result.)
                loop.malformed_from = len(messages) - 1
        elif loop.malformed_from is not None:
            dropped = len(messages) - 1 - loop.malformed_from
            del messages[loop.malformed_from:-1]
            self._logged -= dropped
            trace.emit("malformed_dropped", messages=dropped)
            loop.malformed_from = None
        return output, parsed

    # The outputs of a reply between programs (OUTPUTS): "end" ends the loop.

    def _out_empty(self, reply, parsed, loop):
        """Reasoning only: asked again at once, with no format error to show."""
        loop.empties += 1
        self.summary["empty_replies"] = self.summary.get("empty_replies", 0) + 1
        self.trace.emit("empty_reply", call=self.summary["model_calls"], usage=reply.usage, seconds=reply.seconds,
                        **({"reasoning": reply.reasoning} if reply.reasoning else {}))
        self.reason = "empty"

    def _current_output(self, loop):
        return (not self._inbox and not self._pending_events and loop.revision == self._revision
                and (loop.ahead_generation is None or loop.ahead_generation == self._ahead_generation))

    def _out_message(self, reply, parsed, loop):
        """A plain reply: the model talks to the user (or a sub-agent asks its parent)."""
        with self._condition:
            if not self._current_output(loop):
                return None
            self.question = reply.text.strip()
            self.trace.emit("agent_message", text=reply.text.strip())
        self._await_input()

    def _out_invalid(self, reply, parsed, loop):
        """A reply nothing came of: told why, and asked again."""
        if reply.usage.get("finish_reason") == "length":
            # The reply hit the output limit before its closing tag.
            text = (f"Your reply was cut off after {reply.usage.get('output_tokens')} tokens, before the "
                    f"closing tag, so nothing ran. Write the program again more compactly: short "
                    f"comments, helper functions for repeated steps.")
        elif str(parsed).startswith("The reply said what it would do"):
            who = "the agent that started you" if self.parent is not None else "the user"
            text = decisions.ANNOUNCED.format(block="<action>" if loop.direct else "<python>", who=who)
        else:
            blocks = "<action> or <finish>" if loop.direct else "<python>, <verify>, or <finish>"
            text = (f"Format error: {parsed}. Nothing ran. Reply with the {blocks} block itself, starting with its "
                    "opening tag.")
        self._tell(text)
        self.trace.emit("protocol_error", message=str(parsed), truncated=reply.usage.get("finish_reason") == "length",
                        **({"announced": True} if text.startswith("Nothing ran") else {}))
        self.reason = "format"

    def _out_finish(self, reply, parsed, loop):
        """The task is done: the reply's <finish>, or a program's finish() (source "program")."""
        source = getattr(parsed, "source", None)
        if source is None:
            if loop.assumption is not None and not self._check_assumption(*loop.assumption):
                self._tell("The lookahead condition changed before the finish could be applied.")
                self.reason = "program_end"
                return None
            with self._condition:
                if not self._current_output(loop):
                    return None
        from harness.runtime.learning.active import is_active

        if is_active(self.config.runtime) and self._ahead_allowed():
            before = getattr(self, "_library_version", None)
            self._trial_at_boundary()
            if getattr(self, "_library_version", None) != before:
                self._tell("The host activated your proposal. Use the new revision in a brief practice program, "
                           "check what it does, then finish with the result.")
                self.reason = "program_end"
                return None
        self.result = parsed.body.strip()
        self.trace.emit("finish", text=parsed.body, **({"source": source} if source else {}))
        self.summary["status"] = "finished"
        _wrap_up(self.kernel, self.trace)
        return "end"

    def _out_verify(self, reply, parsed, loop):
        """The verifier's answer on the reply's claim, with the views it judged."""
        with self._condition:
            if not self._current_output(loop):
                return None
        try:
            answer, view = self._verify(parsed.body)
        except ThoughtCancelled:
            with self._condition:
                if self._inbox or self._pending_events or self._closing:
                    return None
            raise
        state = state_text(view["state"], self.config.embodiment, self._steps_shown())
        self._tell([{"type": "input_text", "text": f"Verifier: {answer}\n{loop.told['state_label']}: {state}"},
                    *image_parts(view["images"], self.cameras)])
        self.reason = "verify"

    def _verify(self, claim, cameras=None, request=None):
        cameras = cameras if cameras is not None else self.cameras
        with self._span("env", "observe"):
            view = self.env.call("observe", episode_id=self.episode, cameras=cameras)
        if self.verifier is None:
            answer = "Verifier disabled in this configuration."
        else:
            content = [{"type": "input_text", "text": f"Claim: {claim}"},
                       *image_parts(view["images"], cameras)]
            reply = self._ask_role("verifier", self.verifier,
                                   EMBODIMENT_TEXT[self.config.embodiment]["verifier"],
                                   [{"role": "user", "content": content}], request)
            answer = reply.text.strip()
        self.trace.emit("verify", claim=claim, answer=answer)
        return answer, view

    def _ask_role(self, role, chat, system, messages, request=None):
        request = request or {}
        origin = request.get("id")
        with self._condition:
            if origin in self._cancelled_origins or request.get("revision", self._revision) != self._revision:
                raise ThoughtCancelled("The calling entry stopped")
            if self.config.max_cost_usd is not None and (
                    self.summary["cost_usd"] + self.agents_usage["cost_usd"] >= self.config.max_cost_usd):
                raise RuntimeError("The session model cost budget is exhausted")
            if origin is not None and role != "observer":
                current = self._request
                if current is not None and current.trigger == "ahead":
                    self._settle(current, "discarded", "program requested a model result")
            thought = Thought(role, decisions.TRIGGERS["request"][role], chat, system, messages,
                              timeout=max(0, self.seconds_left()), program=self.summary["cells"] if self._cell_running else None,
                              revision=self._revision, origin=origin,
                              owner={**self._who().get("who", {}), "entry": request.get("entry"),
                                     "frame": request.get("frame")})
            self._thoughts.submit(thought)
        return thought.wait()

    def _thought_request(self, request):
        """Answer the calling entry without holding the kernel reader or worker tick."""
        role = request.get("role")
        try:
            if role == "verifier":
                if self.verifier is None:
                    value = None
                else:
                    text, _ = self._verify(str(request.get("claim") or request.get("text")),
                                           request.get("cameras"), request)
                    value = {"text": text}
            elif role in ("observer", "vlm", "pointer"):
                content = [*({"type": "input_image", "image_url": image, "detail": "auto"}
                             for image in request.get("images") or ()),
                           {"type": "input_text", "text": str(request.get("text") or "")}]
                reply = self._ask_role(role, self._role_chat(role), str(request.get("system") or ""),
                                       [{"role": "user", "content": content}], request)
                value = {"text": reply.text, "usage": reply.usage, "seconds": reply.seconds}
            else:
                raise ValueError(f"Unknown program model role: {role!r}")
            answer = {"value": value}
        except Exception as error:
            answer = {"error": f"{type(error).__name__}: {error}"}
        if self.kernel is not None:
            self.kernel.answer(request["id"], {"thought": True, **answer})

    def _role_chat(self, role):
        from harness.runtime.decision.model import ChatModel

        if role == "verifier":
            return self.verifier
        field = "vlm" if role == "observer" else role
        config = self.config.runtime.get(field)
        if not isinstance(config, dict) or not config.get("model"):
            raise RuntimeError(f"No model is configured for {role}")
        config = {key: value for key, value in config.items() if key not in ("point_format", "class")}
        extra = {"max_image_side": 0} if config.get("backend") == "openai_chat" else {}
        if role == "observer":
            observer = self.config.runtime.get("observer") or {}
            config.update(reasoning_effort=observer.get("reasoning_effort", "none"),
                          max_output_tokens=int(observer.get("max_output_tokens", 1200)))
        return ChatModel({"max_output_tokens": 1024, "temperature": 0.0, "extra_body": extra, **config})

    def _policy_to_end(self) -> None:
        """The model's calls after the learned policy's run are used up: it runs on to the end."""
        trace, summary, kernel = self.trace, self.summary, self.kernel
        with self._span("program", "policy to the end"):
            result = kernel.run("__policy_to_end__()", timeout=self._cell_timeout(policy=True))
        trace.emit("policy_to_end", status=result["status"], error=result.get("error"))
        _cell_usage(summary, result)
        if result.get("strategy"):
            summary["strategy"] = result["strategy"]
        if result["status"] == "episode_ended":
            summary["status"] = "episode_ended"
        else:
            trace.emit("finish", text="the model's calls after the policy's run were used up", source="harness")
            summary["status"] = "finished"
            _wrap_up(kernel, trace)

    def _out_program(self, reply, parsed, loop):
        """Run the reply's program, with the thoughts its triggers start while it runs; then
        what it did is the next thought's news."""
        config, trace, summary, kernel, env = self.config, self.trace, self.summary, self.kernel, self.env
        program, embodiment, cameras = parsed.program, config.embodiment, self.cameras
        if not self._approved(program):
            return None
        if loop.assumption is not None and not self._check_assumption(*loop.assumption):
            self._tell("The lookahead condition changed before the program could start.")
            self.reason = "program_end"
            return None
        with self._condition:
            waiting = self._pause or self._closing
        if waiting:
            # Paused (or closed) while the model was answering: the program waits. It
            # runs after a plain resume; a message from the user replaces it.
            trace.emit("program_held")
            self._checkpoint()
        with self._condition:
            if not self._current_output(loop):
                trace.emit("program_dropped", reason="user_message" if self._inbox else "inputs_changed")
                self._tell("The user paused before this program ran, so nothing ran." if waiting
                           else "A user message came before this program ran, so nothing ran.")
                self.reason = "user"
                return None
            summary["cells"] += 1
            number, policy_ran = summary["cells"], loop.post_from is not None
            self._kinds, self._turns = loop.kinds, loop.turns
            self._request = None
            self._ahead_due = time.monotonic() + decisions.AHEAD_SECONDS if self.ahead != "off" and not policy_ran else None
            self._cell_running = True
            self._budget_stop = self._program_timed_out = False
            self._thoughts.wake()
            if self._pause or self._closing:
                kernel.pause()
        before = time.perf_counter()
        remaining = self._cell_timeout()
        limit = config.runtime.get("cell_timeout_seconds")
        episode_deadline = limit is None or float(limit) >= self.seconds_left()
        deadline = threading.Timer(remaining, self._program_deadline, (number, episode_deadline))
        deadline.daemon = True
        deadline.start()
        try:
            with self._span("program", f"program {number}") as end:
                result = kernel.run(program, timeout=remaining + 60.0)
                end.update(status=result["status"])
        except KernelDied as error:
            summary["kernel_seconds"] += time.perf_counter() - before
            trace.emit("kernel_died", message=str(error))
            if self.seconds_left() > 0:
                raise
            summary["status"] = "wall_time_exhausted"
            return "end"
        finally:
            deadline.cancel()
            with self._condition:
                self._cell_running = False
                self._program_completing = True
                self._ahead_due = None
                ahead = self._request
                if ahead is not None and ahead.trigger == "ahead" and not ahead.exited:
                    self._settle(ahead, "discarded", "program ended before lookahead returned")
                self._condition.notify_all()
        summary["kernel_seconds"] += time.perf_counter() - before
        if self._program_timed_out and result["status"] not in ("episode_ended", "finished"):
            result = {**result, "status": "error", "error": result.get("error") or "Program deadline exceeded"}
        recorded = {k: v for k, v in result.items() if k not in ("attachments", "report")}
        if result.get("report"):
            recorded["report"] = {"text": result["report"].get("text", ""),
                                  "images": sorted(result["report"].get("images") or {})}
        trace.emit("cell", code=program, action=parsed.body if loop.direct else None, result=recorded,
                   attachments=len(result.get("attachments", [])))
        if self.interactive:
            self._stuck(program, result)
        _cell_usage(summary, result)
        self.charge_up()
        if result.get("strategy"):
            summary["strategy"] = result["strategy"]
            if not policy_ran and result["strategy"].get("policy_ran"):
                loop.post_from = summary["model_calls"]
        if result["status"] == "episode_ended":
            summary["status"] = "episode_ended"
            return "end"
        if self._wall_up:
            # (Its USER_PAUSED was the wall time's.)
            self._wall_up = False
            summary["status"] = "wall_time_exhausted"
            return "end"
        finished = False
        with self._condition:
            if result["status"] == "finished":
                self.reason = "program_end"
                if ahead is not None and ahead.trigger == "ahead":
                    self._settle(ahead, "discarded", "the program finished the task")
                    self._request = ahead = None
                if ahead is None and not self._inbox and not self._pending_events:
                    self._program_completing = False
                    finished = True
            else:
                self.reason = {"escalated": "escalation", "error": "error"}.get(result["status"], "program_end")
            taken = _taken_over(result) if self.interactive else None
            calls_left = config.max_model_calls - self._iterations
        if finished:
            return self._out_finish(None, SimpleNamespace(body=str(result.get("finish") or ""),
                                                          source="program"), loop)
        outcome, why = self._program_outcome(ahead, loop.kinds, result, taken)
        note = ("\nThe program ended without calling finish(). If the task is done, finish; otherwise "
                "write a program for the rest of the task." if self.reason == "program_end" and outcome != "used"
                else "")
        if loop.post_from is not None and loop.post_calls:
            calls_left = min(calls_left, loop.post_calls - (summary["model_calls"] - loop.post_from))
            note += ("\nAfter these calls the learned policy runs on by itself to the end of the episode."
                     if calls_left > 0 else "")
        feedback = cell_feedback(result, number, self.profile.get("control_hz"), embodiment, self._steps_shown())
        if ahead is not None and ahead.stopped:
            feedback = f"Program {ahead.program} stopped for your decision.\n" + feedback
        content = [{"type": "input_text", "text": feedback + note
                    + f"\nModel calls left: {calls_left}"}]
        for item in result.get("attachments", [])[:6]:
            content.append({"type": "input_text", "text": f"show(): {item['caption']}"})
            content.append({"type": "input_image", "image_url": item["image_url"], "detail": "auto"})
        if not taken and self.reason in ("error", "escalation") and not self._request:
            self._reflect_learning()
        if taken is not None:
            # The user brought a window of theirs to the front: the computer is theirs
            # until they hand it back, as after Take over.
            trace.emit("user_took_over", window=taken.get("front"))
            self.pause()
            self._checkpoint()
        with self._span("env", "observe"):
            view = env.call("observe", episode_id=self.episode, cameras=cameras)
        # A skill's report (the tracked scene) may outline objects in the same views.
        images = {**view["images"], **((result.get("report") or {}).get("images") or {})}
        content.extend(image_parts(images, cameras))
        with self._condition:
            self._program_completing = False
            if ahead is not None and (ahead.cancelled or ahead.revision != self._revision) and outcome == "used":
                outcome, why = "discarded", "inputs changed before adoption"
            if outcome in ("used", "pending") and not ahead.cancelled:
                self._carry = content
            else:
                if ahead is not None and outcome in ("waited", "discarded"):
                    self._settle(ahead, outcome, why)
                if ahead is not None and ahead.said:
                    self.messages.append({"role": "assistant", "content": ahead.reply.text})
                if ahead is not None and ahead.side is not None:
                    self.messages.append({"role": "assistant", "content": ahead.reply.text})
                    content.insert(0, {"type": "input_text", "text": self._beside_report(ahead)})
                self._request = None
                self._tell(content)
            self._condition.notify_all()
        if view["state"].get("ended"):
            summary["status"] = "episode_ended"
            return "end"
        return None

    def _program_outcome(self, thought, kinds, result, taken):
        if thought is None:
            return None, ""
        if thought.side is not None or thought.said:
            return "beside", ""
        if thought.cancelled or taken is not None:
            return "discarded", "the decision was superseded"
        if thought.trigger != "ahead":
            thought.program_result = result
            return "pending", ""
        if result["status"] != "ok" or not thought.exited or thought.error is not None:
            return "discarded", "lookahead needs a normal completion and a ready reply"
        reply = thought.reply
        if reply is None or reply.usage.get("finish_reason") == "length":
            return "discarded", "lookahead returned no complete reply"
        parsed, _ = decisions._running_reply(reply.text, kinds)
        if parsed is None or parsed.kind == "wait":
            return "waited", "lookahead deferred to the program result"
        condition = decisions._ASSUME.search(reply.text)
        if condition is None or decisions._STOP.search(reply.text):
            return "discarded", "lookahead requires a checkable completion condition"
        thought.assumption = (condition[1].strip(), result)
        if not self._check_assumption(*thought.assumption):
            return "discarded", "lookahead condition was false or could not be checked"
        return "used", ""

    def _check_assumption(self, condition, result):
        """Evaluate a bounded expression over JSON data, never the program namespace."""
        try:
            tree = ast.parse(condition, mode="eval")
            nodes = list(ast.walk(tree))
            if len(nodes) > 64 or not all(isinstance(node, decisions._ASSUME_NODES) for node in nodes):
                return False
            names = {node.id for node in nodes if isinstance(node, ast.Name)}
            if not names <= {"result", "output", "state"} or not names:
                return False
            snapshot = json.loads(json.dumps({key: value for key, value in result.items()
                                              if key not in ("attachments", "report")}))
            state = (self.env.call("state", episode_id=self.episode) if "state" in names else None)
            values = {"result": snapshot, "output": snapshot.get("stdout") or "", "state": state}
            return bool(eval(compile(tree, "<assume>", "eval"), {"__builtins__": {}}, values))
        except Exception:
            return False

    def _think(self, phase, turns, *, learning_report=""):
        """Select a decision from the table and queue its immutable input."""
        triggers = decisions.TRIGGERS[phase]
        now = time.monotonic()
        trigger = next((name for name, check in triggers.items() if check and getattr(self, check)(now)), None)
        running = phase == "running"
        if trigger is None:
            if running:
                return None
            trigger = self.reason
            if trigger not in triggers:
                raise ValueError(f"No model trigger for {trigger!r}")

        number = self.summary["cells"] if running else None
        earlier = self._request
        if running and earlier is not None and (earlier.said or earlier.side is not None):
            self.messages.append({"role": "assistant", "content": earlier.reply.text})
            if earlier.side is not None:
                self._tell(self._beside_report(earlier))
        self._include_escalations()
        self._add_user_messages()
        if running:
            if trigger == "ahead":
                self._ahead_due = None
                text = decisions.AHEAD_RUNNING.format(number=number)
            else:
                text = decisions.LOOK_RUNNING.format(number=number)
                if trigger == "message":
                    text += " You may also answer the user in plain text."
            parts = [{"type": "input_text", "text": text}]
            if self.messages[-1]["role"] == "user":
                self._extend_request(parts)
            else:
                self._tell(parts)

        config, summary, messages = self.config, self.summary, self.messages
        prune_images(messages, int(config.runtime.get("keep_images", 2)))
        request = self._with_what_was_said(window(messages, turns), messages)
        call = summary["model_calls"]
        from copy import deepcopy
        history = deepcopy(messages)
        system = config.system_prompt + learning_report
        thought = Thought("main", trigger, self.chat, system, request,
                          timeout=max(0, self.seconds_left()), program=number, owner=self._who().get("who"),
                          revision=self._revision, call=call, turns=turns,
                          invoke=lambda item: self._complete(item, history))
        thought.ahead_generation = self._ahead_generation
        self.trace.emit("model_request", call=call, thought=thought.id, **decisions._model_of(thought.chat), reason=trigger,
                        program=number, total_messages=len(messages), sent_messages=len(request),
                        new_messages=history[self._logged:], context=context_summary(request, system),
                        library_version=getattr(self, "_library_version", None), revision=thought.revision,
                        events=list(self._pending_events),
                        **({"message": True} if trigger == "message" else {}), **self._replaced())
        self._logged = len(messages)
        summary["model_calls"] += 1
        summary["decisions"][trigger] = summary["decisions"].get(trigger, 0) + 1
        self._iterations += 1
        self._request = thought
        self._thoughts.submit(thought)
        return thought

    def _ahead_allowed(self, reserve=0):
        return (self._iterations + reserve < self.config.max_model_calls
                and (self.config.max_cost_usd is None
                     or self.summary["cost_usd"] + self.agents_usage["cost_usd"] < self.config.max_cost_usd))

    def _extend_request(self, parts):
        last = self.messages[-1]
        content = last["content"]
        if isinstance(content, str):
            content = [{"type": "input_text", "text": content}]
        last["content"] = [*content, *parts]
        if self._logged == len(self.messages):
            self._logged -= 1
            self._replaces = 1

    def _include_escalations(self):
        parts = []
        for identifier, report in self._pending_events.items():
            if identifier not in self._reported_events:
                self._reported_events.add(identifier)
                parts.append({"type": "input_text", "text": f"Unresolved event: {json.dumps(report)}"})
        if parts:
            if self.messages[-1]["role"] == "user":
                self._extend_request(parts)
            else:
                self._tell(parts)

    def _pending_message(self, now):
        return bool(self._inbox)

    def _unresolved(self, now):
        return bool(self._pending_events)

    def _pending_escalation(self, now):
        return bool(self._pending_events) and not self._pending_events.keys() <= self._reported_events

    def _pending_ahead(self, now):
        return (self._ahead_due is not None and self._ahead_due <= now and self._request is None
                and self._ahead_allowed(reserve=1) and not self._thoughts.pending)

    def _decision_tick(self):
        """Coalesce what is visible at this tick before acquiring a transport."""
        if not self._cell_running or self._program_completing or self._closing or self._pause:
            return None
        if not self._ahead_allowed():
            if self._inbox and not self._budget_stop:
                self._budget_stop = True
                self._stop_program_for_decision()
            return None
        if self._thoughts.active is not None:
            return None
        now = time.monotonic()
        if self._think("running", self._turns) is not None:
            return None
        if self._ahead_due is not None and self._ahead_due > now:
            return self._ahead_due
        return None

    def _came_back(self, thought):
        from harness.runtime.decision.model import add_usage

        summary = self.summary
        key = decisions.OUTPUTS["request"].get(thought.role)
        if key is not None:
            summary[key] = summary.get(key, 0) + 1
        summary["agent_seconds"] += thought.seconds
        if thought.reply is not None:
            usage = thought.reply.usage
            add_usage(summary, usage)
            if key == "vision_calls":
                summary["vision_cost_usd"] += float(usage.get("cost_usd") or 0.0)
        self.charge_up()
        if key is not None:
            return
        if thought.outcome is not None:
            self._record_settlement(thought)
        elif (self._cell_running and not self._program_completing and self._request is thought
              and thought.revision == self._revision
              and not self._inbox and not self._pause):
            self._dispatch_running_reply(thought)

    def _dispatch_running_reply(self, thought):
        if thought.cancelled or thought.trigger == "ahead" or thought.reply is None:
            return
        text = thought.reply.text
        if thought.reply.usage.get("finish_reason") == "length":
            return
        parsed, prose = decisions._running_reply(text, self._kinds)
        kind = getattr(parsed, "kind", None)
        stop = bool(decisions._STOP.search(text))
        if prose and thought.trigger == "message":
            output = "message"
        elif kind == "python" and not stop and self.confirmation != "always" and decisions._beside(parsed.body):
            output = "parallel"
        elif kind not in (None, "wait") and (stop or thought.trigger == "message"):
            output = "replace"
        else:
            output = "wait"
        handler = decisions.OUTPUTS["running"][output]
        if handler is not None:
            if output == "parallel":
                self._run_beside(thought, parsed.body)
            else:
                getattr(self, handler)(thought)

    def _interrupt(self, thought: Thought) -> None:
        """Stop the running program at its next step for `thought`'s reply, which runs next
        (the loop uses it when the program ends on the stop); a failed thought made for a
        message stops it too: the model reads the message once it has."""
        if thought.trigger == "escalation":
            found = decisions._STOP.search(thought.reply.text)
            why = " ".join(found.group(1).split()) if found else ""
            why = f"a look: {why}"[:300] if why else "a look"
        else:
            why = "the call failed" if thought.error is not None else "the reply to a message"
        with self._condition:
            if self.kernel is None or not self._cell_running or self._request is not thought:
                return
            thought.stopped = thought.error is None
            self.trace.emit("program_stopped", program=thought.program, call=thought.call + 1, why=why)
            self._stop_program_for_decision()

    def _stop_program_for_decision(self):
        self._interruptions += 1
        if self.agents is not None:
            self.agents.wake()
        self.kernel.message()

    def _say_beside(self, thought: Thought) -> bool:
        """A reply in prose to a message that came while a program runs: it reaches the user
        at once (an agent_message), the program going on, and joins the history when the
        program ends; False when the program has ended."""
        with self._condition:
            if not (self._cell_running and self._request is thought):
                return False
            thought.said = True
            self._settle(thought, "said", "told the user while the program ran")
            self._pending_events.clear()
            self.question = thought.reply.text.strip()
            self.trace.emit("agent_message", text=self.question, program=thought.program)
        return True

    def _beside_report(self, ahead: Thought) -> str:
        """What a block run beside the program did, for the model."""
        side = ahead.side["result"] or {"status": "still running"}
        return (f"The program you ran beside program {ahead.program}: {side.get('status')}"
                + (f"\n{side['error']}" if side.get("error") else "")
                + (f"\nEvent: {side['escalation']['event']['kind']}" if side.get("escalation") else ""))

    def _run_beside(self, ahead: Thought, program: str) -> bool:
        """Start a block that can run beside the program."""
        identifier = uuid.uuid4().hex[:12]
        with self._condition:
            kernel = self.kernel if self._cell_running and self._request is ahead else None
            if kernel is None or not kernel.side(program, identifier):
                return False
            ahead.side = {"id": identifier, "code": program, "result": None}
            self._sides[identifier] = ahead
            self.trace.emit("side_program", id=identifier, program=ahead.program, call=ahead.call + 1,
                            code=program)
            self._settle(ahead, "beside", "ran beside the program")
            self._pending_events.clear()
        return True

    def _side_ended(self, record: dict) -> None:
        """How a program run beside the running one ended (the kernel's side_result)."""
        with self._condition:
            ahead = self._sides.pop(record.get("id"), None)
        result = {key: record.get(key) for key in ("status", "error", "escalation") if record.get(key) is not None}
        self.trace.emit("side_program_end", id=record.get("id"), **result)
        if ahead is not None:
            ahead.side["result"] = result
            if result.get("status") in ("error", "escalated"):
                self._escalation({"id": record["id"], "entry": record["id"], "event": result})

    def _replaced(self) -> dict:
        """What the next request record says of the history messages it replaces."""
        replaces, self._replaces = self._replaces, 0
        return {"replaces": replaces} if replaces else {}

    def _settle(self, thought, outcome, why=""):
        if thought.outcome is not None:
            return
        thought.outcome = outcome, why
        if outcome in ("discarded", "unused"):
            if thought.exited:
                thought.cancel(why)
                self.trace.emit("thought_cancelled", thought=thought.id, role=thought.role,
                                trigger=thought.trigger, reason=why)
            else:
                self._thoughts.cancel_where(lambda item: item is thought, why)
        if thought.exited:
            self._record_settlement(thought)

    def _record_settlement(self, thought):
        outcome, why = thought.outcome
        summary, reply = self.summary, thought.reply
        if thought.program is not None:
            outcomes = summary.setdefault("ahead_outcomes", {})
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            self.trace.emit("ahead", thought=thought.id, call=thought.call + 1, program=thought.program,
                            trigger=thought.trigger, outcome=outcome, why=why,
                            seconds=round(thought.seconds, 3), cancelled=thought.cancelled)
        if thought.program is None and outcome != "used":
            self.trace.emit("model_preempted", thought=thought.id, call=thought.call + 1, reason=why,
                            back=reply is not None, **({"text": reply.text, "usage": reply.usage} if reply else {}))
        elif reply is not None and outcome != "used":
            self._record_reply(reply, thought.call + 1, thought=thought.id, ahead=outcome)

    def _record_reply(self, reply, call, **detail):
        self.trace.emit("model_reply", call=call, text=reply.text, usage=reply.usage, response_id=reply.response_id,
                        seconds=reply.seconds, **detail, **({"reasoning": reply.reasoning} if reply.reasoning else {}))

    def _complete(self, thought, history):
        """The main transport, including bounded context shortening within one Thought."""
        from harness.runtime.decision.model import ChatModel

        request, chat, turns = thought.messages, thought.chat, thought.turns
        options = {"on_text": self._streamed(thought.call + 1, stop=lambda: thought.cancelled)} if getattr(
            chat, "streams_text", False) else {}
        if isinstance(chat, ChatModel):
            options["cancellation"] = thought.cancellation
        attempt = 0
        name = decisions._model_of(chat).get("model") or str(self.config.main.get("model", "model"))
        with self._span("model", name, call=thought.call + 1,
                        thought=thought.id, role="main", reason=thought.trigger, program=thought.program) as end:
            while True:
                thought.cancellation.check()
                attempt += 1
                try:
                    reply = chat.complete(thought.system, request, **options)
                    end.update(output_tokens=reply.usage.get("output_tokens"), attempts=attempt)
                    thought.turns = turns
                    return reply
                except RuntimeError as error:
                    if "out of GPU memory" not in str(error) or len(request) <= 2:
                        raise
                    turns = max(1, (turns or (len(history) - 1) // 2) - 1)
                    shorter = window(history, turns)
                    if len(shorter) >= len(request):
                        raise
                    self.trace.emit("context_shortened", history_turns=turns, sent_messages=len(shorter))
                    request = shorter

    def _streamed(self, call, every=decisions.STREAMED_SECONDS, stop=None):
        """What gets the pieces of a streamed reply of call `call`: model_text records of
        what came, at most one per kind every `every` seconds (the timeline shows the text
        so far); it cuts the reply off once `stop()` holds, at a piece or a keep-alive
        (an empty piece)."""
        pending, sent = {}, {}

        def on_text(kind, text):
            if stop is not None and stop():
                raise Preempted()
            if not text:
                return
            pending[kind] = pending.get(kind, "") + text
            now = time.monotonic()
            if kind not in sent or now - sent[kind] >= every:
                sent[kind] = now
                self.trace.emit("model_text", call=call, kind=kind, text=pending.pop(kind))
        return on_text

    def _approved(self, program: str) -> bool:
        """Under the confirmation policy always: wait for the user's verdict on the
        program; a rejection goes to the model as the user's answer and nothing runs."""
        if self.confirmation != "always":
            return True
        with self._condition:
            self._decision = None
            identifier = self._program_approval_id = uuid.uuid4().hex
            self.trace.emit("confirmation_request", id=identifier, code=program)
        try:
            self._wait(WAITING_FOR_CONFIRMATION, lambda: self._decision is not None or bool(self._inbox),
                       reason="program", request={"id": identifier, "code": program})
        finally:
            with self._condition:
                self._program_approval_id = None
        with self._condition:
            if self._decision is None:
                return False
            accepted, reason = self._decision
            self._decision = None
        self.trace.emit("confirmation", id=identifier, accepted=accepted, reason=reason)
        if accepted:
            return True
        self._tell("The user rejected this program, so nothing ran." + (f" Their reason: {reason}" if reason else ""))
        self.reason = "rejected"
        return False

    def _reflected(self, system, messages):
        reply = self._ask_role("reflection", self.chat, system, messages)
        with self._condition:
            decisions = self.summary["decisions"]
            decisions["reflect"] = decisions.get("reflect", 0) + 1
        return reply

    def _reflect_learning(self):
        from harness.runtime.learning.learner import executable

        learning = self._learning()
        cells = self.summary["cells"]
        if (not learning or not learning["reflect"] or self.parent is not None
                or cells <= self._reflected_cells or self.seconds_left() <= 0):
            return
        with self._condition:
            if self._pause or self._closing or self._inbox or self._sides:
                return
            revision = self._revision
        since = self._reflected_cells
        self._reflected_cells = cells
        try:
            learner = self._learner()
            names = (self.config.embodiment, self.profile.get("execution") or self.workspace_kind, *self._skills)
            names = tuple(name for name in names if name)
            found, _ = learner.reflect(SimpleNamespace(complete=self._reflected, thinks=True),
                                       self.directory, names, since=since,
                                       holdings=self._active_library)
            if found is not None:
                with self._admission_lock, self._condition:
                    if revision != self._revision or self._pause or self._closing:
                        return
                    value = learner.admit(found, "proposed", pending=executable(found.key),
                                          why="reflection on observed program results")
                    self._library_admitted(learner, value, found.text, found.kind, found.source, "reflection")
                    if value["admitted"] and found.kind == "note":
                        from copy import copy

                        self.config = copy(self.config)
                        self.config.system_prompt += f"\nObservation from this run: {found.text.strip()}\n"
                        self.invalidate_lookahead()
        except ThoughtCancelled:
            pass
        except Exception as error:
            self.trace.emit("cleanup_error", message=f"reflection: {type(error).__name__}: {error}")

    def _shutdown_ends_the_episode(self, outcome) -> bool:
        """The eval client stops the policy server with SIGTERM after scoring. The kernel
        then exits -15 and the bridge is already closed: the episode ended, it did not fail."""
        summary = self.summary
        return (summary.get("status") == "error" and bool(outcome.get("closed"))
                and str(summary.get("error", "")).startswith("KernelDied:")
                and "code -15" in summary["error"])

    def _close_episode(self, token) -> None:
        """End its sub-agents, close the kernel, read the evaluator's outcome with the token,
        write the summary."""
        trace, summary, directory, env = self.trace, self.summary, self.directory, self.env
        with self._condition:
            self._cancel_managed_worker_approvals("the episode ended")
        if self.agents is not None:
            try:
                self.agents.end_all(self)
            except Exception as error:
                trace.emit("cleanup_error", message=f"sub-agents: {type(error).__name__}: {error}")
        if self.kernel is not None:
            try:
                self.kernel.close()
            except Exception as error:
                trace.emit("cleanup_error", message=f"kernel: {type(error).__name__}: {error}")
        if self._managed_dispatcher is not None:
            try:
                self._managed_dispatcher.close()
            except Exception as error:
                trace.emit("cleanup_error", message=f"managed scheduler: {type(error).__name__}: {error}")
        if token is not None:
            try:
                with self._span("env", "outcome"):
                    outcome = env.call("outcome", token=token)
                videos = outcome.pop("videos", None)
                video_error = outcome.pop("video_error", None)
                trace.emit("outcome", outcome=outcome)
                if video_error:
                    trace.emit("cleanup_error", message=f"video: {video_error}")
                if videos:
                    try:
                        trace.emit("episode_video", files=write_episode_videos(directory, videos))
                    except Exception as error:
                        trace.emit("cleanup_error", message=f"video: {type(error).__name__}: {error}")
                summary.update(success=outcome["success"], reward=outcome["reward"],
                               process_score=outcome["process_score"], steps=outcome["steps"])
                # The eval client's SIGTERM after scoring ends the episode; no agent error.
                if self._shutdown_ends_the_episode(outcome):
                    summary["status"] = "episode_ended"
                    summary.pop("error", None)
                if outcome.get("unscorable") and summary["status"] != "interrupted":
                    # The environment dropped this episode (e.g. RoboDojo marked it unstable
                    # mid-way): neither a success nor a failure of the policy.
                    summary["status"] = "error"
                    summary["error"] = f"Unscorable: {outcome['unscorable']}"
                    trace.emit("error", message=summary["error"])
            except Exception as error:
                trace.emit("cleanup_error", message=f"outcome: {type(error).__name__}: {error}")
        learning = self._learning()
        if self.kernel is not None:
            self._reflect_learning()
        table = self.config.runtime.get("library") or {}
        uses = table.get("uses", {"learn": "on", "off": "off"}.get(table.get("experience"), "learn"))
        self._thoughts.close()
        with self._condition:
            if not self._condition.wait_for(lambda: self._thoughts.active is None, timeout=2):
                summary["model_transport_pending"] = self._thoughts.active.id
        if self.kernel is not None and table and (
                uses == "on" or uses == "learn" and learning is not None):
            # What this episode's closed loops of library skills did, as their uses in the
            # library's index (runtime/learning/usage.py fold_uses).
            try:
                trace.emit("library", action="used", uses=fold_uses(self._learner(), directory))
            except Exception as error:
                trace.emit("cleanup_error", message=f"library uses: {type(error).__name__}: {error}")
        summary["wall_seconds"] = time.perf_counter() - self.started
        if self.agents_usage["started"] or self.agents_usage["model_calls"]:
            summary["agents"] = {**self.agents_usage, "cost_usd": round(self.agents_usage["cost_usd"], 6)}
        write_json(directory / "summary.json", summary)
        self.charge_up()
        self._set_status(ERROR if summary["status"] == "error" else FINISHED, reason=summary["status"])


def _object(reference: str):
    """The object a "module:attribute" reference names."""
    import importlib

    module, _, attribute = reference.partition(":")
    return getattr(importlib.import_module(module), attribute)
