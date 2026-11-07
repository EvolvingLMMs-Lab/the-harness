"""Framed RPC over a workspace worker's private stdin and stdout."""

from concurrent.futures import Future
import json
from queue import Full, Queue
import threading

from harness.runtime.safety.approval import worker_approval_proof


_MAX_FRAME = 32 * 1024 * 1024


def _read(pipe):
    frame = pipe.readline(_MAX_FRAME + 1)
    if not frame:
        raise EOFError("The private worker pipe closed")
    if len(frame) > _MAX_FRAME or not frame.endswith(b"\n"):
        raise ValueError("Invalid private worker frame")
    return json.loads(frame)


def _write(pipe, value):
    frame = json.dumps(value, allow_nan=False, separators=(",", ":")).encode() + b"\n"
    if len(frame) > _MAX_FRAME:
        raise ValueError("Private worker frame is too large")
    # Unbuffered process pipes can write only part of a frame.
    view = memoryview(frame)
    while view:
        count = pipe.write(view)
        if not count:
            raise EOFError("The private worker pipe closed while writing")
        view = view[count:]
    pipe.flush()


def serve(api, incoming, outgoing):
    """Serve one request at a time. EOF ends the worker with its host."""
    sequence = 0
    while True:
        try:
            message = _read(incoming)
        except EOFError:
            return
        sequence += 1
        if message["sequence"] != sequence:
            raise ValueError("Unexpected private worker request sequence")
        request = message["request"]
        try:
            result = {"result": api.dispatch(request["method"], request["arguments"],
                                             approval_proof=message["proof"])}
        except Exception as error:
            result = {"error": f"{type(error).__name__}: {error}"}
        _write(outgoing, {"sequence": sequence, **result})


class WorkerRejected(RuntimeError):
    """The worker responded with an error on the expected RPC sequence."""


class WorkerPipe:
    """Host I/O for a single workspace lease. A failed exchange closes the stream to callers."""

    def __init__(self, process, key):
        self._key = key
        self._requests = Queue(maxsize=1)
        self._sequence = 0
        self._failed = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._exchange, args=(process,), daemon=True)
        self._thread.start()

    def request(self, method, arguments, *, timeout):
        with self._lock:
            if self._failed:
                raise RuntimeError("The private worker transport has ended")
            request = {"method": method, "arguments": arguments}
            proof = worker_approval_proof(self._key, request)
            future = Future()
            self._sequence += 1
            try:
                self._requests.put_nowait(({"sequence": self._sequence, "request": request, "proof": proof}, future))
            except Full:
                self._sequence -= 1
                raise RuntimeError("The worker still has a pending request") from None
            try:
                response = future.result(timeout=timeout)
            except TimeoutError:
                # A read-only receipt query can follow the outstanding delivery.
                raise
            except Exception:
                self._failed = True
                raise
        if "error" in response:
            raise WorkerRejected(response["error"])
        return response["result"]

    def close(self):
        # The process owner closes or kills the worker to wake any in-flight pipe I/O.
        # The queue sentinel also wakes an idle exchange thread on normal release.
        with self._lock:
            self._failed = True
            try:
                self._requests.put_nowait(None)
            except Full:
                pass  # Process termination wakes the queued exchange.

    def _exchange(self, process):
        while (job := self._requests.get()) is not None:
            message, future = job
            try:
                _write(process.stdin, message)
                response = _read(process.stdout)
                if response["sequence"] != message["sequence"] or ("result" in response) == ("error" in response):
                    raise ValueError("Invalid private worker reply")
                future.set_result(response)
            except Exception as error:
                future.set_exception(error)
                return
