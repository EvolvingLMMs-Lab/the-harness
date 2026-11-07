"""A trusted local page trial. Only the host launches it and interprets the observations."""

import ast
import importlib.metadata
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import tomllib

from harness.sdk import sha256


PYTHON = "/opt/fixture-python/bin/python"
CHROME = "/opt/google/chrome/chrome"
ACTIONS = {"click", "press", "type_text"}
ACTION_SOURCE = "computer/skills/desktop/__init__.py"
MAX_TEXT = 12000


def describe(config):
    return (f"Browser fixture for {config['skill']}: propose a zero-argument function of that name "
            f"using literal click, press and type_text calls. Set test={config['skill'] + '()'!r}. "
            "Finish the proposing program so the host can verify the effect on its own page.")


def prepare(config, entry):
    """Read a single skill with literal actions and a test consisting of one invocation."""
    name, source, test = entry.name, entry.text, entry.test
    if entry.kind != "skill" or entry.attachments:
        raise ValueError("the browser fixture covers input skills without attachments")
    if set(config) != {"type", "skill", "html", "target", "before", "after", "bundle", "bundle_sha256"} or config["skill"] != name:
        raise ValueError("fixture needs a local page, input target, values and pinned runtime bundle")
    if not isinstance(config["html"], str) or not 0 < len(config["html"].encode()) <= 65536:
        raise ValueError("fixture HTML must be at most 64 KiB")
    before, after = config["before"], config["after"]
    if (not isinstance(config["target"], str) or not 0 < len(config["target"]) <= 200
            or not all(isinstance(text, str) and len(text) <= MAX_TEXT for text in (before, after)) or before == after):
        raise ValueError("fixture needs one input selector and distinct bounded values")
    if not test or len(test) > 256 or len(source) > 8192:
        raise ValueError("fixture needs a bounded skill and invocation")
    definitions = ast.parse(source).body
    if len(definitions) != 1 or not isinstance(definitions[0], ast.FunctionDef):
        raise ValueError("fixture needs a single function")
    definition = definitions[0]
    if (definition.name != name or definition.decorator_list or definition.returns or getattr(definition, "type_params", ())
            or ast.dump(definition.args) != ast.dump(ast.parse("def f(): pass").body[0].args)):
        raise ValueError("fixture skill must be a plain zero-argument function")
    if ast.dump(ast.parse(test)) != ast.dump(ast.parse(f"{name}()")):
        raise ValueError("fixture test must invoke the skill once")
    body = definition.body[1:] if ast.get_docstring(definition) is not None else definition.body
    if not 1 <= len(body) <= 16:
        raise ValueError("fixture skill needs one to sixteen actions")
    commands = []
    for statement in body:
        call = statement.value if isinstance(statement, ast.Expr) else None
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id not in ACTIONS
                or call.keywords or not all(isinstance(arg, ast.Constant) for arg in call.args)):
            raise ValueError("fixture supports only literal click, press and type_text calls")
        args = [arg.value for arg in call.args]
        action = call.func.id
        if action == "click":
            valid = len(args) == 2 and all(type(arg) is int and 0 <= arg <= 1920 for arg in args)
        elif action == "type_text":
            valid = len(args) == 1 and isinstance(args[0], str) and len(args[0]) <= 2000
        else:
            valid = 1 <= len(args) <= 3 and all(isinstance(arg, str) and 0 < len(arg) <= 12 for arg in args)
        if not valid:
            raise ValueError(f"unsupported fixture arguments for {action}")
        commands.append((action, args))
    return commands


def bindings(commands, sources):
    return tuple((action, "skills.desktop", "Desktop", sources[ACTION_SOURCE])
                 for action in sorted({action for action, _ in commands}))


class Page:
    """Serve a single document in memory. No route ever continues or fetches a request."""

    def __init__(self, url, html):
        self.url, self.html = url, html
        self.served = self.blocked = False
        self.page = None

    def configure(self, context):
        context.route("**/*", self._route)
        context.route_web_socket("**/*", self._socket)
        context.on("page", self._page)

    def _route(self, route):
        request = route.request
        if (self.served or request.url != self.url or request.method != "GET"
                or not request.is_navigation_request() or request.redirected_from is not None):
            self.blocked = True
            route.abort()
            return
        self.served = True
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=self.html, headers={
            "Content-Security-Policy": (
                "sandbox allow-scripts allow-same-origin; default-src 'none'; script-src 'none'; "
                "style-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'"),
            "Referrer-Policy": "no-referrer",
        })

    def _socket(self, socket):
        self.blocked = True
        socket.close()

    def _page(self, page):
        if self.page is not None:
            self.blocked = True
            page.close()
            return
        self.page = page
        page.on("download", self._download)
        page.on("framenavigated", self._navigated)

    def _download(self, download):
        self.blocked = True
        download.cancel()

    def _navigated(self, frame):
        if frame.url != self.url:
            self.blocked = True

    def watch_input(self, selector):
        """Watch a single editable control. Only trusted input on this node counts."""
        return self.page.evaluate_handle("""selector => {
            const matches = document.querySelectorAll(selector);
            if (matches.length !== 1) throw Error("fixture target must match one control");
            const target = matches[0];
            if (!(target instanceof HTMLTextAreaElement ||
                  target instanceof HTMLInputElement && ["text", "search", "email", "url", "tel"].includes(target.type))
                || target.disabled || target.readOnly) throw Error("fixture target must be editable text");
            let events = 0;
            target.addEventListener("input", event => { if (event.isTrusted) events++; });
            return () => ({url: location.href, value: target.value, events});
        }""", selector)


def _run(request):
    from benches.browser.runtime import BrowserEnvironment
    from skills.desktop import Desktop

    fixture = Page(request["url"], request["html"])
    worker = BrowserEnvironment(fixture=fixture, settle_seconds=0.1, step_limit=17)
    try:
        observation = worker.reset("free", 0)
        episode = observation.episode_id

        class Inputs(Desktop):
            step = observation.step

            def _input(self, skill, command):
                result = worker.call("tick", {"episode_id": episode, "step": self.step, "command": command})
                if result["executed"] is not True:
                    raise RuntimeError("fixture input rejected by worker shield")
                self.step = result["state"]["step"]

        inputs = Inputs()
        inputs._input("navigate", {"type": "navigate", "url": fixture.url})
        input_state = fixture.watch_input(request["target"])
        before = input_state.evaluate("read => read()")
        for action, arguments in request["actions"]:
            if action not in ACTIONS:
                raise ValueError("unsupported fixture input")
            getattr(inputs, action)(*arguments)
        after = input_state.evaluate("read => read()")
        return {"episode_id": episode, "before": before, "after": after,
                "blocked": fixture.blocked or not fixture.served, "steps": inputs.step}
    finally:
        worker.close()


def _command(root):
    """Mount only kernel interfaces. The executable and libraries are staged bytes."""
    script = """
set -eu
root="$1"
mount --bind "$root" "$root"
mount -o remount,bind,ro "$root"
mount --bind /proc "$root/proc"
mount -o remount,bind,ro "$root/proc"
for name in null zero random urandom; do
    mount --bind "/dev/$name" "$root/dev/$name"
done
mount -t tmpfs tmpfs "$root/tmp"
mount -t tmpfs tmpfs "$root/dev/shm"
exec chroot "$root" /usr/bin/setpriv --bounding-set=-all --inh-caps=-all --ambient-caps=-all \\
    --no-new-privs /opt/fixture-python/bin/python -P -s -B -m benches.browser.fixture
"""
    return ["unshare", "--map-current-user", "--mount", "--net", "--pid", "--mount-proc",
            "--kill-child", "--keep-caps", "--", "/bin/sh", "-c", script, "fixture", str(root)]


def supported():
    if sys.platform != "linux" or os.geteuid() == 0 or not all(
            shutil.which(tool, path="/usr/bin:/usr/sbin") for tool in ("unshare", "chroot", "setpriv")):
        raise RuntimeError("browser fixtures require unprivileged Linux namespaces")


def observe(config, actions, root, budget):
    """Observe a distinct worker over private pipes and reap it inside the deadline."""
    supported()
    url = f"https://{secrets.token_hex(16)}.invalid/"
    payload = json.dumps({"url": url, "html": config["html"], "target": config["target"], "actions": actions}).encode()
    env = {"PATH": "/usr/bin:/usr/sbin:/bin", "HOME": "/tmp", "TMPDIR": "/tmp",
           "PYTHONPATH": "/fixture/core:/fixture/browser:/fixture/computer",
           "HARNESS_PACKAGE_ROOTS": "/fixture/browser:/fixture/computer",
           "HARNESS_HOME": "/tmp/harness", "HARNESS_DATA": "/tmp/data", "HARNESS_CHROME_PATH": CHROME}
    for path in (PYTHON, CHROME, "/usr/bin/setpriv"):
        if not (root / path.lstrip("/")).is_file():
            raise ValueError("fixture bundle lacks its interpreter, browser or privilege dropper")
    for directory in ("tmp", "run", "dev/shm", "proc"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for device in ("null", "zero", "random", "urandom"):
        (root / "dev" / device).touch()
    budget.remaining(reserve=1)
    process = subprocess.Popen(_command(root), env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        while True:
            try:
                data, stderr = process.communicate(payload, timeout=min(0.05, budget.remaining(reserve=1)))
                break
            except subprocess.TimeoutExpired:
                payload = None
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=max(0, budget.deadline - time.monotonic()))
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("fixture process did not reap by its deadline") from error
        finally:
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()
    budget.remaining()
    if process.returncode:
        errors = stderr.decode("utf-8", errors="replace").splitlines()
        diagnostic = [line for line in errors if "Error:" in line or "FATAL:" in line]
        detail = " | ".join(diagnostic[-4:] or errors[-4:])[:1400]
        raise RuntimeError(f"isolated browser fixture exited with {process.returncode}: {detail}")
    return _verdict(config, actions, url, json.loads(data))


def _verdict(config, actions, url, result):
    before, after = result["before"], result["after"]
    if (result["blocked"] or before["url"] != url or after["url"] != url
            or result["steps"] != len(actions) + 1):
        raise RuntimeError("browser fixture left its page or returned incomplete observations")
    return {"ok": (before["events"] == 0 and after["events"] > 0
                   and before["value"] == config["before"] and after["value"] == config["after"]),
            "episode_id": result["episode_id"], "observation_sha256": sha256([before, after])}


if __name__ == "__main__":
    # The bench pins Playwright, including its browser request interception protocol.
    manifest = tomllib.loads(Path(__file__).with_name("bench.toml").read_text(encoding="utf-8"))
    if f"playwright=={importlib.metadata.version('playwright')}" not in manifest["environment"]["requirements"]:
        raise RuntimeError("unsupported fixture Playwright revision")
    print(json.dumps(_run(json.load(sys.stdin))), flush=True)
