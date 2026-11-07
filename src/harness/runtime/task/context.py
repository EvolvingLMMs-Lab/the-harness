"""Task-local working memory and its common entry representation.

The store belongs to one bounded task. Sharing is explicit; it is not a persistent
agent identity. Library projections live in runtime.learning.views, usage accounting
in runtime.learning.usage, and historical reconstruction in core.memory.
"""

import math
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass


DEFAULT_MERGE = 3.0
DEFAULT_FRESH = 600.0
LIMIT = 2000
TEXT_CHARS = 32768
SEEN_EVERY = 5.0      # a thing seen again is recorded at most this often
SURE = 0.5            # the least confidence the summary mentions
SUMMARY_CHARS = 160   # an entry's text in the summary, at most (recall() gives it whole)
SEEN = "seen"         # a run's entry's evidence, below EVIDENCE


@dataclass(frozen=True)
class Kind:
    name: str
    about: str = ""
    merge: float = DEFAULT_MERGE      # sightings of it this close are the same thing
    fresh: float = DEFAULT_FRESH      # seconds a sighting stays worth mentioning


def family(kind: str) -> str:
    return str(kind).split(":", 1)[0]


def _position(where):
    """`where` as a position (a tuple of finite numbers), or None for a named place."""
    if where is None or isinstance(where, str):
        return None
    position = tuple(float(v) for v in where)
    if not 2 <= len(position) <= 3 or not all(math.isfinite(v) for v in position):
        raise ValueError(f"a position is two or three finite numbers, got {list(where)}")
    return position


def _words(text) -> set:
    return set(re.findall(r"[a-z0-9]{2,}", str(text).lower()))


def _score(query, *texts) -> float:
    have = _words(" ".join(str(text).replace("_", " ") for text in texts))
    overlap = len(_words(query) & have)
    return round(overlap / math.sqrt(len(have)), 4) if overlap else 0.0


class WorkingMemory:
    """What a run saw and where (see the module docstring)."""

    def __init__(self, kinds=(), clock=time.monotonic, limit=LIMIT):
        self.kinds = {kind.name: kind for kind in kinds}
        self.compass, self.up = None, 1
        self.items = {}
        self.clock = clock
        self.start = clock()
        self.limit = limit
        self.observation_limit = limit
        self._changes = deque(maxlen=4096)
        self.library = []          # the library's memory entries as the run started, and those it admits
        self.version = 0
        self._slots = {}
        self._expires = {}
        self._frames = {}
        self._lock = threading.RLock()

    def declare(self, world: dict | None, record=None) -> None:
        """An embodiment's kinds and direction words (its profile's `world`); with `record`,
        each entry the store already holds is recorded as carried into the run."""
        world = world or {}
        for item in list(self.items.values()) if record else ():
            record(action="carried", **self._fields(item))
        for kind in world.get("kinds") or ():
            self.kinds[kind["name"]] = Kind(kind["name"], kind.get("about", ""), float(kind.get("merge", DEFAULT_MERGE)),
                                            float(kind.get("fresh", DEFAULT_FRESH)))
        if world.get("compass"):
            self.compass = list(world["compass"])
        self.up = int(world.get("up", self.up))
        self.observation_limit = max(self.limit, min(200000, int(world.get("observation_limit", self.limit))))

    def remember(self, kind, text="", where=None, name=None, confidence=0.5, source="main", space=None,
                 record=None, *, slot=None, ttl=None, stale_after=None, ident=None) -> dict:
        """Note a thing (see the module docstring): its entry."""
        if not isinstance(kind, str) or not kind:
            raise ValueError("kind is a name such as \"tree\", \"window\" or \"ore:iron\"")
        record = record or (lambda **fields: None)
        position = _position(where)
        confidence = min(1.0, max(0.0, float(confidence)))
        text, name = str(text or ""), None if name is None else str(name)
        if len(text) > TEXT_CHARS:
            raise ValueError(f"a working memory entry is at most {TEXT_CHARS} characters")
        with self._lock:
            now = round(self.clock() - self.start, 2)
            self._expire(now, record)
            known = (self.items.get(self._slots.get((space, slot))) if slot is not None
                     else self.items.get(ident) or self._same(kind, position, where, name, text, space))
            if known is not None and slot is not None:
                if (confidence < known["confidence"] and kind != known["kind"]
                        and (stale_after is None or now - known["last"] < stale_after)):
                    return entry(known)
                if (kind, position or where, confidence) == (known["kind"], known["where"], known["confidence"]):
                    if ttl is not None:
                        self._expires[known["id"]] = now + float(ttl)
                    if confidence == 1:
                        known["last"] = now
                    return entry(known)
                self.version += 1
                known.update(kind=kind, where=position or where, confidence=confidence, last=now,
                             version=self.version, seen=known["seen"] + 1)
                self._changes.append((self.version, space, slot, known["id"]))
                record(action="seen", **self._fields(known))
                return entry(known)
            self.version += 1
            if known is not None:
                if ttl is not None:
                    self._expires[known["id"]] = now + float(ttl)
                weight = known["confidence"] / (known["confidence"] + confidence) if known["confidence"] + confidence else 0.5
                if position is not None and ttl is not None:
                    known["where"] = position
                elif position is not None:
                    known["where"] = tuple(round(a * weight + b * (1 - weight), 2) for a, b in zip(known["where"], position))
                known["confidence"] = round(1 - (1 - known["confidence"]) * (1 - confidence), 3)
                known["last"], known["seen"], known["version"] = now, known["seen"] + 1, self.version
                replacement = text if text or (name is not None and where is None) else known["text"]
                changed = replacement != known["text"]
                known["text"] = replacement
                if str(source) not in known["source"].split("+"):
                    known["source"] = known["source"] + "+" + str(source)
                # A thing in view is seen again every look: recorded at most every SEEN_EVERY s
                # (a new text at once).
                if changed or ttl is not None or now - known.get("recorded", -SEEN_EVERY) >= SEEN_EVERY:
                    known["recorded"] = now
                    record(action="seen", **self._fields(known))
                return entry(known)
            ident = ident or f"memory/{uuid.uuid4().hex}.md"
            item = self.items[ident] = {
                "id": ident, "kind": kind, "name": name, "text": text,
                "where": tuple(round(v, 2) for v in position) if position is not None else where,
                "space": space, "confidence": round(confidence, 3), "source": str(source), "first": now, "last": now,
                "seen": 1, "recorded": now, "version": self.version}
            if slot is not None:
                self._slots[space, slot] = ident
                item["slot"] = slot
                self._changes.append((self.version, space, slot, ident))
            if ttl is not None:
                item["tracked"] = True
                self._expires[ident] = now + float(ttl)
            record(action="remember", **self._fields(item))
            ordinary_count = len(self.items) - len(self._slots) - len(self._expires)
            if slot is None and ttl is None and ordinary_count > self.limit:
                ordinary = (each for each in self.items.values() if "slot" not in each and not each.get("tracked"))
                ranked = sorted(ordinary, key=lambda each: (each["last"], each["confidence"]))
                for old in ranked[:ordinary_count - self.limit]:
                    self._drop(old["id"], record, reason="capacity")
            return entry(item)

    def recall(self, query=None, k=5, kind=None, near=None, radius=None, space=None, *, library=(), record=None) -> list[dict]:
        """Entries of `kind` (a name or a family), in `space` when given: nearest to `near`
        first (with "distance"; within `radius`), then, without a radius, those that have
        no position, newest first; else best for `query` (with "score"), else newest
        first; at most k (0: all)."""
        near = _position(near)
        found, placeless = [], []
        with self._lock:
            self._expire(self.clock() - self.start, record)
            items = {item["id"]: item for item in library}
            for ident, item in self.items.items():
                if self._in_space(item, space):
                    stored = items.get(ident)
                    items[ident] = {**item, "scope": "library", "evidence": stored["evidence"]} if stored else dict(item)
            items = list(items.values())
        for item in items:
            if kind is not None and item["kind"] != kind and family(item["kind"]) != kind:
                if item["kind"] != "memory" or not _score(kind, item["name"], item.get("summary") or ""):
                    continue
            if not self._in_space(item, space):
                continue
            shown = entry(item, item.get("scope", "run"))
            if query:
                shown["score"] = _score(query, item["kind"], item["name"] or "", item["text"],
                                        item["where"] if isinstance(item["where"], str) else "", item.get("summary") or "")
                if not shown["score"]:
                    continue
            if near is not None:
                position = _position(item["where"]) if not isinstance(item["where"], str) else None
                if position is None or len(position) != len(near):
                    if radius is None:
                        placeless.append(shown)
                    continue
                shown["distance"] = round(math.dist(position, near), 1)
                if radius is not None and shown["distance"] > float(radius):
                    continue
            found.append(shown)
        if near is not None:
            found.sort(key=lambda e: (e["distance"], -(e["last"] or 0)))
            found += sorted(placeless, key=lambda e: -(e["last"] or 0))
        elif query:
            found.sort(key=lambda e: (-e["score"], -(e["last"] or 0)))
        else:
            found.sort(key=lambda e: -(e["last"] or 0))
        return found[:int(k)] if k else found

    @staticmethod
    def _in_space(item, space):
        if space is None or item.get("space") is None:
            return True
        own = tuple(item["space"]) if isinstance(item["space"], list) else item["space"]
        if item.get("where") is None and isinstance(space, tuple) and isinstance(own, tuple):
            return own[0] == space[0]
        return own == space

    def _drop(self, ident, record, **detail):
        item = self.items.pop(ident, None)
        if item is not None:
            self.version += 1
            self._expires.pop(ident, None)
            if "slot" in item:
                self._slots.pop((item["space"], item["slot"]), None)
                self._changes.append((self.version, item["space"], item["slot"], None))
            if record is not None:
                record(action="forget", id=ident, kind=item["kind"], **detail)
        return item is not None

    def _expire(self, now, record):
        for ident, expiry in list(self._expires.items()):
            if expiry <= now:
                self._drop(ident, record, reason="expired")

    def forget(self, ident, record=None, *, space=None) -> bool:
        """Drop a visible working entry by its ID."""
        with self._lock:
            ident = int(ident) if str(ident).isdigit() else ident
            item = self.items.get(ident)
            return bool(item is not None and self._in_space(item, space) and self._drop(ident, record))

    def summary(self, near=None, space=None, limit=8, sure=SURE) -> str:
        """A few lines for the model after each program: the notes without a position (the
        newest first, however old), then the places nearest to `near` (else the newest)
        still fresh and at least `sure` confident, where they are and how long ago; at most
        `limit` in all."""
        now = self.clock() - self.start
        near = _position(near)
        entries = self.recall(k=0, space=space)
        notes = [item for item in entries if item["where"] is None]
        places = [item for item in entries if item["where"] is not None and item["confidence"] >= sure
                  and now - item["last"] <= self.kinds.get(item["kind"], Kind(item["kind"])).fresh]
        if near is not None:
            def distance(item):
                position = _position(item["where"]) if not isinstance(item["where"], str) else None
                return math.dist(position, near) if position is not None and len(position) == len(near) else math.inf
            places.sort(key=distance)
        leading = notes[:max(1, limit // 2)] if places and limit else notes[:limit]
        lines = []
        for item in leading + places[:max(0, limit - len(leading))]:
            what = item["kind"] + (f" {item['name']}" if item["name"] else "") + (f" ({_clip(item['text'])})" if item["text"] else "")
            where = self._where(item, near)
            lines.append(f"- {what}{' ' + where if where else ''}, seen {_ago(now - item['last'])} ago"
                         f"{' x%d' % item['seen'] if item['seen'] > 1 else ''} [#{item['id']}, {item['source']}]")
        more = len(notes) + len(places) - len(lines)
        if more > 0:
            lines.append(f"- and {more} more (recall())")
        return "\n".join(lines)

    # -- the host's side of the skill ------------------------------------------------------

    def handle(self, request: dict, *, record=None, source="main", space=None, library=None, persist=None):
        """A program's request (skills/memory): remember, recall (this run's entries and the
        library's as the run holds them), forget, summary. An entry's kind and id may come
        as "of" and "entry" (a kernel note's own fields are "kind" and "id"). `space`: the
        writer's own, when it works in a world of its own (a sub-agent's workspace)."""
        request = {{"of": "kind", "entry": "id"}.get(key, key): value for key, value in request.items()}
        record = record or (lambda **fields: None)
        action = request.get("action")
        requested_space = request.get("space")
        if space is not None:
            requested_space = (space, requested_space)
        holdings = self.library if library is None else library
        if action == "remember":
            if request.get("keep") and persist is None:
                raise ValueError("this run cannot keep memory in the library")
            existing = next((item for item in holdings if request.get("keep") and request.get("name") is not None
                             and item["name"] == request["name"] and item["kind"] == request["kind"]
                             and item["where"] == request.get("where") and self._in_space(item, requested_space)), None)
            found = self.remember(request["kind"], request.get("text", ""), request.get("where"), request.get("name"),
                                  request.get("confidence", 0.5), request.get("source") or source,
                                  requested_space, record, ident=existing["id"] if existing else None)
            return persist(found) if request.get("keep") else found
        if action == "observe":
            with self._lock:
                frame = request.get("frame")
                stream = (space, request.get("stream"))
                if frame is not None:
                    if frame <= self._frames.get(stream, -1):
                        return self.version
                    self._frames[stream] = frame
                for observation in request["observations"]:
                    if observation.get("kind") is None:
                        ident = self._slots.get((requested_space, observation["slot"]))
                        if ident is not None:
                            self._drop(ident, record)
                    else:
                        self.remember(observation["kind"], where=observation["where"], space=requested_space,
                                      confidence=observation.get("confidence", 1), source=request.get("source") or source,
                                      record=record, slot=observation.get("slot"), ttl=observation.get("ttl"),
                                      stale_after=observation.get("stale_after"))
                overflow = len(self._slots) + len(self._expires) - self.observation_limit
                if overflow > 0:
                    observed = (item for item in self.items.values() if "slot" in item or item.get("tracked"))
                    oldest = sorted(observed, key=lambda item: (item["last"], item["confidence"]))
                    for item in oldest[:overflow + self.observation_limit // 20]:
                        self._drop(item["id"], record, reason="capacity")
            return self.version
        if action in ("recall", "observations"):
            if request.get("radius") is not None and request.get("near") is None:
                raise ValueError("recall() needs a position for a radius: give near or use a worker that reports here")
            if action == "observations":
                with self._lock:
                    self._expire(self.clock() - self.start, record)
                    version = request.get("version")
                    if request.get("cells") and version is not None and self._changes and version >= self._changes[0][0]:
                        changed = {slot: ident for changed_at, own_space, slot, ident in self._changes
                                   if changed_at > version and own_space == requested_space}
                        return {"version": self.version, "delta": True,
                                "entries": [entry(self.items[ident]) for ident in changed.values() if ident is not None],
                                "removed": [slot for slot, ident in changed.items() if ident is None]}
                    return {"version": self.version, "entries": (
                        [entry(item) for item in self.items.values()
                         if ("slot" in item or item.get("tracked") and not request.get("cells"))
                         and self._in_space(item, requested_space)]
                        if version != self.version else None)}
            k = int(request.get("k", 5))
            found = self.recall(request.get("query"), k, request.get("kind"), request.get("near"),
                                request.get("radius"), requested_space, library=holdings, record=record)
            record(action="recall", **{key: request[key] for key in ("query", "kind", "near", "radius")
                                       if request.get(key) is not None}, found=[item["id"] for item in found],
                   results=found, k=k, space=requested_space)
            return found
        if action == "forget":
            ident = request["id"]
            kept = next((item for item in holdings if item["id"] == ident and self._in_space(item, requested_space)), None)
            if kept is not None:
                if persist is None:
                    raise ValueError("this run cannot forget memory in the library")
                persist(kept, forgotten=True)
            return self.forget(ident, record, space=requested_space) or kept is not None
        if action == "summary":
            return self.summary(request.get("near"), requested_space, int(request.get("limit", 8)))
        raise ValueError(f"memory: unknown request {action!r}")

    def kept(self, item):
        """Keep an admitted entry in the standalone kernel's memory."""
        with self._lock:
            self.library[:] = [old for old in self.library if old["id"] != item["id"]] + [item]

    # -- inside ----------------------------------------------------------------------------

    def _same(self, kind, position, where, name, text, space):
        best, nearest = None, self.kinds.get(kind, Kind(kind)).merge
        for item in self.items.values():
            if "slot" in item or item["kind"] != kind or item["space"] != space:
                continue
            if position is not None:
                mine = _position(item["where"]) if not isinstance(item["where"], str) else None
                if mine is not None and len(mine) == len(position) and math.dist(mine, position) <= nearest:
                    best, nearest = item, math.dist(mine, position)
            elif where is not None:
                if item["where"] == where and (name is None or item["name"] == name):
                    return item
            elif item["where"] is None and (item["name"] == name if name is not None else item["text"] == text):
                return item
        return best

    @staticmethod
    def _fields(item) -> dict:
        """A change as its `world` record says it (enough to rebuild the entry, from_records()):
        the writer as `by`, since a record's `source` is where it comes from."""
        return {{"source": "by"}.get(key, key): list(value) if key == "where" and isinstance(value, tuple) else value
                for key, value in item.items() if key not in ("recorded", "first", "last") and value is not None}

    def _where(self, item, near):
        where = item["where"]
        if where is None:
            return ""
        if isinstance(where, str):
            return f"at {where}"
        if near is None or len(where) != len(near) or len(where) != 3:
            return "at " + " ".join(f"{v:.0f}" for v in where)
        delta = [a - b for a, b in zip(where, near)]
        dy = delta.pop(self.up)
        (da, db), direction = delta, ""
        if self.compass:
            yaw = math.degrees(math.atan2(-da, db))
            step = 360.0 / len(self.compass)
            direction = " " + self.compass[int(((yaw + step / 2) % 360) // step)]
        height = f", {abs(dy):.0f} {'up' if dy > 0 else 'down'}" if abs(dy) >= 2 else ""
        return f"{math.hypot(da, db):.0f} away{direction}{height}"


def _clip(text, chars=SUMMARY_CHARS):
    text = " ".join(str(text).split())
    return text if len(text) <= chars else text[:chars - 3] + "..."


def _ago(seconds):
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def entry(item: dict, scope="run") -> dict:
    """An entry in the one format (see the module docstring)."""
    where = item.get("where")
    return {"id": item["id"], "scope": scope, "kind": item["kind"], "name": item.get("name"), "text": item.get("text", ""),
            "where": list(where) if isinstance(where, tuple) else where, "space": item.get("space"),
            "evidence": item.get("evidence", SEEN), "confidence": item.get("confidence"), "source": item.get("source"),
            "seen": item.get("seen"), "first": item.get("first"), "last": item.get("last"), "version": item.get("version"),
            "summary": item.get("summary"), "history": item.get("history"), "rate": item.get("rate"),
            **({"slot": item["slot"]} if "slot" in item else {})}
