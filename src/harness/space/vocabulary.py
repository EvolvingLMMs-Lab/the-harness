"""Acting from a space's vocabulary, as a model is given an MCP server's tools.

A space without skills of its own (one entered by its address) is used through its
vocabulary alone: every verb becomes a function of the conversation's programs,
`<namespace>.<verb>(object, **args)`, whose name, one-line summary and parameters go into
the model's context (describe); a page of the vocabulary is read only when a program asks
for it (`space_page(name)`). The function returns the action's result when it is done and
raises ActionFailed otherwise, whose `outcome` is typed: `outcome.end` (refused, failed,
cancelled, unknown) and `outcome.reason.code`, so a program decides from it whether to wait,
try again or do something else. The core names no space: what a function is, is read from
the vocabulary.
"""

from __future__ import annotations

import keyword
from typing import Any

from harness.space.environment import ActionFailed


def _schema_text(schema: dict | None) -> str:
    """A verb's parameters in one line: name: type (constraints), ? when optional."""
    if not isinstance(schema, dict):
        return ""
    props = schema.get("properties") or {}
    required = set(schema.get("required") or ())
    parts = []
    for name, prop in props.items():
        prop = prop if isinstance(prop, dict) else {}
        kind = prop.get("type") or ("one of " + "/".join(map(str, prop["enum"])) if "enum" in prop else "any")
        bounds = [f"{k} {prop[k]}" for k in ("minimum", "maximum", "minLength", "maxLength") if k in prop]
        parts.append(f"{name}{'' if name in required else '?'}: {kind}" + (f" ({', '.join(bounds)})" if bounds else ""))
    return ", ".join(parts)


# Names a program has whatever skills it runs with (runtime/execution/session.py).
CORE_NAMES = frozenset({"set_reflex", "drop_reflex", "reflexes", "start_reflex", "stop_reflex", "reflex_method",
                        "guide", "facts", "at_priority", "atomic", "until", "expect", "after", "situations",
                        "run_controller", "decide", "observe", "space_page", "print", "len", "list", "dict"})


def reserved() -> frozenset:
    """Names a namespace of a vocabulary may not take: the core's and every built-in skill's
    exports, and Python's built-ins."""
    import builtins
    import tomllib

    from harness.paths import ROOT

    names_ = set(CORE_NAMES) | set(dir(builtins))
    for path in (ROOT / "skills").glob("*/skill.toml"):
        try:
            with path.open("rb") as handle:
                names_.update(tomllib.load(handle).get("exports") or ())
        except (OSError, ValueError):
            continue
    return frozenset(names_)


def names(vocabulary: dict, taken=()) -> dict[str, str]:
    """{namespace: the name its functions go under in programs}: the namespace itself, or
    space_<namespace> where that name is reserved, taken or not a Python name."""
    out = {}
    blocked = reserved() | set(taken)
    for ns in (vocabulary.get("namespaces") or {}):
        name = ns.replace("-", "_")
        if not name.isidentifier() or keyword.iskeyword(name) or name in blocked:
            name = "space_" + "".join(c if c.isalnum() else "_" for c in ns)
        out[ns] = name
    return out


def describe(vocabulary: dict, space: str | None = None, taken=()) -> str:
    """What the model is told of a space it acts in by its vocabulary: one line per verb."""
    named = names(vocabulary, taken)
    lines = [f"\n\nThis conversation is in a space{f' ({space})' if space else ''}, entered through the Agent "
             "Space Protocol. Its vocabulary gives the functions your programs act with, one per verb, each "
             "`namespace.verb(object, **args)`: it returns the action's result when it is done and raises "
             "ActionFailed otherwise (`error.outcome.end`: refused, failed, cancelled or unknown; "
             "`error.outcome.reason.code` says why; unknown means it may have happened: look before you try again)."]
    for ns, info in (vocabulary.get("namespaces") or {}).items():
        lines.append(f"\n{named.get(ns, ns)}: {(info or {}).get('line', ns)}")
    for verb, decl in sorted((vocabulary.get("verbs") or {}).items()):
        ns, _, short = verb.partition(".")
        params = _schema_text(decl.get("params"))
        obj = f"object: {decl['object']}" if decl.get("object") else ""
        signature = ", ".join(p for p in (obj, params) if p)
        effect = decl.get("effect")
        lines.append(f"  {named.get(ns, ns)}.{short}({signature}) [{effect}] {decl.get('line', '')}".rstrip())
    types = vocabulary.get("types") or {}
    if types:
        lines.append("Things: " + "; ".join(f"{name}: {decl.get('line', '')}".rstrip(": ") for name, decl in sorted(types.items())))
    events = vocabulary.get("events") or {}
    if events:
        lines.append("Events it pushes (each can be a reflex's `when`, set_reflex(name, kind, program)): "
                     + "; ".join(f"{name}: {decl.get('line', '')}".rstrip(": ") for name, decl in sorted(events.items())))
    lines.append("observe(forms=None) gives what you perceive now: its `structure` (things, their properties and "
                 "relations) and the forms asked for (\"text\")."
                 + (f" Pages to read when you need them: {', '.join(sorted(vocabulary['pages']))} (space_page(name))."
                    if vocabulary.get("pages") else ""))
    return "\n".join(lines) + "\n"


class Namespace:
    """The functions of one namespace of a vocabulary, `name.verb(...)`."""

    def __init__(self, name: str, functions: dict[str, Any], line: str = ""):
        self._name, self._functions, self.__doc__ = name, functions, line
        for short, fn in functions.items():
            setattr(self, short, fn)

    def __repr__(self) -> str:
        return "\n".join([f"{self._name}: {self.__doc__ or ''}",
                          *(f"  {self._name}.{short}: {fn.__doc__}" for short, fn in self._functions.items())])

    def __dir__(self):
        return list(self._functions)


def functions(env, vocabulary: dict, taken=()) -> dict[str, Any]:
    """{name: Namespace or function} for a program's namespace: one Namespace per namespace of
    the vocabulary, observe() and space_page()."""
    named = names(vocabulary, taken)
    grouped: dict[str, dict[str, Any]] = {}
    for verb, decl in (vocabulary.get("verbs") or {}).items():
        ns, _, short = verb.partition(".")
        if ns not in named or not short.isidentifier():
            continue
        grouped.setdefault(ns, {})[short] = _function(env, verb, decl)
    out: dict[str, Any] = {named[ns]: Namespace(named[ns], fns, ((vocabulary.get("namespaces") or {}).get(ns) or {}).get("line", ""))
                           for ns, fns in grouped.items()}

    def observe(forms=None):
        """What the agent perceives now: {seq, structure: {things, relations}, forms}."""
        return env.participant.observe(list(forms or []), timeout=env.timeout)

    def space_page(name):
        """A page of the space's vocabulary, read when it is needed."""
        pages = vocabulary.get("pages") or {}
        if name not in pages:
            raise KeyError(f"no page {name!r}; there are {', '.join(sorted(pages)) or 'none'}")
        page = pages[name]
        return page.get("text") or page.get("line") or str(page) if isinstance(page, dict) else str(page)

    out["observe"], out["space_page"], out["ActionFailed"] = observe, space_page, ActionFailed
    return out


def _function(env, verb: str, decl: dict):
    needs_object = bool(decl.get("object"))

    def act(object=None, /, **args):
        if needs_object and object is None:
            raise TypeError(f"{verb} acts on a {decl['object']}: give it first")
        outcome = env.participant.act(verb, object, args, id=env.next_id(), timeout=env.timeout + 30)
        env._outcome(outcome, verb)
        if outcome.done:
            return outcome.result
        reason = outcome.reason
        raise ActionFailed(outcome, f"{verb}: {outcome.end.value}" + (f" ({reason.code}" + (f": {reason.text}" if reason.text else "") + ")" if reason else ""))

    act.__name__ = verb.partition(".")[2]
    act.__doc__ = f"{decl.get('line', '')} ({_schema_text(decl.get('params')) or 'no arguments'}) [{decl.get('effect')}]"
    return act
