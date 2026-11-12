"""One conversation with one model: turns in it, model decisions and Automatic Control.

A conversation starts with one model. Every program the model writes runs as a unit of its
own in the kernel (runtime/execution/kernel.py): the model's call comes back at once, with
the program's result when it was over within a short grace, else with its handle, and the
result reaches the model when the unit ends. A message, an unhandled event and a unit's
end are events to the model; a reply made before one of them is set aside.

A turn is the model's work from what started it (the instruction, a message, a unit's end,
an event) to its answer: a reply that is text, with no program and no wait (<finish> and a
program's finish() are that same answer). A limit (model calls and wall time, both of the
turn; cost, of the conversation), an error, an interrupt and the environment's end end a
turn too. Every turn ends with a result record (decisions.TURN_ENDS); then the conversation
is IDLE and keeps its messages, the kernel's namespace, rules, facts and the environment.
The units still running after an answer go on, and what reaches the model starts the next
turn. Only the user or the host ends the conversation (close()), or a kernel that died; a
caller without a user (interactive False: a benchmark's run) ends it after the first turn.

A conversation with a user writes what continues it in another process as it goes
(conversation.json beside its trace: its messages, what the user said, its facts): a
TaskRun given that (`restore`: saved()) goes on in the same directory and trace with a new
kernel, and tells the model what died with the old process.
"""

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
from harness.runtime.decision.messages import _inbox_parts, content_parts
from harness.runtime.execution.results import _taken_over, _cell_usage, _wrap_up
from harness.runtime.safety.approval import CONFIRMATION_POLICIES
from harness.runtime.status import Closed, Interrupted

from harness.bench import bench_names, bench_spec
from harness.core.remote import RemoteEnvironment
from harness.core.media import write_episode_videos
from harness.core import atomic_write, sha256
from harness.core.http import Preempted
from harness.core.trace import Trace, context_summary, provenance, write_json
from harness.embodiments import KINDS as EMBODIMENT_KINDS, embodiment_kind
from harness.runtime.decision.thoughts import Thought, ThoughtCancelled, ThoughtQueue
from harness.runtime.execution.kernel import DEFAULT_BOOTSTRAP, Kernel, KernelDied, kernel_python
from harness.runtime.learning.library import SECTIONS, admitted_by, eligible, executable, library_for
from harness.runtime.task import context as memory_view
from harness.runtime.task.context import WorkingMemory
from harness.runtime.learning.usage import fold_uses
from harness.runtime.decision.messages import (EMBODIMENT_TEXT, attachment_parts, cell_feedback, image_parts,
                                               prune_images, prune_views, state_text, text_only, unit_feedback,
                                               unit_text, view_parts)
from harness.runtime.events import EVENTS
from harness.runtime.status import ERROR, FINISHED, IDLE, PAUSED, RUNNING, STATUSES, WAITING_FOR_CONFIRMATION
from harness.runtime.learning.active import sandbox_of
from harness.runtime.reactive.tree import told as tree_told
from harness.runtime.decision.messages import clear_results, latest, recent_start
from harness.runtime.decision.protocol import (DIRECT_KINDS, KINDS, ProtocolError, announces, looks_like_action,
                                               parse_reply, wait_seconds)

import harness.runtime.learning.views as library_view


# What continues a conversation in another process, in its directory.
CONVERSATION_FILE = "conversation.json"


def saved(directory) -> dict | None:
    """What the conversation in `directory` kept to be continued (TaskRun's `restore`):
    {"messages", "said", "facts", "units", "turns", "summary"}; None when it kept nothing."""
    try:
        kept = json.loads((Path(directory) / CONVERSATION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return kept if isinstance(kept, dict) and isinstance(kept.get("messages"), list) and kept["messages"] else None


class TaskRun:
    """One episode of `config.task` with `seed`, its trace and files under `directory`.
    `chat`, `verifier` and `environment` replace the configured models and worker.
    `interactive`: a user takes part (see the module docstring); `confirmation`: one of
    CONFIRMATION_POLICIES; `instruction`: the user's own instruction in place of the
    task's (the evaluator's outcome still scores the task). `agents` (runtime/task/delegation.py)
    starts the sub-agents its programs ask for; `parent`: the agent that started this one.
    `restore`: what an earlier process kept of this conversation (saved(directory)): it goes
    on from there, in the same directory and trace.
    Managed workspaces are acquired by the host before the conversation starts."""

    def __init__(self, config, seed: int, directory, *, chat=None, verifier=None, environment=None,
                 interactive: bool = False, confirmation: str = "never", instruction: str | None = None,
                 agents=None, parent=None, memory=None, restore: dict | None = None):
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
        # The tokens of context the model's last call read and wrote (what compaction goes
        # by), the summaries in a row the model did not give, and the learning report as
        # the model was last told it.
        self._context_tokens, self._compact_failures, self._learning_told = 0, 0, None
        # When the model last replied (what clearing old results goes by).
        self._replied_at = None
        self._captured_library = None
        self._activation_queue = {}
        self._activation_interrupt = 0
        self._fixture_attempts = set()
        # What the host allows for admitting learned code (learner.ADMISSION): set by the host
        # that starts the conversation from the user's setting learning.admission; None is
        # $HARNESS_LEARNING_ADMISSION, else "fixture". Never part of the run's configuration.
        self.library_admission = None
        self._admission_level = None
        self._trial_interrupted = set()
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
        grace = config.runtime.get("turn_grace_seconds", decisions.TURN_GRACE_SECONDS)
        if isinstance(grace, bool) or not isinstance(grace, (int, float)) or grace < 0:
            raise ValueError(f"runtime.turn_grace_seconds must be a number of seconds >= 0, got {grace!r}")
        longest = config.runtime.get("longest_wait_seconds", decisions.LONGEST_WAIT_SECONDS)
        if isinstance(longest, bool) or not isinstance(longest, (int, float)) or longest <= 0:
            raise ValueError(f"runtime.longest_wait_seconds must be a number of seconds > 0, got {longest!r}")
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
            if parent is None:
                role_prompt = decisions.INTERACTIVE_PROMPT
            else:
                deepest = agents is None or self.depth >= agents.max_depth
                role_prompt = SUB_AGENT_PROMPT + (
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
        self.trace = Trace(directory, EVENTS, append=restore is not None)
        self._restore = restore
        if restore is not None:
            # Its last summary said it had ended: it is open again, so nothing takes it for ended.
            write_json(directory / "summary.json", {**(restore.get("summary") or {}), "open": True})
        # The facts of its programs as the kernel reports their changes: kept to be restored.
        self._facts = dict((restore or {}).get("facts") or {})
        self.status = IDLE
        self.messages = []
        self.kernel = None
        self.episode = None
        self.summary = None
        self._condition = threading.Condition()
        self._inbox = []
        self._pause = False
        self._closing = False
        # The user asked to end the turn that runs (cancel()).
        self._interrupt = False
        self._decision = None
        # Of the turn that runs: when it began, the time it waited for the user, the
        # model's calls before it, and how many turns began.
        self._turn_began = None
        self._waited = 0.0
        self._calls_before = 0
        self._turns = 0
        self._program_span = None
        # The model's units that run ({unit id: {"name", "kind", "cell", "started"}}), its
        # programs whose result has not come ({the kernel's cell: {"number", "code", "action",
        # "span", "unit"}}),
        # the results of the units that ended and the model has not been told, and how
        # long a program may hold the model's turn before the turn comes back with its handle.
        self._units = {}
        self._programs = {}
        self._unit_news = []
        self._grace = float(grace)
        # The longest a <wait> of the model lasts.
        self._longest_wait = float(longest)
        # A unit ended the turn: "episode_ended", or ("finished", the summary its finish() gave).
        self._run_end = None
        # The model's call count when the learned policy first ran (runtime.post_policy_calls).
        self._post_from = None
        self._request = None
        self._revision = 0
        self._pending_events = {}
        self._inbound = None     # the listener its worker tells through (runtime/task/inbound.py)
        self._seen_events = set()
        self._reported_events = set()
        self._thoughts = ThoughtQueue(self._condition, on_exit=self._came_back, trace=self.trace)
        self._cancelled_origins = set()
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
        self.mcp_authorize = parent.mcp_authorize if parent is not None else None
        self._mcp_slot = threading.BoundedSemaphore(16)
        self._mcp_cancelled = set()
        self._mcp_entries = set()
        self.mcp_resources = parent.mcp_resources if parent is not None else None
        self._managed_workspace = self._managed_dispatcher = None
        # Other environments this conversation may take, and its sub-agents on request
        # (runtime/task/environments.py): the session host's, None where there is none.
        self.environments = None
        # Skills the user switched on while it runs: loaded between programs.
        self._skills_due = []
        # How views reach the model. A configuration that declares runtime.cameras has a
        # standing watch from the opening message on (an evaluation's observation contract:
        # every turn carries those cameras, keep_images of them stay). Any other looks on
        # the model's demand: text every turn, a view only when a program looked (look,
        # watch), kept for `_view_keep` replies or while pinned (the model says).
        self._standing = "cameras" in config.runtime
        self._view_keep, self._view_pins = 1, set()
        # A main model that reads no images gets none (its role's `images` is false).
        self._images = config.main.get("images") is not False
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
            self.trace.emit("user_message", text=text, **({"files": files} if files else {}),
                            **({"sender": sender} if sender != "user" else {}))
            self._revision += 1
            if self._managed_dispatcher is not None:
                # (The message stops no program; an approval asked before it is void.)
                self._cancel_managed_worker_approvals("a new user message arrived")
            if self._physical is not None and self._physical["id"] in self._worker_approvals:
                request = self._physical
                self._worker_approvals.pop(request["id"])
                self._physical = None
                self._answer_physical(request, False, "once", "superseded by a user message")
            self._preempt("user message")
            self._condition.notify_all()

    def pause(self) -> None:
        """Pause: every unit of the model stops at its next execution step or wait, and
        nothing of it acts; the model is not called again until resume() or a message."""
        with self._condition:
            if self.status in (FINISHED, ERROR):
                return
            self._pause = True
            self._activation_interrupt += 1
            self._thoughts.cancel_where(lambda item: item.role == "reflection", "paused")
            if self._managed_dispatcher is not None:
                self._managed_dispatcher.stop()
            self._cancel_managed_worker_approvals("paused")
            kernel = self.kernel
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
            kernel = self.kernel
            self._condition.notify_all()
        if kernel is not None:
            kernel.resume()

    def set_model(self, model: str | None = None, reasoning_effort: str | None = None) -> dict:
        """Change the main model (another id of its provider) or its reasoning effort (EFFORTS,
        "" for the provider's default; runtime.thinking still bounds it) from its next call on:
        a model_changed record. Returns the model and effort now."""
        from harness.runtime.decision.model import BUILT_IN, ChatModel

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
                # Its connection as it is (a provider's transport), with the new role; a
                # package's backend (an ACP agent) is made for its role.
                packaged = chat.packaged or main.get("backend", "openrouter") not in BUILT_IN
                chat = ChatModel(main, transport=None if packaged else chat.transport)
            self.config.main = main
            if chat is not None:
                replaced, self.chat = self.chat, chat
                if replaced.packaged:
                    replaced.close()
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
                self._host_tool["reason"] = str(reason or "")
                self._answer_physical(request, accept, "once", reason, host_only=True)
                self._condition.notify_all()
                return
            if pending is not None and pending["workspace"] is not None:
                self._answer_physical(request, accept, "once", reason, host_only=True)
                if not accept:
                    self.cancel_worker_approval(pending, reason=reason or "the approval was refused")
                return
        self._answer_physical(request, accept, remember or "once", reason)

    # What a frontend may ask of it besides messages (the host's /api/conversations/cancel).
    capabilities = {"cancel_turn": True}

    def cancel(self) -> None:
        """End the turn that runs: the call in flight is set aside, the model's units are
        cancelled, and the conversation waits for the next message (nothing between turns)."""
        with self._condition:
            if self.status in (FINISHED, ERROR, IDLE) or self._interrupt:
                return
            self._interrupt = True
            self._revision += 1
            self._preempt("interrupted")
            self._condition.notify_all()

    def close(self) -> None:
        """End the conversation: at once while it waits, else at the next step boundary."""
        with self._condition:
            self._closing = True
            if self._request is not None:
                self._preempt("conversation closed")
            if self._managed_dispatcher is not None:
                self._managed_dispatcher.stop()
            self._cancel_managed_worker_approvals("closed")
            kernel = self.kernel
            self._condition.notify_all()
        if self.agents is not None:
            self.agents.wake()
        self._drop_physical("closed")
        if kernel is not None:
            # The run ends: so do its units.
            kernel.cancel()

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
            managed = bool(getattr(self.env, "approval_key", None)) or (
                self.environments is not None and self.environments.any_managed())
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
        """A record from the kernel: a span (a skill's execution, a service call) under the
        program whose unit made it, a note, a unit's start or end."""
        record = dict(record)
        kind = record.pop("op")
        if kind == "worker_request":
            self._queue_host_request(record, worker=True)
            return
        if kind == "unit_end":
            self._unit_arrived(record)
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
            elif note == "environment":
                threading.Thread(target=self._environment_request, args=(record,), name="environment",
                                 daemon=True).start()
            elif note == "views":
                self._views_changed(record)
            elif note == "mcp_request":
                self._queue_host_request(record)
            elif note == "mcp_cancel":
                with self._condition:
                    self._mcp_cancelled.add(record["id"])
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
            elif note == "escalation":
                self._escalation(record)
            elif note == "memory":
                self._memory_request(record)
            elif note == "reflexes":
                # How the tree of reflexes stands (runtime/reactive/tree.py tell): told with every turn.
                with self._condition:
                    self._reflex_nodes = dict(record.get("nodes") or {})
            elif note == "preempted":
                self._taken(record)
            elif note == "held_back":
                self._held_back(record)
            elif note == "uninterruptible":
                with self._condition:
                    if record.get("unit") in self._units:
                        self._units[record["unit"]]["uninterruptible"] = True
            elif note == "fact":
                record.pop("time", None)
                data = record.pop("data", None)
                with self._condition:
                    if record.get("dropped"):
                        self._facts.pop(record.get("name"), None)
                    elif data is not None:
                        self._facts[record["name"]] = json.loads(data)
                self.trace.emit("fact", **record)
            elif note in EVENTS:
                if note == "program_output":
                    with self._condition:
                        unit = self._units.get(record.get("unit"))
                        if unit is not None and "printed" in unit:
                            unit["printed"] = time.time()
                record.pop("time", None)
                self.trace.emit(note, **record)
                if note == "guard" and self.summary is not None:
                    self.summary["guard_triggers"] += 1
            return
        if kind in ("entry_start", "entry_end"):
            with self._condition:
                if kind == "entry_start":
                    self._mcp_entries.add(record["id"])
                    if record.get("kind") in ("program", "agent"):
                        self._units[record["id"]] = {"name": record.get("name"), "kind": record["kind"],
                                                     "cell": record.get("cell"), "started": time.time()}
                        if record["kind"] == "program" and self._managed_dispatcher is None:
                            # What it prints reaches the host while it runs (program_output).
                            self._units[record["id"]]["printed"] = None
                        program = self._programs.get(record.get("cell"))
                        if program is not None:
                            program["unit"] = record["id"]
                else:
                    self._mcp_entries.discard(record["id"])
                    self._units.pop(record["id"], None)
                self._condition.notify_all()
        if kind == "span_start" and record.get("parent") is None:
            # Under the program whose unit made it, else under the host's own program span.
            cell = (self._units.get(record.get("entry")) or {}).get("cell")
            record["parent"] = (self._programs.get(cell) or {}).get("span") or self._program_span
        self.trace.emit(kind, **record)

    def _queue_host_request(self, request, *, worker=False):
        identifier = request.get("id")
        owner = request.get("entry") if not worker else None
        if not isinstance(identifier, str) or len(identifier) != 32:
            return
        with self._condition:
            kernel = self.kernel
            if kernel is None or (not worker and owner not in self._mcp_entries) or self._closing or self._pause:
                if worker and kernel is not None:
                    kernel.answer(identifier, {"worker": True, "error": "The calling program has stopped"})
                return
            slot = self._worker_slot if worker else self._mcp_slot
            if worker and request.get("environment"):
                # An attached environment's call (runtime/execution/attached.py): its own slots.
                try:
                    slot = self.environments.of(request["environment"])["slot"]
                except Exception as error:
                    kernel.answer(identifier, {"worker": True, "error": str(error)})
                    return
            if not slot.acquire(blocking=False):
                kernel.answer(identifier, {"worker": worker, "error": "Another request is still running"})
                return

        def still_current():
            return (self.kernel is kernel and (worker or owner in self._mcp_entries)
                    and not self._pause and not self._closing
                    and (worker or identifier not in self._mcp_cancelled))

        threading.Thread(target=self._host_request, args=(kernel, request, still_current, slot),
                         kwargs={"worker": worker}, name="host-request", daemon=True).start()

    def _host_request(self, kernel, request, still_current, slot, *, worker=False):
        """Make a host-owned worker or MCP call without blocking the kernel reader."""
        from harness.services.mcp import ToolAccess

        action = None
        dispatched = False
        def mark_dispatched(server):
            nonlocal dispatched
            dispatched = True
            self.trace.emit("mcp_dispatched", id=request["id"], server=server, tool=request.get("tool"))
        if not worker:
            self.trace.emit("mcp_submitted", **request)
        try:
            with self._condition:
                if not still_current():
                    raise PermissionError("The calling program has stopped")
                if not worker and not hasattr(self, "_mcp_access"):
                    self._mcp_access = ToolAccess(self.config.runtime.get("mcp") or {}, prepare=self.mcp_prepare,
                                                  resources=self.mcp_resources, directory=self.directory / "services",
                                                  authorize=self.mcp_authorize)
                plain = None
                if worker:
                    name, args = request.get("name"), dict(request.get("arguments") or {})
                    env, episode = self.env, self.episode
                    if request.get("environment"):
                        attached = self.environments.of(request["environment"])
                        env, episode = attached["env"], attached["episode"]
                        if not getattr(env, "approval_key", None) or name not in env.host_controls:
                            # What the worker serves to anyone: sent as the kernel would send it.
                            if args.get("episode_id", episode) != episode:
                                raise PermissionError("The call belongs to another episode")
                            plain = attached["plain"]
                if worker and plain is None:
                    if not getattr(env, "approval_key", None) or name not in env.host_controls:
                        raise PermissionError("The host does not own this worker control")
                    if args.setdefault("episode_id", episode) != episode:
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
                            args = {"op": "answer", "episode_id": episode, "id": identifier,
                                    "accept": accept, "remember": remember}
                            del self._worker_approvals[identifier]
                    elif (name not in getattr(env, "program_controls", ()) and name != "use_screen"
                          and not (name == "physical" and op in ("check", "status"))):
                        raise PermissionError("This worker control is reserved to the host")
            if worker and plain is not None:
                reply = {"value": plain.call(name, **args)}
            elif worker:
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
                        (episode, args["execution_id"], action)):
                    with self._condition:
                        if still_current():
                            self._register_worker_approval(offered, args)
            elif request.get("method") == "list":
                reply = {"value": self._mcp_access.tools()}
            elif request.get("method") == "call":
                reply = {"value": self._mcp_access.call(request.get("tool"), request.get("arguments"),
                             approve=lambda tool, target: self._approve_host_tool(tool, target, still_current),
                             current=still_current, dispatched=mark_dispatched)}
            else:
                raise ValueError("Unknown MCP operation")
        except Exception as error:
            reply = {"error": f"{type(error).__name__}: {error}"}
        finally:
            slot.release()
        with self._condition:
            if not worker:
                self.trace.emit("mcp_receipt", id=request["id"], tool=request.get("tool"),
                                late=not still_current(), dispatched=dispatched,
                                outcome="unknown" if dispatched and "error" in reply else
                                        "not_dispatched" if "error" in reply else "returned", **reply)
            if worker and action and self.kernel is not kernel:
                result = reply.get("value") or {}
                self.trace.emit("late_receipt", action_id=action, executed=result.get("executed"),
                                step=(result.get("state") or {}).get("step"), error=reply.get("error"))
            if still_current() or worker and self.kernel is kernel:
                kernel.answer(request["id"], {"worker" if worker else "mcp": True, **reply})

    def _approve_host_tool(self, tool, target, still_current):
        """Await and claim a decision for one operation already bound by the host."""
        from harness.runtime.safety import approval

        request = approval.request("irreversible", target, [tool])
        return self._await_host_decision(request, still_current, approval.WORKER_APPROVAL_SECONDS)[0]

    def _await_host_decision(self, request, still_current, seconds=None):
        """Put a request of the host's own to the user as every frontend shows an approval,
        and wait for their answer: (accepted, their reason). Refused without asking when
        nobody is there, another approval is pending or the asking program has stopped."""
        with self._condition:
            if (not self.interactive or not still_current() or self._physical is not None
                    or self._host_tool is not None):
                return False, "another approval is pending" if self._physical is not None else ""
            deadline = time.monotonic() + seconds if seconds else float("inf")
            pending = self._host_tool = {"request": request, "decision": None, "deadline": deadline, "reason": ""}
            self._physical = request
            self.trace.emit("physical_request", **request)
            self._set_status(WAITING_FOR_CONFIRMATION, reason="physical", request=request)

            ready = self._condition.wait_for(lambda: pending["decision"] is not None or not still_current(),
                                             timeout=seconds)
            self._host_tool = None
            if self._physical is request:
                self._drop_physical("the approval expired or was interrupted")
            accepted = ready and still_current() and time.monotonic() < deadline and pending["decision"] is True
            return accepted, pending["reason"] or ("" if ready else "the question was interrupted")

    def _ask_user(self, kind, target, *, why="", **detail):
        """Ask the user one of the host's own questions (another environment, sub-agents) from
        a running program: (accepted, their reason). It waits as long as the user takes; a
        pause, a new message or the conversation's end leaves it unanswered."""
        from harness.runtime.safety import approval

        with self._condition:
            kernel, revision = self.kernel, self._revision

        def still_current():
            return (self.kernel is kernel and self._revision == revision and not self._pause
                    and not self._closing)

        request = approval.request(kind, target, [kind], why=str(why)[:500], **detail)
        return self._await_host_decision(request, still_current)

    def _views_changed(self, record):
        """What a program said of its views (runtime/execution/session.py): how many programs'
        views stay in sight, a watch begun or ended, a pin let go."""
        action = record.get("action")
        with self._condition:
            if action == "keep":
                self._view_keep = max(1, min(20, int(record.get("keep") or 1)))
            elif action == "unpin":
                if record.get("pin") is None:
                    self._view_pins.clear()
                else:
                    self._view_pins.discard(str(record["pin"]))
        self.trace.emit("views", **{key: value for key, value in record.items() if key not in ("time", "id")})

    def _described(self, looks) -> list[dict]:
        """Views for a main model that reads no images: what the vision role says of each
        (runtime.viewer), or that it was not sent."""
        from harness.runtime.decision.model import ChatModel

        viewer = self.config.runtime.get("viewer")
        parts = []
        for item in list(looks)[-4:]:
            name = f"View: {item['camera']}" + (f" region {item['region']}" if item.get("region") else "")
            if not isinstance(viewer, dict) or not viewer.get("model"):
                parts.append({"type": "input_text", "text": f"{name}: not sent. This model reads no images and no "
                              "vision model is configured (model.vision); use the state and what the "
                              "environment's calls return as text."})
                continue
            try:
                chat = self.__dict__.setdefault("_viewer_chat", None) or ChatModel(
                    {"max_output_tokens": 1024, **{key: value for key, value in viewer.items() if key != "images"}})
                self._viewer_chat = chat
                reply = self._ask_role("vlm", chat, VIEWER, [{"role": "user", "content": [
                    {"type": "input_image", "image_url": item["image_url"], "detail": "auto"},
                    {"type": "input_text", "text": "Describe this view."}]}])
                parts.append({"type": "input_text", "text": f"{name}, as the vision model describes it:\n"
                                                            + reply.text.strip()})
            except Exception as error:
                parts.append({"type": "input_text", "text": f"{name}: not described ({type(error).__name__}: {error})"})
        return parts

    def _environment_request(self, request):
        """A program asks for another environment, to give one back, or for sub-agents
        (skills/environments): answered through the kernel."""
        if self.environments is None:
            answer = {"error": "this conversation cannot take another environment"}
        else:
            answer = self.environments.handle(request)
        if self.kernel is not None:
            self.kernel.answer(request.get("id"), answer)

    def _prompt_added(self, text):
        from copy import copy

        with self._condition:
            self.config = copy(self.config)
            self.config.system_prompt += text

    def _prompt_removed(self, text):
        from copy import copy

        with self._condition:
            self.config = copy(self.config)
            self.config.system_prompt = self.config.system_prompt.replace(text, "", 1)

    def _skill_added(self, name) -> bool:
        """A skill switched on while the conversation runs: part of its skills and prompt now."""
        with self._condition:
            if name in self._skills:
                return False
            self._skills = [*self._skills, name]
        if self.environments is not None and name == "agents":
            self._prompt_added("\n\nSub-agents are on for this conversation now.\n"
                               + (self.environments.place.agents().get("prompt") or ""))
        return True

    def enable_agents(self) -> bool:
        """The user switches sub-agents on for this conversation (any frontend): their calls
        load before its next program."""
        if self.environments is None:
            raise RuntimeError("this conversation cannot start sub-agents")
        with self._condition:
            if self.status in (FINISHED, ERROR):
                raise RuntimeError("The episode has ended")
        given = self.environments.enable_agents(asked_by="user")
        with self._condition:
            self._skills_due += given["skills"]
            self._condition.notify_all()
        return True

    def _load_due_skills(self) -> None:
        with self._condition:
            due, self._skills_due = self._skills_due, []
            kernel = self.kernel
        if due and kernel is not None:
            result = kernel.run(f"__load_skills__({due!r})", timeout=60)
            if result["status"] != "ok":
                self.trace.emit("cleanup_error", message=f"skills {due}: {result.get('error')}")

    def tell(self, content, source: str | None = None) -> None:
        """The environment tells the model something that happened by itself: a message, in
        the form conversations give content (a string, or a list of text and image parts:
        decision/messages.py content_parts). It reaches the model at once as a message does:
        a wait ends, a call in flight is set aside and asked again; the model reads it as
        "Message from the environment". Called by whoever knows of it: the run's worker
        through its listener (runtime/task/inbound.py), or the code that owns this run."""
        parts = content_parts(content)
        if not parts:
            return
        sender = "environment" + (f" ({source})" if source and source != "environment" else "")
        text = "\n".join(part["text"] for part in parts if part["type"] == "input_text")
        with self._condition:
            if self.status in (FINISHED, ERROR):
                raise RuntimeError("The episode has ended")
            self._inbox.append((sender, text, parts))
            self.trace.emit("user_message", text=text, sender=sender,
                            **({"images": sum(part["type"] == "input_image" for part in parts)}
                               if any(part["type"] == "input_image" for part in parts) else {}))
            self._revision += 1
            self._preempt("environment message")
            self._condition.notify_all()

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

    def _held_back(self, record: dict) -> None:
        """A rule's condition came to hold while an uninterruptible unit had the
        environment (the kernel's `held_back` note, once per rule and unit): the rule did
        not act and is judged again when that unit has ended. An event to the model, told
        at once as a preemption is, so that it may let the rule act by cancelling the unit."""
        record.pop("time", None)
        self.trace.emit("held_back", **record)
        self._escalation({"id": uuid.uuid4().hex, "entry": record.get("by"), "event": {
            "kind": "HELD_BACK", "source": record.get("rule"),
            "detail": {key: record[key] for key in ("rule", "priority", "by", "by_name") if record.get(key) is not None}}})

    def _taken(self, record: dict) -> None:
        """A unit of higher priority (a rule's program) took the environment from an
        execution that ran (the tick's `preempted` note): an event to the model, told at
        once as every event that reaches it is: a wait ends, a call in flight is set
        aside and asked again. It says which unit and rule took the environment, from
        which unit and execution, whether that execution is started again, and the state."""
        record.pop("time", None)
        state = record.pop("state", None) or {}
        self.trace.emit("preempted", **record)
        if record.get("of_reflex"):
            # The call of a reflex's program: its node begins again by itself when its turn comes.
            return
        told = {key: record[key] for key in ("rule", "by", "by_name", "unit", "name", "execution", "restart")
                if record.get(key) is not None}
        self._escalation({"id": uuid.uuid4().hex, "entry": record.get("unit"), "event": {
            "kind": "PREEMPTED", "source": record.get("rule") or record.get("by_name") or record.get("by"),
            "detail": {**told, **({"state": state_text(state, self.config.embodiment, self._steps_shown())}
                                  if state else {})}}})

    def _preempt(self, reason):
        """Something reached the model while its call is in flight: the call is set aside
        (its reply would not know), and so are the role calls that reason makes stale."""
        thought = self._request
        if thought is not None and thought.outcome is None:
            self._settle(thought, "discarded", reason)
        if reason == "user message":
            self._thoughts.cancel_where(lambda item: item.role in ("verifier", "observer", "vlm", "pointer", "reflection"),
                                        reason)
        elif reason == "unhandled escalation":
            self._thoughts.cancel_where(lambda item: item.role == "observer", reason)

    def _busy(self) -> bool:
        """Whether a program of the model runs (code it spawned to go on beside does not count)."""
        return bool(self._programs)

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

    def _admission(self) -> str:
        """How learned code is admitted in this conversation (learner.admission): what the
        host allows (the conversation that started this one decides for its sub-agents),
        for this worker's profile. Read once, when the profile is known."""
        if self._admission_level is None:
            import os

            from harness.runtime.learning.learner import ADMISSION_VARIABLE, admission

            root = self
            while root.parent is not None:
                root = root.parent
            allowed = os.environ.get(ADMISSION_VARIABLE) or root.library_admission
            profile = getattr(self, "profile", None)
            if profile is None:
                return admission(None, allowed)     # before the worker answered: asked again later
            self._admission_level = admission(profile, allowed)
            if self.config.runtime.get("library"):
                self.trace.emit("library", action="admission", level=self._admission_level,
                                allowed=allowed or "fixture", physical=self.profile.get("physical"))
        return self._admission_level

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
                         "verified": bool(row.get("proof")), "admitted_by": admitted_by(row),
                         "uses": info["seen"], "success_rate": info["rate"]})
        return rows

    def _learning_progress(self):
        from harness.runtime.learning.active import progress

        return {**progress(self._learning_rows(), self.seconds_left(), self.config.max_wall_seconds or 0.0,
                           self._situations()), "fixture_status": self._fixture_status,
                "fixture_feedback": dict(self._fixture_feedback), "admission": self._admission()}

    def _learning_report(self) -> str:
        from harness.runtime.learning import active

        if not active.is_active(self.config.runtime):
            return ""
        level = self._admission()
        report = active.report(self._learning_rows(), self.seconds_left(), self._situations(), level)
        if self._fixture_descriptions:
            report += "\n" + "\n".join(self._fixture_descriptions)
        if level == "off":
            report += "\nThe host admits no code here. Keep what you learn as notes and memory entries."
        elif level == "own_test":
            report += ("\nThe host runs a pending proposal's own test between programs: end the program after "
                       "proposing. A proposal whose test passes is active in your next program.")
        elif not self._fixture_descriptions and self._fixture_status == "unavailable":
            report += "\nNo trusted fixture is configured here. Keep observations and leave executable proposals pending."
        if self._fixture_feedback:
            report += "\n" + "\n".join(f"{key}: {why}" for key, why in self._fixture_feedback.items())
        return "\n" + report

    def _trial_at_boundary(self, *, replay=False):
        """Run at most one trial between programs, or recheck pinned entries at startup. What
        verifies a pending proposal is the admission level in force (_admission): a fixture
        the host has for it; where the level is own_test and it has none, its own test
        (_own_test_trial); nothing where the level is off."""
        from harness.runtime.learning import fixtures
        from harness.runtime.learning.learner import CANDIDATES, OWN_TEST

        learning = self._learning()
        if not learning or self.parent is not None or (replay and not learning["replay"]):
            return
        level = self._admission()
        if level == "off":
            self._fixture_status = "off"
            return
        with self._condition:
            if self._closing or self._pause or self._busy() or (self._inbox and not replay):
                return
            generation = self._activation_interrupt, self._revision

        def cancelled():
            with self._condition:
                return (self._closing or self._pause or self._busy()
                        or generation != (self._activation_interrupt, self._revision))

        own_test = level == OWN_TEST and not replay
        try:
            inventory = fixtures.configured(self.profile)
        except (OSError, TypeError, ValueError) as error:
            inventory = ()
            if self._fixture_status != "unavailable":
                self.trace.emit("library", action="fixture_unavailable", reason=str(error))
        self._fixture_descriptions = fixtures.describe(inventory)
        self._fixture_status = "configured" if self._fixture_descriptions else "unavailable"
        if not self._fixture_descriptions and not own_test:
            return
        learner = self._learner()
        trials = {fixture.get("skill"): fixture for fixture in inventory} if self._fixture_descriptions else {}
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
            if not fixture and own_test and pending and (row.get("demoted") or {}).get("revision") == expected:
                uses = row["demoted"]
                self._fixture_feedback[key] = (f"Sent back to pending after failing in use ({uses.get('ok', 0)} of "
                                               f"{uses.get('ok', 0) + uses.get('failed', 0)} uses succeeded): rewrite it "
                                               "and propose it again.")
                continue
            if ((not fixture and not (own_test and pending)) or not expected or expected in self._fixture_attempts
                    or cancelled() or self.seconds_left() <= 0):
                continue
            self._fixture_attempts.add(expected)
            if not fixture:
                # A fixture, where the host has one for the entry, wins: this is the rest.
                self._own_test_trial(learner, key, expected, cancelled)
                return
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

    def _own_test_trial(self, learner, key, expected, cancelled):
        """Verify one pending proposal by its own test, where the admission level is own_test:
        the kernel stages the exact revision, the host runs its test on the staged revision
        as a cell of its own (Kernel.run_staged: bounded, counted as testing, the entry not
        yet in the programs' namespace) and reads the cell's result. The kernel never grades:
        a pass makes the host write the proof (method "own_test", this worker's profile, the
        receipt) and admit the revision as provisional, then commit it; anything else leaves
        nothing loaded, and a test that ran and did not pass marks the proposal failed."""
        from harness.runtime.learning import fixtures
        from harness.runtime.learning.learner import OWN_TEST, OWN_TEST_SECONDS, STAGED_TEST

        def pending(reason, tell=True):
            if tell:
                self._fixture_feedback[key] = f"Still pending: {reason[:300]}."
            self.trace.emit("library", action="trial_pending", key=key, revision=expected, reason=reason)

        try:
            entry = learner.candidate_from(key, pending=True)
        except (OSError, ValueError) as error:
            return pending(str(error))
        if entry is None or not entry.test or entry.revision().revision != expected:
            return
        if entry.test.startswith(STAGED_TEST) and not sandbox_of(self.config.runtime):
            return pending("its test stages a scene in the practice sandbox, and this run has none")
        item = entry.revision()
        budget = fixtures.Budget(self.seconds_left(), cancelled, limit=OWN_TEST_SECONDS + 60.0)
        observed = {}

        def test(kernel):
            """Why the staged revision's own test did not pass; None when it passed."""
            limit = max(0.01, min(OWN_TEST_SECONDS, self.seconds_left()))
            self.trace.emit("library", action="trial_started", key=key, revision=expected, method=OWN_TEST)
            began = time.perf_counter()
            try:
                with self._span("program", f"test of {key}") as end:
                    # The test runs as a unit with `limit` as its time: the kernel ends it then.
                    result = kernel.run_staged(entry.test, timeout=limit)
                    end.update(status=result["status"])
            finally:
                self.summary["kernel_seconds"] += time.perf_counter() - began
            _cell_usage(self.summary, result)
            self.charge_up()
            why = None
            if result["status"] != "ok" and "deadline exceeded" in str(result.get("error") or "").lower():
                why = f"its test did not end within {limit:.0f} s"
            elif result["status"] != "ok":
                why = str(result.get("error") or f"its test ended the program with {result['status']}")
            elif (result.get("state") or {}).get("ended"):
                why = "its test ended the episode"
            receipt = {"ok": why is None, "method": OWN_TEST, "run": str(self.directory), "episode_id": self.episode,
                       "revision": expected, "seconds": round(time.perf_counter() - began, 3),
                       **({"error": why[-600:]} if why else {})}
            observed["receipt"] = receipt
            self.trace.emit("library", action="trial_observed", key=key, **receipt,
                            stdout=str(result.get("stdout") or "")[-2000:])
            return why

        def publish():
            budget.remaining()
            receipt = observed["receipt"]
            proof = {"revision": item.revision, "receipt": receipt,
                     "conditions": {"method": OWN_TEST, "profile_sha256": sha256(self.profile)}}
            value = learner.admit(entry, "provisional", proof=proof, test_run=receipt, expected=expected,
                                  check=budget.remaining)
            self._library_admitted(learner, value, entry.text, entry.kind, entry.source, entry.origin)
            self._fixture_feedback.pop(key, None)
            observed["admitted"] = value
            return value["row"]

        proof = {"revision": item.revision, "conditions": {"method": OWN_TEST, "profile_sha256": sha256(self.profile)}}
        row = {**(learner.index().get(f"candidates/{key}") or {}), "revision": item.revision, "proof": proof,
               "evidence": "provisional"}
        loads = learner.wanted(entry, "provisional") and self._library_eligible(
            item, row, learner.layers, learner.settings["load"])
        try:
            outcome = self._activate_library([(item, row)], publish=publish, budget=budget, test=test, commit=loads)
        except (OSError, ValueError, RuntimeError, TimeoutError) as error:
            if isinstance(error, KernelDied):
                raise
            outcome = {"status": "error", "error": str(error)}
        receipt = observed.get("receipt")
        active = (self.config.runtime.get("library") or {}).get("trigger") == "active"
        if "admitted" in observed:
            if not active:
                self._tell(f"The host ran the test of your proposal {key} and it passed"
                           + (": it is active from your next program." if outcome.get("status") == "activated"
                              else "; it waits for validation before it is loaded."))
            return
        if receipt is not None and not receipt["ok"]:
            try:
                with self._admission_lock, self._condition:
                    learner.record_trial(key, expected, item, pending=True, evidence="failed", receipt=receipt,
                                         check=lambda: None)
            except (OSError, ValueError) as error:
                self.trace.emit("library", action="trial_pending", key=key, revision=expected, reason=str(error))
            self._fixture_feedback[key] = f"Its own test failed when the host ran it: {receipt['error'][-300:]}"
            if not active:
                self._tell(f"The host ran the test of your proposal {key} and it failed: {receipt['error'][-300:]}\n"
                           "It stays out of your library; rewrite it and propose it again if you still need it.")
            return
        # No verdict: the revision could not be staged, or the boundary was taken (a pause, a
        # message, an event). One more try at a later boundary, then it waits.
        if outcome.get("status") == "cancelled" or receipt is not None:
            if expected not in self._trial_interrupted:
                self._trial_interrupted.add(expected)
                self._fixture_attempts.discard(expected)
            pending("its test was interrupted", tell=False)
        else:
            pending(f"it could not be loaded for its test: {outcome.get('error') or 'unknown'}")

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
        if executable(item.key) and row and row.get("origin") != "hand" and self._admission() == "off":
            return False    # the host admits no learned code: it is not loaded either
        conditions = (row.get("proof") or {}).get("conditions") or {}
        if isinstance(conditions, dict) and conditions.get("profile_sha256") not in (None, sha256(self.profile)):
            return False
        return eligible(item, row, layers, load)

    def _activate_library(self, selected, *, startup=False, publish=None, budget=None, test=None, commit=True):
        """Stage `selected` in the kernel, publish (the admission, when given) and commit.
        `test(kernel)` runs after staging and says why the staged revision must not be
        published (None: go on); without `commit` the staged revision is admitted and not
        loaded. {"status": "activated", "admitted", "cancelled" or "error"[, "error"]}."""
        if not selected:
            return {"status": "cancelled"}
        def can_switch():
            return startup or (not (self._busy() or self._inbox)
                               and (publish is not None or all(
                                   self._activation_queue.get(item.key, (None,))[0] == item for item, _ in selected)))

        with self._condition:
            if self._pause or self._closing or not can_switch():
                return {"status": "cancelled"}
            kernel = self.kernel
            interrupt = self._activation_interrupt
        for item, _ in selected:
            item.save(self.directory)
        entries = [(item, startup and row.get("origin", "hand") == "hand") for item, row in selected]
        with self._span("program", "library"):
            prepared = kernel.load_library("prepare", entries, **({"timeout": budget.remaining()} if budget else {}))
        rejected = None
        if prepared["status"] == "ok" and test is not None:
            try:
                rejected = test(kernel)
            except KernelDied:
                raise
            except (OSError, ValueError, RuntimeError) as error:
                rejected = str(error)
        with self._admission_lock, self._condition:
            cancelled = (self._closing or self._pause or self.kernel is not kernel
                         or self._activation_interrupt != interrupt or not can_switch())
            if not cancelled and prepared["status"] == "ok" and rejected is None and publish is not None:
                try:
                    selected = [(selected[0][0], publish())]
                except (OSError, ValueError, RuntimeError) as error:
                    rejected = str(error)
        if prepared["status"] != "ok" or cancelled or rejected or not commit:
            if prepared["status"] == "ok" and self.kernel is kernel:
                kernel.load_library("discard")
            if prepared["status"] == "ok" and not cancelled and not rejected:
                return {"status": "admitted"}
            self.trace.emit("library", action="load_failed", status="cancelled" if cancelled else "error",
                            error=rejected or prepared.get("error"), revisions={item.key: item.revision for item, _ in selected})
            if cancelled or rejected:
                return {"status": "cancelled" if cancelled else "error", "error": rejected}
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
            return {"status": "error", "error": prepared.get("error")}
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
        return {"status": "activated"}

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
                **({"verification": row["proof"], "admitted_by": admitted_by(row)} if row.get("proof") else {})}

    def _startup_holdings(self):
        from harness.runtime.learning import active

        situations = self._situations()
        rows = [{"section": item.key.split("/", 1)[0], "name": Path(item.key).stem,
                 "summary": row.get("summary"), "passed": bool(row.get("proof")), "admitted_by": admitted_by(row)}
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
        closes the conversation meanwhile, Interrupted when they end the turn."""
        self._set_status(status, **detail)
        began = time.perf_counter()
        with self._condition:
            while not self._closing and not self._interrupt and not ready():
                self._condition.wait()
            closing, interrupted = self._closing, self._interrupt
        self._waited += time.perf_counter() - began
        if closing:
            raise Closed()
        if interrupted:
            raise Interrupted()
        self._set_status(RUNNING)

    def _take_inbox(self) -> list[str]:
        with self._condition:
            pending, self._inbox = self._inbox, []
        return pending

    def _checkpoint(self) -> None:
        """Between steps: stop when closing, wait while paused."""
        with self._condition:
            closing, interrupted, paused = self._closing, self._interrupt, self._pause
        if closing:
            raise Closed()
        if interrupted:
            raise Interrupted()
        if paused:
            self._wait(PAUSED, lambda: not self._pause or bool(self._inbox))
            with self._condition:
                self._pause = False
                kernel = self.kernel
            if kernel is not None:
                # (A message ends the pause as Continue does: the units may act again.)
                kernel.resume()
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

    def _woken(self) -> bool:
        """Whether something reached the model that starts a turn: a message, the end of a
        unit (one that was cancelled is told with the next turn, it starts none), an event
        it has not been told."""
        return (bool(self._inbox) or self._run_end is not None
                or any(item["status"] != "cancelled" for item in self._unit_news)
                or any(identifier not in self._reported_events for identifier in self._pending_events))

    def _idle(self, reason: str) -> None:
        """Between turns: the conversation waits, IDLE with the reason its last turn ended
        for, with everything it has (messages, the kernel and its units, rules, facts, the
        environment) until something reaches the model. Closed when the user or the host
        ends the conversation meanwhile."""
        self.waiting_since = time.time()
        # No turn runs: the next one has its whole time.
        self._turn_began = None
        try:
            self._set_status(IDLE, reason=reason)
            with self._condition:
                while not self._closing and not self._woken():
                    self._condition.wait()
                # (An interrupt asked for when the turn was over ends nothing.)
                closing, self._interrupt = self._closing, False
            if closing:
                raise Closed()
            self._set_status(RUNNING)
        finally:
            self.waiting_since = None

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
        """Add a user message to the history."""
        self.messages.append({"role": "user", "content": content})

    def _say(self, parts) -> None:
        """Tell the model `parts` with its next call: in the user message that ends the
        history, or as a new one after a reply."""
        if self.messages and self.messages[-1]["role"] == "user":
            self._extend_request(parts)
        else:
            self._tell(parts)

    def _tree_told(self) -> str:
        """What this turn is told of the tree of reflexes: what changed in it since the
        model was last told (runtime/reactive/tree.py told)."""
        nodes = getattr(self, "_reflex_nodes", {})
        text = tree_told(nodes, getattr(self, "_reflex_told", {}))
        self._reflex_told = dict(nodes)
        return text

    def _compact_if_due(self, loop) -> None:
        """Compaction: when the context the model's last call read has reached
        runtime.compact_at_tokens, the model writes a summary of the conversation
        (decisions.COMPACT), which then stands in the first message in place of every
        message before the recent ones (messages.recent_start). Interactive: the summary is
        followed by everything the user said (they hold the task). The system prompt, the
        kernel, the library, the tree of reflexes and the running units are as they were;
        what a turn is told of the tree and of what was learned is told anew."""
        import re
        from copy import deepcopy

        limit, messages = self.config.runtime.get("compact_at_tokens"), self.messages
        if (not limit or self._context_tokens < int(limit) or len(messages) <= 3
                or loop.malformed_from is not None):
            return
        tail = messages[recent_start(messages, decisions.KEEP_MIN_TOKENS, decisions.KEEP_MIN_MESSAGES,
                                     decisions.KEEP_MAX_TOKENS):]
        request = deepcopy(messages) if self._images else text_only(deepcopy(messages))
        ask = {"type": "input_text", "text": decisions.COMPACT}
        if request[-1]["role"] == "user":
            content = request[-1]["content"]
            request[-1]["content"] = [*([{"type": "input_text", "text": content}] if isinstance(content, str)
                                        else content), ask]
        else:
            request.append({"role": "user", "content": [ask]})
        before, tokens = len(messages), self._context_tokens
        reply = self._ask_role("compaction", self.chat, self.config.system_prompt, request)
        found = re.search(r"<summary>(.*?)(?:</summary>|$)", reply.text, re.S)
        text = (found.group(1) if found else "").strip()
        if not text:
            self._compact_failures += 1
            self.trace.emit("compaction", action="failed", tokens=tokens, attempts=self._compact_failures)
            if self._compact_failures >= 3:
                raise RuntimeError("The conversation could not be compacted: the model gave no summary")
            return
        if self.interactive and self._said:
            text += "\n\nThe user's messages so far, oldest first:\n" + "\n".join(
                f"{number}. {said}" for number, said in enumerate(self._said, 1))
        with self._condition:
            first = dict(messages[0])
            content = first["content"]
            first["content"] = [
                *([{"type": "input_text", "text": content}] if isinstance(content, str)
                  else [part for part in content if not part.get("summary")]),
                {"type": "input_text", "text": decisions.COMPACTED.format(summary=text), "summary": True}]
            messages[:] = [first, *tail]
            # The next request's record replaces every message the trace has (rebuild_messages).
            self._replaces, self._logged = self._replaces + self._logged, 0
            self._context_tokens, self._compact_failures = 0, 0
            self._reflex_told, self._learning_told = {}, None
        self.trace.emit("compaction", action="done", tokens=tokens, messages_before=before, messages=len(messages),
                        summary=text)
        self._save()

    def seconds_left(self) -> float:
        """What the turn has left of its wall time (max_wall_seconds): the time it ran, less
        the time it waited for the user, counts; the whole budget before it starts."""
        began = self._turn_began
        ran = time.perf_counter() - began - self._waited if began is not None else 0.0
        return float(self.config.max_wall_seconds) - ran

    def _cell_timeout(self, *, policy=False) -> float:
        """The program's declared deadline, bounded by the turn."""
        seconds = self.seconds_left()
        configured = self.config.runtime.get("cell_timeout_seconds")
        if configured is not None and not policy:
            seconds = min(seconds, float(configured))
        return max(0.01, seconds)

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
        """Run the conversation to its end and return its summary (the status of its last
        turn, evaluator outcome, model calls, tokens, cost, times), also written with the
        trace and manifest under the directory at every turn's end. An error ends the turn
        (before the first one: the conversation) with status "error" instead of raising."""
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
            if self.profile.get("tells"):
                # The worker tells what happens by itself: it is given where (inbound.py).
                from harness.runtime.task.inbound import Inbound

                self._inbound = Inbound(self)
                env.call("tell_to", episode_id=self.episode, url=self._inbound.url, token=self._inbound.token)
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
                scope = f"\nThis isolated workspace exposes only these operations: {operations}.\n"
                config.system_prompt += scope
                config.base_prompt += scope
                self.kernel = Kernel(DEFAULT_BOOTSTRAP, {}, managed=self._managed_dispatcher,
                                     managed_launcher=self._managed_workspace.program_command,
                                     log_path=directory / "kernel.log", start_timeout=30,
                                     on_span=self._kernel_span)
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
                    # The model looks itself (look, watch) unless the configuration declares
                    # a standing watch (runtime.cameras).
                    **({} if self._standing else {"views": {"mode": "demand", "cameras": list(told["cameras"])}}),
                    **({"host_controls": sorted(env.host_controls), "timeout_seconds": env.timeout}
                       if getattr(env, "approval_key", None) and env.host_controls else {}),
                    "skills": skills,
                    **kernel_services, **image_clients,
                    "memory": self._recall_library,
                    # The facts an earlier process of this conversation kept.
                    **({"facts": self._facts} if self._facts else {}),
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
                    # What the environment gives to act with, where programs can read it (core/worker.py).
                    **({"references": list(self.profile["references"])} if self.profile.get("references") else {}),
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
            if self._managed_workspace is not None:
                # A managed workspace's programs reach only its listed operations: its views
                # come with every turn, as before.
                self._standing = True
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
            if self._standing:
                first = image_parts(observation.images, self.cameras)
            else:
                # Text only: the views are named, and the model looks when it needs one.
                first = []
                if self.cameras:
                    opening += (f"Views of this environment: {', '.join(self.cameras)}. None is shown until a "
                                "program looks: look().\n")
            if self.profile.get("references"):
                opening += ("What this environment gives you to act with, its documentation and source, is in these "
                            "folders, which a program can read: " + ", ".join(map(str, self.profile["references"])) + "\n")
            self.messages = [{"role": "user", "content": [
                {"type": "input_text",
                 "text": opening + f"{told['state_label']}: "
                         f"{state_text(observation.state, embodiment, self._steps_shown())}"},
                *first]}]
            if self._restore is not None:
                self._continue(self._restore, f"{told['state_label']}: "
                               f"{state_text(observation.state, embodiment, self._steps_shown())}")
                self._idle("resumed")
            while True:
                reason = self._turn(skills, told)
                if not self.interactive or self.kernel.process.poll() is not None:
                    # Nobody is there for another turn, or the kernel died with what it held.
                    break
                self._turn_result(reason, open=True)
                self._idle(reason)
            if reason == "answer":
                # The benchmark's convention at the end of an episode that was answered.
                self.kernel.cancel()
                _wrap_up(self.kernel, trace)
        except Closed:
            # Closed by the user or the host: the benchmark's convention ends it. Between
            # turns the summary keeps how the last turn ended; a turn that was cut short
            # (or a conversation that had none) is "closed".
            if self._turn_began is not None or not self._turns:
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

    def _continue(self, kept: dict, state: str) -> None:
        """Go on with what an earlier process kept of this conversation (saved()): its
        messages, what the user said, its turns and the model's spending so far (its facts
        are in the new kernel already). What died with that process (the namespace, the
        rules, the units that ran) is a note the model reads with its next prompt, with
        the state as it is now; it starts no turn."""
        summary = self.summary
        self.messages = list(kept["messages"])
        self._said = [str(said) for said in kept.get("said") or self._said]
        self._turns = int(kept.get("turns") or 0)
        self._replied_at = kept.get("replied")
        spent = kept.get("summary") or {}
        for key, value in spent.items():
            if key in summary and type(value) in (int, float):
                summary[key] = value
        summary["decisions"] = dict(spent.get("decisions") or {})
        if isinstance(spent.get("status"), str):
            # (How its last turn ended, until its next one ends.)
            summary["status"] = spent["status"]
        self._logged = len(self.messages)
        units = [str(unit) for unit in kept.get("units") or ()]
        self._say([{"type": "input_text", "text": decisions.CONTINUED.format(
            units=": " + "; ".join(units) if units else "") + "\n" + state}])
        self.trace.emit("resumed", messages=len(kept["messages"]), facts=sorted(self._facts), units=units)

    def _save(self) -> None:
        """Write what continues this conversation in another process (CONVERSATION_FILE), at
        every call of the model and every turn's end: with a user or without one (a run
        nobody talks to is continued with a message as well). A sub-agent lives and ends
        with the process of the agent that started it."""
        if self.parent is not None:
            return
        with self._condition:
            kept = json.dumps({
                "schema_version": 1, "messages": self.messages, "said": self._said, "facts": self._facts,
                "units": [unit_text(identifier, unit, printed=False) for identifier, unit in self._units.items()],
                "turns": self._turns, "replied": self._replied_at, "summary": self.summary}, ensure_ascii=False)
        atomic_write(self.directory / CONVERSATION_FILE, kept)

    def _turn(self, skills, told) -> str:
        """One turn, from what started it to how it ended (a key of decisions.TURN_ENDS,
        whose status the summary takes). Its limits are its own: the model's calls and the
        wall time begin anew. An error ends the turn; so does cancel(). Only an answer
        leaves the model's units running: after any other end they are cancelled, so that
        nothing starts a turn until the user says how to go on."""
        summary, trace = self.summary, self.trace
        summary.pop("error", None)
        with self._condition:
            self._turns += 1
            self._turn_began, self._waited = time.perf_counter(), 0.0
            self._calls_before = summary["model_calls"] + self.agents_usage["model_calls"]
            self._iterations = 0
        try:
            reason = self._loop(skills, told)
        except Interrupted:
            trace.emit("interrupted")
            reason = "interrupted"
        except Closed:
            raise
        except Exception as error:
            summary["error"] = f"{type(error).__name__}: {error}"
            trace.emit("error", message=summary["error"])
            reason = "error"
        with self._condition:
            self._interrupt = False
            if reason in decisions.TURN_STOPS:
                # What reached the model in this turn and met no call of it is in its
                # history: it starts no turn by itself, the user's next message does.
                self._include_escalations()
                self._add_user_messages()
        summary["status"] = decisions.TURN_ENDS[reason]
        if reason != "answer":
            self.kernel.cancel()
        return reason

    def _turn_result(self, reason: str, open: bool = False) -> None:
        """The end of a turn: learning reflects on it, the summary is written (`open`: the
        conversation goes on, which the file says, so that nothing takes it for ended),
        and the turn's result record says why it ended, in which session, the model's
        calls in it (its sub-agents' counted), the conversation's cost so far and the
        turn's seconds."""
        summary = self.summary
        began = self._turn_began
        if self.kernel is not None and began is not None:
            self._reflect_learning()
        self._write_summary(open)
        self.trace.emit(
            "turn_result", reason=reason, turn=self._turns, session=(self.identity or {}).get("session"),
            model_calls=summary["model_calls"] + self.agents_usage["model_calls"] - self._calls_before,
            cost_usd=round(summary["cost_usd"] + self.agents_usage["cost_usd"], 6),
            seconds=round(time.perf_counter() - began - self._waited, 3) if began is not None else 0.0,
            **({"result": self.result} if reason == "answer" and self.result is not None else {}),
            **({"error": summary["error"]} if summary.get("error") else {}))

    def _write_summary(self, open: bool = False) -> None:
        """Write the summary as it stands, and what continues the conversation; its
        spending is charged to the agent that started it."""
        summary = self.summary
        summary["wall_seconds"] = time.perf_counter() - self.started
        if self.agents_usage["started"] or self.agents_usage["model_calls"]:
            summary["agents"] = {**self.agents_usage, "cost_usd": round(self.agents_usage["cost_usd"], 6)}
        write_json(self.directory / "summary.json", {**summary, "open": True} if open else summary)
        self._save()
        self.charge_up()

    def _loop(self, skills, told) -> str:
        try:
            return self._steps(skills, told)
        finally:
            with self._condition:
                if self._request is not None:
                    self._settle(self._request, "unused", "the turn ended first")
                self._request = None

    def _steps(self, skills, told) -> str:
        """The loop of one turn: the model is told what its units ended with, asked on the
        trigger of what happened last (self.reason), and its reply's output is done
        (OUTPUTS), until an output, a unit, a limit or the environment ends the turn: how
        it ended (decisions.TURN_ENDS). No program holds the loop."""
        config, summary, runtime = self.config, self.summary, self.config.runtime
        direct = runtime.get("mode", "program") == "direct"
        post_calls = runtime.get("post_policy_calls")
        # What the outputs share in this loop. Direct control: the agent's action vocabulary
        # turns each <action> into a program (runtime.actions, "module:function").
        # malformed_from: the first reply without a valid block since the last valid one (such
        # exchanges leave the history once a valid reply comes). nudged: replies in a row sent
        # back for only announcing an action (ANNOUNCED); empties: empty replies in a row asked
        # again (EMPTY_RETRIES). post_calls: the model's calls after the learned policy's first
        # run are bounded (finishing with its own tools cost half the spend for no score), from
        # self._post_from on; then the policy runs on.
        loop = SimpleNamespace(skills=skills, told=told, direct=direct, kinds=DIRECT_KINDS if direct else KINDS,
                               actions=_object(runtime["actions"]) if direct else None,
                               malformed_from=None, nudged=0, empties=0,
                               post_calls=None if post_calls is None else int(post_calls))
        # What the first call of the turn is made for: the instruction, else what started
        # the turn (a message or an event comes first: decisions.TRIGGERS).
        self.reason = "start" if self._turns == 1 else "unit_end"
        while True:
            self._checkpoint()
            self._load_due_skills()
            with self._condition:
                selected = tuple(self._activation_queue.values())
            self._activate_library(selected)
            self._trial_at_boundary()
            self._checkpoint()
            if ended := self._ended_by_unit(loop):
                return ended
            self._tell_news(loop)
            if ended := self._ended_by_unit(loop):
                return ended
            self._compact_if_due(loop)
            with self._condition:
                if self._iterations >= config.max_model_calls:
                    return "budget"
                policy = (self._post_from is not None and loop.post_calls is not None
                          and summary["model_calls"] - self._post_from >= loop.post_calls and not self._inbox)
                if self.seconds_left() <= 0:
                    return "wall_time"
                if not self._within_budget():
                    return "cost"
                if not policy:
                    current = self._think()
                    self._condition.wait_for(lambda: current.back(0) or self._closing or self._interrupt)
                    if self._closing:
                        raise Closed()
                    if self._interrupt:
                        raise Interrupted()
                    self._request = None
                    if current.cancelled:
                        # Set aside (a message, an event, a unit's end came first), or out of time.
                        if isinstance(current.error, ThoughtCancelled) and "deadline" in str(current.error):
                            raise current.error
                        continue
                    reply = current.wait()
                    self._replied_at = time.time()
                    self._context_tokens = (
                        int(reply.usage.get("input_tokens") or 0) + int(reply.usage.get("output_tokens") or 0)
                        or (sum(row["chars"] for row in context_summary(current.messages, current.system))
                            + len(reply.text)) // 4)
                    self._settle(current, "used")
                    self._pending_events.clear()
                    loop.revision = current.revision
                    loop.call, loop.thought = current.call, current.id
            if policy:
                return self._policy_to_end()
            output, parsed = self._output(reply, loop)
            if ended := getattr(self, decisions.OUTPUTS[output])(reply, parsed, loop):
                return ended

    def _ended_by_unit(self, loop) -> str | None:
        """How a unit ended the turn, if one did: the episode ended in it, or it called
        finish() (which a message or an unresolved event for the model overrides)."""
        with self._condition:
            end, self._run_end = self._run_end, None
            if end is None:
                return None
            if end == "episode_ended":
                return "episode_ended"
            if self._inbox or self._pending_events:
                return None
        return self._out_answer(None, SimpleNamespace(body=end[1], source="program"), loop)

    def _output(self, reply, loop) -> tuple[str, object]:
        """What a reply does (a key of OUTPUTS) and its parsed block (or the error that kept
        it from parsing); the reply joins the trace and the history."""
        trace, messages = self.trace, self.messages
        if (not reply.text.strip() and reply.usage.get("finish_reason") != "length"
                and loop.empties < decisions.EMPTY_RETRIES):
            return "empty", None
        loop.empties = 0
        # An empty reply is a format error after EMPTY_RETRIES, never an answer.
        plain = (reply.usage.get("finish_reason") != "length"
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
            presentation = {"kind": parsed.kind, "thought": (parsed.thought or "").strip(), "body": parsed.body}
            output = {"python": "program", "action": "program"}.get(parsed.kind, parsed.kind)
        except (ProtocolError, ValueError) as failed:
            parsed, output = failed, "message" if plain else "invalid"
            if announced:
                parsed = ProtocolError("The reply said what it would do, without a block")
            presentation = ({"kind": "message", "body": reply.text.strip(), "announced": True} if announced else
                            {"kind": "message" if plain else "invalid", "body": reply.text.strip() if plain else ""})
        self._record_reply(reply, loop.call + 1, thought=loop.thought, presentation=presentation)
        messages.append({"role": "assistant", "content": reply.text})
        if output == "invalid":
            if loop.malformed_from is None:
                loop.malformed_from = len(messages) - 1
        elif loop.malformed_from is not None:
            dropped = len(messages) - 1 - loop.malformed_from
            del messages[loop.malformed_from:-1]
            self._logged -= dropped
            trace.emit("malformed_dropped", messages=dropped)
            loop.malformed_from = None
        return output, parsed

    # The outputs of a reply (OUTPUTS): what one returns is how the turn ended (None: it goes on).

    def _out_empty(self, reply, parsed, loop):
        """Reasoning only: asked again at once, with no format error to show."""
        loop.empties += 1
        self.summary["empty_replies"] = self.summary.get("empty_replies", 0) + 1
        self.trace.emit("empty_reply", call=self.summary["model_calls"], usage=reply.usage, seconds=reply.seconds,
                        **({"reasoning": reply.reasoning} if reply.reasoning else {}))
        self.reason = "empty"

    def _current_output(self, loop):
        """Whether nothing reached the model since the call whose reply is being done."""
        return not self._inbox and not self._pending_events and loop.revision == self._revision

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
            blocks = "<action> or <wait>" if loop.direct else "<python>, <verify> or <wait>"
            text = (f"Format error: {parsed}. Nothing ran. Reply with the {blocks} block itself, starting with its "
                    "opening tag, or with your answer in plain text.")
        self._tell(text)
        self.trace.emit("protocol_error", message=str(parsed), truncated=reply.usage.get("finish_reason") == "length",
                        **({"announced": True} if text.startswith("Nothing ran") else {}))
        self.reason = "format"

    def _out_answer(self, reply, parsed, loop):
        """The model's answer: a reply that is text, the reply's <finish>, or a program's
        finish() (source "program"), all the same. The turn ends with it; the conversation
        and the units that run go on."""
        source = getattr(parsed, "source", None)
        if source is None:
            with self._condition:
                if not self._current_output(loop):
                    return None
        # (A reply without a block parsed to no block: its text is the answer.)
        text = reply.text if isinstance(parsed, Exception) else parsed.body
        from harness.runtime.learning.active import is_active

        if is_active(self.config.runtime) and self._within_budget():
            before = getattr(self, "_library_version", None)
            self._trial_at_boundary()
            if getattr(self, "_library_version", None) != before:
                self._tell("The host activated your proposal. Use the new revision in a brief practice program, "
                           "check what it does, then answer with the result.")
                self.reason = "program_end"
                return None
        self.result = text.strip()
        if isinstance(parsed, Exception):
            # (The reply is already recorded by _output: reply_call names it, so that
            # transcript consumers do not show it twice.)
            self.trace.emit("agent_message", text=self.result, reply_call=loop.call + 1)
        else:
            self.trace.emit("finish", text=text, **({"source": source} if source else {}))
        return "answer"

    def _out_wait(self, reply, parsed, loop):
        """The model waits by choice: no call is made until the first of a unit it started
        ended, a message or an event reached it, or its time (the block's seconds, at most
        the run's longest wait, which a wait without a time gets). It is told which."""
        asked = wait_seconds(parsed.body)
        limit = max(0.0, min(asked if asked is not None else self._longest_wait, self._longest_wait,
                             self.seconds_left()))
        began = time.monotonic()

        def reached():
            return ("unit" if self._unit_news or self._run_end is not None else "message" if self._inbox
                    else "event" if self._pending_events else None)

        with self._condition:
            self.trace.emit("wait", seconds=round(limit, 3), **({"asked": asked} if asked is not None else {}))
            self._condition.wait_for(lambda: reached() or self._closing or self._pause or self._interrupt,
                                     timeout=limit)
            why = reached() or ("time" if time.monotonic() - began >= limit else "pause")
            waited = time.monotonic() - began
            self.trace.emit("wait_end", why=why, seconds=round(waited, 3))
            running = [unit_text(identifier, unit) for identifier, unit in self._units.items()]
            # (Last in the message when nothing else is told: the bare end of a wait.)
            self._say([{"type": "input_text", "text": decisions.WAIT_ENDED.format(
                seconds=waited, why=decisions.WAIT_ENDS.get(why, "the user paused"))
                + ("\nUnits running: " + latest(running) if running else "")
                + "\n" + self._tree_told()}])
            self.reason = "wait_end"

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
                    *(image_parts(view["images"], self.cameras) if self._standing else [])])
        self.reason = "verify"

    def _verify(self, claim, cameras=None, request=None):
        cameras = cameras if cameras is not None else self.cameras
        with self._span("env", "observe"):
            view = self.env.call("observe", episode_id=self.episode, cameras=cameras)
        if self.verifier is None:
            answer = "Verifier disabled in this configuration."
        elif self._standing:
            content = [{"type": "input_text", "text": f"Claim: {claim}"},
                       *image_parts(view["images"], cameras)]
            reply = self._ask_role("verifier", self.verifier,
                                   EMBODIMENT_TEXT[self.config.embodiment]["verifier"],
                                   [{"role": "user", "content": content}], request)
            answer = reply.text.strip()
        else:
            # The verifier judges on what the model itself can get: the state, the structure
            # the environment reports as text, and its views (a verifier that reads images).
            told = EMBODIMENT_TEXT[self.config.embodiment]
            structure = (request or {}).get("evidence")
            if structure is None and request is None:
                structure = self._evidence()
            text = (f"Claim: {claim}\n{told['state_label']}: "
                    f"{state_text(view['state'], self.config.embodiment, self._steps_shown())}"
                    + (f"\nWhat the environment reports as text:\n{str(structure)[:12000]}" if structure else ""))
            images = image_parts(view["images"], cameras) if {**self.config.main, **self.config.verifier}.get(
                "images") is not False else []
            reply = self._ask_role("verifier", self.verifier, told["verifier"] + VERIFIER_EVIDENCE,
                                   [{"role": "user", "content": [{"type": "input_text", "text": text}, *images]}],
                                   request)
            answer = reply.text.strip()
        self.trace.emit("verify", claim=claim, answer=answer)
        return answer, view

    def _evidence(self) -> str:
        """What the environment reports as text for a claim (its session's __evidence__: a
        window's elements, a page's text), read between programs; empty when it has none."""
        kernel = self.kernel
        if kernel is None:
            return ""
        try:
            result = kernel.run("__evidence__()", timeout=30)
        except Exception:
            return ""
        return (result.get("stdout") or "").strip() if result.get("status") == "ok" else ""

    def _ask_role(self, role, chat, system, messages, request=None):
        request = request or {}
        origin = request.get("id")
        with self._condition:
            if origin in self._cancelled_origins or request.get("revision", self._revision) != self._revision:
                raise ThoughtCancelled("The calling entry stopped")
            if self.config.max_cost_usd is not None and (
                    self.summary["cost_usd"] + self.agents_usage["cost_usd"] >= self.config.max_cost_usd):
                raise RuntimeError("The session model cost budget is exhausted")
            thought = Thought(role, decisions.REQUESTS[role], chat, system, messages,
                              timeout=max(0, self.seconds_left()), revision=self._revision, origin=origin,
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

    def _policy_to_end(self) -> str:
        """The model's calls after the learned policy's run are used up: it runs on to the
        end, which ends the turn (how: decisions.TURN_ENDS)."""
        trace, summary, kernel = self.trace, self.summary, self.kernel
        with self._span("program", "policy to the end"):
            result = kernel.run("__policy_to_end__()", timeout=self._cell_timeout(policy=True))
        trace.emit("policy_to_end", status=result["status"], error=result.get("error"))
        _cell_usage(summary, result)
        if result.get("strategy"):
            summary["strategy"] = result["strategy"]
        if result["status"] == "episode_ended":
            return "episode_ended"
        trace.emit("finish", text="the model's calls after the policy's run were used up", source="harness")
        return "answer"

    def _out_program(self, reply, parsed, loop):
        """Start the reply's program as a unit of the model. The turn comes back at once:
        with the program's result when it was over within the grace, else with its handle;
        the result then reaches the model when the unit ends (_unit_arrived)."""
        trace, summary, kernel = self.trace, self.summary, self.kernel
        program = parsed.program
        if not self._approved(program):
            return None
        self._load_due_skills()
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
                           else "A user message came before this program ran, so nothing ran." if self._inbox
                           else "An event reached you before this program ran, so nothing ran.")
                self.reason = "user"
                return None
            summary["cells"] += 1
            number, span = summary["cells"], uuid.uuid4().hex[:12]
            started = {"number": number, "code": program, "action": parsed.body if loop.direct else None,
                       "span": span, "unit": None}
            trace.emit("span_start", id=span, lane="program", name=f"program {number}", parent=None)

        def announce(cell):
            with self._condition:
                self._programs[cell] = started

        try:
            result = kernel.start(program, self._grace, timeout=self._cell_timeout(), name=f"program {number}",
                                  announce=announce)
        except KernelDied as error:
            trace.emit("span_end", id=span, error=f"KernelDied: {error}"[:300])
            trace.emit("kernel_died", message=str(error))
            if self.seconds_left() > 0:
                raise
            return "wall_time"
        if result["status"] != "running":
            self._unit_arrived(result)
            return None
        with self._condition:
            if started in self._programs.values():
                # (Else it ended meanwhile: its result is what the model is told.)
                self._tell(decisions.RUNNING.format(number=number, unit=result["unit"])
                           + f"\nModel calls left: {self.config.max_model_calls - self._iterations}")
                self.reason = "program_running"
        return None

    def _unit_arrived(self, result: dict) -> None:
        """A unit of the model ended: its result came as the reply to its program, or as the
        kernel's unit_end message (any thread). It is recorded now and told to the model
        with its next call (_tell_news); an end that is an event (an error, an unhandled
        event, the episode's end, finish()) sets a call in flight aside."""
        trace, summary = self.trace, self.summary
        result = {key: value for key, value in result.items() if key not in ("op", "time")}
        number = result.get("cell")
        with self._condition:
            program = self._programs.pop(number, None) if number is not None else None
            recorded = {key: value for key, value in result.items() if key not in ("attachments", "report", "looks")}
            if program is not None:
                if result.get("report"):
                    recorded["report"] = {"text": result["report"].get("text", ""),
                                          "images": sorted(result["report"].get("images") or {})}
                if result.get("looks"):
                    recorded["looks"] = result["looks"]
                trace.emit("cell", number=program["number"], code=program["code"], action=program["action"],
                           result=recorded, attachments=len(result.get("attachments", [])))
                trace.emit("span_end", id=program["span"], status=result["status"])
                summary["kernel_seconds"] += float(result.get("seconds") or 0.0)
                result["program"] = program
            elif number is None:
                trace.emit("unit_end", **recorded, attachments=len(result.get("attachments", [])))
                if result.get("quiet"):
                    # The tree of reflexes started it and answers its end itself
                    # (runtime/reactive/tree.py): recorded, and nothing for the model.
                    _cell_usage(summary, result)
                    return
            else:
                # A program the host ran itself (wrap-up, a library load): nothing for the model.
                return
            _cell_usage(summary, result)
            if result.get("strategy"):
                summary["strategy"] = result["strategy"]
                if self._post_from is None and result["strategy"].get("policy_ran"):
                    self._post_from = summary["model_calls"]
            status = result["status"]
            if status == "episode_ended":
                self._run_end = "episode_ended"
            elif status == "finished" and self._run_end is None:
                self._run_end = ("finished", str(result.get("finish") or ""))
            self._unit_news.append(result)
            if status not in ("ok", "cancelled") and not result.get("handled"):
                self._revision += 1
                self._preempt("a unit ended with an event")
            self._condition.notify_all()
        self.charge_up()

    def _tell_news(self, loop) -> None:
        """Tell the model what its units ended with since its last call: each program's
        feedback (status, output, events, state), each other unit's end, what they showed
        and looked at, the units still running and the calls left."""
        with self._condition:
            news, self._unit_news = self._unit_news, []
        if not news:
            return
        config, trace, embodiment, cameras = self.config, self.trace, self.config.embodiment, self.cameras
        order = ("unit_end", "program_end", "escalation", "error")
        content, looks, outlines, reason, taken, state, programs = [], [], {}, "unit_end", None, None, 0
        for result in news:
            program, status = result.get("program"), result["status"]
            if program is not None:
                programs += 1
                if self.interactive:
                    self._stuck(program["code"], result)
                    taken = taken or _taken_over(result)
                why = {"escalated": "escalation", "error": "error"}.get(status, "program_end")
                text = cell_feedback(result, program["number"], self.profile.get("control_hz"), embodiment,
                                     self._steps_shown())
                if why == "program_end":
                    text += decisions.PROGRAM_ENDED
                state = result.get("state") or state
            else:
                why = "escalation" if status in ("error", "escalated") and not result.get("handled") else "unit_end"
                text = unit_feedback(result)
            reason = max(reason, why, key=order.index)
            content.append({"type": "input_text", "text": text, "result": True})
            for item in result.get("attachments", [])[:6]:
                content.append({"type": "input_text", "text": f"show(): {item['caption']}"})
                content.append({"type": "input_image", "image_url": item["image_url"], "detail": "auto"})
            # A skill's report (the tracked scene) may outline objects in the same views.
            outlined = (result.get("report") or {}).get("images") or {}
            outlines.update(outlined)
            seen = [{**item, "image_url": outlined[item["camera"]]}
                    if item["camera"] in outlined and not item.get("region") else item
                    for item in result.get("looks") or ()]
            if seen and not self._standing:
                trace.emit("views", action="looked", program=(program or {}).get("number"), unit=result.get("unit"),
                           views=[{key: item[key] for key in ("camera", "region", "pin") if key in item}
                                  for item in seen])
            looks += seen
        self.reason = reason
        with self._condition:
            calls_left = config.max_model_calls - self._iterations
            running = [unit_text(identifier, unit) for identifier, unit in self._units.items()]
            tree = self._tree_told()
        note = ""
        if self._post_from is not None and loop.post_calls:
            calls_left = min(calls_left, loop.post_calls - (self.summary["model_calls"] - self._post_from))
            note = ("After these calls the learned policy runs on by itself to the end of the episode.\n"
                    if calls_left > 0 else "")
        # What was learned so far, where this run learns: whole when it changed, else its first line.
        head, _, body = self._learning_report().strip().partition("\n")
        learned = (head + ("\n" + body if body != self._learning_told else " as you were last told") + "\n") if head else ""
        self._learning_told = body
        content.append({"type": "input_text", "text": ("Units running: " + latest(running) + "\n" if running else "")
                        + (tree + "\n" if tree else "") + learned + note + f"Model calls left: {calls_left}"})
        if not taken and reason in ("error", "escalation"):
            self._reflect_learning()
        if taken is not None:
            # The user brought a window of theirs to the front: the computer is theirs
            # until they hand it back, as after Take over.
            trace.emit("user_took_over", window=taken.get("front"))
            self.pause()
            self._checkpoint()
        if self._standing:
            if programs:
                with self._span("env", "observe"):
                    view = self.env.call("observe", episode_id=self.episode, cameras=cameras)
                content.extend(image_parts({**view["images"], **outlines}, cameras))
                state = view["state"]
        else:
            # Only what the units looked at (look, a standing watch of the model's own).
            with self._condition:
                self._view_pins |= {item["pin"] for item in looks if item.get("pin")}
            content.extend(view_parts(looks) if self._images else self._described(looks))
        with self._condition:
            self._say(content)
            if (state or {}).get("ended"):
                self._run_end = "episode_ended"

    def _think(self):
        """Queue the model's next call with its immutable input, on the trigger of what is
        pending (a message, an unresolved event), else of what happened last (self.reason)."""
        triggers = decisions.TRIGGERS
        trigger = next((name for name, check in triggers.items() if check and getattr(self, check)()), None)
        if trigger is None:
            trigger = self.reason
            if trigger not in triggers:
                raise ValueError(f"No model trigger for {trigger!r}")
        self._include_escalations()
        self._add_user_messages()
        config, summary, messages = self.config, self.summary, self.messages
        if self._standing:
            prune_images(messages, int(config.runtime.get("keep_images", 2)))
        else:
            prune_views(messages, self._view_keep, self._view_pins)
        idle = time.time() - self._replied_at if self._replied_at else 0.0
        after = float(config.runtime.get("clear_results_after_minutes") or 0) * 60
        if after and idle >= after:
            # The provider's cache of the conversation is cold: this call reads all of it anew.
            cleared = clear_results(messages, decisions.KEPT_RESULTS, decisions.CLEARED)
            if cleared:
                self._replaces, self._logged = self._replaces + self._logged, 0
                self.trace.emit("results_cleared", results=cleared, idle_seconds=round(idle))
        request = messages if self._images else text_only(messages)
        call = summary["model_calls"]
        from copy import deepcopy
        history = deepcopy(messages)
        system = config.system_prompt
        thought = Thought("main", trigger, self.chat, system, request,
                          timeout=max(0, self.seconds_left()), owner=self._who().get("who"),
                          revision=self._revision, call=call, invoke=self._complete)
        self.trace.emit("model_request", call=call, thought=thought.id, **decisions._model_of(thought.chat), reason=trigger,
                        total_messages=len(messages), sent_messages=len(request),
                        new_messages=history[self._logged:], context=context_summary(request, system),
                        library_version=getattr(self, "_library_version", None), revision=thought.revision,
                        events=list(self._pending_events), **self._replaced())
        self._logged = len(messages)
        summary["model_calls"] += 1
        summary["decisions"][trigger] = summary["decisions"].get(trigger, 0) + 1
        self._iterations += 1
        self._save()
        self._request = thought
        self._thoughts.submit(thought)
        return thought

    def _within_budget(self):
        """Whether the model may be called again: calls and cost left."""
        return (self._iterations < self.config.max_model_calls
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
            self._say(parts)

    def _pending_message(self):
        return bool(self._inbox)

    def _unresolved(self):
        return bool(self._pending_events)

    def _came_back(self, thought):
        from harness.runtime.decision.model import add_usage

        summary = self.summary
        key = decisions.COUNTS.get(thought.role)
        if key is not None:
            summary[key] = summary.get(key, 0) + 1
        summary["agent_seconds"] += thought.seconds
        if thought.reply is not None:
            usage = thought.reply.usage
            add_usage(summary, usage)
            if key == "vision_calls":
                summary["vision_cost_usd"] += float(usage.get("cost_usd") or 0.0)
        self.charge_up()
        if key is None and thought.outcome is not None:
            self._record_settlement(thought)

    def _replaced(self) -> dict:
        """What the next request record says of the history messages it replaces."""
        replaces, self._replaces = self._replaces, 0
        return {"replaces": replaces} if replaces else {}

    def _settle(self, thought, outcome, why=""):
        """What became of a call of the model: used, or set aside (discarded: something
        reached the model first; unused: the run ended first)."""
        if thought.outcome is not None:
            return
        thought.outcome = outcome, why
        if outcome != "used":
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
        reply = thought.reply
        if outcome != "used":
            self.trace.emit("model_preempted", thought=thought.id, call=thought.call + 1, reason=why,
                            back=reply is not None, **({"text": reply.text, "usage": reply.usage} if reply else {}))

    def _record_reply(self, reply, call, **detail):
        self.trace.emit("model_reply", call=call, text=reply.text, usage=reply.usage, response_id=reply.response_id,
                        seconds=reply.seconds, **detail, **({"reasoning": reply.reasoning} if reply.reasoning else {}))

    def _complete(self, thought):
        """The main transport."""
        from harness.runtime.decision.model import ChatModel

        chat = thought.chat
        options = {"on_text": self._streamed(thought.call + 1, stop=lambda: thought.cancelled)} if getattr(
            chat, "streams_text", False) else {}
        if isinstance(chat, ChatModel):
            options["cancellation"] = thought.cancellation
        name = decisions._model_of(chat).get("model") or str(self.config.main.get("model", "model"))
        with self._span("model", name, call=thought.call + 1,
                        thought=thought.id, role="main", reason=thought.trigger) as end:
            thought.cancellation.check()
            reply = chat.complete(thought.system, thought.messages, **options)
            end.update(output_tokens=reply.usage.get("output_tokens"))
            return reply

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
            if self._pause or self._closing or self._inbox or self._busy():
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
        """The conversation ends: end its sub-agents, close the kernel, read the evaluator's
        outcome with the token (a worker evaluates once: at the end), and give the result
        of the turn that ran (none ran when it ends between turns)."""
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
        if self.environments is not None:
            self.environments.close()
        for model in (self.chat, self.verifier):
            # A package's backend holds a process of its own (an ACP agent).
            if getattr(model, "packaged", False):
                try:
                    model.close()
                except Exception as error:
                    trace.emit("cleanup_error", message=f"model: {type(error).__name__}: {error}")
        if self._inbound is not None:
            try:
                self._inbound.close()
            except Exception as error:
                trace.emit("cleanup_error", message=f"listener: {type(error).__name__}: {error}")
        if hasattr(self, "_mcp_access"):
            try:
                self._mcp_access.close()
            except Exception as error:
                trace.emit("cleanup_error", message=f"MCP: {type(error).__name__}: {error}")
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
        table = self.config.runtime.get("library") or {}
        if self._turn_began is not None or not self._turns:
            # The turn that ran (or a conversation that had none) ends with the conversation.
            ending = summary["status"]
            self._turn_result(next((reason for reason, status in decisions.TURN_ENDS.items() if status == ending),
                                   ending))
        else:
            # Ended between turns: the last turn gave its result; the summary is closed.
            self._write_summary()
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
                learner = self._learner()
                trace.emit("library", action="used", uses=fold_uses(learner, directory))
                for entry in learner.demoted:
                    # Admitted by its own test, it kept failing in use (learner.record_uses).
                    trace.emit("library", action="demoted", **entry)
                learner.demoted.clear()
            except Exception as error:
                trace.emit("cleanup_error", message=f"library uses: {type(error).__name__}: {error}")
        if "model_transport_pending" in summary:
            write_json(directory / "summary.json", summary)
        self._set_status(ERROR if summary["status"] == "error" else FINISHED, reason=summary["status"])


# Added to a kind's verifier instructions when the model looks on demand.
VERIFIER_EVIDENCE = (" Besides any pictures, the message gives the state and what the environment reports as text "
                     "(a window's elements, a page's text): judge on all of it, and answer NO when together it "
                     "does not show enough to confirm the claim.")
# What the vision role is asked of a view, for a main model that reads no images.
VIEWER = ("You describe a view for an agent that cannot see it. Say what is shown: the windows or objects, the "
          "text and numbers exactly as written, the controls and where each is (pixel coordinates from the top "
          "left). Facts only, no advice.")


def _object(reference: str):
    """The object a "module:attribute" reference names."""
    import importlib

    module, _, attribute = reference.partition(":")
    return getattr(importlib.import_module(module), attribute)
