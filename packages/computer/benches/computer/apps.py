"""The computer worker's windows (harness/desktop): what an agent works in when its steps
go to a window instead of the whole screen.

A Desk keeps, for one worker's episode, the ids of the windows (w1, w2, ...) and elements
(e1, e2, ...) the agent was shown, the window it works in (the current one: an apps
workspace shows it instead of the screen), and each window's picture: its frame scaled
to at most `max_side` pixels on the long side, in whose pixels the agent's points into
that window are. It also remembers which windows its backend launched (and their
processes): those are the agent's. Standard library at import (Pillow when a picture is
taken).
"""

import io

import harness_computer.desktop as desktop

# The picture shown when the agent works in no window yet, or its window shows nothing
# (minimized).
EMPTY = (640, 400)


# JPEG quality of the pictures the model gets (the screen's, a window's): a 1920 x 1080 screen
# at 80 is ~180 KB (at 90 it was ~230 KB), and every model call carries a few of them.
JPEG_QUALITY = 80

class Desk:
    def __init__(self, backend: desktop.Backend, max_side: int):
        self.backend = backend
        self.max_side = int(max_side)
        self.windows = desktop.Ids("w")
        self.elements = desktop.Ids("e")
        self.current = None
        # Window id -> (frame [l, t, r, b], scale): how its last picture maps to the screen.
        self._pictures = {}
        # The windows and processes the backend launched (kept across episodes, as the
        # backend keeps them).
        self._launched = (set(), set())

    def reset(self) -> None:
        self.windows.clear()
        self.elements.clear()
        self.current = None
        self._pictures.clear()

    # -- windows -------------------------------------------------------------------------

    def rows(self, seen=None) -> list[dict]:
        """The windows as the agent sees them (with their ids): `seen(row)` is the row as
        the agent may see it, or None for one it is not shown (and gets no id)."""
        listed = []
        for row in self.backend.windows():
            self.note(row)
            shown = row if seen is None else seen(row)
            if shown is not None:
                listed.append((self.windows.assign(row["handle"], row), shown))
        return [self.describe(name, shown) for name, shown in listed]

    def describe(self, name, row) -> dict:
        frame = row["rect"]
        about = {"id": name, "app": row.get("app"), "title": row.get("title"), "size": list(self.size(frame))}
        for key in ("minimized", "offscreen", "launched", "foreground"):
            if row.get(key):
                about[key] = True
        # The window a dialog belongs to, by the id the agent was shown (none: not shown).
        parent = self.windows.name(row["owner"]) if row.get("owner") else None
        if parent:
            about["dialog_of"] = parent
        return about

    def note(self, row) -> None:
        """Remember a window the backend launched (its row says so)."""
        if row.get("launched"):
            self._launched[0].add(row["handle"])
            if row.get("pid") is not None:
                self._launched[1].add(row["pid"])

    def launched_here(self, window) -> bool:
        """Whether `window` ({handle, pid}) is one the backend launched, or of a process it
        launched."""
        return window.get("handle") in self._launched[0] or (window.get("pid") is not None
                                                              and window["pid"] in self._launched[1])

    def window(self, name=None) -> tuple[str, dict]:
        """The id and fresh row of window `name` (the current one by default)."""
        name = str(name or self.current or "")
        if not name:
            raise LookupError("no window yet: launch an app or use_window(id) first (windows() lists them)")
        handle = self.windows.key(name)
        if handle is None:
            raise LookupError(f"no window {name}: windows() lists the windows and their ids")
        row = self.backend.window(handle)
        if row is None:
            raise LookupError(f"the window {name} is closed")
        self.note(row)
        self.windows.assign(handle, row)
        return name, row

    def add(self, row) -> str:
        self.note(row)
        return self.windows.assign(row["handle"], row)

    def size(self, frame) -> tuple[int, int]:
        width, height = max(1, frame[2] - frame[0]), max(1, frame[3] - frame[1])
        scale = min(1.0, self.max_side / max(width, height))
        return max(1, round(width * scale)), max(1, round(height * scale))

    # -- pictures and points -------------------------------------------------------------

    def picture(self, name=None, image_format="jpeg", max_side=None) -> tuple[bytes, list, str | None]:
        """Window `name`'s picture (the current one; an empty picture with no window):
        encoded bytes, its size, and why it shows nothing (None when it shows the window)."""
        from PIL import Image

        why = None
        image = None
        if name or self.current:
            name, row = self.window(name)
            shot = self.backend.capture(row)
            if shot is None:
                why = "the window is minimized: no picture (its elements still work)" if row.get("minimized") else \
                    "the window showed nothing to capture"
            else:
                image = shot["image"]
                frame = row["rect"]
                width, height = self.size(frame)
                if max_side is None:
                    self._pictures[name] = (list(frame), width / max(1, frame[2] - frame[0]))
                else:
                    scale = min(1.0, max_side / max(width, height))
                    width, height = max(1, round(width * scale)), max(1, round(height * scale))
                if image.size != (width, height):
                    image = image.resize((width, height), Image.LANCZOS)
        else:
            why = "no window yet"
        if image is None:
            image = Image.new("RGB", EMPTY, (24, 24, 24))
        buffer = io.BytesIO()
        if image_format == "png":
            image.save(buffer, format="PNG")
        else:
            image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
        return buffer.getvalue(), list(image.size), why

    def to_screen(self, name, x, y) -> tuple[int, int]:
        """A point of window `name`'s picture as a physical screen point; the window's frame
        now (it may have moved since its picture)."""
        name, row = self.window(name)
        frame = row["rect"]
        scale = self._pictures.get(name, (None, None))[1]
        if scale is None:
            width, _ = self.size(frame)
            scale = width / max(1, frame[2] - frame[0])
        return frame[0] + int((float(x) + 0.5) / scale), frame[1] + int((float(y) + 0.5) / scale)

    def to_picture(self, name, rect) -> list[int]:
        """A screen rect as the window's picture pixels."""
        frame, scale = self._pictures.get(name, (None, None))
        if frame is None:
            _, row = self.window(name)
            frame = row["rect"]
            scale = self.size(frame)[0] / max(1, frame[2] - frame[0])
        return [round((rect[0] - frame[0]) * scale), round((rect[1] - frame[1]) * scale),
                round((rect[2] - frame[0]) * scale), round((rect[3] - frame[1]) * scale)]

    def inside(self, name, x, y) -> bool:
        width, height = self.size(self.window(name)[1]["rect"])
        return 0 <= float(x) < width and 0 <= float(y) < height

    # -- elements ----------------------------------------------------------------------------

    def tree(self, name=None) -> tuple[str, list[dict], list[str]]:
        """Window `name`'s elements (backend rows) and their ids."""
        name, row = self.window(name)
        elements = self.backend.tree(row)
        names = []
        for element in elements:
            element["window_id"] = name
            names.append(self.elements.assign((name, element["key"]), element))
        return name, elements, names

    def listed(self, name=None, role=None, text=None, limit=200) -> tuple[list[dict], int, str]:
        """The elements of window `name` as the agent sees them, rects in its picture's
        pixels, those that match `role` and `text` (in the name or value) when given: at
        most `limit` of them, how many more matched, and the listed ones as outline lines."""
        name, elements, names = self.tree(name)
        rows, more, kept = [], 0, []
        for element, element_id in zip(elements, names):
            if role and element.get("role") != role:
                continue
            if text and str(text).lower() not in f"{element.get('name') or ''} {element.get('value') or ''}".lower():
                continue
            if len(rows) >= limit:
                more += 1
                continue
            row = desktop.describe_element(element, element_id)
            row["rect"] = self.to_picture(name, element["rect"])
            rows.append(row)
            kept.append((element, element_id))
        return rows, more, desktop.outline([element for element, _ in kept], [key for _, key in kept], limit)

    def element(self, element_id) -> dict:
        row = self.elements.get(element_id)
        if row is None:
            raise LookupError(f"no element {element_id}: read the window's elements first (elements())")
        return row
