"""Shared HTTP requests, cancellation and event-stream decoding."""

import json
from http.client import HTTPConnection, HTTPSConnection
import socket
import threading
from urllib.request import HTTPHandler, HTTPSHandler, Request, build_opener, urlopen


class Preempted(BaseException):
    """The caller cancelled the request. This must bypass provider retry handling."""


class RequestCancellation:
    """Cancel the current HTTP exchange and wake a retry wait."""

    def __init__(self):
        self.event = threading.Event()
        self._lock = threading.Lock()
        self._socket = None

    def check(self):
        if self.event.is_set():
            raise Preempted()

    def bind(self, sock):
        with self._lock:
            self._socket = sock
            self.check()

    def cancel(self):
        with self._lock:
            self.event.set()
            if self._socket is not None:
                try:
                    self._socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass  # The exchange already closed.

    def opener(self):
        # Bind before writing the request, including when urlopen handles a proxy or redirect.
        # Closing the response from another thread can block on its buffered reader.
        cancellation = self

        class Connection:
            def connect(self):
                cancellation.check()
                super().connect()
                try:
                    cancellation.bind(self.sock)
                except Preempted:
                    self.close()
                    raise

        class HTTP(Connection, HTTPConnection):
            pass

        class HTTPS(Connection, HTTPSConnection):
            pass

        class HttpHandler(HTTPHandler):
            def http_open(self, request):
                return self.do_open(HTTP, request)

        class HttpsHandler(HTTPSHandler):
            def https_open(self, request):
                return self.do_open(HTTPS, request, context=self._context)

        return build_opener(HttpHandler(), HttpsHandler()).open


def open_url(url, body=None, headers=None, timeout=60.0, *, cancellation=None):
    """The open response (a context manager) to a request to `url`: a POST of `body` as
    JSON (no NaN; numpy values as lists), a GET without one. urllib's HTTPError and
    URLError go to the caller, which says what failed."""
    data = None if body is None else json.dumps(body, allow_nan=False, default=_jsonable).encode()
    headers = {"user-agent": "the-harness", **({} if data is None else {"content-type": "application/json"}),
               **(headers or {})}
    opener = urlopen if cancellation is None else cancellation.opener()
    return opener(Request(url, data=data, headers=headers, method="GET" if data is None else "POST"), timeout=timeout)


def post_json(url, body, headers=None, timeout=60.0, *, cancellation=None):
    """POST `body` as JSON to `url` and return the JSON answer."""
    with open_url(url, body, headers, timeout, **({"cancellation": cancellation} if cancellation else {})) as response:
        return json.loads(response.read())


def read_sse(lines):
    """The events of a text/event-stream as they come, as (event, data): data is the
    event's data lines joined, event its event field ("message" without one). `lines` is
    a response or any iterable of byte lines. A comment (": keep-alive") comes as (None,
    its text), so a reader hears that the stream is alive."""
    event, data = None, []
    for raw in lines:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if data or event:
                yield event or "message", "\n".join(data)
            event, data = None, []
        elif line.startswith(":"):
            yield None, line[1:].strip()
        else:
            name, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if name == "data":
                data.append(value)
            elif name == "event":
                event = value
    if data:
        yield event or "message", "\n".join(data)


def _jsonable(value):
    """numpy arrays and scalars (a program's positions, say) as JSON values."""
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def redact(text, secret):
    if secret and secret in text:
        return text.replace(secret, "[redacted]")
    return text
