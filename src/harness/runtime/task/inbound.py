"""What the environment tells a run, pushed in.

A run keeps one entry for things that happen by themselves in its environment and that the
model must hear of: `TaskRun.tell(kind, detail, views=...)`. Whoever calls it puts the
event before the model at once (a wait ends, a call in flight is asked again), with the
pictures given beside the event's text. Nothing is read on time for it.

A worker reaches it over HTTP: when its profile says "tells", the run opens a listener on
this computer (one address and token for the run) and gives both to the worker
(`tell_to`); the worker's `tell()` (core/worker.py Tells) posts there.

    POST <url>   {"token", "kind", "source", "detail", "views": [{"caption", "image_url"}]}
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import secrets
import threading

# What one told event may carry: its JSON, pictures included.
MAX_BYTES = 32 * 1024 * 1024


class Inbound:
    """The listener of one run: `url` and `token` are what its worker is given."""

    def __init__(self, run):
        self.token = secrets.token_urlsafe(24)
        inbound = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                try:
                    length = int(self.headers.get("content-length") or 0)
                    if not 0 < length <= MAX_BYTES:
                        raise ValueError("an event is a JSON body")
                    told = json.loads(self.rfile.read(length))
                    if not hmac.compare_digest(str(told.get("token") or ""), inbound.token):
                        self.send_response(403)
                        self.end_headers()
                        return
                    run.tell(str(told["kind"]), told.get("detail"), source=str(told.get("source") or "environment"),
                             views=told.get("views") or ())
                    answer, status = b'{"told": true}', 200
                except Exception as error:
                    answer, status = json.dumps({"error": f"{type(error).__name__}: {error}"}).encode(), 400
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(answer)))
                self.end_headers()
                self.wfile.write(answer)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/tell"
        threading.Thread(target=self.server.serve_forever, name="harness-told", daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
