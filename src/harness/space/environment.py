"""The runtime's environment, reached as an Agent Space Protocol participant.

The run, the host and the kernel use an environment through one interface (tools, reset,
call, managed_call, sensitive_approval, close: core/contracts.py Environment). SpaceEnvironment
is that interface over a participant of a space: every call becomes a protocol message, and
every action comes back with exactly one typed outcome (agent_space.Outcome: End, Reason).

- `SpaceEnvironment.for_worker(endpoint, ...)` starts the translation layer beside a worker
  (harness.space.translate) and enters it as the owner; `kernel_token` lets the conversation's
  programs enter the same space as members.
- `SpaceEnvironment.connect(address, ...)` enters any space: the translation layer of another
  process, or a space that speaks the protocol itself.
- `SpaceEnvironment.local(environment)` serves an environment object of this process
  (a host-owned lease) through the translation layer on a thread of its own.

A call that is an action returns the worker's result when the outcome is done, and the
envelope of a refused tick as the worker gave it (the shield stopped the command); any other
outcome raises ActionFailed, a RuntimeError whose text is the reason's text (the worker's own
error text) and whose `outcome` is the typed outcome. `outcomes` keeps every outcome of this
participant, for the trace.
"""

from __future__ import annotations

import base64
import itertools
import json
import os
import secrets
import subprocess
import sys
import threading
import urllib.request
from collections import deque
from typing import Any

from agent_space import End, Outcome, SyncParticipant, generate_key

from harness.core.contracts import Observation

PROTOCOL_VERSION = 0


class ActionFailed(RuntimeError):
    """An action of a space whose outcome is not done (nor a refusal the caller reads)."""

    def __init__(self, outcome: Outcome, text: str | None = None):
        self.outcome = outcome
        reason = outcome.reason
        super().__init__(text or (reason.text if reason and reason.text else f"{outcome.end}" + (f": {reason.code}" if reason else "")))


class SpaceEnvironment:
    """An environment the runtime reaches as a participant of a space (see the module)."""

    name = "space"

    def __init__(self, participant: SyncParticipant, *, address: str, timeout: float = 600.0, approval_key=None,
                 host_controls=(), relay=None, child=None, kernel_token=None, role=None, local=None):
        self.participant = participant
        self.address = self.endpoint = address
        self.timeout = timeout
        self.approval_key = approval_key
        self.host_controls = frozenset(host_controls)
        self.program_controls = frozenset()
        self.relay = relay
        self.kernel_token = kernel_token
        self.role = role
        self.outcomes: deque[Outcome] = deque(maxlen=1000)
        self._child = child
        self._local = local
        self._ids = itertools.count(1)
        self._prefix = secrets.token_hex(4)
        self._tells = None
        self._listeners: list = []
        self._outcome_listeners: list = []
        self._subscribed = False
        hello = participant.hello
        self.space = hello.get("space")
        self.capabilities = hello.get("capabilities") or {}
        self.worker = hello.get("harness.worker") or {}
        self.kind = self.worker.get("kind")
        self.joined = participant.join(role) if role else participant.join()
        self.presence = self.joined.get("presence")
        self._vocabulary = None

    # -- Entering ---------------------------------------------------------------------------

    @classmethod
    def for_worker(cls, endpoint: str, *, timeout: float = 600.0, approval_key=None,
                   python: str | None = None, role: str = "evaluator") -> "SpaceEnvironment":
        """Start the translation layer beside the worker at `endpoint` and enter it."""
        key = generate_key()
        kernel_token = secrets.token_hex(16)
        command = [python or sys.executable, "-m", "harness.space.translate", "--worker", endpoint,
                   "--listen", "ws://127.0.0.1:0", "--startup-from-stdin"]
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        startup = {"owner": key.identity, "tokens": {kernel_token: "kernel"}, "timeout": timeout,
                   **({"approval_key": approval_key} if approval_key else {}),
                   **({"worker_token": os.environ["HARNESS_WORKER_TOKEN"]} if os.environ.get("HARNESS_WORKER_TOKEN") else {})}
        try:
            child.stdin.write((json.dumps(startup) + "\n").encode())
            child.stdin.flush()
            line = child.stdout.readline()
            if not line:
                raise RuntimeError(f"the translation layer for {endpoint} did not start (exit {child.wait(10)})")
            address = json.loads(line)["space"]
            participant = SyncParticipant.connect(address, key=key, reconnect=False,
                                                  client={"name": "the-harness"})
            return cls(participant, address=address, timeout=timeout, approval_key=approval_key, child=child,
                       kernel_token=kernel_token, role=role)
        except BaseException:
            _stop(child)
            raise

    @classmethod
    def connect(cls, address: str, *, token: str | None = None, key=None, role: str | None = None,
                timeout: float = 300.0, host_controls=(), relay=None) -> "SpaceEnvironment":
        """Enter the space at `address` (a ws:// or http:// URL, or a command)."""
        participant = SyncParticipant.connect(address, key=key if token is None else None, token=token,
                                              reconnect=address.startswith(("ws", "http")),
                                              client={"name": "the-harness"})
        return cls(participant, address=address, timeout=timeout, host_controls=host_controls, relay=relay,
                   role=role)

    @classmethod
    def local(cls, environment, *, timeout: float = 600.0) -> "SpaceEnvironment":
        """Serve an environment object of this process through the translation layer, on a
        thread of its own, and enter it as the owner."""
        import asyncio

        from harness.space.translate import WorkerSpace

        key = generate_key()
        ready, holder = threading.Event(), {}

        def serve():
            async def main():
                space = WorkerSpace(_ObjectWorker(environment), owner=key.identity)
                holder["space"] = space
                await space.serve("ws://127.0.0.1:0", lambda address: (holder.update(address=address), ready.set()))

            try:
                asyncio.run(main())
            except BaseException as error:  # noqa: BLE001 - reported to the caller below
                holder["error"] = error
                ready.set()

        thread = threading.Thread(target=serve, daemon=True, name="space")
        thread.start()
        ready.wait(60)
        if "address" not in holder:
            raise RuntimeError(f"the translation layer did not start: {holder.get('error')!r}")
        participant = SyncParticipant.connect(holder["address"], key=key, reconnect=False, client={"name": "the-harness"})
        env = cls(participant, address=holder["address"], timeout=timeout, role="evaluator", local=holder)
        env.approval_key = getattr(environment, "approval_key", None)
        return env

    def member(self) -> "SpaceEnvironment":
        """The same space entered as a member (the calls anyone may make), as programs do."""
        return SpaceEnvironment.connect(self.address, token=self.kernel_token, timeout=self.timeout) \
            if self.kernel_token else self

    # -- The environment interface -------------------------------------------------------------

    def describe(self) -> dict:
        w = self.worker
        return {"protocol_version": w.get("protocol_version", 1), "name": w.get("name") or self.space,
                "tools": [], "methods": [v.split(".", 1)[1] for v in self.verbs()],
                **({"managed_approval": True} if w.get("managed_approval") else {}),
                **({"managed_control_calls": w["managed_control_calls"],
                    "program_control_calls": w.get("program_control_calls", []),
                    "authenticated_controls": True} if w.get("managed_control_calls") else {})}

    def tools(self) -> list[dict]:
        """Checks the space and takes the worker's name and host controls, as a worker's
        describe did."""
        description = self.describe()
        if self.worker and description["protocol_version"] != 1:
            raise ValueError("Unsupported worker protocol version")
        if self.approval_key:
            if not (self.worker.get("managed_control_calls") or self.worker.get("managed_approval")):
                raise RuntimeError("Worker did not enable authenticated controls")
            self.host_controls = frozenset([*self.worker.get("managed_control_calls", ()), "sensitive_approval"])
            self.program_controls = frozenset(self.worker.get("program_control_calls", ())) & self.host_controls
        self.name = description["name"]
        return []

    def vocabulary(self) -> dict:
        if self._vocabulary is None:
            self._vocabulary = self.participant.vocabulary(timeout=self.timeout)
        return self._vocabulary

    def verbs(self) -> dict:
        return self.vocabulary().get("verbs") or {}

    def reset(self, task: str, seed: int) -> Observation:
        """A new episode of `task` with `seed` (the capability episode), its first observation."""
        out = self._finish(self.participant.participant, {"type": "episode", "task": task, "seed": seed})
        return Observation(**out.result["observation"])

    def call(self, name: str, /, **arguments):
        if name in self.host_controls and self.approval_key is None and self.relay is not None:
            return self.relay({"name": name, "arguments": arguments}, self.timeout)
        if name == "observe" and set(arguments) <= {"episode_id", "cameras"}:
            seen = self.participant.observe(["text", *self._camera_forms(arguments.get("cameras"))], timeout=self.timeout)
            return _report(seen, self.kind)
        if name == "state":
            seen = self.participant.observe([], timeout=self.timeout)
            return (_environment(seen).get("report") or {}).get("state")
        if name == "claim_outcome":
            return {"token": "asp-score"}
        if name == "outcome":
            out = self._finish(self.participant.participant, {"type": "score"})
            return out.result["score"]
        if name == "tell_to":
            return self._tell_to(arguments.get("url"), arguments.get("token"))
        return self.act(f"{self.kind}.{name}" if self.kind else name, arguments)

    def act(self, verb: str, args: dict | None = None, *, object: str | None = None, basis: int | None = None):
        """One action: the result when done; a refused tick's envelope; else ActionFailed."""
        outcome = self.participant.act(verb, object, args or {}, basis=basis, id=f"{self._prefix}.{next(self._ids)}",
                                       timeout=self.timeout + 30)
        self._outcome(outcome, verb)
        if outcome.end is End.DONE:
            return outcome.result
        data = outcome.reason.data if outcome.reason else None
        if outcome.end is End.REFUSED and isinstance(data, dict) and data.get("executed") is False:
            return data
        raise ActionFailed(outcome)

    def managed_call(self, name, /, *, approval_key, **arguments):
        return self.call(name, **arguments)

    def sensitive_approval(self, op, *, approval_key, **arguments):
        return self.act(f"{self.kind}.sensitive_approval", {"op": op, **arguments})

    def execute(self, action, episode_id, step):
        raise RuntimeError("This environment accepts actions only through call('tick')")

    def close(self) -> None:
        try:
            self.participant.close()
        except Exception:
            pass
        if self._child is not None:
            _stop(self._child)
            self._child = None
        if self._local and self._local.get("space"):
            space = self._local["space"]
            loop = space._loop
            if loop is not None:
                import asyncio

                asyncio.run_coroutine_threadsafe(space.space.close(), loop)

    # -- Helpers ----------------------------------------------------------------------------------

    def _camera_forms(self, cameras) -> list[str]:
        if not cameras or not self.kind:
            return []
        return [f"{self.kind}.{c}" for c in cameras]

    def _finish(self, participant, message) -> Outcome:
        import asyncio

        async def go():
            return await participant.request(message)

        out = asyncio.run_coroutine_threadsafe(go(), self.participant._loop).result(self.timeout + 30)
        self._outcome(out, message["type"])
        if not out.done:
            raise ActionFailed(out)
        return out

    # -- What the space pushes, and what came of this participant's actions ------------------------

    def listen(self, fn) -> None:
        """Call `fn(entry)` with every record entry the space pushes from now on (events of the
        space and of other participants, and the protocol's own entries, `asp.*`), each once
        and in order, on the participant's thread."""
        self._listeners.append(fn)
        if not self._subscribed:
            self._subscribed = True
            self.participant.on("event", self._entry)
            self.participant.subscribe(timeout=self.timeout)

    def on_outcome(self, fn) -> None:
        """Call `fn(outcome, verb)` with the outcome of every action of this participant."""
        self._outcome_listeners.append(fn)

    def _entry(self, entry) -> None:
        for fn in list(self._listeners):
            try:
                fn(entry)
            except Exception as error:  # a listener's error must not stop the others
                print(f"space listener: {type(error).__name__}: {error}", file=sys.stderr)

    def _outcome(self, outcome: Outcome, verb: str) -> None:
        self.outcomes.append(outcome)
        for fn in list(self._outcome_listeners):
            try:
                fn(outcome, verb)
            except Exception as error:
                print(f"outcome listener: {type(error).__name__}: {error}", file=sys.stderr)

    def _tell_to(self, url, token):
        """What the environment tells by itself goes where the run listens (runtime/task/inbound.py)."""
        kind = f"{self.kind}.told"

        def deliver(entry):
            if entry.get("type") != kind:
                return
            data = entry.get("data") or {}
            body = json.dumps({"token": token, "content": data.get("content"), "source": data.get("source")}).encode()

            def send():
                try:
                    request = urllib.request.Request(url, data=body, method="POST",
                                                     headers={"content-type": "application/json"})
                    urllib.request.urlopen(request, timeout=20).read()
                except Exception:
                    pass

            threading.Thread(target=send, daemon=True, name="space-tells").start()

        if self._tells is None:
            self._tells = deliver
            self.listen(deliver)
        return {"tells": True}


class _ObjectWorker:
    """An environment object of this process with the runtime's interface, as the translation
    layer's worker."""

    def __init__(self, environment):
        self.environment = environment
        self.endpoint = None

    def describe(self) -> dict:
        describe = getattr(self.environment, "describe", None)
        if callable(describe):
            return describe()
        self.environment.tools()
        return {"protocol_version": 1, "name": getattr(self.environment, "name", "environment"), "tools": [],
                "methods": sorted(getattr(self.environment, "methods", ()))}

    def reset(self, task, seed):
        return self.environment.reset(task, seed)

    def call(self, name, /, **arguments):
        return self.environment.call(name, **arguments)

    def managed_call(self, name, /, *, approval_key, **arguments):
        return self.environment.managed_call(name, approval_key=approval_key, **arguments)

    def sensitive_approval(self, op, *, approval_key, **arguments):
        return self.environment.sensitive_approval(op, approval_key=approval_key, **arguments)


def _environment(observation: dict) -> dict:
    for thing in (observation.get("structure") or {}).get("things") or []:
        if thing.get("id") == "environment":
            return thing
    return {}


def _images(observation: dict, kind) -> dict:
    images = {}
    prefix = f"{kind}." if kind else ""
    for name, form in (observation.get("forms") or {}).items():
        if prefix and name.startswith(prefix) and form.get("media", "").startswith("image/"):
            images[name[len(prefix):]] = f"data:{form['media']};base64,{form.get('data', '')}"
    return images


def _report(observation: dict, kind) -> dict:
    """The worker's observe answer, as it gave it."""
    thing = _environment(observation)
    report = dict(thing.get("report") or {})
    images = _images(observation, kind)
    order = thing.get("keys") or [*report, "images"]
    full = {**report, "images": images}
    return {key: full[key] for key in order if key in full}


def _stop(child) -> None:
    try:
        if child.stdin:
            child.stdin.close()
    except Exception:
        pass
    try:
        child.wait(15)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(5)


def decode_data(form: dict) -> bytes:
    return base64.b64decode(form.get("data", ""))
