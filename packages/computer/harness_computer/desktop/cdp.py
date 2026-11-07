"""A small client of the Chrome DevTools Protocol over its WebSocket: what the desktop
backends drive a Chromium or Electron app with, when the agent launched it with a
debugging port. Standard library only."""

import base64
import json
from pathlib import Path
import os
import re
import socket
import struct
import threading
from urllib.parse import urlparse


class DevTools:
    """One connection to a browser's DevTools endpoint (ws://127.0.0.1:PORT/devtools/
    browser/ID). call() sends a command, to a page through its session, and waits for
    its answer; events that arrive meanwhile are dropped."""

    def __init__(self, url: str, timeout: float = 10.0):
        parts = urlparse(url)
        if parts.scheme != "ws" or parts.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(f"a local DevTools endpoint is ws://127.0.0.1:PORT/..., not {url!r}")
        self.url = url
        self._sock = socket.create_connection((parts.hostname, parts.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        self._sock.sendall((f"GET {parts.path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n"
                            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode("ascii"))
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("DevTools closed the connection during the handshake")
            head += chunk
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise ConnectionError(f"DevTools refused the connection: {status.decode('latin-1')}")
        self._rest = head.split(b"\r\n\r\n", 1)[1]
        self._id = 0
        self._lock = threading.Lock()
        self._sessions = {}
        # What is being typed in a page's address bar (dispatch): {session: text}.
        self.address = {}

    def call(self, method: str, params: dict | None = None, session: str | None = None) -> dict:
        with self._lock:
            self._id += 1
            message = {"id": self._id, "method": method, "params": params or {}}
            if session:
                message["sessionId"] = session
            self._send(1, json.dumps(message).encode("utf-8"))
            while True:
                reply = self._message()
                if reply.get("id") == self._id:
                    if "error" in reply:
                        raise RuntimeError(f"DevTools {method}: {reply['error'].get('message', reply['error'])}")
                    return reply.get("result", {})

    def pages(self) -> list[dict]:
        """The browser's pages: targetId, title, url."""
        return [target for target in self.call("Target.getTargets")["targetInfos"] if target["type"] == "page"]

    def session(self, target: str) -> str:
        """A session on page `target` (made once). Its file inputs open no native dialog (the
        file chooser is intercepted): a file is given with set_value()."""
        if target not in self._sessions:
            session = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
            try:
                self.call("Page.enable", {}, session)
                self.call("Page.setInterceptFileChooserDialog", {"enabled": True}, session)
            except RuntimeError:
                pass
            self._sessions[target] = session
        return self._sessions[target]

    def close(self) -> None:
        try:
            self._send(8, b"")
        except OSError:
            pass
        self._sock.close()

    # -- WebSocket frames (RFC 6455; a client masks what it sends) --------------------

    def _send(self, opcode: int, payload: bytes) -> None:
        header = bytes([0x80 | opcode])
        size = len(payload)
        if size < 126:
            header += bytes([0x80 | size])
        elif size < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", size)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", size)
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._sock.sendall(header + mask + masked)

    def _read(self, size: int) -> bytes:
        while len(self._rest) < size:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("DevTools closed the connection")
            self._rest += chunk
        data, self._rest = self._rest[:size], self._rest[size:]
        return data

    def _message(self) -> dict:
        parts = b""
        while True:
            first, second = self._read(2)
            opcode, size = first & 0x0F, second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._read(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._read(8))[0]
            if second & 0x80:
                mask = self._read(4)
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(self._read(size)))
            else:
                payload = self._read(size)
            if opcode == 9:
                self._send(10, payload)
                continue
            if opcode == 8:
                raise ConnectionError("DevTools closed the connection")
            if opcode == 10:
                continue
            parts += payload
            if first & 0x80:
                return json.loads(parts.decode("utf-8"))


# Key names (runtime/safety/shield.py KEY_NAMES) as DevTools' key events want them: key, code,
# Windows virtual-key code.
KEYS = {"enter": ("Enter", "Enter", 13), "return": ("Enter", "Enter", 13), "tab": ("Tab", "Tab", 9),
        "backspace": ("Backspace", "Backspace", 8), "delete": ("Delete", "Delete", 46), "del": ("Delete", "Delete", 46),
        "esc": ("Escape", "Escape", 27), "escape": ("Escape", "Escape", 27), "space": (" ", "Space", 32),
        "up": ("ArrowUp", "ArrowUp", 38), "down": ("ArrowDown", "ArrowDown", 40),
        "left": ("ArrowLeft", "ArrowLeft", 37), "right": ("ArrowRight", "ArrowRight", 39),
        "home": ("Home", "Home", 36), "end": ("End", "End", 35), "pageup": ("PageUp", "PageUp", 33),
        "pgup": ("PageUp", "PageUp", 33), "pagedown": ("PageDown", "PageDown", 34),
        "pgdn": ("PageDown", "PageDown", 34), "insert": ("Insert", "Insert", 45)}
MODIFIERS = {"alt": 1, "altleft": 1, "altright": 1, "option": 1, "optionleft": 1, "optionright": 1, "ctrl": 2,
             "ctrlleft": 2, "ctrlright": 2, "command": 4, "win": 4, "winleft": 4, "winright": 4, "shift": 8,
             "shiftleft": 8, "shiftright": 8}


def key_event(name: str) -> dict:
    """The fields of DevTools' Input.dispatchKeyEvent for one key name."""
    name = name.lower()
    if name in KEYS:
        key, code, vk = KEYS[name]
    elif len(name) >= 2 and name[0] == "f" and name[1:].isdigit():
        key, code, vk = name.upper(), name.upper(), 111 + int(name[1:])
    elif len(name) == 1:
        key, vk = name, ord(name.upper()) if name.isalnum() else 0
        code = f"Key{name.upper()}" if name.isalpha() else (f"Digit{name}" if name.isdigit() else "")
    else:
        raise ValueError(f"no DevTools key for {name!r}")
    return {"key": key, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}


def devtools_url(launched: dict) -> str | None:
    """The browser endpoint of an app launched with --remote-debugging-port=0: from its
    profile's DevToolsActivePort (a Chromium), else what it printed (an Electron app)."""
    profile = launched.get("profile")
    if profile:
        try:
            port, path = (Path(profile) / "DevToolsActivePort").read_text(encoding="utf-8").split()[:2]
            return f"ws://127.0.0.1:{int(port)}{path}"
        except (OSError, ValueError):
            pass
    return launched.get("url")


def page_session(devtools: DevTools, title: str | None) -> str:
    """A session on the page whose title is `title`, else the first page."""
    pages = devtools.pages()
    if not pages:
        raise RuntimeError("the app shows no page")
    page = next((page for page in pages if page.get("title") == title), None) or pages[0]
    return devtools.session(page["targetId"])


# The keys that put a browser's focus in its address bar (a person's: ctrl+l, alt+d, f6).
ADDRESS_KEYS = ({"ctrl", "l"}, {"command", "l"}, {"alt", "d"}, {"f6"})


def dispatch(devtools: DevTools, session: str, event: dict, css, centre) -> None:
    """Send one input event (desktop.EVENTS, its points on the screen) to a page:
    `css(x, y)` maps a screen point to the page's CSS pixels, `centre` is the screen point
    a scroll without one goes to. Input over DevTools reaches the page, never the browser's
    own bar, so the address bar's keys are done here: after ctrl+l (alt+d, f6), what is
    typed is the address, enter goes there (navigate), escape or any other input is the
    page's again."""
    kind = event["type"]
    if _address(devtools, session, event):
        return

    def mouse(kind_, x, y, **extra):
        devtools.call("Input.dispatchMouseEvent", {"type": kind_, "x": x, "y": y, **extra}, session)

    if kind == "click":
        x, y = css(event["x"], event["y"])
        button = event.get("button", "left")
        mouse("mouseMoved", x, y)
        for count in range(1, int(event.get("count", 1)) + 1):
            mouse("mousePressed", x, y, button=button, clickCount=count)
            mouse("mouseReleased", x, y, button=button, clickCount=count)
    elif kind == "drag":
        x, y = css(event["x"], event["y"])
        to_x, to_y = css(event["to_x"], event["to_y"])
        mouse("mousePressed", x, y, button="left", clickCount=1)
        for number in range(1, 9):
            mouse("mouseMoved", x + (to_x - x) * number / 8, y + (to_y - y) * number / 8, button="left", buttons=1)
        mouse("mouseReleased", to_x, to_y, button="left", clickCount=1)
    elif kind == "scroll":
        point = (event["x"], event["y"]) if event.get("x") is not None else centre
        x, y = css(*point)
        step = 100 * int(event.get("amount", 5))
        dx, dy = {"up": (0, -step), "down": (0, step), "left": (-step, 0), "right": (step, 0)}[event["direction"]]
        mouse("mouseWheel", x, y, deltaX=dx, deltaY=dy)
    elif kind == "type":
        piece = ""
        for char in event["text"] + "\0":
            if char in "\n\t\0":
                if piece:
                    devtools.call("Input.insertText", {"text": piece}, session)
                    piece = ""
                if char != "\0":
                    press(devtools, session, ["enter" if char == "\n" else "tab"])
            else:
                piece += char
    elif kind == "key":
        press(devtools, session, event["keys"])
    else:
        raise ValueError(f"an input event is one of click, drag, scroll, type, key, not {kind!r}")


def _address(devtools: DevTools, session: str, event: dict) -> bool:
    """Whether `event` was the address bar's (its keys, typing an address, enter)."""
    keys = {key.lower() for key in event.get("keys", ())} if event["type"] == "key" else set()
    if keys in ADDRESS_KEYS:
        devtools.address[session] = ""
        return True
    typed = devtools.address.get(session)
    if typed is None:
        return False
    if event["type"] == "type":
        text, enter, _ = event["text"].partition("\n")
        devtools.address[session] = typed + text
        if enter:
            navigate(devtools, session, devtools.address.pop(session))
        return True
    if keys in ({"enter"}, {"return"}):
        navigate(devtools, session, devtools.address.pop(session))
        return True
    if keys == {"backspace"}:
        devtools.address[session] = typed[:-1]
        return True
    if keys in ({"ctrl", "a"}, {"command", "a"}):
        devtools.address[session] = ""
        return True
    # Escape, a click or other keys: back to the page (escape is the bar's only).
    devtools.address.pop(session, None)
    return keys == {"escape"}


def navigate(devtools: DevTools, session: str, address: str) -> None:
    """Load `address` in the page (a bare host is https://)."""
    address = address.strip()
    if not address:
        return
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", address):
        address = "https://" + address
    devtools.call("Page.navigate", {"url": address}, session)


def press(devtools: DevTools, session: str, keys) -> None:
    """A key, or a combination with modifiers, pressed in a page."""
    keys = [key.lower() for key in keys]
    modifiers = sum({value for key, value in MODIFIERS.items() if key in keys})
    main = [key for key in keys if key not in MODIFIERS] or keys[-1:]
    fields = key_event(main[-1])
    text = {"enter": "\r", "return": "\r", "tab": "\t", "space": " "}.get(main[-1], main[-1] if len(main[-1]) == 1
                                                                        else "")
    down = {"type": "keyDown" if text and not modifiers & 7 else "rawKeyDown", "modifiers": modifiers, **fields}
    if text and not modifiers & 7:
        down["text"] = text
    devtools.call("Input.dispatchKeyEvent", down, session)
    devtools.call("Input.dispatchKeyEvent", {"type": "keyUp", "modifiers": modifiers, **fields}, session)


# Chromium's accessibility roles (Accessibility.queryAXTree) of the fields a value is typed into.
TYPED_ROLES = ("textbox", "searchbox", "combobox", "spinbutton")


def node_of(devtools: DevTools, session: str, name: str, near, typed: bool = False) -> int:
    """The DOM node (backendNodeId) of the page's element whose accessible name is `name`
    (a field a value is typed into, or a file input, when `typed`); of several, the one
    nearest `near` (x, y in the page's CSS pixels, of its viewport). How an element of the
    accessibility tree (AT-SPI) is found in the page: by its name and its place. A file
    input's AT-SPI name carries what it holds after its label ("Attach: No file chosen")."""
    root = devtools.call("DOM.getDocument", {"depth": 0}, session)["root"]["nodeId"]
    found = []
    for each in dict.fromkeys([name, *([name.rsplit(": ", 1)[0]] if ": " in name else [])]):
        found = [node["backendDOMNodeId"] for node in devtools.call(
            "Accessibility.queryAXTree", {"nodeId": root, "accessibleName": each}, session).get("nodes", [])
                 if node.get("backendDOMNodeId") and not node.get("ignored")
                 and (not typed or (node.get("role") or {}).get("value") in TYPED_ROLES
                      or file_input(devtools, session, node["backendDOMNodeId"]))]
        if found:
            break
    if not found:
        raise RuntimeError(f"the page has no {'field' if typed else 'element'} named {name!r}")

    def distance(node):
        try:
            quad = devtools.call("DOM.getBoxModel", {"backendNodeId": node}, session)["model"]["border"]
        except (RuntimeError, KeyError):
            return float("inf")
        return abs((quad[0] + quad[4]) / 2 - near[0]) + abs((quad[1] + quad[5]) / 2 - near[1])

    return min(found, key=distance)


def scroll_into_view(devtools: DevTools, session: str, node: int) -> None:
    devtools.call("DOM.scrollIntoViewIfNeeded", {"backendNodeId": node}, session)


def file_input(devtools: DevTools, session: str, node: int) -> bool:
    described = devtools.call("DOM.describeNode", {"backendNodeId": node}, session)["node"]
    attributes = described.get("attributes") or []
    return described.get("localName") == "input" and dict(zip(attributes[::2], attributes[1::2])).get("type") == "file"


def file_inputs(devtools: DevTools, session: str) -> list[tuple]:
    """The page's file inputs, in document order: (accessible name, the names of the files
    they hold)."""
    root = devtools.call("DOM.getDocument", {"depth": 0}, session)["root"]["nodeId"]
    found = []
    for node in devtools.call("DOM.querySelectorAll", {"nodeId": root, "selector": "input[type=file]"},
                              session)["nodeIds"]:
        about = devtools.call("Accessibility.getPartialAXTree", {"nodeId": node, "fetchRelatives": False},
                              session)["nodes"]
        name = ((about[0].get("name") or {}).get("value") if about else "") or ""
        held = devtools.call("Runtime.callFunctionOn", {
            "objectId": devtools.call("DOM.resolveNode", {"nodeId": node}, session)["object"]["objectId"],
            "functionDeclaration": "function () { return [...this.files].map(file => file.name).join(', '); }",
            "returnByValue": True}, session)["result"].get("value") or ""
        found.append((name, held))
    return found


def set_value(devtools: DevTools, session: str, node: int, value, home=None) -> str:
    """Field `node`'s text replaced as typing does (the page gets its input events): shown,
    focused, its text selected, then `value` inserted (an empty value deletes the text). A file
    input gets the file at path `value` instead (~ is `home`, the browser's), as a person's
    choice in its dialog gives it (the page gets its change event). Says how."""
    if file_input(devtools, session, node):
        path = str(value)
        if path == "~" or path.startswith("~/"):
            path = str(home or Path.home()) + path[1:]
        devtools.call("DOM.setFileInputFiles", {"files": [path] if path else [], "backendNodeId": node}, session)
        return "DevTools DOM.setFileInputFiles"
    scroll_into_view(devtools, session, node)
    devtools.call("DOM.focus", {"backendNodeId": node}, session)
    field = devtools.call("DOM.resolveNode", {"backendNodeId": node}, session)["object"]["objectId"]
    devtools.call("Runtime.callFunctionOn", {"objectId": field, "functionDeclaration": (
        "function () { if (this.select) this.select(); else document.execCommand('selectAll'); }")}, session)
    if str(value):
        devtools.call("Input.insertText", {"text": str(value)}, session)
    else:
        press(devtools, session, ["delete"])
    return "DevTools Input.insertText"
