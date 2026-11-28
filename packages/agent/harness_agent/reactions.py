"""An identity's tree of reactions: the minimal initial behaviour tree (T_0) judged all the time.

One behaviour tree per identity, saved in its folder (reactions.json, format 2) and judged by
its life whenever the world changes or a time comes, from its root, at zero model cost (the
core's Reflexes, runtime/reactive/tree.py, judges it: a selector at every place, the earlier
first; a node whose condition holds is gone into, its narrower nodes first, then what it does
itself). Position is priority: a node higher up interrupts what a lower one is doing as soon
as its condition holds.

A node has three parts:

    condition   when it takes over:
                  {"event": KIND or [KINDS] or "*", "match": {field: value or [values]}, "place"?: ID}
                      an event of a place or internal life/clock event (match reads event data first)
                  {"outcome": [ENDS], "verb"?: VERB, "place"?: ID}   an ASP outcome ended so
                  {"fact": NAME, "is"|"in"|"below"|"above"|"has": VALUE}
                      a fact of the moment: working_in, owner_active, asleep, pace_ok,
                      proactive_mode, learning_mode, paused, battery, hour
                  {"all": [...]}, {"any": [...]}, {"not": {...}}
    answer      one of five, and only these:
                  {"skill": NAME, "args"?: {}}         call a builtin or verified learned skill
                  {"wake": True | {whose, mode?}, "notify"?: KIND}  wake the model
                  {"stop": True | "chat" | "all" | {"place_kind": K} | {"place": ID}, ...}
                  {"remind": TEXT, "notify"?: KIND}    remind (and optionally notify) the owner
                  {"nothing": True}                    suppress event at zero cost
                a situation container node with nodes under it may have do=None (gate / slot).
    position    the node it hangs under (`under`) and its place among the nodes there.

Twenty-three minimal built-in core nodes (T_0: 6 gate/slot containers + 17 leaves) ship with
every identity and can be disabled by the owner, never deleted. Agent self-evolution (`evolve`
with authority="own") is restricted to learned nodes inside the canonical extension slots
(`learned_reactive`, `learned_proactive`) or owner-created non-core branches below
`owner_message`, and must pass anti-lobotomy, non-shadowing, and evidence-gate checks."""
from copy import deepcopy
import json
import threading
import time

from harness.runtime.reactive.tree import Reflexes
from harness.sdk import atomic_write
from .state import read

FORMAT = 2
ANSWERS = ("skill", "wake", "stop", "remind", "nothing")
NOTIFY_KINDS = ("approval", "limit", "failed", "login")
SOURCES = ("builtin", "owner", "learned")
EVIDENCE = ("builtin", "owner", "proposed", "own_test", "replayed", "effective")
EVIDENCE_RANK = {"proposed": 0, "own_test": 1, "replayed": 2, "effective": 3}
FACTS = (
    "battery",
    "owner_active",
    "working_in",
    "asleep",
    "paused",
    "hour",
    "pace_ok",
    "proactive_mode",
    "learning_mode",
)
EXTENSION_SLOTS = ("learned_reactive", "learned_proactive")
EXTERNAL_CONSEQUENCE_PLACES = frozenset({"desktop", "browser", "space", "ssh"})
PROTECTED_EVENTS = frozenset({
    "owner.message",
    "approval.waiting",
    "channel.login_expired",
    "clock.midnight",
    "clock.dream",
    "clock.morning",
    "chat.quiet",
    "sleep.deferred_ready",
})
PROMOTE_USES, PROMOTE_RATE = 5, 0.8
DEMOTE_USES, DEMOTE_RATE = 3, 0.25

# The formally verified 23-node Minimal Initial Behavior Tree (T_0):
#   Tier 1 (1-4):   Immediate protection & critical alerts (0 LLM cost; active even when asleep)
#   Tier 2 (5-9):   Owner & passive reactive layer (owner always reachable on reserve)
#   Tier 3 (10-11): Zero-cost daily clock boundaries
#   Tier 4 (12-23): Own-budget energy cut-set (awake_own) -> deferred, learning, proactive, learn_only
BUILTIN = (
    # --- Tier 1: Immediate Protection & Critical Alerts ---
    {
        "name": "desktop_yield",
        "under": None,
        "core": True,
        "about": "owner active on desktop -> stop desktop work immediately",
        "when": {"all": [
            {"fact": "working_in", "has": "desktop"},
            {"fact": "owner_active", "is": True},
        ]},
        "do": {"stop": {"place_kind": "desktop"}},
    },
    {
        "name": "approval_waiting",
        "under": None,
        "core": True,
        "about": "needs approval -> remind the owner",
        "when": {"event": "approval.waiting"},
        "do": {"remind": "An action waits for your approval", "notify": "approval"},
    },
    {
        "name": "channel_login_expired",
        "under": None,
        "core": True,
        "about": "channel login expired -> remind the owner",
        "when": {"event": "channel.login_expired"},
        "do": {"remind": "A channel login expired", "notify": "login"},
    },
    {
        "name": "sleep_notice",
        "under": None,
        "core": True,
        "about": "own daily budget exhausted -> notify the owner on entering asleep",
        "when": {"fact": "asleep", "is": True},
        "do": {
            "remind": "Daily proactive budget reached; asleep until 00:00 (still answering you)",
            "notify": "limit",
        },
    },
    # --- Tier 2: Owner & Passive Reactive Layer ---
    {
        "name": "owner_message",
        "under": None,
        "core": True,
        "about": "direct message from owner -> owner turn (uses reserve if asleep)",
        "when": {"event": "owner.message"},
        "do": {"wake": {"whose": "owner", "mode": "turn"}},
    },
    {
        "name": "owner_calendar_due",
        "under": None,
        "core": True,
        "about": "owner-scheduled calendar entry due -> wake on owner reserve",
        "when": {"event": "calendar.due", "match": {"by": "owner"}},
        "do": {"wake": {"whose": "owner", "mode": "wake"}},
    },
    {
        "name": "learned_reactive",
        "under": None,
        "core": True,
        "slot": True,
        "about": "learned passive reflexes (active when learning_mode != off)",
        "when": {"not": {"fact": "learning_mode", "is": "off"}},
        "do": None,
    },
    {
        "name": "named",
        "under": None,
        "core": True,
        "about": "named or aimed at it -> wake it",
        "when": {"event": "*", "match": {"addressed": True}},
        "do": {"wake": {"whose": "from_event", "mode": "wake"}},
    },
    {
        "name": "action_failed",
        "under": None,
        "core": True,
        "about": "an action ended failed or unknown -> notify & wake it",
        "when": {"outcome": ["failed", "unknown"]},
        "do": {"wake": {"whose": "from_outcome", "mode": "wake"}, "notify": "failed"},
    },
    # --- Tier 3: Zero-Cost Daily Clock Boundaries ---
    {
        "name": "midnight_reset",
        "under": None,
        "core": True,
        "about": "00:00 daily boundary -> reset budget, end sleep, release deferred backlog",
        "when": {"event": "clock.midnight"},
        "do": {"skill": "builtin.reset_day"},
    },
    {
        "name": "morning_brief",
        "under": None,
        "core": True,
        "about": "06:00 daily summary -> record 24h brief to main conversation and DREAMS.md",
        "when": {"event": "clock.morning"},
        "do": {"skill": "builtin.morning_brief"},
    },
    # --- Tier 4: Own-Budget Hard Cut-Set (awake_own) ---
    {
        "name": "awake_own",
        "under": None,
        "core": True,
        "about": "awake with own budget remaining (asleep == false)",
        "when": {"fact": "asleep", "is": False},
        "do": None,
    },
    {
        "name": "deferred_wakeup",
        "under": "awake_own",
        "core": True,
        "about": "sleep-deferred events released after 00:00 -> wake to catch up",
        "when": {"event": "sleep.deferred_ready"},
        "do": {"wake": {"whose": "own", "mode": "wake"}},
    },
    {
        "name": "learning_evolution",
        "under": "awake_own",
        "core": True,
        "about": "learning & tree evolution active (frozen/off stops all mutation)",
        "when": {"fact": "learning_mode", "in": ["on", "review_first", "replay_always"]},
        "do": None,
    },
    {
        "name": "dreaming",
        "under": "learning_evolution",
        "core": True,
        "about": "00:30 consolidation -> merge, archive, extract skills, audit tree, write DREAMS.md",
        "when": {"event": "clock.dream"},
        "do": {"skill": "builtin.dream"},
    },
    {
        "name": "quiet_review",
        "under": "learning_evolution",
        "core": True,
        "about": "chat quiet after a turn (within pace) -> lightweight review",
        "when": {"all": [
            {"fact": "pace_ok", "is": True},
            {"event": "chat.quiet"},
        ]},
        "do": {"skill": "builtin.review"},
    },
    {
        "name": "proactive_act",
        "under": "awake_own",
        "core": True,
        "about": "proactive acting enabled (proactive_mode == on)",
        "when": {"fact": "proactive_mode", "is": "on"},
        "do": None,
    },
    {
        "name": "learned_proactive",
        "under": "proactive_act",
        "core": True,
        "slot": True,
        "about": "learned proactive skills & triggers (zero-cost skills unthrottled by pace)",
        "when": {"not": {"fact": "learning_mode", "is": "off"}},
        "do": None,
    },
    {
        "name": "proactive_wakes",
        "under": "proactive_act",
        "core": True,
        "about": "within hourly own-budget pace (pace_ok == true)",
        "when": {"fact": "pace_ok", "is": True},
        "do": None,
    },
    {
        "name": "agent_calendar_due",
        "under": "proactive_wakes",
        "core": True,
        "about": "agent-scheduled calendar block due -> wake on own budget",
        "when": {"event": "calendar.due", "match": {"by": "agent"}},
        "do": {"wake": {"whose": "own", "mode": "wake"}},
    },
    {
        "name": "intention_due",
        "under": "proactive_wakes",
        "core": True,
        "about": "saved intention due (time or event) -> wake on own budget",
        "when": {"event": "intention.due"},
        "do": {"wake": {"whose": "own", "mode": "wake"}},
    },
    {
        "name": "backlog_piled",
        "under": "proactive_wakes",
        "core": True,
        "about": "space event backlog reached threshold -> proactive wake",
        "when": {"event": "space.piled"},
        "do": {"wake": {"whose": "own", "mode": "wake"}},
    },
    {
        "name": "practice_due",
        "under": "awake_own",
        "core": True,
        "about": "learn_only mode (within pace): practice intention or learning plan due -> wake",
        "when": {"all": [
            {"fact": "proactive_mode", "is": "learn_only"},
            {"fact": "pace_ok", "is": True},
            {"any": [
                {"event": "intention.due", "match": {"kind": "practice"}},
                {"event": "calendar.due", "match": {"by": "agent", "kind": "plan"}},
            ]},
        ]},
        "do": {"wake": {"whose": "own", "mode": "wake"}},
    },
)

# Legacy format-1 builtin names mapped to their format-2 equivalents on migration.
_LEGACY_BUILTIN_MAP = {
    "named": "named",
    "failed": "action_failed",
    "approval": "approval_waiting",
}


def _default_nodes(now=None) -> list:
    created = time.time() if now is None else now
    rows = []
    for node in BUILTIN:
        row = {
            **deepcopy(node),
            "source": "builtin",
            "evidence": "builtin",
            "enabled": True,
            "uses": 0,
            "done": 0,
            "failed": 0,
            "created": created,
        }
        rows.append(row)
    return rows


def check_condition(condition, depth=0) -> dict:
    """A condition as kept: only the objective forms above."""
    if depth > 8 or not isinstance(condition, dict) or len(condition) == 0:
        raise ValueError("a condition is an object: event, outcome, fact, all, any or not")
    keys = set(condition)
    if keys & {"all", "any"}:
        (name,) = keys & {"all", "any"}
        if keys != {name} or not isinstance(condition[name], list) or not condition[name]:
            raise ValueError(f"{name} is a nonempty list of conditions")
        return {name: [check_condition(part, depth + 1) for part in condition[name]]}
    if "not" in keys:
        if keys != {"not"}:
            raise ValueError("not takes one condition")
        return {"not": check_condition(condition["not"], depth + 1)}
    if "event" in keys:
        if not keys <= {"event", "match", "place"}:
            raise ValueError("an event condition is {event, match?, place?}")
        kinds = condition["event"]
        if not (isinstance(kinds, str) or (isinstance(kinds, list) and kinds and all(isinstance(k, str) for k in kinds))):
            raise ValueError("event is a kind, a list of kinds, or *")
        if not isinstance(condition.get("match", {}), dict):
            raise ValueError("match is {field: value}")
        return dict(condition)
    if "outcome" in keys:
        if not keys <= {"outcome", "verb", "place"}:
            raise ValueError("an outcome condition is {outcome: [ends], verb?, place?}")
        ends = condition["outcome"]
        if not isinstance(ends, list) or not ends or not set(ends) <= {"done", "refused", "failed", "cancelled", "unknown"}:
            raise ValueError("outcome lists ends: done, refused, failed, cancelled, unknown")
        return dict(condition)
    if "fact" in keys:
        if condition["fact"] not in FACTS:
            raise ValueError(f"a fact is one of {', '.join(FACTS)}")
        ops = keys - {"fact"}
        if len(ops) != 1 or not ops <= {"is", "in", "below", "above", "has"}:
            raise ValueError("a fact condition has one of is, in, below, above, has")
        if "in" in condition and not isinstance(condition["in"], (list, tuple)):
            raise ValueError("fact `in` requires a list of values")
        return dict(condition)
    raise ValueError("a condition is event, outcome, fact, all, any or not: an objective condition")


def check_answer(answer):
    """An answer as kept: one of the five; stopping may come with reminding the owner, and
    remind/wake/stop may declare one of the four R9 system notification kinds."""
    if answer is None:
        return None
    if not isinstance(answer, dict) or not answer:
        raise ValueError("an answer is one of: call a skill, wake it, stop, remind the owner, or nothing")
    kinds = set(answer) - {"args", "notify"}
    valid = ({"skill"}, {"wake"}, {"stop"}, {"stop", "remind"}, {"remind"}, {"nothing"})
    if kinds not in valid or ("args" in answer and kinds != {"skill"}):
        raise ValueError("an answer is one of: call a skill, wake it, stop, remind the owner, or nothing "
                         "(stopping may come with a reminder)")
    if "notify" in answer and answer["notify"] not in NOTIFY_KINDS:
        raise ValueError(f"notify is one of {', '.join(NOTIFY_KINDS)}")
    if "skill" in answer and (not isinstance(answer["skill"], str) or not answer["skill"].strip()):
        raise ValueError("skill names the skill to call")
    if "remind" in answer and not isinstance(answer["remind"], str):
        raise ValueError("remind is the text to remind the owner with")
    if "wake" in answer:
        wake = answer["wake"]
        if isinstance(wake, bool):
            if not wake:
                raise ValueError("wake must be true or {whose, mode?}")
        elif isinstance(wake, dict):
            if wake.get("whose") not in ("owner", "own", "from_event", "from_outcome"):
                raise ValueError("wake.whose is owner, own, from_event or from_outcome")
            if wake.get("mode", "wake") not in ("turn", "wake"):
                raise ValueError("wake.mode is turn or wake")
        else:
            raise ValueError("wake must be true or {whose, mode?}")
    if "stop" in answer:
        stop = answer["stop"]
        if stop is True or stop in ("chat", "all"):
            pass
        elif isinstance(stop, dict) and set(stop) in ({"place_kind"}, {"place"}):
            pass
        else:
            raise ValueError("stop is true, 'chat', 'all', {'place_kind': ...} or {'place': ...}")
    return dict(answer)


def _value(view, path):
    value = view
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def holds(condition, view) -> bool:
    """Whether `condition` holds on `view` ({event?, facts, now})."""
    if "all" in condition:
        return all(holds(part, view) for part in condition["all"])
    if "any" in condition:
        return any(holds(part, view) for part in condition["any"])
    if "not" in condition:
        return not holds(condition["not"], view)
    event = view.get("event")
    if "event" in condition:
        if not event or event.get("kind") == "asp.outcome":
            return False
        kinds = condition["event"]
        if kinds != "*" and event.get("kind") not in ([kinds] if isinstance(kinds, str) else kinds):
            return False
        if condition.get("place") and event.get("place") != condition["place"]:
            return False
        data = event.get("data") or {}
        for field, wanted in (condition.get("match") or {}).items():
            # Envelope `kind` is matched by condition["event"]; match checks payload data first
            # and falls back to envelope attributes (`addressed`, `place`, `by`) when absent.
            have = _value(data, field)
            if have is None and field in ("addressed", "place", "by"):
                have = event.get(field)
            if isinstance(wanted, list):
                if have not in wanted:
                    return False
            elif have != wanted:
                return False
        return True
    if "outcome" in condition:
        if not event or event.get("kind") != "asp.outcome" or event.get("end") not in condition["outcome"]:
            return False
        if condition.get("verb") and event.get("verb") != condition["verb"]:
            return False
        return not condition.get("place") or event.get("place") == condition["place"]
    if "fact" in condition:
        have = (view.get("facts") or {}).get(condition["fact"])
        if "is" in condition:
            return have == condition["is"]
        if "in" in condition:
            return have in condition["in"]
        if "has" in condition:
            return isinstance(have, (list, tuple, set)) and condition["has"] in have
        if have is None:
            return False
        if "below" in condition:
            return have < condition["below"]
        return have > condition["above"]
    return False


def is_situation(condition) -> bool:
    """Whether the condition is a situation the agent is in for a while (facts only), which
    narrower nodes can hang under, as opposed to an event that happens once."""
    if "all" in condition or "any" in condition:
        return all(is_situation(part) for part in condition.get("all") or condition.get("any"))
    if "not" in condition:
        return is_situation(condition["not"])
    return "fact" in condition


def _contains_unconstrained_wildcard(condition: dict) -> bool:
    if "all" in condition:
        return all(_contains_unconstrained_wildcard(p) for p in condition["all"])
    if "any" in condition:
        return any(_contains_unconstrained_wildcard(p) for p in condition["any"])
    if "not" in condition:
        return False
    if "event" in condition:
        return condition["event"] == "*" and not condition.get("place") and not condition.get("match")
    return False


def _matches_protected_event(condition: dict) -> bool:
    if "all" in condition or "any" in condition:
        parts = condition.get("all") or condition.get("any")
        return any(_matches_protected_event(p) for p in parts)
    if "not" in condition:
        return _matches_protected_event(condition["not"])
    if "event" in condition:
        ev = condition["event"]
        kinds = [ev] if isinstance(ev, str) else ev
        return bool(set(kinds) & PROTECTED_EVENTS)
    return False


class Tree:
    """One identity's tree of reactions (see the module)."""

    def __init__(self, identity):
        self.identity = identity
        self.path = identity.directory / "reactions.json"
        self._lock = threading.RLock()
        saved = read(self.path, None)
        if saved is None:
            saved = {"format": FORMAT, "extension_slots": list(EXTENSION_SLOTS), "nodes": _default_nodes()}
            self._save(saved)
        elif int(saved.get("format") or 1) < FORMAT:
            saved = self._migrate(saved)
            self._save(saved)
        self.data = saved
        self.lit = []
        self._build()

    def _migrate(self, old: dict) -> dict:
        """Upgrade a format-1 tree to format-2 (23-node T_0), keeping owner/learned nodes and
        carrying over enabled/disabled states of legacy builtins."""
        defaults = _default_nodes()
        by_name = {n["name"]: n for n in defaults}
        custom = []
        for node in old.get("nodes") or ():
            if not isinstance(node, dict) or not node.get("name"):
                continue
            if node.get("source") == "builtin":
                mapped = _LEGACY_BUILTIN_MAP.get(node["name"])
                if mapped and mapped in by_name:
                    by_name[mapped]["enabled"] = bool(node.get("enabled", True))
                    by_name[mapped]["uses"] = int(node.get("uses") or 0)
                    by_name[mapped]["done"] = int(node.get("done") or 0)
                continue
            row = dict(node)
            row.setdefault("failed", 0)
            row.setdefault("core", False)
            if row["name"] in by_name:
                continue
            custom.append(row)
        return {"format": FORMAT, "extension_slots": list(EXTENSION_SLOTS), "nodes": defaults + custom}

    def _save(self, data=None) -> None:
        atomic_write(self.path, json.dumps(data or self.data, ensure_ascii=False, indent=2) + "\n")

    def _build(self) -> None:
        """The nodes as a behaviour tree the core judges."""
        reflexes = Reflexes(1.0)
        for node in self._in_order():
            condition = node["when"]
            answer = node.get("do")
            reflexes.set(node["name"], lambda view, c=condition: holds(c, view),
                         (lambda a=answer: a) if answer else None, under=node.get("under"))
            if not node.get("enabled", True):
                reflexes.nodes[node["name"]].stopped = True
        self.reflexes = reflexes

    def _in_order(self) -> list:
        """The nodes, each after the node it hangs under, in their order at each place."""
        nodes = self.data["nodes"]
        placed, out = set(), []
        while len(out) < len(nodes):
            progressed = False
            for node in nodes:
                if node["name"] not in placed and (node.get("under") is None or node["under"] in placed):
                    out.append(node)
                    placed.add(node["name"])
                    progressed = True
            if not progressed:
                break  # a node whose parent is gone is not judged
        return out

    def node(self, name) -> dict | None:
        return next((node for node in self.data["nodes"] if node["name"] == name), None)

    def judge(self, view) -> dict | None:
        """The node that takes over on `view` and its answer ({node, answer, path}), or None."""
        with self._lock:
            # A situation's own answer comes when the situation comes (judge_situations), not
            # with every event while it lasts; events are answered by event/outcome nodes.
            found = self.reflexes.select(view, accept=lambda n: not is_situation(self.node(n.name)["when"]))
            if found is None:
                return None
            return self._took(found)

    def judge_situations(self, view, held: set) -> list[dict]:
        """With no event: all situation leaves whose condition just transitioned False -> True
        (rising-edge latching in tree priority order), updating `held` with currently active leaves."""
        with self._lock:
            sit_view = {**view, "event": None}
            active: list = []

            def walk(parent=None) -> None:
                for rnode in self.reflexes.children(parent):
                    if rnode.stopped or rnode.set_aside:
                        continue
                    row = self.node(rnode.name)
                    if row is None or not is_situation(row["when"]):
                        continue
                    if not holds(row["when"], sit_view):
                        continue
                    walk(rnode.name)
                    if row.get("do") is not None:
                        active.append(rnode)

            walk(None)
            active_names = {rnode.name for rnode in active}
            newly = [rnode for rnode in active if rnode.name not in held]
            held.clear()
            held.update(active_names)
            return [self._took(rnode) for rnode in newly]

    def judge_situation(self, view, held) -> dict | None:
        """Compatibility wrapper returning the highest-priority newly entered situation leaf, or None."""
        fired = self.judge_situations(view, held)
        return fired[0] if fired else None

    def _took(self, found) -> dict:
        with self._lock:
            answer = found.do() if callable(found.do) else None
            node = self.node(found.name)
            node["uses"] = int(node.get("uses") or 0) + 1
            node["last"] = time.time()
            self.lit = self.reflexes.path(found.name)
            self._save()
            return {"node": found.name, "answer": answer, "path": list(self.lit), "about": node.get("about"),
                    "rank": self._rank(found.name)}

    def _rank(self, name) -> list:
        """Where a node stands in the order (smaller first): an earlier node interrupts a later one."""
        ranks, node = [], self.reflexes.nodes.get(name)
        while node is not None:
            siblings = self.reflexes.children(node.under)
            ranks.insert(0, [n.name for n in siblings].index(node.name))
            node = self.reflexes.nodes.get(node.under) if node.under is not None else None
        return ranks

    def counted(self, name, done) -> bool:
        """Record the outcome of a node's answer. Returns True if a failing learned node was
        automatically demoted/disabled (anti-livelock: >=3 uses and <25% success)."""
        demoted = False
        with self._lock:
            node = self.node(name)
            if node is None:
                return False
            if done:
                node["done"] = int(node.get("done") or 0) + 1
            else:
                node["failed"] = int(node.get("failed") or 0) + 1
            if node.get("source") == "learned" and node.get("enabled", True):
                total = int(node.get("done") or 0) + int(node.get("failed") or 0)
                if total >= DEMOTE_USES and int(node.get("done") or 0) / total < DEMOTE_RATE:
                    node["enabled"] = False
                    node["evidence"] = "proposed"
                    demoted = True
                    self._build()
            self._save()
        return demoted

    def audit(self) -> dict:
        """Dreaming health audit over learned nodes: promote effective ones (>=5 uses, >=80% done)
        and demote/disable failing ones (>=3 uses, <25% done)."""
        promoted, demoted = [], []
        with self._lock:
            changed = False
            for node in self.data["nodes"]:
                if node.get("source") != "learned":
                    continue
                done = int(node.get("done") or 0)
                failed = int(node.get("failed") or 0)
                total = done + failed
                if total >= DEMOTE_USES and done / total < DEMOTE_RATE and node.get("enabled", True):
                    node["enabled"] = False
                    node["evidence"] = "proposed"
                    demoted.append(node["name"])
                    changed = True
                elif (
                    total >= PROMOTE_USES
                    and done / total >= PROMOTE_RATE
                    and node.get("evidence") in ("proposed", "own_test", "replayed")
                ):
                    node["evidence"] = "effective"
                    promoted.append(node["name"])
                    changed = True
            if changed:
                self._save()
                self._build()
        return {"promoted": promoted, "demoted": demoted}

    # Changing the tree.

    def _check_learned_guard(self, under, when, do, *, skills=None, places=None) -> None:
        """Enforce anti-lobotomy, non-shadowing, and R11 evidence gate for agent self-evolution."""
        if under is None:
            raise ValueError("learned nodes must attach under learned_reactive, learned_proactive, "
                             "or an owner situation branch")
        parent = self.node(under)
        if parent is None:
            raise ValueError(f"no node {under!r} to hang it under")
        anc = self.reflexes.path(under)
        in_slot = any(slot in anc for slot in EXTENSION_SLOTS)
        if not in_slot:
            # Allow hanging under an owner-created non-core branch (strictly below owner_message).
            top = self.node(anc[0]) if anc else None
            owner_msg = self.node("owner_message")
            if top is None or top.get("source") != "owner":
                raise ValueError("learned nodes must stay inside learned_reactive or learned_proactive")
            if owner_msg is not None and self._rank(top["name"]) < self._rank("owner_message"):
                raise ValueError("learned nodes cannot attach above owner_message")
        if _matches_protected_event(when):
            raise ValueError("a learned node cannot intercept protected core events")
        if _contains_unconstrained_wildcard(when):
            raise ValueError("a learned node cannot use unconstrained wildcard event '*'")
        if do and "skill" in do:
            sname = do["skill"]
            if sname.startswith("builtin."):
                raise ValueError("a learned node cannot invoke builtin lifecycle skills")
            if skills is not None:
                srow = skills.get(sname)
                if not srow or srow.get("archived"):
                    raise ValueError(f"skill {sname!r} does not exist or is archived")
                place_id = when.get("place")
                pkind = (places or {}).get(place_id, {}).get("kind") if place_id else None
                ev_level = srow.get("evidence", "proposed")
                if pkind != "folder" and ev_level != "effective":
                    raise ValueError(f"skill {sname!r} is {ev_level!r}; external-consequence spaces require 'effective'")
                if pkind == "folder" and EVIDENCE_RANK.get(ev_level, 0) < EVIDENCE_RANK["own_test"]:
                    raise ValueError(f"skill {sname!r} has not passed own_test")

    def evolve(self, *, authority, op, name, when=None, do=None, under=None, before=None,
               about=None, skills=None, places=None, origin=None) -> dict:
        """Full governed tree evolution (add | edit | move | enable | disable | remove) enforcing
        provenance authority, anti-lobotomy kernel protection, non-shadowing, and R11 evidence."""
        if authority not in ("owner", "own"):
            raise ValueError("only the owner or the agent's own initiative may evolve the behavior tree")
        if op not in ("add", "edit", "move", "enable", "disable", "remove"):
            raise ValueError(f"unknown tree_evolve op {op!r}")
        with self._lock:
            existing = self.node(name)
            if authority == "own" and existing is not None:
                if existing.get("core") or existing.get("source") in ("builtin", "owner"):
                    raise ValueError(f"cannot {op} protected {existing.get('source')} node {name!r}")
            if op == "add":
                target_under = under
                if authority == "own" and target_under is None:
                    target_under = "learned_reactive"
                checked_when = check_condition(when)
                checked_do = check_answer(do)
                if authority == "own":
                    self._check_learned_guard(target_under, checked_when, checked_do, skills=skills, places=places)
                return self.add(name, checked_when, checked_do, under=target_under, before=before,
                                about=about or "", source="owner" if authority == "owner" else "learned",
                                origin=origin)
            if existing is None:
                raise ValueError(f"no node {name!r}")
            if op == "edit":
                if existing.get("source") == "builtin" and (when is not None or do is not None):
                    raise ValueError("a built-in reaction's condition and action cannot be changed")
                new_when = check_condition(when) if when is not None else existing["when"]
                new_do = check_answer(do) if do is not None else existing.get("do")
                if any(n.get("under") == name for n in self.data["nodes"]) and not is_situation(new_when):
                    raise ValueError(f"{name!r} has nodes under it; its condition must stay a situation")
                if authority == "own":
                    self._check_learned_guard(existing.get("under"), new_when, new_do, skills=skills, places=places)
                return self.edit(name, about=about, when=new_when if when is not None else None,
                                 do=new_do if do is not None else None)
            if op == "move":
                if existing.get("source") == "builtin":
                    raise ValueError("a built-in reaction cannot be moved")
                if authority == "own":
                    self._check_learned_guard(under, existing["when"], existing.get("do"), skills=skills, places=places)
                return self.move(name, under=under, before=before)
            if op in ("enable", "disable"):
                if op == "enable" and authority == "own":
                    self._check_learned_guard(existing.get("under"), existing["when"], existing.get("do"),
                                              skills=skills, places=places)
                return self.enable(name, op == "enable")
            if op == "remove":
                self.remove(name)
                return {"removed": name}
            raise ValueError(f"unknown tree_evolve op {op!r}")

    def add(self, name, when, do, *, under=None, before=None, about="", source="owner", evidence=None,
            origin=None) -> dict:
        """A node hung under `under` (None: the root), last there unless `before`."""
        with self._lock:
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise ValueError("a node's name is 1-80 characters")
            if source not in SOURCES or source == "builtin":
                raise ValueError("a node is added by the owner or learned")
            if self.node(name) is not None:
                raise ValueError(f"a node {name!r} is in the tree already")
            when = check_condition(when)
            do = check_answer(do)
            if under is not None:
                parent = self.node(under)
                if parent is None:
                    raise ValueError(f"no node {under!r} to hang it under")
                if not is_situation(parent["when"]):
                    raise ValueError(f"{under!r} answers something that happens once; nodes hang under a situation")
            row = {"name": name, "about": about or name, "when": when, "do": do, "under": under,
                   "core": False, "source": source,
                   "evidence": evidence or ("owner" if source == "owner" else "proposed"),
                   "enabled": True, "uses": 0, "done": 0, "failed": 0, "created": time.time(),
                   **({"origin": origin} if origin else {})}
            nodes = self.data["nodes"]
            if before is not None:
                index = next((i for i, n in enumerate(nodes) if n["name"] == before and n.get("under") == under), None)
                if index is None:
                    raise ValueError(f"before={before!r} names no node at that place")
                nodes.insert(index, row)
            else:
                nodes.append(row)
            self._save()
            self._build()
            return row

    def move(self, name, *, under=None, before=None) -> dict:
        with self._lock:
            node = self.node(name)
            if node is None:
                raise ValueError(f"no node {name!r}")
            if node.get("source") == "builtin":
                raise ValueError("a built-in reaction cannot be moved")
            self.data["nodes"].remove(node)
            try:
                if under is not None and (under == name or name in self.reflexes.path(under)):
                    raise ValueError("a node cannot hang under itself")
                if under is not None:
                    parent = self.node(under)
                    if parent is None or not is_situation(parent["when"]):
                        raise ValueError(f"{under!r} is not a situation node")
                node["under"] = under
                nodes = self.data["nodes"]
                index = next((i for i, n in enumerate(nodes) if n["name"] == before), len(nodes)) if before else len(nodes)
                nodes.insert(index, node)
            except ValueError:
                self.data["nodes"].append(node)
                raise
            self._save()
            self._build()
            return node

    def edit(self, name, *, about=None, when=None, do=None) -> dict:
        """Update a node's description, condition, or answer."""
        with self._lock:
            node = self.node(name)
            if node is None:
                raise ValueError(f"no node {name!r}")
            if node.get("source") == "builtin" and (when is not None or do is not None):
                raise ValueError("a built-in reaction's condition and action cannot be changed")
            if about is not None:
                node["about"] = str(about).strip() or node["name"]
            if when is not None:
                checked = check_condition(when)
                if any(n.get("under") == name for n in self.data["nodes"]) and not is_situation(checked):
                    raise ValueError(f"{name!r} has nodes under it; its condition must stay a situation")
                node["when"] = checked
            if do is not None:
                node["do"] = check_answer(do)
            self._save()
            self._build()
            return node

    def enable(self, name, on=True) -> dict:
        with self._lock:
            node = self.node(name)
            if node is None:
                raise ValueError(f"no node {name!r}")
            node["enabled"] = bool(on)
            self._save()
            self._build()
            return node

    def remove(self, name) -> None:
        with self._lock:
            node = self.node(name)
            if node is None:
                raise ValueError(f"no node {name!r}")
            if node["source"] == "builtin":
                raise ValueError("a built-in reaction can be disabled, not deleted")
            gone = {name} | {n["name"] for n in self.data["nodes"] if name in self.reflexes.path(n["name"])}
            if any(self.node(g).get("source") == "builtin" for g in gone if self.node(g)):
                raise ValueError("cannot remove a subtree containing a built-in reaction")
            self.data["nodes"] = [n for n in self.data["nodes"] if n["name"] not in gone]
            self._save()
            self._build()

    def set_evidence(self, name, evidence) -> None:
        if evidence not in EVIDENCE:
            raise ValueError(f"evidence is one of {', '.join(EVIDENCE)}")
        with self._lock:
            node = self.node(name)
            if node is not None:
                node["evidence"] = evidence
                self._save()

    # Browsing it like folders.

    def level(self, path=()) -> dict:
        """One level of the tree, in order: the nodes under the last name of `path` (the root
        when empty), each with how many nodes it holds and whether it is on the path of the
        node that last took over."""
        path = [name for name in path if name]
        under = path[-1] if path else None
        if under is not None and self.node(under) is None:
            raise ValueError(f"no node {under!r}")
        rows = []
        for node in self._in_order():
            if node.get("under") != under:
                continue
            below = [n for n in self.data["nodes"] if node["name"] in self.reflexes.path(n["name"])[:-1]]
            rows.append({"name": node["name"], "about": node.get("about"), "when": node["when"], "do": node.get("do"),
                         "source": node["source"], "evidence": node.get("evidence"), "enabled": node.get("enabled", True),
                         "core": bool(node.get("core")), "slot": bool(node.get("slot")),
                         "uses": node.get("uses", 0), "done": node.get("done", 0), "failed": node.get("failed", 0),
                         "children": len(below), "last": node.get("last"), "lit": node["name"] in self.lit,
                         "origin": node.get("origin")})
        return {"path": path, "nodes": rows}

    def full(self) -> dict:
        """The whole tree as a nested hierarchy for an explorer-style two-pane editor."""
        with self._lock:
            by_parent: dict[str | None, list[dict]] = {}
            for node in self._in_order():
                by_parent.setdefault(node.get("under"), []).append(node)

            def build(parent: str | None) -> list[dict]:
                out = []
                for node in by_parent.get(parent, ()):
                    kids = build(node["name"])
                    out.append({
                        "name": node["name"], "about": node.get("about") or node["name"],
                        "when": node["when"], "do": node.get("do"), "under": node.get("under"),
                        "core": bool(node.get("core")), "slot": bool(node.get("slot")),
                        "source": node["source"], "evidence": node.get("evidence"),
                        "enabled": node.get("enabled", True), "uses": node.get("uses", 0),
                        "done": node.get("done", 0), "failed": node.get("failed", 0),
                        "last": node.get("last"), "lit": node["name"] in self.lit,
                        "origin": node.get("origin"), "situation": is_situation(node["when"]),
                        "children": kids,
                    })
                return out

            return {"nodes": build(None), "lit": list(self.lit)}

    def describe(self) -> str:
        """The tree as the model is told of it: one line a node, indented under its parent."""
        lines = []
        for node in self._in_order():
            depth = len(self.reflexes.path(node["name"])) - 1
            answer = node.get("do") or {}
            does = next(iter(answer), "—") if answer else ("(extension slot)" if node.get("slot") else "(gate)")
            lines.append("  " * depth + f"- {node['name']}: {node.get('about')} [{json.dumps(node['when'], ensure_ascii=False)}"
                         f" → {does}]{'' if node.get('enabled', True) else ' (disabled)'}")
        return "\n".join(lines)
