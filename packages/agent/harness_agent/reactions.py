"""An identity's tree of reactions: passive answers to what happens to it, judged all the time.

One behaviour tree per identity, saved in its folder (reactions.json) and judged by its life
whenever the world changes or a time comes, from its root, with or without a task running,
anyone asking or budget left (the core's Reflexes, runtime/reactive/tree.py, judges it: a
selector at every place, the earlier first; a node whose condition holds is gone into, its
narrower nodes first, then what it does itself). Position is priority: a node higher up
interrupts what a lower one is doing as soon as its condition holds.

A node has three parts:

    condition   when it takes over and, for a situation, when that is over:
                  {"event": KIND or [KINDS] or "*", "match": {field: value or [values]}}
                      an event of a place (its data's fields), e.g. addressed
                  {"outcome": [ENDS], "verb": VERB?}   an action ended so
                  {"fact": NAME, "is"|"below"|"above"|"has": VALUE}
                      a fact of the moment: battery, owner_active, working_in, asleep
                  {"all": [...]}, {"any": [...]}, {"not": {...}}
                `over`: a condition that says the situation is past (else: when the
                condition no longer holds)
    answer      one of five, and only these: {"skill": NAME, "args": {}} call a skill,
                {"wake": true} wake the model, {"stop": true} stop what it is doing,
                {"remind": TEXT} remind the owner, {"nothing": true}; a node with nodes
                under it may have none of its own
    position    the node it hangs under (`under`) and its place among the nodes there

A reaction belongs in the tree only if its condition is objective and it is needed even when
the agent is passive: goals, plans, task steps and ways of doing things never go here (ways
of doing things are skills). Three nodes ship with every identity and can be disabled, never
deleted. A node the owner asks for is marked "added by owner"; one it learns goes through
the evidence levels (proposed, own test passed, replay passed, effective)."""
import json
import threading
import time

from harness.runtime.reactive.tree import Reflexes
from harness.sdk import atomic_write
from .state import read

FORMAT = 1
ANSWERS = ("skill", "wake", "stop", "remind", "nothing")
SOURCES = ("builtin", "owner", "learned")
EVIDENCE = ("builtin", "owner", "proposed", "own_test", "replayed", "effective")
FACTS = ("battery", "owner_active", "working_in", "asleep", "paused", "hour")
BUILTIN = (
    {"name": "named", "about": "named or aimed at it → wake it",
     "when": {"event": "*", "match": {"addressed": True}}, "do": {"wake": True}},
    {"name": "failed", "about": "an action ended failed or unknown → wake it",
     "when": {"outcome": ["failed", "unknown"]}, "do": {"wake": True}},
    {"name": "approval", "about": "needs approval → remind the owner",
     "when": {"event": "approval.waiting"}, "do": {"remind": "An action waits for your approval"}},
)


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
        if not (isinstance(kinds, str) or (isinstance(kinds, list) and all(isinstance(k, str) for k in kinds))):
            raise ValueError("event is a kind, a list of kinds, or *")
        if not isinstance(condition.get("match", {}), dict):
            raise ValueError("match is {field: value}")
        return dict(condition)
    if "outcome" in keys:
        if not keys <= {"outcome", "verb", "place"}:
            raise ValueError("an outcome condition is {outcome: [ends], verb?, place?}")
        ends = condition["outcome"]
        if not isinstance(ends, list) or not set(ends) <= {"done", "refused", "failed", "cancelled", "unknown"}:
            raise ValueError("outcome lists ends: done, refused, failed, cancelled, unknown")
        return dict(condition)
    if "fact" in keys:
        if condition["fact"] not in FACTS:
            raise ValueError(f"a fact is one of {', '.join(FACTS)}")
        ops = keys - {"fact"}
        if len(ops) != 1 or not ops <= {"is", "below", "above", "has"}:
            raise ValueError("a fact condition has one of is, below, above, has")
        return dict(condition)
    raise ValueError("a condition is event, outcome, fact, all, any or not: an objective condition")


def check_answer(answer):
    """An answer as kept: one of the five; stopping may come with reminding the owner ("stop
    what you are doing and remind me to plug in")."""
    if answer is None:
        return None
    kinds = set(answer) - {"args"} if isinstance(answer, dict) else set()
    if not kinds or not kinds <= set(ANSWERS) or (len(kinds) > 1 and kinds != {"stop", "remind"}) or             ("args" in answer and kinds != {"skill"}):
        raise ValueError("an answer is one of: call a skill, wake it, stop, remind the owner, or nothing "
                         "(stopping may come with a reminder)")
    if "skill" in answer and not isinstance(answer["skill"], str):
        raise ValueError("skill names the skill to call")
    if "remind" in answer and not isinstance(answer["remind"], str):
        raise ValueError("remind is the text to remind the owner with")
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
        for field, wanted in (condition.get("match") or {}).items():
            have = event.get(field) if field in ("addressed", "place", "kind") else _value(event.get("data") or {}, field)
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


class Tree:
    """One identity's tree of reactions (see the module)."""

    def __init__(self, identity):
        self.identity = identity
        self.path = identity.directory / "reactions.json"
        self._lock = threading.RLock()
        saved = read(self.path, None)
        if saved is None:
            saved = {"format": FORMAT, "nodes": [{**node, "source": "builtin", "evidence": "builtin", "enabled": True,
                                                  "under": None, "uses": 0, "done": 0, "created": time.time()}
                                                 for node in BUILTIN]}
            self._save(saved)
        self.data = saved
        self.lit = []
        self._build()

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
            # A situation's own answer comes when the situation comes (judge_situation), not
            # with every event while it lasts; events are answered by event nodes.
            found = self.reflexes.select(view, accept=lambda n: not is_situation(self.node(n.name)["when"]))
            if found is None:
                return None
            return self._took(found)

    def judge_situation(self, view, held) -> dict | None:
        """With no event: the situation node that takes over now, only when its situation
        has just come (`held`, the names that held at the last look, is kept up to date)."""
        with self._lock:
            found = self.reflexes.select({**view, "event": None},
                                         accept=lambda n: is_situation(self.node(n.name)["when"]))
            name = found.name if found is not None else None
            if name is None or name in held:
                held.clear()
                if name:
                    held.add(name)
                return None
            held.clear()
            held.add(name)
        return self._took(found)

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

    def counted(self, name, done) -> None:
        """What its answer came to: one more done when it ended done."""
        with self._lock:
            node = self.node(name)
            if node is not None and done:
                node["done"] = int(node.get("done") or 0) + 1
                self._save()

    # Changing the tree.

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
            row = {"name": name, "about": about or name, "when": when, "do": do, "under": under, "source": source,
                   "evidence": evidence or ("owner" if source == "owner" else "proposed"),
                   "enabled": True, "uses": 0, "done": 0, "created": time.time(), **({"origin": origin} if origin else {})}
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
            self.data["nodes"].remove(node)
            try:
                if under is not None and (under == name or name in self.reflexes.path(under)):
                    raise ValueError("a node cannot hang under itself")
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
                         "uses": node.get("uses", 0), "done": node.get("done", 0), "children": len(below),
                         "last": node.get("last"), "lit": node["name"] in self.lit, "origin": node.get("origin")})
        return {"path": path, "nodes": rows}

    def describe(self) -> str:
        """The tree as the model is told of it: one line a node, indented under its parent."""
        lines = []
        for node in self._in_order():
            depth = len(self.reflexes.path(node["name"])) - 1
            answer = node.get("do") or {}
            does = next(iter(answer), "—") if answer else "(narrower nodes only)"
            lines.append("  " * depth + f"- {node['name']}: {node.get('about')} [{json.dumps(node['when'], ensure_ascii=False)}"
                         f" → {does}]{'' if node.get('enabled', True) else ' (disabled)'}")
        return "\n".join(lines)
