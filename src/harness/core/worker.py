"""A serial worker keeps all simulator operations on the serving thread.

A worker is an embodiment's process: it serves the worker protocol (WORKER_METHODS) behind
its shield (runtime/safety/shield.py CommandShield), which judges every command before it moves
anything. The session skeleton (runtime/execution/session.py EpisodeCore) needs nothing else of it.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json

from harness.runtime.safety.approval import APPROVAL_PIPE_FLAG, WORKER_APPROVAL_HEADER, WORKER_APPROVAL_KEY, read_worker_startup, worker_approval_proof
from .codec import EpisodeCursor, OutcomeToken
from .contracts import Action
from .ports import OwnPort

# The worker protocol: what every worker serves to the session skeleton and the
# conversation, besides describe, reset and execute: what the embodiment is (profile: its kind,
# control rate, how it is driven (max_hz, step_seconds: runtime/tick.py driving), channels, cameras and shield),
# its state now, one control period's
# command, judged by its shield (tick), the views of its cameras or screen (observe), and
# the evaluator's outcome (claim_outcome, outcome). An embodiment adds its own methods (a robot's
# fk, ik and plan; a computer's windows; a game's world): `methods = (*WORKER_METHODS, ...)`.
WORKER_METHODS = ("profile", "state", "tick", "observe", "claim_outcome", "outcome")


class BenchWorker:
    """What a benchmark's worker shares (a mixin): the call dispatch to its `_call_<name>`
    methods, input refused outside tick (which its shield checks), the state call, the
    check of the views observe takes, the envelope of a tick, and the outcome behind a
    token claimed once per episode (OutcomeToken).

    A worker sets `methods` (its calls), LABEL (its name in messages), INPUT ("input", or
    "motion" for a robot) and VIEWS (the views it has); keeps `_cursor` (EpisodeCursor);
    and defines `_state()`, `_ended()` and `_evaluate()` (the outcome, asked once). Its
    reset calls `new_outcome()`."""

    methods = WORKER_METHODS
    LABEL = "worker"
    INPUT = "input"
    VIEWS = ("screen",)

    def tools(self):
        return []

    def execute(self, action, episode_id, step):
        raise RuntimeError(f"The {self.LABEL} accepts {self.INPUT} only through call('tick'), which the shield checks")

    def call(self, name, arguments):
        if name not in self.methods:
            raise ValueError(f"Unknown {self.LABEL} method: {name}")
        return getattr(self, f"_call_{name}")(**arguments)

    def _check_episode(self, episode_id) -> None:
        """The call is for the current episode (a worker may also refuse an episode it can no
        longer score)."""
        self._cursor.check(episode_id, self._cursor.step)

    def _call_state(self, episode_id):
        self._check_episode(episode_id)
        return self._state()

    def views(self, cameras) -> list:
        """The views observe is asked for (all of VIEWS without any); ValueError for one this
        worker has not."""
        views = list(cameras or self.VIEWS)
        unknown = set(views) - set(self.VIEWS)
        if unknown:
            raise ValueError(f"Unknown views: {sorted(unknown)}; this worker has {', '.join(self.VIEWS)}")
        return views

    def _call_observe(self, episode_id, cameras=None):
        """A desktop's view (a robot's worker overrides it: its cameras)."""
        self._check_episode(episode_id)
        self.views(cameras)
        # The picture first: on a computer with several screens it picks the one the state names.
        images = self._screenshot()
        return {"state": self._state(), "images": images}

    # -- The envelope of a tick ------------------------------------------------------

    def tick_begins(self, episode_id, step) -> None:
        """A tick's checks: the episode and step are the current ones, the episode goes on."""
        self._cursor.check(episode_id, step)
        if self._ended():
            raise ValueError("The episode has ended; the command was not executed")

    def tick_refused(self, decision) -> dict:
        """The shield stopped the command: nothing was executed."""
        return {"executed": False, "shield": decision.to_dict(), "state": self._state()}

    def acted(self, act, on_error=None):
        """`act()` once, then the next step. When it raises, the input may have reached the
        environment: the episode cannot go on from a state nobody observed, so the cursor is
        invalidated (the step is never sent again) and `on_error(error)` records it."""
        try:
            value = act()
        except Exception as error:
            self._cursor.invalidate()
            if on_error is not None:
                on_error(error)
            raise
        self._cursor.advance()
        return value

    def tick_executed(self, decision, episode_id, cameras=None, **result) -> dict:
        """The result of an executed tick, with the views after it when `cameras` asks."""
        envelope = {"executed": True, "shield": decision.to_dict(), "state": self._state(), **result}
        if cameras:
            envelope["observation"] = self._call_observe(episode_id, cameras=cameras)
        return envelope

    # -- The outcome behind a token -------------------------------------------------------

    def new_outcome(self) -> None:
        """A new episode: a new token (core/codec.py OutcomeToken), no outcome asked."""
        self._outcome_token = OutcomeToken()
        self._outcome = None

    def _call_claim_outcome(self, episode_id):
        self._check_episode(episode_id)
        return {"token": self._outcome_token.claim()}

    def _call_outcome(self, token):
        self._outcome_token.check(token)
        if getattr(self, "_outcome", None) is None:
            self._outcome = self._evaluate()
        return dict(self._outcome)


class WorkerAPI:
    """The worker's RPC methods over one environment: describe, reset, and call.

    Action-tool workers without a tick use the legacy execute route and an EpisodeCursor
    owned here. Tick workers own their cursor. Both use the observation contract. A worker
    that supports managed approval declares its protected `call` names in
    `managed_control_calls`."""

    def __init__(self, environment, contract=None, *, approval_key=None, approval_from_stdin=False, host_pipe=False):
        self.environment = environment
        self._approval_key = approval_key
        self._managed_approval = (approval_from_stdin and bool(approval_key)
                                  and callable(getattr(environment, "_sensitive_approval", None)))
        if host_pipe and not self._managed_approval:
            raise ValueError("A host-owned workspace requires a managed approval worker")
        self._host_pipe = host_pipe
        self._managed_control_calls = frozenset()
        if approval_from_stdin and approval_key:
            self._managed_control_calls = frozenset(getattr(environment, "managed_control_calls", ()))
            if not self._managed_control_calls.issubset(environment.methods) or self._managed_approval and not self._managed_control_calls:
                raise ValueError("Managed approval requires a declaration of protected worker calls")
        self._program_control_calls = frozenset(getattr(environment, "program_control_calls", ()))
        if not self._program_control_calls.issubset(self._managed_control_calls) and approval_from_stdin:
            raise ValueError("Program controls must be authenticated worker controls")
        if self._managed_approval:
            environment._managed_approval = True
        # What the clients may see (embodiments.contract_filter); None reports everything.
        self.contract = contract
        self._legacy_cursor = None if "tick" in getattr(environment, "methods", ()) else EpisodeCursor()

    def _filtered(self, method, arguments, result):
        return self.contract.apply(method, arguments, result) if self.contract is not None else result

    def dispatch(self, method: str, arguments: dict, *, approval_proof=""):
        """The result of one RPC: `describe` (protocol version, name, tools, methods),
        `reset`, `execute` (only on the current episode and step) or `call` (one of the
        environment's own methods). An unknown method is an error."""
        if self._host_pipe:
            request = {"method": method, "arguments": arguments}
            if not hmac.compare_digest(approval_proof, worker_approval_proof(self._approval_key, request)):
                raise PermissionError("Worker control requires the host proof")
        if method == "describe":
            description = {"protocol_version": 1, "name": self.environment.name,
                           "tools": self.environment.tools(), "snapshot_restore": False,
                           "methods": sorted(getattr(self.environment, "methods", ()))}
            if self._managed_approval:
                description["managed_approval"] = True
            if self._managed_control_calls:
                description["authenticated_controls"] = True
                description["managed_control_calls"] = sorted(self._managed_control_calls)
                description["program_control_calls"] = sorted(self._program_control_calls)
            if self._host_pipe:
                description["host_pipe"] = True
            return description
        control_call = method == "call" and arguments.get("name") in self._managed_control_calls
        if method == "sensitive_approval" or self._managed_control_calls and (control_call or method in ("reset", "execute")):
            request = {"method": method, "arguments": arguments}
            if not self._managed_control_calls or not hmac.compare_digest(
                    approval_proof, worker_approval_proof(self._approval_key, request)):
                raise PermissionError("Managed worker control requires proof from the host")
        if method == "sensitive_approval":
            approve = getattr(self.environment, "_sensitive_approval", None)
            if approve is None:
                raise ValueError("This worker does not support sensitive approval")
            result = approve(**arguments)
            return self._filtered("tick", arguments, result) if arguments["op"] == "retry" else result
        if method == "call":
            # Environment-specific extensions (e.g. per-tick control for the
            # runtime). The environment enforces its own episode/step checks.
            name = arguments["name"]
            if name not in getattr(self.environment, "methods", ()):
                raise ValueError(f"Unknown environment method: {name}")
            inner = arguments.get("arguments", {})
            if name == "tick" and not self._managed_control_calls and "execution_id" in inner:
                raise PermissionError("Worker execution IDs require an authenticated host")
            return self._filtered(name, inner, self.environment.call(name, inner))
        if method == "reset":
            cursor = self._legacy_cursor
            if cursor is not None:
                cursor.invalidate()
            observation = self.environment.reset(**arguments)
            result = self._filtered("reset", arguments, observation.to_dict())
            if cursor is not None:
                cursor.start(observation.episode_id, observation.step)
            return result
        if method == "execute":
            cursor = self._legacy_cursor
            if cursor is None:
                raise RuntimeError("This worker accepts actions only through call('tick')")
            episode_id, step = arguments["episode_id"], arguments["step"]
            cursor.check(episode_id, step)
            action = Action(**arguments["action"])
            # Consume the cursor before entering the worker; never replay unknown delivery.
            cursor.invalidate()
            transition = self.environment.execute(action, episode_id, step)
            result = transition.to_dict()
            result["observation"] = self._filtered("observe", arguments, result["observation"])
            if not (transition.terminated or transition.truncated):
                observation = transition.observation
                cursor.start(observation.episode_id, observation.step)
            return result
        raise ValueError(f"Unknown worker method: {method}")


def create_server(environment, host="127.0.0.1", port=8765, token=None, contract=None, *, approval_key=None,
                  approval_from_stdin=False):
    """An HTTP server (not yet serving) that answers POST /rpc with WorkerAPI, one request
    at a time. With a `token` (required on a non-loopback host) requests must carry it as a
    bearer token; errors come back as {"error": ...} with status 400."""
    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        raise ValueError("Set HARNESS_WORKER_TOKEN before binding a non-loopback interface")
    if approval_key and approval_key == token:
        raise ValueError("The worker approval key must be separate from the worker bearer token")
    api = WorkerAPI(environment, contract, approval_key=approval_key, approval_from_stdin=approval_from_stdin)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            if self.path != "/rpc":
                self.send_error(404)
                return
            if token and not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                self.send_error(401)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 32 * 1024 * 1024:
                    raise ValueError("Invalid request size")
                request = json.loads(self.rfile.read(size))
                result = {"result": api.dispatch(request["method"], request.get("arguments", {}),
                                                 approval_proof=self.headers.get(WORKER_APPROVAL_HEADER, ""))}
                status = 200
            except Exception as error:
                result = {"error": f"{type(error).__name__}: {error}"}
                status = 400
            body = json.dumps(result, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _WorkerServer((host, port), Handler)


class _WorkerServer(OwnPort, HTTPServer):
    pass


def parser():
    """The worker's arguments (python -m harness.core.worker, harness serve)."""
    import argparse

    parser = argparse.ArgumentParser(prog="harness serve", description="Serve a worker (a robot or simulator) in "
                                                                       "its own Python process")
    parser.add_argument("--factory", required=True,
                        help="module:callable, e.g. benches.robodojo.runtime:create_environment")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--options", help="TOML keyword arguments passed to the factory")
    parser.add_argument("--contract", default="native",
                        help="what clients may see: native (everything, the default) or a contract a package "
                             "registers for the embodiment's kind (contracts.toml; harness.embodiments."
                             "contract_filter), e.g. the robodojo package's xpolicylab or the osomni package's "
                             "screenshot")
    parser.add_argument("--embodiment", help="embodiment name (embodiments/<name>/embodiment.toml) for the contract")
    parser.add_argument("--exit-with-stdin", action="store_true",
                        help="end once standard input closes: the process that started it (the app's workspace "
                             "pool) ended, even without stopping it")
    parser.add_argument(APPROVAL_PIPE_FLAG, dest="approval_from_stdin", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv=None) -> int:
    """python -m harness.core.worker --factory module:callable: serve a worker (a robot, a
    simulator, this computer) in its own Python process; what a suite and the computer's
    workspaces start, and the eval package's harness serve."""
    import importlib
    import os
    import stat
    import sys
    import threading

    args = parser().parse_args(argv)
    # Discard the retired setting before the worker can launch browser or app processes.
    os.environ.pop(WORKER_APPROVAL_KEY, None)
    stdin = sys.stdin.buffer if args.exit_with_stdin else None
    approval_key = None
    host_pipe = False
    output = None
    if args.approval_from_stdin:
        if stdin is None or args.host != "127.0.0.1" or not stat.S_ISFIFO(os.fstat(stdin.fileno()).st_mode):
            raise SystemExit("Managed worker approval requires a local worker with a private stdin pipe")
        try:
            # Keep any buffered bytes after startup on a private, non-inheritable fd.
            stdin = os.fdopen(os.dup(stdin.fileno()), "rb")
            approval_key, host_pipe = read_worker_startup(stdin)
        except ValueError as error:
            raise SystemExit(str(error)) from None
    if host_pipe:
        # Keep library and factory output on the log. Only framed replies reach the host.
        output = os.fdopen(os.dup(1), "wb")
        os.dup2(2, 1)
        # Programs launched by the worker must inherit neither end of its RPC stream.
        with open(os.devnull, "rb") as null:
            os.dup2(null.fileno(), 0)
        os.environ.pop("HARNESS_WORKER_TOKEN", None)
        if os.environ.pop("HARNESS_MANAGED_LINUX_WORKER", None):
            from .linux_sandbox import protect_process_handles

            try:
                protect_process_handles()
            except RuntimeError as error:
                raise SystemExit(str(error)) from None
    from ..config import read_toml
    from ..packages import activate

    # A bench's factory is a module of a package (benches.<name>.runtime): its folder on the path.
    activate()
    module, function = args.factory.split(":", 1)
    factory = getattr(importlib.import_module(module), function)
    contract = None
    if args.contract != "native":
        from ..embodiments import contract_filter, load_embodiment

        if not args.embodiment:
            raise SystemExit("--contract needs --embodiment")
        contract = contract_filter(args.contract, load_embodiment(args.embodiment))
    environment = factory(**(read_toml(args.options) if args.options else {}))
    try:
        if host_pipe:
            from .worker_pipe import serve

            with stdin, output:
                api = WorkerAPI(environment, contract, approval_key=approval_key,
                                approval_from_stdin=True, host_pipe=True)
                serve(api, stdin, output)
            return 0
        with create_server(environment, args.host, args.port, os.environ.get("HARNESS_WORKER_TOKEN"),
                           contract=contract, approval_key=approval_key,
                           approval_from_stdin=args.approval_from_stdin) as server:
            print(json.dumps({"worker": environment.name, "address": server.server_address}), flush=True)
            if stdin is not None:
                def until_closed():
                    while stdin.read(4096):
                        pass
                    server.shutdown()

                threading.Thread(target=until_closed, name="stdin", daemon=True).start()
            server.serve_forever()
    finally:
        environment.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
