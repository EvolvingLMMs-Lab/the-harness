"""The lanes of a run's timeline, read from its trace records: the one computation of them.
harness chat prefixes its lines with a lane's path, the terminal chat's timeline draws rows of them, and the
host serves a snapshot (Lanes.snapshot, GET /api/lanes) that the one web timeline (the app
package's timeline.js: the app, the overlay and a video) draws as it is.

A lane is one part that works on its own: the main model, the verifier, the agent's
programs (the root entry e0, runtime/execution/entries.py), each entry a program spawned (its
children under it, so a lane's path is the ids from e0 down: e0/e2/e5), the world
memory (a mark for each thing remembered, seen again or forgotten), and the
environment; above them, the markers of what happened (a user's message, the end, an error). A lane appears with the first record that needs it and an entry's lane ends
with its entry_end: a view shows the lanes that lived in the time it shows, so lanes come
and go as entries start and end. Each lane holds its spans (core/spans.py), whose `lane`
field says what kind of part recorded them. The model's lane holds a block for each
call, never more: between calls it is empty, also while programs run (pipelining shows
as blocks of both lanes with gaps in each). A call made while a program ran whose reply
was not used (an `ahead` record: discarded or unused) is marked on its span (`ahead`)
and drawn faint. While a call streams, its text so far is the lane's `text`
(model_text records of that call).

Standard library only; reads, never writes.
"""

import math

# The lanes that are not entries, in the order they are drawn (entries go between the
# verifier and the environment).
FIXED = ("model", "verifier", "world", "env")
ROOT = "e0"
# Characters of the streamed text a lane keeps (the end of it).
TEXT = 600
# What became of a call made while a program ran when its reply was not used.
FAINT = ("discarded", "unused")
# The marks of what happened, by event (also a paused run: "‖", and a program's escalation: "▼").
MARKERS = {"user_message": "●", "agent_message": "○", "finish": "■", "error": "×", "kernel_died": "×",
           "stuck": "!", "confirmation_request": "?", "protocol_error": "~"}


class Lane(dict):
    """id, parent (a lane id or None), kind (model, verifier, env, program, agent ...),
    label, claims (an entry's channels, as they change: entry_claims), start, end (None while it lives), status, spans (dicts in start order)
    and text (the model's streamed text of call `call`, the one that runs)."""


class Lanes:
    """The lanes of one run, folded from its records in order (add)."""

    def __init__(self):
        self.lanes = {}
        self.spans = {}
        self.t0 = None
        self.last = None
        self.ended = False
        self.markers = []
        # A trace written before spans: the spans its records imply (the model's calls from
        # request to reply, each program for its duration), used while it has no span of its own.
        self.has_spans = False
        self.implied = []
        self._request = None

    def add(self, record) -> str | None:
        """Fold one trace record in; returns the path of the lane it belongs to (None: the
        conversation's own, a user's message or a status)."""
        time = record.get("time")
        if isinstance(time, (int, float)):
            self.t0 = time if self.t0 is None else min(self.t0, time)
            self.last = time if self.last is None else max(self.last, time)
        kind = record.get("event") or ""
        if kind in ("outcome", "interrupted") or kind == "state" and record.get("status") in ("FINISHED", "ERROR"):
            self.ended = True
        elif kind == "state":
            # It goes on: after a turn that was cancelled, or continued after it had ended.
            self.ended = False
        self._mark(record, kind, time)
        if kind == "span_start":
            self.has_spans = True
            lane = self._span_lane(record)
            span = {"id": record.get("id"), "lane": lane["id"], "part": record.get("lane"), "name": record.get("name"),
                    "parent": record.get("parent"), "start": time, "end": None, "call": record.get("call"),
                    "seq": record.get("seq")}
            self.spans[span["id"]] = span
            lane["spans"].append(span)
            if lane["kind"] == "model":
                lane.update(text="", call=record.get("call"))
            return self.path(lane["id"])
        if kind == "span_end":
            span = self.spans.get(record.get("id"))
            if span is None:
                return None
            span["end"] = time
            span["status"] = record.get("event_kind") or ("error" if record.get("error") else None)
            return self.path(span["lane"])
        if kind == "entry_start":
            lane = self._entry(record.get("id"), record.get("parent") or ROOT)
            lane.update(kind=record.get("kind") or "program", label=_label(record), claims=list(record.get("claims") or []),
                        start=time, agent=record.get("agent"))
            return self.path(lane["id"])
        if kind == "entry_claims":
            lane = self.lanes.get(record.get("id"))
            if lane is None:
                return None
            lane["claims"] = list(record.get("claims") or [])
            return self.path(lane["id"])
        if kind == "entry_end":
            lane = self.lanes.get(record.get("id"))
            if lane is None:
                return None
            lane.update(end=time, status=record.get("status"), error=record.get("error") or record.get("event_kind"))
            return self.path(lane["id"])
        if kind in ("model_request", "model_reply", "model_text"):
            lane = self._fixed("model", time)
            # Calls can overlap (one made while a program ran is still out when the model is
            # asked again) and the reply to one comes when its program ends, maybe while the
            # next call streams: the lane keeps the newest call's text, and only that call's
            # reply clears it.
            if kind == "model_text":
                call = record.get("call")
                if call != lane.get("call"):
                    if _older(call, lane.get("call")):
                        return "model"
                    lane.update(text="", call=call)
                lane["text"] = (lane["text"] + str(record.get("text") or ""))[-TEXT:]
            elif kind == "model_reply" and record.get("call") == lane.get("call"):
                lane["text"] = ""
            return "model"
        if kind == "ahead":
            lane = self._fixed("model", time)
            span = next((span for span in reversed(lane["spans"]) if span.get("call") == record.get("call")), None)
            if span is not None:
                span["ahead"] = record.get("outcome")
            return "model"
        if kind == "verify":
            self._fixed("verifier", time)
            return "verifier"
        if kind == "world":
            # A mark: the moment the memory changed.
            lane = self._fixed("world", time)
            lane["spans"].append({"id": f"w{len(lane['spans'])}", "lane": "world", "part": "world",
                                  "name": f"{record.get('action')} {record.get('kind')}", "parent": None,
                                  "start": time, "end": time, "call": None})
            return "world"
        if kind == "cell":
            self._entry(ROOT, None)
            return ROOT
        if kind in ("reset", "outcome", "episode_video"):
            self._fixed("env", time)
            return "env"
        if kind == "agent_report":
            lane = next((lane for lane in self.lanes.values() if lane.get("agent") == record.get("agent")), None)
            return self.path(lane["id"]) if lane else ROOT
        if kind.startswith("agent_"):
            return ROOT
        return None

    def _mark(self, record, kind, time) -> None:
        """The marks of what happened, and the spans a trace without spans implies."""
        what = None
        if kind == "state" and record.get("status") == "PAUSED":
            glyph, what = "‖", "paused"
        elif kind == "cell" and (record.get("result") or {}).get("escalation"):
            escalation = record["result"]["escalation"]
            glyph, what = "▼", f"{(escalation.get('event') or {}).get('kind')} in {escalation.get('skill')}"
        if what is not None:
            self.markers.append({"time": time, "glyph": glyph, "what": what, "seq": record.get("seq")})
        if kind in MARKERS:
            said = record.get("text") or record.get("message") or record.get("repeated") or kind
            self.markers.append({"time": time, "glyph": MARKERS[kind], "what": f"{kind}: {str(said)[:160]}",
                                 "seq": record.get("seq")})
        if kind == "model_request":
            self._request = record
        elif kind == "model_reply" and self._request is not None:
            self.implied.append({"id": f"m{record.get('seq')}", "lane": "model", "part": "model",
                                 "name": f"call {record.get('call')}", "parent": None, "start": self._request.get("time"),
                                 "end": time, "call": record.get("call"), "seq": self._request.get("seq"),
                                 "derived": True})
            self._request = None
        elif kind == "cell":
            seconds = (record.get("result") or {}).get("seconds") or 0
            self.implied.append({"id": f"c{record.get('seq')}", "lane": ROOT, "part": "program", "name": "program",
                                 "parent": None, "start": time - seconds, "end": time, "call": None,
                                 "seq": record.get("seq"), "derived": True,
                                 "status": (record.get("result") or {}).get("status")})

    def snapshot(self) -> dict:
        """The lanes as every view draws them: {t0, last, ended, lanes, markers}; each lane
        in drawing order (ordered) with its path, depth, first (the time it appeared) and its
        spans; a trace without spans has the lanes of the spans its records imply."""
        out = []
        for lane in self.ordered():
            starts = [value for value in (lane["start"], *(span["start"] for span in lane["spans"][:1])) if value is not None]
            out.append({key: lane.get(key) for key in ("id", "parent", "kind", "label", "agent", "claims", "start", "end",
                                                       "status", "error")}
                       | {"path": self.path(lane["id"]), "depth": self.depth(lane["id"]),
                          "first": min(starts) if starts else None,
                          "spans": [{key: span.get(key) for key in ("id", "lane", "part", "name", "parent", "start", "end",
                                                                    "status", "ahead", "call", "seq", "derived")}
                                    for span in lane["spans"]]})
        return {"t0": self.t0, "last": self.last, "ended": self.ended, "lanes": out, "markers": list(self.markers)}

    def _implied_lanes(self) -> "Lanes":
        implied = Lanes()
        for span in self.implied:
            lane = implied._fixed("model", span["start"]) if span["part"] == "model" else implied._entry(ROOT, None)
            lane["spans"].append(dict(span, lane=lane["id"]))
        return implied

    def _fixed(self, name, time) -> Lane:
        lane = self.lanes.get(name)
        if lane is None:
            lane = self.lanes[name] = Lane(id=name, parent=None, kind=name, label=name, claims=[], start=time,
                                           end=None, status=None, spans=[], text="")
        return lane

    def _entry(self, identifier, parent) -> Lane:
        lane = self.lanes.get(identifier)
        if lane is None:
            if parent is not None and parent not in self.lanes:
                self._entry(parent, None if parent == ROOT else ROOT)
            root = identifier == ROOT
            lane = self.lanes[identifier] = Lane(id=identifier, parent=None if root else parent, kind="program",
                                                 label="programs" if root else identifier, claims=[], start=None,
                                                 end=None, status=None, spans=[], text="")
        return lane

    def _span_lane(self, record) -> Lane:
        """A span's lane: the model's, the verifier's and the environment's spans their own;
        a span of an entry's code (`entry`) that entry's; a skill or service call its parent
        span's; the rest (a program) the agent's programs."""
        part = record.get("lane")
        if part in FIXED:
            return self._fixed(part, record.get("time"))
        if record.get("entry"):
            return self._entry(record["entry"], ROOT)
        parent = self.spans.get(record.get("parent"))
        if parent is not None:
            return self.lanes[parent["lane"]]
        return self._entry(ROOT, None)

    def path(self, identifier) -> str:
        """A lane's ids from the root entry down (e0/e2/e5); a lane that is not an entry
        its name."""
        parts = []
        while identifier is not None:
            parts.append(identifier)
            identifier = (self.lanes.get(identifier) or {}).get("parent")
        return "/".join(reversed(parts))

    def depth(self, identifier) -> int:
        return self.path(identifier).count("/")

    def ordered(self) -> list[Lane]:
        """The lanes in the order they are drawn: the model, the verifier, the world memory,
        the entries (each under its parent, in the order they started), the environment."""
        if not self.has_spans and self.implied:
            return self._implied_lanes().ordered()
        children = {}
        for lane in self.lanes.values():
            if lane["id"] not in FIXED:
                children.setdefault(lane["parent"], []).append(lane)
        entries = []

        def walk(parent):
            for lane in children.get(parent, []):
                entries.append(lane)
                walk(lane["id"])
        walk(None)
        lanes = [self.lanes[name] for name in ("model", "verifier", "world") if name in self.lanes]
        return lanes + entries + ([self.lanes["env"]] if "env" in self.lanes else [])

    def visible(self, t0, t1, now=None) -> list[Lane]:
        """The lanes that lived between t0 and t1 (times as the records have them): a lane
        starts with its first span or its entry, and ends with its entry (else it lives on)."""
        shown = []
        for lane in self.ordered():
            starts = [value for value in (lane["start"], *(span["start"] for span in lane["spans"][:1]))
                      if value is not None]
            start = min(starts) if starts else None
            end = lane["end"]
            if start is not None and start > t1 or end is not None and end < t0:
                continue
            shown.append(lane)
        return shown

    def columns(self, lane, t0, t1, width, now, faint=None) -> list[bool]:
        """For each of `width` equal stretches of t0 to t1, whether one of the lane's spans
        ran in it; a span still open runs until `now`. `faint` True counts only the calls
        whose reply was not used (FAINT), False only the others, None all."""
        step = (t1 - t0) / max(width, 1)
        busy = [False] * width
        for span in lane["spans"]:
            if faint is not None and (span.get("ahead") in FAINT) != faint:
                continue
            start, end = span["start"], span["end"] if span["end"] is not None else now
            if start is None or end is None or start > t1 or end < t0:
                continue
            first = max(int((start - t0) / step), 0) if step > 0 else 0
            # A span that ends on a column's edge does not reach into the next one.
            last = min(max(math.ceil((end - t0) / step) - 1, first), width - 1) if step > 0 else width - 1
            for column in range(first, last + 1):
                busy[column] = True
        return busy

    def alive(self, lane, a, b, now) -> bool:
        """Whether a spawned entry's lane lived at some time between a and b (the agent's
        programs and the other lanes only have their spans)."""
        if lane["kind"] in FIXED or lane["id"] == ROOT or lane["start"] is None:
            return False
        end = lane["end"] if lane["end"] is not None else now
        return lane["start"] < b and end >= a

    def now(self, clock=None) -> float:
        """The time a view ends at: the last record's once the run ended, else `clock`."""
        if self.ended or clock is None:
            return self.last if self.last is not None else 0.0
        return max(clock, self.last or clock)


def _older(call, than) -> bool:
    """Whether call number `call` was made before call `than`."""
    return isinstance(call, int) and isinstance(than, int) and call < than


def _label(record) -> str:
    """An entry's label: its name, and the sub-agent it is."""
    name = str(record.get("name") or record.get("id"))
    if record.get("agent") and record["agent"] not in name:
        return f"{name} ({record['agent']})"
    return name
