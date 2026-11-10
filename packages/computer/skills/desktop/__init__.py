"""The computer's input steps, screenshots, show() and finish(): what every desktop program
needs. Each input step is one bounded execution of one step, which the worker's shield
passes unchanged or rejects (SHIELD_REJECTED).

Background window APIs live in the separate windowtools skill."""

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

    def _evidence(self):
        """What this computer reports as text for a claim: the elements of the window in
        use, and a background browser's page text."""
        parts = []
        try:
            if self.profile.get("elements") or self.profile.get("windows"):
                result = self.env.call("elements", episode_id=self.episode_id, window=None, role=None, text=None,
                                       limit=150)
                if result.get("outline"):
                    parts.append("Elements:\n" + result["outline"])
        except Exception:
            pass
        if "browser" in getattr(self, "skills", ()):
            try:
                page = self.env.call("page_text", episode_id=self.episode_id, offset=0, limit=6000)
                parts.append(f"Page {page.get('url')} ({page.get('title')}):\n{page.get('text')}")
            except Exception:
                pass
        return "\n".join(parts)

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

    def click(self, x, y, button="left", count=1):
        """Click screenshot coordinates using the screen's real pointer."""
        return self._input("click", {"type": "click", "x": x, "y": y, "button": button, "count": count})

    def drag(self, x, y, to_x, to_y, seconds=0.4):
        """Drag the real pointer between screenshot coordinates."""
        return self._input("drag", {"type": "drag", "x": x, "y": y, "to_x": to_x, "to_y": to_y,
                                    "duration_ms": int(round(float(seconds) * 1000))})

    def scroll(self, direction, amount=5, x=None, y=None):
        """Scroll the real pointer's wheel, optionally at screenshot coordinates."""
        command = {"type": "scroll", "direction": direction, "amount": amount}
        if x is not None or y is not None:
            command.update(x=x, y=y)
        return self._input("scroll", command)

    def type_text(self, text):
        """Enter text at the current foreground keyboard focus."""
        return self._input("type_text", {"type": "type", "text": text})

    def press(self, *keys):
        """Press and release real keyboard keys together."""
        return self._input("press", {"type": "key", "keys": list(keys)})

    def wait(self, seconds=1.0):
        """Wait `seconds` (one step) for the screen to settle."""
        return self._input("wait", {"type": "wait", "ms": int(round(float(seconds) * 1000))})

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


def _element(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"e\d+(?:_\d+_\d+)?", value) is not None


def _to(command, window):
    """A step into `window` (its id), when one is given."""
    return {**command, "window": window} if window is not None else command


def exports(session):
    result = {"finish": session.finish, "__wrap_up__": session._wrap_up, "get_state": session.get_state,
            "get_observation": session.get_observation, "show": session.show, "click": session.click,
            "drag": session.drag, "scroll": session.scroll, "type_text": session.type_text,
            "press": session.press, "wait": session.wait, "SCREEN": session.screen}
    # All skill mixins exist on a session. Bind the exposed input API to the worker's
    # capabilities, rather than depending on the mixins' method resolution order.
    inputs = Desktop
    if session.profile.get("windows") or session.profile.get("elements"):
        from skills.windowtools import WindowTools
        inputs = WindowTools
    for name in ("click", "drag", "scroll", "type_text", "press"):
        result[name] = getattr(inputs, name).__get__(session)
    return result
