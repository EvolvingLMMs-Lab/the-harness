"""Terminal glyphs and rows for a shared timeline."""

from ..core.lanes import Lanes


# Characters of a lane in a terminal: a span ran in the cell (only a call whose reply was
# not used: FAINT), a spawned entry lived but ran nothing, its end (done, failed, cancelled).
BUSY = "█"
SHADE = "▒"
IDLE = "─"
ENDS = {"done": "┤", "failed": "×", "cancelled": "╳"}


def claimed(lane) -> str:
    """What follows an entry's label: the channels it claims (the last it claimed, once it
    ended)."""
    return f" [{','.join(map(str, lane['claims']))}]" if lane.get("claims") else ""


def rows(lanes: Lanes, t0: float, t1: float, width: int, now: float) -> list[dict]:
    """The lanes living between t0 and t1 as rows of `width` characters (a terminal's
    timeline): each {"lane", "path", "label", "cells"}. Only cells: what the model says is
    the conversation's, never the timeline's."""
    step = (t1 - t0) / max(width, 1)
    out = []
    for lane in lanes.visible(t0, t1, now):
        busy = lanes.columns(lane, t0, t1, width, now, faint=False)
        shaded = lanes.columns(lane, t0, t1, width, now, faint=True)
        cells = []
        for column in range(width):
            a, b = t0 + column * step, t0 + (column + 1) * step
            if busy[column]:
                cells.append(BUSY)
            elif shaded[column]:
                cells.append(SHADE)
            elif lanes.alive(lane, a, b, now):
                end = lane["end"]
                cells.append(ENDS.get(lane["status"], IDLE) if end is not None and a <= end < b else IDLE)
            else:
                cells.append(" ")
        indent = "  " * lanes.depth(lane["id"])
        out.append({"lane": lane, "path": lanes.path(lane["id"]), "label": indent + lane["label"] + claimed(lane),
                    "cells": "".join(cells)})
    return out


def strip(lanes: Lanes, t0: float, t1: float, width: int, now: float) -> str:
    """A mini timeline in one line of `width` characters: the upper half of a cell when the
    model was called in it, the lower half when a program, entry or the environment
    worked, both when both did (the Sessions page)."""
    thinking = [False] * width
    acting = [False] * width
    for lane in lanes.ordered():
        target = thinking if lane["kind"] == "model" else acting
        for column, busy in enumerate(lanes.columns(lane, t0, t1, width, now)):
            target[column] = target[column] or busy
    return "".join("█" if up and down else "▀" if up else "▄" if down else " "
                   for up, down in zip(thinking, acting))
