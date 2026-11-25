"""The translation layer: any worker as an Agent Space Protocol space.

A worker serves the worker protocol (core/worker.py: describe, reset, call) over HTTP. This
module wraps one, unchanged, in a space built on the SDK's space skeleton, which keeps the
protocol's guarantees: every action with an ID gets exactly one final outcome, an ID sent
again returns the first outcome without reaching the worker again, everything is recorded.
It runs where the worker's environment is (`python -m harness.space.translate`), beside the
worker, and the core reaches the worker only through it (harness.space.environment).

How the worker protocol maps onto the space:

  presence      `episode {task, seed}` (the capability episode) resets the worker: the runtime
                starts each conversation's episode so. A participant that observes or acts
                before any episode was started (a worker whose task is "free" needs none) is in
                the one the layer starts for it, `reset("free", 0)` (or the first of --tasks).
  observe       The structure has one thing, `environment` (type `<kind>.environment`), with
                the worker's report (`state`, its episode and step). Without forms the worker's
                `state` answers; with forms its `observe` does: `text` is the state as JSON,
                `<kind>.<camera>` a picture of that view.
  verbs         Every other method of the worker is the verb `<kind>.<method>`; the action's
                args are its arguments. `episode_id` is filled in when it is missing, and for
                `<kind>.tick` the step the action's `basis` was observed at (the current one
                without a basis), so a participant that knows nothing of the worker acts; a
                basis whose step is past is refused (stale) without reaching the worker.
  outcomes      A tick the shield passes and the worker executes is done (its envelope is the
                result); one the shield stops is refused (the envelope is the reason's data).
                A worker error ends the action by what the worker's step cursor says about it:
                the cursor where it was means nothing was executed (refused: stale for a stale
                step, forbidden for a permission, malformed for bad arguments); a cursor that
                moved on means it executed and failed (failed); a cursor the worker invalidated
                means the input may have reached the environment (unknown), as does a worker
                that does not answer. The worker's error text is the reason's text.
  score         `claim_outcome` and `outcome` become the capability episode's `score`, for the
                evaluator role only.
  events        A worker that tells (its profile says "tells") is given where to tell, here;
                what it tells becomes the event `<kind>.told`, pushed and recorded.
  roles         owner (every verb, the worker's host controls with the host's key), member
                (the verbs without the host controls: programs), evaluator (owner's verbs and
                the score), guest (looks only). With `--owner`, only that identity may take the
                owner and evaluator roles; with tokens, a token's name fixes its role.

The layer keeps its record in memory: it lives as long as the conversation that started it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import URLError

from agent_space.space import Failed, MemoryStore, Refused, Space, SqliteStore, Stopped, Uncertain
from agent_space.util import now

# Worker methods the protocol has messages for; the rest are verbs. (`observe` is a verb too, for a
# look asked with more than views: a picture of the last seconds.)
PROTOCOL_METHODS = frozenset({"state", "claim_outcome", "outcome", "tell_to"})
# Worker methods that take no episode_id.
NO_EPISODE = frozenset({"profile", "outcome"})
PROTOCOL_VERSION = 0


class WorkerError(RuntimeError):
    """An error the worker answered with; `uncertain` when the input may have reached the
    environment although the call failed (core/worker.py marks those)."""


class LocalWorker:
    """A worker in this process (`--factory`): the worker protocol called directly."""

    def __init__(self, environment, contract=None):
        from harness.core.worker import WorkerAPI

        self.api = WorkerAPI(environment, contract)
        self.environment = environment
        self.endpoint = None

    def describe(self) -> dict:
        return self.api.dispatch("describe", {})

    def reset(self, task, seed):
        from harness.core.contracts import Observation

        return Observation(**self.api.dispatch("reset", {"task": task, "seed": seed}))

    def call(self, name, /, **arguments):
        try:
            return self.api.dispatch("call", {"name": name, "arguments": arguments})
        except Exception as error:
            failure = WorkerError(f"{type(error).__name__}: {error}")
            failure.worker_error = str(failure)
            failure.uncertain = bool(getattr(error, "uncertain", False))
            raise failure from error

    def managed_call(self, name, /, *, approval_key, **arguments):
        return self.call(name, **arguments)

    def sensitive_approval(self, op, *, approval_key, **arguments):
        return self.api.dispatch("sensitive_approval", {"op": op, **arguments})

    def close(self):
        close = getattr(self.environment, "close", None)
        if callable(close):
            close()


class _Store(MemoryStore):
    """The record, which also tells the layer where each tick's outcome lands."""

    def __init__(self, on_append):
        super().__init__()
        self._on_append = on_append

    def append(self, entries):
        done = super().append(entries)
        self._on_append(done)
        return done


class _SqliteStore(SqliteStore):
    """A record kept on disk (--data), which also tells the layer where each tick's outcome
    lands: a layer started again finds every action it had not ended, and the skeleton ends
    them unknown (restarted)."""

    def __init__(self, path, on_append):
        super().__init__(path)
        self._on_append = on_append

    def append(self, entries):
        done = super().append(entries)
        self._on_append(done)
        return done


class _Args:
    """An action's context with other args: how a composed verb calls the tick's law."""

    def __init__(self, ctx, args, basis):
        self._ctx, self.args, self.basis = ctx, args, basis

    def __getattr__(self, name):
        return getattr(self._ctx, name)


class WorkerSpace:
    """One worker as a space. `worker` has describe(), reset(task, seed), call(name, **kw),
    managed_call(...) and sensitive_approval(...): core.remote.RemoteEnvironment or
    LocalWorker. `approval_key` signs the worker's host controls for the owner role."""

    def __init__(self, worker, *, tasks=(), owner=None, tokens=None, approval_key=None,
                 declarations=None, seed=0, data=None, episode=None):
        from harness.embodiments import embodiment_kind

        self.worker = worker
        self.approval_key = approval_key
        self.owner = owner
        self.tokens = dict(tokens or {})
        self.tasks = list(tasks)
        self.seed = seed
        self.pool = ThreadPoolExecutor(1, thread_name_prefix="worker")
        self.description = worker.describe()
        self.profile = worker.call("profile")
        self.kind = embodiment_kind(self.profile)
        self.declared = declarations if declarations is not None else _declarations(self.kind, self.description.get("name"))
        self.methods = [m for m in self.description.get("methods", ()) if m not in PROTOCOL_METHODS]
        self.host_controls = frozenset(self.description.get("managed_control_calls") or ())
        if approval_key and self.description.get("managed_approval"):
            # The host answers a worker that asks for approval in the middle of a tick.
            self.methods.append("sensitive_approval")
            self.host_controls |= {"sensitive_approval"}
        self.cameras = list(_cameras(self.kind))
        # An episode started elsewhere (by whoever reset the worker) is adopted, not started again.
        self.episode = episode
        self.instruction = ""
        self.step = None
        # (record sequence number, (episode, step)) from oldest to newest: what the worker's
        # cursor was when the record reached that number.
        self._steps: list[tuple[int, tuple]] = []
        self._ticks: dict[str, tuple] = {}
        self._loop = None
        self._inbound = None
        # Verbs the package declares that are made of a tick (declarations.py).
        self.composed = {name: decl for name, decl in (self.declared.get("verbs") or {}).items()
                         if isinstance(decl, dict) and "tick" in decl and name not in self.methods
                         and "tick" in self.methods}
        store = _Store(self._appended) if data is None else _SqliteStore(str(data), self._appended)
        probes = self.declared.get("inspector")
        self.space = Space(capabilities=self.capabilities(), vocabulary=self.vocabulary(),
                           store=store, tokens=self.tokens,
                           hello={"harness.worker": self._worker_info(),
                                  **({"inspector.profile": probes} if probes else {})})
        self.space.handlers.observe = self._observe
        self.space.handlers.admit = self._admit
        for method in self.methods:
            self.space.handlers.verbs[f"{self.kind}.{method}"] = self._verb(method)
        for name, decl in self.composed.items():
            self.space.handlers.verbs[f"{self.kind}.{name}"] = self._composed(name, decl)
        self.space.handlers.episode = self._episode
        self.space.handlers.score = self._score

    # -- What the space declares ----------------------------------------------------------

    def _worker_info(self) -> dict:
        d = self.description
        return {"name": d.get("name"), "kind": self.kind, "protocol_version": d.get("protocol_version"),
                "managed_control_calls": sorted(self.host_controls),
                "program_control_calls": sorted(d.get("program_control_calls") or ()),
                "managed_approval": bool(d.get("managed_approval")), "host_key": bool(self.approval_key),
                "asp": PROTOCOL_VERSION}

    def capabilities(self) -> dict:
        p = self.profile
        verbs = [f"{self.kind}.{m}" for m in [*self.methods, *self.composed]]
        # A verb made of a tick is a host control where the tick is one.
        controls = self.host_controls | ({*self.composed} if "tick" in self.host_controls else set())
        member = [v for v in verbs if v.split(".", 1)[1] not in controls] if self.approval_key else verbs
        capabilities = {
            "state": "external",
            "lifetime": "disposable",
            "participants": {
                "roles": {
                    "owner": {"line": "Whoever started the worker: every verb.", "verbs": ["*"], "consent": True},
                    "member": {"line": "A program of the conversation: the verbs without the host's controls.",
                               "verbs": member},
                    "evaluator": {"line": "The evaluator: the owner's verbs and the score.", "verbs": ["*"]},
                    "guest": {"line": "Looks only.", "verbs": []},
                },
                "default_role": "member",
                # A person at the real desktop is a participant outside the protocol.
                "outside": bool(p.get("physical")),
                "grace_seconds": 60,
            },
            "forms": ["text", *(f"{self.kind}.{c}" for c in self.cameras)],
            "episode": {"tasks": self.tasks, "evaluator": "evaluator"},
        }
        pace = {}
        if isinstance(p.get("max_hz"), (int, float)) and p["max_hz"] > 0:
            pace["max_hz"] = float(p["max_hz"])
        if isinstance(p.get("step_seconds"), (int, float)) and p["step_seconds"] > 0:
            pace["step_seconds"] = float(p["step_seconds"])
            pace["clock"] = "stepped"
        else:
            pace["clock"] = "wall"
        capabilities["pace"] = pace
        for key, value in (self.declared.get("capabilities") or {}).items():
            if isinstance(capabilities.get(key), dict) and isinstance(value, dict):
                capabilities[key] = {**capabilities[key], **value}
            else:
                capabilities[key] = value
        return capabilities

    def vocabulary(self) -> dict:
        declared = self.declared or {}
        own = declared.get("verbs") or {}
        verbs = {}
        for method in [*self.methods, *self.composed]:
            name = f"{self.kind}.{method}"
            decl = dict(own.get(method) or {})
            verbs[name] = {
                "line": decl.get("line") or f"The worker's {method} call; its arguments are the action's args.",
                "params": decl.get("params") or {"type": "object"},
                "effect": decl.get("effect") or ("read" if method in ("profile", "process", "observe") else "change"),
                "default": decl.get("default") or {"end": "refused", "reason": {"code": "unsupported",
                                                                                 "text": f"the worker has no {method}"}},
                "stale": decl.get("stale") or ("refuse" if method == "tick" else "allow"),
                "outcomes": decl.get("outcomes") or (["done", "refused", "failed", "cancelled", "unknown"]
                                                     if decl.get("follow") else ["done", "refused", "failed", "unknown"]),
                **({"object": decl["object"]} if decl.get("object") else {}),
                **({"reasons": decl["reasons"]} if decl.get("reasons") else {}),
            }
        vocabulary = {
            "namespaces": {self.kind: {"version": "0", "line": declared.get("line") or
                                       f"{self.description.get('name')}, a worker of The Harness, through its translation layer"}},
            "types": {f"{self.kind}.environment": {"line": "The environment: the worker's report of its state, "
                                                          "with the episode and step it is at."}},
            "verbs": verbs,
            "events": {f"{self.kind}.told": {"line": "The environment told something by itself: `content` is a "
                                                     "message (text, or parts with images), `source` who; it is "
                                                     "addressed to the agent.",
                                             "perceived": "all"}},
            "forms": {"text": {"media": "text/plain", "line": "The state as JSON."},
                      **{f"{self.kind}.{c}": {"media": "image/*", "line": f"The view of {c}."} for c in self.cameras}},
        }
        pages = {**(declared.get("pages") or {})}
        if pages:
            vocabulary["pages"] = pages
        for key in ("types", "events"):
            vocabulary[key].update(declared.get(key) or {})
        return vocabulary

    # -- The worker, one call at a time ---------------------------------------------------

    async def _run(self, fn, *args, **kwargs):
        return await asyncio.get_running_loop().run_in_executor(self.pool, lambda: fn(*args, **kwargs))

    def _reset(self, task, seed):
        observation = self.worker.reset(task, seed)
        self.episode, self.step, self.instruction = observation.episode_id, observation.step, observation.instruction
        self._steps.append((self.space.head, (self.episode, self.step)))
        if self.profile.get("tells"):
            self._listen_tells()
        return observation

    def _ensure_episode(self):
        if self.episode is None:
            self._reset(self.tasks[0] if self.tasks else "free", self.seed)

    def _call(self, method, arguments):
        if method == "sensitive_approval":
            arguments = {k: v for k, v in arguments.items() if k != "episode_id"}
            return self.worker.sensitive_approval(arguments.pop("op"), approval_key=self.approval_key, **arguments)
        if method in self.host_controls and self.approval_key:
            return self.worker.managed_call(method, approval_key=self.approval_key, **arguments)
        return self.worker.call(method, **arguments)

    # -- Handlers -------------------------------------------------------------------------

    def _admit(self, request):
        role, participant = request["role"], request.get("participant") or ""
        if participant.startswith("token:"):
            name = participant[6:]
            fixed = {"kernel": "member", "owner": "owner", "evaluator": "evaluator"}.get(name, "member")
            return fixed
        if role in ("owner", "evaluator") and self.owner and participant != self.owner:
            raise Refused("forbidden", f"only the identity that started the worker may take the {role} role")
        return role

    async def _observe(self, ctx):
        await self._run(self._ensure_episode)
        cameras = [f.split(".", 1)[1] for f in ctx.forms if f.startswith(self.kind + ".")]
        episode = self.episode
        if ctx.forms:
            report = await self._run(self._call, "observe", {"episode_id": episode, **({"cameras": cameras} if cameras else {})})
        else:
            report = {"state": await self._run(self._call, "state", {"episode_id": episode})}
        state = report.get("state") or {}
        step = state.get("step", self.step) if isinstance(state, dict) else self.step
        if isinstance(step, int):
            self.step = step
        self._steps.append((self.space.head, (self.episode, self.step)))
        thing = {"id": "environment", "type": f"{self.kind}.environment", "confirmed": now(),
                 "episode": self.episode, "step": self.step, "instruction": self.instruction,
                 "report": {k: v for k, v in report.items() if k != "images"}, "keys": list(report)}
        forms = {}
        if "text" in ctx.forms:
            forms["text"] = {"media": "text/plain", "data": json.dumps(state, ensure_ascii=False, sort_keys=True, default=str)}
        for name, url in (report.get("images") or {}).items():
            media, data = _split_data_url(url)
            forms[f"{self.kind}.{name}"] = {"media": media, "data": data}
        return {"structure": {"things": [thing]}, "forms": forms, "confirmed": thing["confirmed"]}

    def _verb(self, method):
        async def law(ctx):
            arguments = dict(ctx.args)
            if self.episode is None and arguments.get("episode_id"):
                self.episode = arguments["episode_id"]  # the participant acts in an episode it knows
            await self._run(self._ensure_episode)
            takes_episode = ((self.declared.get("verbs") or {}).get(method) or {}).get("episode", True)
            if method not in NO_EPISODE and method != "sensitive_approval" and takes_episode                     and "episode_id" not in arguments:
                arguments["episode_id"] = self.episode
            if method == "tick":
                if "step" not in arguments:
                    arguments["step"] = self._step_at(ctx.basis)
                    if ctx.basis is not None and arguments["step"] != self.step:
                        # Based on an observation of a step that is past: whatever the worker
                        # would make of it, the layer does not send it.
                        raise Refused("stale", f"the action is based on step {arguments['step']}; the "
                                               f"environment is at step {self.step}")
                asked = (arguments.get("episode_id"), arguments.get("step"), self.step)
            try:
                result = await self._run(self._call, method, arguments)
            except Exception as error:
                if method == "tick":
                    await self._judge_tick_error(error, asked)
                raise self._judge_error(error) from None
            if method == "tick" and isinstance(result, dict):
                state = result.get("state") if isinstance(result.get("state"), dict) else {}
                if result.get("executed"):
                    self.step = state.get("step", (asked[1] or 0) + 1)
                    self._ticks[ctx.id] = (self.episode, self.step)
                if result.get("executed") is False:
                    shield = result.get("shield") or {}
                    reasons = "; ".join(str(r) for r in shield.get("reasons") or []) or "the shield stopped the command"
                    raise Refused("harness.shield", reasons, result)
            return {"result": result}

        return law

    def _composed(self, name, decl):
        """A verb made of a tick: its command is the declared `tick` with the action's args; with
        `follow`, it lasts until what the tick started ends (declarations.py)."""
        tick = self._verb("tick")
        follow, ends = decl.get("follow"), decl.get("ends") or {}

        async def law(ctx):
            command = {**decl["tick"], **ctx.args}
            # A verb that reads (stale = "allow") acts on the current step, whatever it saw.
            basis = None if decl.get("stale", "refuse") == "allow" else ctx.basis
            ran = await tick(_Args(ctx, {"command": command}, basis))
            receipt = ran["result"]
            if not follow:
                return ran
            result = receipt.get("result") if isinstance(receipt.get("result"), dict) else {}
            ident = result.get(follow["id"])
            status_key, until = follow.get("status", "status"), follow.get("until", "ready")
            if ident is None or result.get(status_key) not in (follow.get("running") or ["running"]):
                return self._ended(result.get(status_key), result, ends, None)
            asked = {"episode_id": self.episode, follow.get("id_argument", follow["id"]): ident}
            stopped = None
            while True:
                report = await self._run(self._call, follow["poll"], dict(asked))
                if report.get(until):
                    return self._ended(report.get(status_key), report, ends, stopped)
                if stopped is None and ctx.stopping:
                    stopped = ctx.stop_reason
                    try:
                        await self._run(self._call, follow["cancel"], {**asked, "reason": stopped})
                    except Exception:
                        pass
                else:
                    await asyncio.sleep(float(follow.get("every", 0.2)))

        return law

    def _ended(self, status, report, ends, stopped):
        """The outcome a followed action has, by the status it ended with."""
        end = ends.get(status, "unknown" if status is not None else "done")
        end, code = (end.get("end"), end.get("code")) if isinstance(end, dict) else (end, None)
        if stopped == "deadline" and end == "cancelled":
            end, code = "failed", "deadline"  # stopped because its deadline passed: it did not finish
        text = f"it ended {status}" if status else "it ended"
        if end == "done":
            return {"result": report}
        if end == "cancelled":
            raise Stopped()
        if end == "failed":
            raise Failed(code or f"{self.kind}.{status}", text, data=report)
        if end == "refused":
            raise Refused(code or f"{self.kind}.{status}", text, report)
        raise Uncertain(code or f"{self.kind}.{status or 'unknown'}", text, known={"status": status},
                        unconfirmed=["ended"])

    async def _judge_tick_error(self, error, asked):
        """Raise the outcome a failed tick has, by where the worker's cursor is now."""
        if _unreachable(error):
            raise Uncertain("harness.worker_unreachable", f"the worker did not answer: {error}",
                            known={"sent": True}, unconfirmed=["executed"])
        if getattr(error, "uncertain", False):
            self._invalidate()
            raise Uncertain("harness.acted", f"the input may have reached the environment: {error}",
                            known={"sent": True}, unconfirmed=["executed"])
        try:
            state = await self._run(self._call, "state", {"episode_id": asked[0]})
        except Exception:
            # The cursor was invalidated: the worker could not tell whether the input acted.
            self._invalidate()
            raise Uncertain("harness.acted", f"the input may have reached the environment: {error}",
                            known={"sent": True}, unconfirmed=["executed"]) from None
        step = state.get("step") if isinstance(state, dict) else None
        if isinstance(step, int) and isinstance(asked[2], int) and step > asked[2]:
            # The cursor moved on in this call: it executed, and failed.
            self.step = step
            raise Failed("harness.error", str(error))

    def _judge_error(self, error):
        text = str(error)
        said = getattr(error, "worker_error", None) or text  # "Type: message", as the worker said it
        if _unreachable(error):
            return Uncertain("harness.worker_unreachable", f"the worker did not answer: {text}",
                             known={"sent": True}, unconfirmed=["executed"])
        if "Stale or missing observation" in said:
            return Refused("stale", text)
        if said.startswith("PermissionError") or isinstance(error, PermissionError):
            return Refused("forbidden", text)
        if said.startswith("TypeError") or isinstance(error, TypeError):
            return Refused("malformed", text)
        if "episode has ended" in said:
            return Refused("closed", text)
        if said.startswith(("ValueError", "KeyError")) or isinstance(error, (ValueError, KeyError)):
            return Refused("harness.rejected", text)
        return Failed("harness.error", text)

    def _invalidate(self):
        self.step = None

    def _step_at(self, basis):
        """The worker's step at a record sequence number (the current one without)."""
        if basis is None:
            return self.step
        found = None
        for seq, where in self._steps:
            if seq <= basis:
                found = where
        if found is None or found[0] != self.episode:
            return self.step
        return found[1]

    def _appended(self, entries):
        for entry in entries:
            if entry.get("type") == "asp.outcome":
                data = entry.get("data") or {}
                where = self._ticks.pop(data.get("id"), None) if data.get("end") == "done" else None
                if where is not None:
                    self._steps.append((entry["seq"], where))

    async def _episode(self, request):
        task, seed = request.get("task") or (self.tasks[0] if self.tasks else "free"), request.get("seed")
        if self.tasks and task not in self.tasks:
            raise Refused("malformed", f"no task {task!r}; there are {', '.join(self.tasks)}")
        # On the worker's own thread: a reset may take a while (a browser starting), and the
        # space answers its other participants meanwhile. Whatever goes wrong is an outcome.
        try:
            observation = await self._run(self._reset, task, 0 if seed is None else seed)
        except Refused:
            raise
        except Exception as error:
            raise Refused("harness.reset_failed", f"the worker did not start the episode: {error}") from None
        return {"episode": observation.episode_id, "observation": observation.to_dict()}

    async def _score(self, request):
        try:
            return await self._run(self._score_now, request)
        except Refused:
            raise
        except Exception as error:
            raise Refused("harness.rejected", str(error)) from None

    def _score_now(self, request):
        self._ensure_episode()
        episode = request.get("episode") or self.episode
        if episode != self.episode:
            raise Refused("closed", "only the current episode's score can be read")
        try:
            token = self._call("claim_outcome", {"episode_id": episode})["token"]
            outcome = self._call("outcome", {"token": token})
        except Exception as error:
            raise Refused("harness.rejected", str(error)) from None
        return {"episode": episode, "score": outcome}

    # -- What the worker tells by itself --------------------------------------------------

    def _listen_tells(self):
        if self._inbound is None:
            self._inbound = _Inbound(self._told)
        self._call("tell_to", {"episode_id": self.episode, "url": self._inbound.url, "token": self._inbound.token})

    def _told(self, content, source):
        loop = self._loop
        if loop is None:
            return
        # What a worker tells is for the agent: addressed to every presence.
        data = {"content": content, **({"source": source} if source else {}), "addressed": True}
        loop.call_soon_threadsafe(lambda: self.space.emit(f"{self.kind}.told", data, things=["environment"],
                                                          source="outside"))

    # -- Running --------------------------------------------------------------------------

    async def serve(self, listen: str, ready=None, close_on_eof=False):
        self._loop = asyncio.get_running_loop()
        if listen == "stdio":
            # One participant on standard input and output: the space ends when it leaves.
            accept = self.space.accept

            def accept_once(conn):
                accept(conn)
                closed = conn.on_close

                def on_close():
                    if closed:
                        closed()
                    self._loop.create_task(self.space.close())

                conn.on_close = on_close

            self.space.accept = accept_once
        listener = await self.space.listen(listen)
        if ready:
            ready(listener.address)
        if close_on_eof:
            closed = asyncio.Event()

            def wait_eof():
                try:
                    while sys.stdin.buffer.read(4096):
                        pass
                finally:
                    self._loop.call_soon_threadsafe(closed.set)

            threading.Thread(target=wait_eof, daemon=True, name="stdin").start()
            await closed.wait()
            await self.space.close()
        else:
            await self.space.wait_closed()
        if self._inbound:
            self._inbound.close()
        if isinstance(self.worker, LocalWorker):
            # Closed on the thread that used it (a browser's driver is bound to its thread).
            await self._run(self.worker.close)
        self.pool.shutdown(wait=False)


class _Inbound:
    """Where a worker tells (Tells.tell): a loopback HTTP listener with a token."""

    def __init__(self, deliver):
        self.token = secrets.token_hex(16)
        token = self.token

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                    if not secrets.compare_digest(str(body.get("token", "")), token):
                        self.send_error(401)
                        return
                    deliver(body.get("content"), body.get("source"))
                    self.send_response(204)
                    self.end_headers()
                except Exception:
                    self.send_error(400)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/tell"
        threading.Thread(target=self.server.serve_forever, daemon=True, name="tells").start()

    def close(self):
        self.server.shutdown()


def _declaration_file(path):
    if not path:
        return None
    import tomllib

    with open(path, "rb") as handle:
        return tomllib.load(handle)


def _record_file(folder):
    if not folder:
        return None
    from pathlib import Path

    Path(folder).mkdir(parents=True, exist_ok=True)
    return Path(folder) / "record.db"


def _unreachable(error) -> bool:
    text = str(error)
    return isinstance(error, (URLError, TimeoutError, ConnectionError)) or "timed out" in text or "Connection refused" in text


def _split_data_url(url: str) -> tuple[str, str]:
    if isinstance(url, str) and url.startswith("data:") and ";base64," in url:
        head, data = url[5:].split(";base64,", 1)
        return head or "application/octet-stream", data
    return "text/uri-list", str(url)


def _cameras(kind):
    from harness.embodiments import KINDS

    return KINDS[kind].cameras if kind in KINDS else ()


def _declarations(kind, worker=None) -> dict:
    """What the package that gives `kind` declares of its space (harness.space.declarations)."""
    from harness.space.declarations import declared

    return declared(kind, worker)


def parser():
    parser = argparse.ArgumentParser(prog="python -m harness.space.translate",
                                     description="Serve a worker as an Agent Space Protocol space")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--worker", help="the worker's endpoint (http://127.0.0.1:PORT)")
    source.add_argument("--factory", help="module:callable that makes the environment, run in this process")
    parser.add_argument("--options", help="TOML keyword arguments for --factory")
    parser.add_argument("--listen", default="ws://127.0.0.1:0", help="ws://HOST:PORT, http://HOST:PORT or stdio")
    parser.add_argument("--tasks", default="", help="the worker's tasks, comma separated (any by default); "
                                                      "the first is the one started for a participant that starts none")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--data", help="a folder for the record (record.db); in memory without")
    parser.add_argument("--declaration", help="a package's spaces/<name>.toml to use (else the installed packages')")
    parser.add_argument("--owner", help="the identity (ed25519:...) that may take the owner and evaluator roles")
    parser.add_argument("--close-on-eof", action="store_true", help="close once standard input ends")
    parser.add_argument("--startup-from-stdin", action="store_true",
                        help="read one JSON line first: approval_key, worker_token, owner, tokens, episode")
    return parser


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    startup = {}
    if args.startup_from_stdin:
        startup = json.loads(sys.stdin.buffer.readline() or b"{}")
    if args.worker:
        from harness.core.remote import RemoteEnvironment

        if startup.get("worker_token"):
            os.environ["HARNESS_WORKER_TOKEN"] = startup["worker_token"]
        # With the host's key when it has one: a managed worker takes its resets and host controls
        # only with the host's proof.
        worker = RemoteEnvironment(args.worker, timeout=float(startup.get("timeout") or 600),
                                   approval_key=startup.get("approval_key"))
    else:
        import importlib

        from harness.config import read_toml
        from harness.packages import activate

        activate()
        module, function = args.factory.split(":", 1)
        environment = getattr(importlib.import_module(module), function)(**(read_toml(args.options) if args.options else {}))
        worker = LocalWorker(environment)
    space = WorkerSpace(worker, tasks=[t for t in args.tasks.split(",") if t], owner=startup.get("owner") or args.owner,
                        tokens=startup.get("tokens"), approval_key=startup.get("approval_key"), seed=args.seed,
                        data=_record_file(args.data), declarations=_declaration_file(args.declaration),
                        episode=startup.get("episode"))

    def ready(address):
        if address != "stdio":  # on stdio, standard output is the space's own stream
            print(json.dumps({"space": address, "kind": space.kind}), flush=True)

    asyncio.run(space.serve(args.listen, ready, close_on_eof=(args.close_on_eof or args.startup_from_stdin) and args.listen != "stdio"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
