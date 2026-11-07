"""Isolated web browsing. No desktop input, user profile or system clipboard.

Playwright is imported only in the worker, on the thread serving its requests. Chrome
must already be installed; starting a worker never downloads a browser. The viewport
stays fixed when the activity panel asks for smaller previews. `locale` (a language tag such
as en-US; default the computer's) is the language its pages see and websites are asked for:
the context's locale (navigator.language, Accept-Language, Intl), and --lang for a Chrome of
its own. With $HARNESS_CHROME (a
shared Chrome's endpoint, benches/browser/chrome.py; the app's workspaces and
`harness run --workspaces` set it) the worker attaches to that Chrome and works in a
context of its own; without it, it starts a Chrome of its own.
"""

import base64
from collections import deque
import json
import os
import re
import signal
import time
from urllib.parse import urlsplit

from benches.computer.runtime import ComputerEnvironment, METHODS
from harness.sdk import PASS, ShieldResult, reject
from harness_computer.shield import DesktopShield

from .dom import BrowserDOM
from harness_computer.workspaces import browser_locale
from harness_computer.workspaces import CHROME_ENV, CHROME_PATH_ENV, LAYOUT_ENV, WINDOW_ENV


def create_environment(**options):
    unknown = set(options) - {"instruction", "max_side", "step_limit", "settle_seconds", "locale", "strict_input"}
    if unknown:
        raise ValueError(f"Unknown browser worker options: {sorted(unknown)}")
    # `harness serve` closes its environment in finally, including on worker shutdown.
    signal.signal(signal.SIGTERM, _shutdown)
    window = os.environ.get(WINDOW_ENV)
    return BrowserEnvironment(**options, chrome=os.environ.get(CHROME_ENV) or None,
                              window=tuple(int(value) for value in window.split(",")) if window else None,
                              layout=os.environ.get(LAYOUT_ENV) or None)


def _shutdown(*_):
    raise SystemExit(0)


KEYS = {"ctrl": "Control", "command": "Meta", "win": "Meta", "alt": "Alt", "option": "Alt",
        "shift": "Shift", "enter": "Enter", "return": "Enter", "tab": "Tab", "esc": "Escape",
        "escape": "Escape", "space": "Space", "backspace": "Backspace", "delete": "Delete",
        "del": "Delete", "home": "Home", "end": "End", "pageup": "PageUp", "pagedown": "PageDown",
        "up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft", "right": "ArrowRight"}


class BrowserShield(DesktopShield):
    def check(self, command, **context):
        if isinstance(command, dict) and command.get("type") == "navigate":
            url = command.get("url")
            try:
                target = urlsplit(url) if isinstance(url, str) and 0 < len(url) <= 8192 else None
                valid = (target is not None and target.scheme in ("http", "https") and bool(target.hostname)
                         and target.username is None and target.password is None
                         and not any(char.isspace() or ord(char) < 32 for char in url))
            except ValueError:
                valid = False
            if not valid or set(command) != {"type", "url"}:
                return reject({"check": "url", "reason": "navigate requires an http(s) URL, at most 8192 characters"})
            return ShieldResult(PASS, dict(command), [])
        result = super().check(command, **context)
        if result.command and command["type"] == "key":
            keys = command["keys"]
            if any(key not in KEYS and not (len(key) == 1 or key in {f"f{i}" for i in range(1, 13)}) for key in keys):
                return reject({"check": "keys", "reason": "unsupported browser key"})
            # Browser chrome (address bar/tabs) is absent. Never use the OS clipboard.
            if set(keys) & {"ctrl", "command", "win"} and set(keys) & {"c", "v", "x", "l", "t", "w", "n"}:
                return reject({"check": "keys", "reason": "use navigate()/read_page(); clipboard and browser-window shortcuts are unavailable"})
        return result


# Pixels of Chrome's own bar (tabs and address) above a page in a window of its own,
# until it is measured.
BAR = 87

# Where an agent's pointer rests in its page before its first click (CSS pixels).
REST = (36, 28)

# An agent's pointer in its window (browser windows shown, the agent named: the pointer
# method): an arrow in its colour with its name, drawn over the page where it clicks, never
# in the way (no events, hidden from assistive technology and from the page's text). Built
# with the DOM, so a page's content security policy lets it in.
POINTER = """([label, color]) => {
  const ID = "__harness_pointer";
  const make = () => {
    let host = document.getElementById(ID);
    if (host || !document.documentElement) return host;
    host = document.createElement("div");
    host.id = ID;
    host.setAttribute("aria-hidden", "true");
    Object.assign(host.style, { position: "fixed", left: "0", top: "0", zIndex: "2147483647", pointerEvents: "none",
                                display: "none", transition: "transform 0.22s ease-out" });
    const shadow = host.attachShadow({ mode: "closed" });
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    for (const [key, value] of Object.entries({ width: "22", height: "26", viewBox: "0 0 22 26" })) svg.setAttribute(key, value);
    Object.assign(svg.style, { display: "block", filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.35))" });
    const arrow = document.createElementNS("http://www.w3.org/2000/svg", "path");
    for (const [key, value] of Object.entries({ d: "M2 2 L2 21 L7 16.5 L10.5 24 L14 22.5 L10.5 15 L17 15 Z", fill: color,
                                                stroke: "#ffffff", "stroke-width": "1.6", "stroke-linejoin": "round" }))
      arrow.setAttribute(key, value);
    svg.appendChild(arrow);
    const name = document.createElement("span");
    name.textContent = label;
    Object.assign(name.style, { position: "absolute", left: "15px", top: "21px", padding: "2px 7px", borderRadius: "4px",
                                background: color, color: "#ffffff", font: "600 12px/1.4 system-ui, sans-serif",
                                whiteSpace: "nowrap", boxShadow: "0 1px 2px rgba(0,0,0,0.3)" });
    shadow.append(svg, name);
    document.documentElement.appendChild(host);
    return host;
  };
  // Show it at (x, y) of the page's window: it glides there from where it was.
  window.__harnessPointer = (x, y) => {
    const host = make();
    if (!host) return;
    if (host.style.display === "none") host.style.transition = "none";
    host.style.display = "block";
    host.style.transform = `translate(${x - 2}px, ${y - 2}px)`;
    host.getBoundingClientRect();
    host.style.transition = "transform 0.22s ease-out";
  };
}"""


class BrowserScreen:
    left = top = 0
    # How its steps are delivered: Chrome's input events (Playwright), never the desktop's.
    method = "CDP"

    def __init__(self, max_side=1920, chrome=None, locale=None, window=None, layout=None, fixture=None):
        # The shared Chrome's endpoint, or None: a Chrome of this worker's own.
        self.chrome = chrome
        # The language its pages see (None: the computer's).
        self.locale = None if browser_locale(locale) == "system" else browser_locale(locale)
        # Its window's place (x, y, width, height: browser windows shown), or None: headless;
        # how windows show (tiled, cascade).
        self.window = tuple(window) if window else None
        self.layout = layout if self.window else None
        self.fixture = fixture
        # The agent's pointer drawn in its window: (name, colour), or None.
        self.pointer = None
        if self.window:
            # The page fills the window under Chrome's own bar (measured once it shows).
            self.width, self.height = self.window[2], max(self.window[3] - BAR, 200)
        else:
            self.width = min(1440, max(640, int(max_side)))
            self.height = round(self.width * 0.625)
        self._playwright = self._browser = self._context = self._page = None
        self._capture_session = None
        self._position = (0, 0)
        self._documents = {}
        self._page_serial = 0
        self.dialogs = deque(maxlen=32)
        self._dialog_sequence = 0

    def _start(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            try:
                if self.chrome:
                    self._browser = self._playwright.chromium.connect(self.chrome)
                else:
                    place = ([f"--window-position={self.window[0]},{self.window[1]}",
                              f"--window-size={self.window[2]},{self.window[3]}"] if self.window else [])
                    path = os.environ.get(CHROME_PATH_ENV)
                    self._browser = self._playwright.chromium.launch(
                        **({"executable_path": path} if path else {"channel": "chrome"}),
                        # The fixture launcher already supplies a private network, PID and mount namespace.
                        headless=not self.window, chromium_sandbox=self.fixture is None,
                        args=([f"--lang={self.locale}"] if self.locale else []) + place)
            except Exception as error:
                self.close()
                if self.chrome:
                    raise RuntimeError(f"Could not attach to the shared background Chrome: {error}") from error
                raise RuntimeError("Could not start background Chrome. An installed Google Chrome is required: "
                                   f"{error}") from error
        if self._context is None:
            self._context = self._browser.new_context(viewport={"width": self.width, "height": self.height},
                                                     accept_downloads=False, permissions=[],
                                                     **({"service_workers": "block"} if self.fixture else {}),
                                                     **({"locale": self.locale} if self.locale else {}))
            self._context.set_default_timeout(10000)
            self._context.set_default_navigation_timeout(20000)
            if self.pointer and self.window:
                self._context.add_init_script(f"({POINTER})({json.dumps(list(self.pointer))})")
            if self.fixture:
                self.fixture.configure(self._context)
            self._context.on("page", self._new_page)
            self._context.new_page()

    def _new_page(self, page):
        self._page = page
        self._capture_session = None
        page.on("dialog", self._dismiss_dialog)
        page.on("close", lambda: self._documents.pop(page, None))
        if self.window:
            self._place(page)

    def _dismiss_dialog(self, dialog):
        dialog.dismiss()
        self._dialog_sequence += 1
        self.dialogs.append({"id": self._dialog_sequence, "type": dialog.type})

    @property
    def dom(self):
        page = self.page
        if page not in self._documents:
            self._page_serial += 1
            self._documents[page] = BrowserDOM(page, self._page_serial)
        return self._documents[page]

    def _place(self, page):
        """Put the window of `page` in this worker's tile and let the page fill it below
        Chrome's own bar."""
        try:
            session = page.context.new_cdp_session(page)
            target = session.send("Browser.getWindowForTarget")
            x, y, width, height = self.window
            session.send("Browser.setWindowBounds", {"windowId": target["windowId"],
                                                     "bounds": {"windowState": "normal"}})
            session.send("Browser.setWindowBounds", {"windowId": target["windowId"], "bounds": {
                "left": x, "top": y, "width": width, "height": height}})
            session.detach()
            bar = page.evaluate("outerHeight - innerHeight") or BAR
            self.width, self.height = width, max(height - int(bar), 200)
            page.set_viewport_size({"width": self.width, "height": self.height})
        except Exception:
            # The page still works where Chrome put it.
            pass

    @property
    def page(self):
        self._start()
        if self._page.is_closed():
            self._capture_session = None
            self._page = next((page for page in reversed(self._context.pages) if not page.is_closed()), None)
            if self._page is None:
                self._context.new_page()
        return self._page

    def reset(self):
        self._documents.clear()
        self.dialogs.clear()
        if self._context is not None:
            self._context.close()
            self._context = self._page = None
        self._position = (0, 0)
        self._start()

    def close(self):
        try:
            if self._context is not None:
                self._context.close()
            # An attached (shared) Chrome only disconnects; its other contexts go on.
            if self._browser is not None:
                self._browser.close()
        finally:
            if self._playwright is not None:
                self._playwright.stop()
            self._playwright = self._browser = self._context = self._page = None
            self._capture_session = None

    def grab(self, size, image_format):
        page = self.page
        # A page it came to since (a navigation) shows its pointer where it was.
        self.show_pointer()
        # Detaching a capture session clears Chrome's viewport emulation. Keep it
        # for this page; closing the episode's context closes its sessions as well.
        if self._capture_session is None:
            self._capture_session = self._context.new_cdp_session(page)
            self._capture_session.send("Emulation.setDeviceMetricsOverride", {
                "width": self.width, "height": self.height, "deviceScaleFactor": 1, "mobile": False,
            })
        session = self._capture_session
        viewport = session.send("Page.getLayoutMetrics")["cssVisualViewport"]
        request = {"format": image_format, **({"quality": 85} if image_format == "jpeg" else {}),
                   "captureBeyondViewport": False,
                   "clip": {"x": viewport["pageX"], "y": viewport["pageY"], "width": self.width, "height": self.height,
                            "scale": size[0] / self.width}}
        # A window just placed (the window manager still mapping or moving it) has no frame
        # to capture for a moment.
        for attempt in range(8 if self.window else 1):
            try:
                shot = session.send("Page.captureScreenshot", request)
                break
            except Exception as error:
                if "Unable to capture screenshot" not in str(error) or attempt == (7 if self.window else 0):
                    raise
                time.sleep(0.25)
        return base64.b64decode(shot["data"])

    def position(self):
        return self._position

    def show_pointer(self, x=None, y=None):
        """The agent's pointer drawn at (x, y) of its page (default: where it last was), when
        it has one. A page that cannot run it (still loading, gone) shows it on its next step."""
        if not self.pointer or not self.window:
            return
        # Until it clicks, it rests near the page's top left, its name readable.
        x, y = (x, y) if x is not None else (self._position if self._position != (0, 0) else REST)
        try:
            self.page.evaluate("([x, y]) => window.__harnessPointer && window.__harnessPointer(x, y)", [x, y])
        except Exception:
            pass

    def click(self, x, y, button, count):
        self.show_pointer(x, y)
        self.page.mouse.click(x, y, button=button, click_count=count)
        self._position = (x, y)

    def drag(self, x, y, to_x, to_y, seconds):
        self.show_pointer(x, y)
        mouse = self.page.mouse
        mouse.move(x, y)
        mouse.down()
        try:
            mouse.move(to_x, to_y, steps=max(1, round(seconds * 30)))
        finally:
            mouse.up()
        self._position = (to_x, to_y)

    def scroll(self, direction, amount, x=None, y=None):
        if x is not None:
            self.show_pointer(x, y)
            self.page.mouse.move(x, y)
            self._position = (x, y)
        delta = amount * 100 * (-1 if direction in ("up", "left") else 1)
        self.page.mouse.wheel(delta if direction in ("left", "right") else 0,
                              delta if direction in ("up", "down") else 0)

    def keys(self, keys):
        self.page.keyboard.press("+".join(KEYS.get(key, key.upper() if key.startswith("f") and len(key) > 1 else key)
                                          for key in keys))

    def paste(self, text):
        self.page.keyboard.insert_text(text)

    def active_window(self):
        return self.page.title()

    def front(self):
        """The active isolated page; navigation or title changes keep its identity."""
        return self.page

    def idle_seconds(self):
        """Host keyboard and mouse activity does not enter this isolated browser."""
        return None

    def failsafe(self):
        return BrowserStopped

    def read_page(self, offset, limit):
        # A page still navigating (a slow load, a redirect) destroys the context the query
        # runs in: wait for it to come, then read it once more.
        try:
            return self._read(offset, limit)
        except Exception as error:
            if "Execution context was destroyed" not in str(error):
                raise
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            return self._read(offset, limit)

    def _read(self, offset, limit):
        # A fixed read-only DOM query, never model-supplied JavaScript. Return bounded
        # visible text and links, retaining URL/title so answers can cite their source.
        return self.page.evaluate("""({offset, limit}) => {
            const text = document.body?.innerText || '';
            const links = Array.from(document.querySelectorAll('a[href]'))
                .filter(a => a.getClientRects().length && /^https?:/.test(a.href))
                .slice(0, 80).map(a => ({text: a.innerText.trim().slice(0, 160), url: a.href.slice(0, 8192)}));
            return {url: location.href, title: document.title, text: text.slice(offset, offset + limit),
                    offset, total_chars: text.length, next_offset: offset + limit < text.length ? offset + limit : null,
                    links};
        }""", {"offset": offset, "limit": limit})


class BrowserStopped(Exception):
    pass


class BrowserEnvironment(ComputerEnvironment):
    name = "background-browser"
    methods = (*METHODS, "page_text", "pointer")
    managed_control_calls = ComputerEnvironment.managed_control_calls | {"pointer"}
    # Its clicks and keys go to Chrome's page, never the user's mouse and keyboard: no
    # physical-input policy asks for them.
    own_input = True

    def __init__(self, instruction=None, max_side=1920, step_limit=300, settle_seconds=0.2, chrome=None,
                 locale=None, window=None, layout=None, fixture=None, strict_input=True):
        super().__init__(instruction=instruction, max_side=max_side, step_limit=step_limit,
                         settle_seconds=settle_seconds, strict_input=strict_input,
                         screen=BrowserScreen(max_side, chrome, locale, window, layout, fixture))
        self._shield = BrowserShield(self._shield.profile)
        self._fixture = fixture
        # A navigation still loading when it timed out (its URL), or one that failed (why),
        # until the next step.
        self._loading = None
        self._failed = None
        self._navigation_id = 0
        self._ready_document = self._loading_from = self._failed_document = None

    def call(self, name, arguments):
        if name not in self.methods:
            raise ValueError(f"Unknown browser worker method: {name}")
        return getattr(self, f"_call_{name}")(**arguments)

    def reset(self, task, seed):
        if task != "free":
            raise ValueError('The browser has one task: "free"')
        self._loading = self._failed = None
        self._navigation_id = 0
        self._ready_document = self._loading_from = self._failed_document = None
        self._screen.reset()
        return super().reset(task, seed)

    def close(self):
        super().close()
        self._screen.close()

    def _call_profile(self):
        return {**super()._call_profile(), "execution": "browser", "elements": True}

    def _call_pointer(self, label=None, color=None):
        """Draw the agent's pointer in its window from its next episode on: `label` its name
        (a1), `color` its lane's colour on the timeline (#rrggbb); None: no pointer drawn (the
        worker serves an agent that is not named). Headless: nothing to draw."""
        if label is None:
            self._screen.pointer = None
            return {"pointer": False}
        if not re.fullmatch(r"[A-Za-z0-9._ -]{1,24}", str(label)) or not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
            raise ValueError("pointer needs a short name (letters, digits, . _ -) and a colour #rrggbb")
        self._screen.pointer = (str(label), str(color))
        return {"pointer": bool(self._screen.window)}

    def _state(self):
        # Browser windows shown: where its window is on the screen, and how windows show (a
        # replay outlines tiled ones; overlapping ones show their agent's pointer instead).
        window = {"window": list(self._screen.window), "layout": self._screen.layout} if self._screen.window else {}
        try:
            observed = self._screen.dom.state()
        except Exception:
            observed = {}
        if ready := observed.get("page_ready"):
            self._ready_document = ready
            if ready != self._loading_from:
                self._loading = None
        if self._failed and observed.get("page_ready"):
            ready = observed["page_ready"]
            if self._failed_document is None:
                self._failed_document = ready
            if ready == self._failed_document:
                observed.pop("page_ready")
            else:
                self._failed = None
        return {**super()._state(), **observed, **window, "url": self._screen.page.url, "execution": "browser",
                "navigation_id": self._navigation_id, "browser_dialogs": list(self._screen.dialogs),
                **({"loading": self._loading} if self._loading else {}),
                **({"navigation_error": self._failed} if self._failed else {})}

    def _do(self, command):
        if command["type"] == "navigate":
            self._loading = self._failed = self._failed_document = None
            self._navigation_id += 1
            try:
                self._go(command["url"])
            except Exception as error:
                # The browser was sent there either way, so the step was delivered: a slow
                # page goes on loading (state "loading"); a page that could not be reached
                # (net::ERR_..., a server that does not answer) shows Chrome's error page
                # (state "navigation_error"). The next observation shows where it is. A
                # browser that is gone leaves the delivery unverified, as for any input.
                if type(error).__name__ == "TargetClosedError":
                    raise
                if type(error).__name__ == "TimeoutError":
                    self._loading = command["url"]
                    self._loading_from = self._ready_document
                else:
                    self._failed = str(error).split("\n")[0][:300]
        else:
            super()._do(command)

    def _go(self, url):
        """Request one navigation and observe readiness separately."""
        if self._fixture and url != self._fixture.url:
            raise ValueError("navigation leaves the fixture origin")
        self._screen.page.goto(url, wait_until="domcontentloaded")

    def _call_elements(self, episode_id, window=None, role=None, text=None, limit=200):
        self._check_episode(episode_id)
        if window is not None:
            raise ValueError("browser elements are in its current page")
        result = self._screen.dom.elements(role, text.lower() if text else None, max(1, min(int(limit), 1000)))
        rows = result["rows"]
        return {"elements": rows, "more": result["more"],
                "outline": "\n".join(f"{row['id']} {row['role']} {row['name']!r} [{', '.join(row['actions'])}]"
                                     for row in rows)}

    def _display_input(self, command, attempt):
        kind = command["type"]
        if kind not in ("act", "click", "type", "key"):
            return self._approval_target_changed() if attempt.pending is not None else self._do(command)
        window = {"app": "chrome", "title": self._screen.active_window(), "launched": True}
        if kind == "act":
            selector = {"id": command["element"]}
        elif kind == "click":
            x, y = self._physical_point(command["x"], command["y"])
            selector = {"x": x, "y": y}
        else:
            selector = {}
        try:
            dom = self._screen.dom
            target = dom.target(**selector)
        except Exception:
            target = None
        strict = self._managed_approval and self._strict_input
        if target is None and (kind == "act" or attempt.pending is not None or strict):
            return self._refused({"check": "element", "reason": "the browser could not resolve the live target"},
                                 window, mechanism="semantic")
        refusal = self._sensitive(command, target, window, attempt, route="browser")
        if refusal is not None:
            return refusal
        if kind == "act":
            action, value = command["action"], command.get("value")
        elif attempt.pending is None and (not strict or kind == "key"):
            return self._do(command)
        elif kind == "click" and command.get("button", "left") == "left" and command.get("count", 1) == 1:
            action, value = "click", None
        elif kind == "type" and not any(key in command["text"] for key in ("\t", "\n")):
            action, value = "insert_text", command["text"]
        else:
            return self._refused({"check": "sensitive", "reason": "use an explicit element action for this target"},
                                 window, mechanism="semantic")
        result = dom.act(target, action, str(value) if value is not None else None, **selector)
        if not result.get("delivered"):
            return self._refused({"check": "element", "reason": result["refused"]}, window, mechanism="semantic")

    def _call_page_text(self, episode_id, offset=0, limit=12000):
        self._cursor.check(episode_id, self._cursor.step)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 12000:
            raise ValueError("page_text needs offset >= 0 and limit between 1 and 12000")
        return self._screen.read_page(offset, limit)
