"""The computer's input steps, screenshots, show() and finish(): what every desktop program
needs. Each input step is one bounded execution of one step, which the worker's shield
passes unchanged or rejects (SHIELD_REJECTED).

Where the worker reaches windows (its profile's `windows`: a desktop backend,
harness/desktop), steps also go to one window in the background: windows(), launch() and
use_window() pick it, elements() reads its accessibility tree (element ids e1, e2, ...),
act() does an element's action, and the input steps take `window` (points in that
window's picture). Window selection and launch use the same bounded execution.
Read-only queries return observations."""

import re

from harness.sdk import ProgramFinished
from harness.sdk import input_sent
from harness_computer.session import Screenshot


class Desktop:
    def finish(self, summary="", infeasible=False):
        """End the episode now: the program's own checks say the task is done, or, with
        infeasible=True on a bench whose tasks may be impossible (the profile's
        `infeasible`), that it cannot be done. No further model call follows."""
        if infeasible:
            if not self.profile.get("infeasible"):
                raise ValueError("This bench's tasks can all be done: finish() without infeasible")
            self.env.call("declare_infeasible", episode_id=self.episode_id, reason=str(summary))
        raise ProgramFinished(summary)

    def _wrap_up(self):
        """After the episode is finished: a desktop leaves everything as it is."""
        return []

    def get_state(self):
        """The computer's state, read fresh: step, ended, screen [width, height], step_limit
        when the connection reports it, and the window in front: front "own" (yours, its
        title active_window) or "other" (the user's, named only as far as they allow)."""
        self.state = self.env.call("state", episode_id=self.episode_id)
        return self.state

    def get_observation(self):
        """The screen now as a Screenshot: .image (RGB uint8 HxWx3), .size (width, height)
        and .state."""
        data = self.env.call("observe", episode_id=self.episode_id, cameras=["screen"])
        self.state = data["state"]
        return Screenshot(data)

    def click(self, x, y=None, button="left", count=1, window=None):
        """Click at pixel (x, y): button "left" or "right", count 1 or 2 (left only). With
        `window`, (x, y) is in that window's picture and the click goes to it in the
        background. click("e12") is act("e12")."""
        if y is None and _element(x):
            if button != "left" or count != 1 or window is not None:
                raise ValueError("element clicks take only an element id")
            return self.act(x)
        command = {"type": "click", "x": x, "y": y, "button": button, "count": count}
        return self._input("click", _to(command, window))

    def drag(self, x, y, to_x, to_y, seconds=0.4, window=None):
        """Press the left button at (x, y), move to (to_x, to_y) in `seconds`, release."""
        return self._input("drag", _to({"type": "drag", "x": x, "y": y, "to_x": to_x, "to_y": to_y,
                                        "duration_ms": int(round(float(seconds) * 1000))}, window))

    def scroll(self, direction, amount=5, x=None, y=None, window=None):
        """Scroll "up", "down", "left" or "right" by `amount` wheel clicks, over (x, y) when
        given (else where the pointer is)."""
        command = {"type": "scroll", "direction": direction, "amount": amount}
        if x is not None or y is not None:
            command.update(x=x, y=y)
        return self._input("scroll", _to(command, window))

    def type_text(self, text, window=None):
        """Type `text` key by key where the keyboard focus is (printable ASCII, newline
        and tab)."""
        return self._input("type_text", _to({"type": "type", "text": text}, window))

    def press(self, *keys, window=None):
        """Press keys together and release them: press("enter"), press("ctrl", "s")."""
        return self._input("press", _to({"type": "key", "keys": list(keys)}, window))

    def wait(self, seconds=1.0):
        """Wait `seconds` (one step) for the screen to settle."""
        return self._input("wait", {"type": "wait", "ms": int(round(float(seconds) * 1000))})

    # -- Windows and their elements (a worker whose profile has `windows`) ---------------

    def windows(self):
        """Your windows (launched, or worked in), and the user's as far as they let you know
        them (by default none): [{"id", "app", "title", "size" (its picture), and
        minimized, offscreen, launched, foreground, dialog_of where they hold}]."""
        return self._windows_call("windows")["windows"]

    def use_window(self, window, visible=None):
        """Work in `window` (an id of windows()): it becomes yours (refused while another
        agent works in it); in an apps workspace your screenshots show it and steps without
        a window go to it. visible=True moves a window you launched onto the user's screens,
        False off them, without taking their focus. Returns its row."""
        self._require_windows()
        command = {"type": "use_window", "window": window}
        if visible is not None:
            command["visible"] = bool(visible)
        trace = self._input("use_window", command)
        return (trace.result or {}).get("window") if trace.ok else None

    def launch(self, app, *args, visible=False):
        """Start an application (a program name such as "notepad", "chrome", "code"; on macOS
        an app's name such as "TextEdit"; or a path) with `args`, and work in its window: it
        starts off the user's screens and without their focus unless `visible`. Returns its
        row."""
        self._require_windows()
        trace = self._input("launch", {"type": "launch", "app": app, "args": list(args), "visible": bool(visible)},
                            max_seconds=60.0)
        return (trace.result or {}).get("window") if trace.ok else None

    def elements(self, window=None, role=None, text=None, limit=200):
        """The elements of `window` (yours by default): [{"id", "role", "name", "value",
        "rect" (in the window's picture), "actions", "states"}], those of `role` ("button",
        "edit", ...) and with `text` in their name or value, at most `limit`; printed, one
        outline line each (`e7 button "Save" [invoke]`)."""
        if not self.profile.get("elements"):
            self._require_windows()
        result = self.env.call("elements", episode_id=self.episode_id, window=window, role=role, text=text, limit=limit)
        if result.get("more"):
            print(f"elements(): {len(result['elements'])} listed, {result['more']} more left out; filter with role= or "
                  f"text=, or pass a larger limit= (at most 1000)")
        return Elements(result["elements"], result.get("outline") or "")

    def act(self, element, action="click", value=None):
        """Do an element's action in the background: "click" (what a click on it does),
        "invoke", "toggle", "select", "expand", "collapse", "set_value" (value: its new text
        or number; on a page's file input, the file's path), "scroll_into_view"."""
        command = {"type": "act", "element": element, "action": action}
        if value is not None:
            command["value"] = value
        return self._input(f"act_{action}", command)

    def _require_windows(self):
        if not self.profile.get("windows"):
            raise RuntimeError("this computer gives no access to its windows (the screen's steps work)")

    def _windows_call(self, name, **arguments):
        self._require_windows()
        return self.env.call(name, episode_id=self.episode_id, **arguments)

    def _input(self, skill, command, max_seconds=None):
        """One input step as a bounded execution: COMPLETED when the worker executed it."""
        sent = []

        def step(state, tick):
            if sent:
                return None
            sent.append(command)
            return command

        return self._execute(skill, input_sent(command), step,
                             max_seconds=max_seconds if max_seconds is not None else 2.0 / self.hz,
                             region=None, until=None)


class Elements(list):
    """elements()'s rows; printed, their outline lines."""

    def __init__(self, rows, outline):
        super().__init__(rows)
        self.outline = outline

    def __str__(self):
        return self.outline or "(no elements)"


def _element(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"e\d+(?:_\d+_\d+)?", value) is not None


def _to(command, window):
    """A step into `window` (its id), when one is given."""
    return {**command, "window": window} if window is not None else command


def exports(session):
    return {"finish": session.finish, "__wrap_up__": session._wrap_up, "get_state": session.get_state,
            "get_observation": session.get_observation, "show": session.show, "click": session.click,
            "drag": session.drag, "scroll": session.scroll, "type_text": session.type_text,
            "press": session.press, "wait": session.wait, "windows": session.windows,
            "use_window": session.use_window, "launch": session.launch, "elements": session.elements,
            "act": session.act, "SCREEN": session.screen}
