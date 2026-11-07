"""The desktop's session: the episode core (runtime/execution/session.py) for a computer.

A desktop session connects to a desktop worker (profile, state, tick, observe). A step is
one input step; its command is an input event in screen pixels (runtime/safety/shield.py
DESKTOP_COMMANDS), which the worker's DesktopShield passes unchanged or rejects. Guards
observe the step and the time; an execution's scope is a window, for workers that report
the active window. The desktop skills' constants live here.

The screen moves without the agent (a dialog opens, a page loads), so the rules watch it
as needed, and their view carries the changes as `events`. Subscribed handlers
receive each change through the normal observation and event paths.

A step that uses the user's real mouse and keyboard may meet a physical-input policy that
asks the user first (harness/physical.py): the worker refuses it with a request, the
session puts the request to the user through the host (a note, physical_request; the
conversation asks in every frontend and sends the answer back, runtime/execution/control.py), gives
the answer to the worker, and sends the step once more when the user allowed it. How each
step was delivered and what it sent goes to the host as an `input` note, which the trace
keeps.
"""


from harness.sdk import EpisodeCore, Event, decode_data_url
from harness.sdk import PhysicalInput


class Screenshot:
    """A view of the screen: .image (RGB uint8 HxWx3), .size (width, height) and .state."""

    def __init__(self, data):
        self.state = data["state"]
        self._urls = data["images"]
        self.size = tuple(self.state.get("screen") or ())
        self._image = None

    @property
    def image(self):
        if self._image is None:
            import cv2
            import numpy as np

            raw = np.frombuffer(decode_data_url(self._urls["screen"]), dtype=np.uint8)
            self._image = cv2.cvtColor(cv2.imdecode(raw, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        return self._image

    def __repr__(self):
        return f"Screenshot(size={self.size}, step={self.state['step']})"


class DesktopSession(PhysicalInput, EpisodeCore):
    """The episode core for a computer: input-step commands, a screen, and a window as an
    execution's scope."""

    embodiment = "desktop"
    still_executions = ("hold", "wait")
    observation_event_kinds = frozenset({"window_opened", "window_closed", "dialog_appeared",
                                         "focus_changed", "page_loaded", "navigation_failed"})

    def _embodiment_setup(self, options):
        width, height = self.profile["screen"]
        self.screen = (int(width), int(height))
        self._ready_documents = set()

    def _base_command(self, state):
        return {"type": "noop"}

    def _dispatch_action(self, action_id, command, cameras, *, approval_id=None):
        identity = {"action_id": action_id} if self.profile.get("action_ids") else {}
        return self._tick(command, cameras, approval_id=approval_id, **identity)

    def _tick(self, command, cameras=None, *, approval_id=None, **identity):
        cursor = {"episode_id": self.episode_id, "step": self.state["step"]}
        if approval_id is None:
            extra = {"cameras": list(cameras)} if cameras else {}
            result = self.env.call("tick", command=command, **cursor, **extra, **identity)
        else:
            result = self.env.call("sensitive_approval", op="retry", id=approval_id, **cursor, **identity)
        return self._receive(command, result)

    def _receive(self, command, result):
        if result.get("observation") is not None:
            self._live = Screenshot(result["observation"])
        self.state = result["state"]
        return result

    def _record_receipt(self, command, result):
        if result.get("delivery"):
            self._note_input(command, result)

    def _reactive_view(self, state, tick):
        view = {"step": state["step"], "t": tick / self.hz, "screen": list(self.screen)}
        for key in ("active_window", "front", "url"):
            if key in state:
                view[key] = state[key]
        view["events"] = [dict(event) for event in self._observation_changes(state)]
        return view

    def _observation_changes(self, state):
        seen = self.__dict__.get("_seen_state")
        if seen is None or seen[0] is not state:
            changes = window_events(seen[0] if seen else None, state)
            if ready := state.get("page_ready"):
                if ready in self._ready_documents:
                    changes = [event for event in changes if event["kind"] != "page_loaded"]
                self._ready_documents.add(ready)
            seen = self._seen_state = (state, changes)
        return seen[1]

    def _take_observation_events(self, state):
        changes = self._observation_changes(state)
        if self.__dict__.get("_published_state") is state:
            return ()
        self._published_state = state
        return (Event(event["kind"], "environment", {k: v for k, v in event.items() if k != "kind"}, state["step"])
                for event in changes)

    def _outside(self, region, state):
        """region: {"window": text}, outside when the active window's title does not
        contain it, or another window whose title the agent may not know is in front."""
        if "active_window" not in state:
            if state.get("front") == "other":
                return True
            raise ValueError("This desktop does not report its active window: an execution cannot be scoped to one")
        return str(region["window"]) not in str(state["active_window"])


def window_events(before, after) -> list[dict]:
    """What changed on the screen from state `before` to `after` (None: nothing seen yet),
    as events for the rules: {"kind", ...}."""
    if before is None:
        return []
    events = []
    known = {row["id"]: row for row in before.get("windows") or ()}
    now = {row["id"]: row for row in after.get("windows") or ()}
    if "windows" in before and "windows" in after:
        for name, row in now.items():
            if name not in known:
                kind = "dialog_appeared" if row.get("dialog_of") else "window_opened"
                events.append({"kind": kind, "window": name, **{key: row[key] for key in ("title", "dialog_of")
                                                                 if row.get(key)}})
        closed = set(after.get("closed_windows", ()))
        events += [{"kind": "window_closed", "window": name} for name in known if name in closed]
    focus = after.get("focus_id")
    if (after.get("front"), focus or after.get("active_window")) != (
            before.get("front"), before.get("focus_id") or before.get("active_window")):
        events.append({"kind": "focus_changed", "front": after.get("front"), "target": focus,
                       "title": after.get("active_window")})
    if after.get("page_ready") is not None and after["page_ready"] != before.get("page_ready"):
        events.append({"kind": "page_loaded", "page": after["page_ready"], "url": after["url"]})
    if after.get("navigation_error") and after.get("navigation_id") != before.get("navigation_id"):
        events.append({"kind": "navigation_failed", "reason": after["navigation_error"], "url": after.get("url")})
    old_dialogs = {dialog["id"] for dialog in before.get("browser_dialogs", ())}
    events.extend({"kind": "dialog_appeared", "dialog": dialog, "dismissed": True}
                  for dialog in after.get("browser_dialogs", ()) if dialog["id"] not in old_dialogs)
    return events
