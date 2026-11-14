"""Skills: the API a model's programs call.

A skill is a package `skills/<name>/` in the source checkout with

    skill.toml      name, summary, layer, the names it exports, what it needs
    __init__.py     a mixin class with the methods (and optional exports(session) and
                    turn_report(session): what the skill adds to the model's next turn
                    after every program)

A skill runs on the embodiment kinds its `embodiments` names ("*" for every kind). The
kernel's session class is the embodiment's session (runtime/execution/session.py) plus the mixin of
every skill for that embodiment, so skills can call each other's methods. Which skills a
program sees is decided per run: the system names them (or the interface layers do), and
a skill whose services are missing, or that does not run on the run's embodiment, is
dropped, from the kernel namespace and from the prompt alike (runtime/decision/prompts.py), so the
model never reads about an API it cannot call.

The packages' skills (each package's skills/, paths.roots: those of a source checkout and
those a user installed) load beside these; one that does not check, or clashes with one
of these, is left out (USER_PROBLEMS says why) and never changes the built-in skills.
"""

from dataclasses import dataclass, field, replace
import importlib
import sys
from pathlib import Path
import tomllib

from harness.embodiments import KINDS
from harness.paths import ROOT, roots


SKILLS_ROOT = ROOT / "skills"
# Why a package's skill was left out: {folder: reason}.
USER_PROBLEMS: dict[str, str] = {}
# Layers of the interface ladder (R0-R4); every other skill belongs to "base".
LAYERS = ("learned", "reactive", "handlers")
# Which layers an agent has when its configuration does not say: learned off, reactive
# and handlers on.
LAYER_DEFAULTS = {"learned": False, "reactive": True, "handlers": True}
# Service kinds a skill can need (services/<name>/service.toml `kind`).
SERVICE_KINDS = ("segmenter", "vision", "pointer", "vlm", "verifier", "policy", "world_model", "mcp")
# What the agent knows of an environment whose kind declares `knowledge`: "learned", only what
# the agent learned itself (runtime/learning/learner.py), no skill written for it by hand
# loaded; "handwritten", those skills (a reference baseline's) may load.
KNOWLEDGE = ("learned", "handwritten")
# The keys of skills/<name>/skill.toml.
SKILL_KEYS = {
    "name": "the skill's name, the same as its directory",
    "summary": "one line: what the skill gives programs",
    "layer": "base, or the interface layer that turns it on: learned, reactive or handlers",
    "mixin": "the class with its methods, as \"module:Class\" (e.g. \"skills.motion:Motion\")",
    "exports": "the names programs see: the mixin's methods, or names its exports(session) returns",
    "interface": "per-embodiment overrides for summary, mixin and exports (a kind's package can declare its own "
                 "in kinds.toml: interfaces)",
    "required": "never dropped: the session cannot run without it (core)",
    "needs": "service kinds that must all be available",
    "needs_any": "service kinds of which at least one must be available",
    "requires": "skills whose API this one's results or documentation refer to; dropped with them",
    "conflicts": "skills it cannot be enabled with: they export some of the same names",
    "optional": "not among the skills of its layer: only a configuration that enables it by name has it",
    "order": "position in the session's method resolution and in the prompt (lower first)",
    "embodiments": f"the embodiment kinds it runs on, among {', '.join(KINDS)} or [\"*\"] for all installed kinds",
    "requirements": "a skill a user installs: pip requirements, installed into its own .deps folder",
    "knowledge": "\"handwritten\": knowledge of an environment written by hand, left out (not even imported) when "
                 "the agent learns the environment itself (its kind's knowledge = \"learned\")",
    "probe": "a table: the skill is its body's probe, which a run that learns its environment turns on "
             "(runtime/learning/active.py); it exports probe and probe_summary, and its keys say that run's lines for this "
             "body: try (what probe() measures), skills (the basic skills to write) and drills (how a drill's "
             "result is checked)",
}
# The names a body's probe exports, and the keys of its [probe] table (all but try optional).
PROBE_EXPORTS = ("probe", "probe_summary")
PROBE_KEYS = ("try", "skills", "drills")


@dataclass(frozen=True)
class Skill:
    """A skill as its skill.toml declares it (SKILL_KEYS); `path` is its directory."""

    name: str
    summary: str
    layer: str
    mixin: str
    exports: tuple[str, ...]
    # Never dropped: the session cannot run without it.
    required: bool = False
    # Every service kind here must be available, and at least one of needs_any.
    needs: tuple[str, ...] = ()
    needs_any: tuple[str, ...] = ()
    # Skills whose API this one's documentation and results refer to.
    requires: tuple[str, ...] = ()
    # Skills that export some of the same names; never enabled together.
    conflicts: tuple[str, ...] = ()
    # Only when a configuration names it (its layer alone does not bring it).
    optional: bool = False
    order: int = 100
    # The embodiment kinds it runs on (embodiments.KINDS).
    embodiments: tuple[str, ...] = ()
    # "handwritten": knowledge of an environment written by hand (KNOWLEDGE); "" otherwise.
    knowledge: str = ""
    # The body's probe: its [probe] table as (key, text) pairs; empty for any other skill.
    probe: tuple[tuple[str, str], ...] = ()
    path: Path = field(default=None, compare=False)
    interface: dict = field(default_factory=dict, compare=False, hash=False)

    def for_embodiment(self, embodiment: str | None) -> "Skill":
        """The skill as an embodiment kind has it: the variant the kind declares for it
        (Kind.interfaces), else the skill's own for that kind (`interface`), else the skill."""
        kind = KINDS.get(embodiment)
        declared = dict(kind.interfaces.get(self.name, {})) if kind is not None else {}
        if "exports" in declared:
            declared["exports"] = tuple(declared["exports"])
        given = declared or self.interface.get(embodiment)
        return replace(self, **given) if given else self

    @property
    def public(self) -> tuple[str, ...]:
        """The exports without a leading underscore: the API programs are told about (the
        conversation's hook `__wrap_up__` is left out)."""
        return tuple(name for name in self.exports if not name.startswith("_"))


def _skill(path: Path) -> Skill:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    unknown = set(data) - set(SKILL_KEYS)
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")
    if data.get("name") != path.parent.name:
        raise ValueError(f"{path}: name must be the directory name {path.parent.name!r}")
    layer = data.get("layer", "base")
    if layer not in ("base", *LAYERS):
        raise ValueError(f"{path}: layer must be base or one of {LAYERS}")
    for key in ("needs", "needs_any"):
        bad = set(data.get(key, ())) - set(SERVICE_KINDS)
        if bad:
            raise ValueError(f"{path}: {key} names unknown service kinds {sorted(bad)}")
    if "embodiments" not in data:
        raise ValueError(f"{path}: needs `embodiments`: the embodiment kinds the skill runs on, or [\"*\"] for every kind")
    embodiments = tuple(data["embodiments"])
    universal = embodiments == ("*",)
    if universal:
        embodiments = tuple(KINDS)
    # Kinds by name: a kind a package registers may not be installed here (a built-in skill
    # without that kind's package), and the skill is then for the kinds there are.
    if not embodiments or not all(isinstance(kind, str) and kind.isidentifier() for kind in embodiments):
        raise ValueError(f"{path}: embodiments names embodiment kinds (such as {', '.join(sorted(KINDS))})")
    if data.get("knowledge", "") not in ("", "handwritten"):
        raise ValueError(f"{path}: knowledge is \"handwritten\" or absent")
    interface = data.get("interface", {})
    if not isinstance(interface, dict):
        raise ValueError(f"{path}: interface must be a table")
    for kind, variant in interface.items():
        if (not kind.isidentifier() or (not universal and kind not in embodiments) or not isinstance(variant, dict)
                or set(variant) != {"summary", "mixin", "exports"}
                or not all(isinstance(variant[key], str) for key in ("summary", "mixin"))
                or not isinstance(variant["exports"], list)
                or any(name not in data["exports"] for name in variant["exports"])):
            raise ValueError(f"{path}: an interface must name an embodiment and declare summary, mixin and "
                             "a subset of exports")
        variant["exports"] = tuple(variant["exports"])
    probe = data.get("probe")
    if probe is not None:
        if (not isinstance(probe, dict) or "try" not in probe or set(probe) - set(PROBE_KEYS)
                or not all(isinstance(text, str) and text.strip() for text in probe.values())):
            raise ValueError(f"{path}: probe is a table of texts: try, and optionally skills and drills")
        missing = set(PROBE_EXPORTS) - set(data["exports"])
        if missing:
            raise ValueError(f"{path}: a body's probe exports {list(PROBE_EXPORTS)}; {sorted(missing)} missing")
    return Skill(name=data["name"], summary=data.get("summary", ""), layer=layer, mixin=data["mixin"],
                 exports=tuple(data["exports"]), required=bool(data.get("required", False)),
                 needs=tuple(data.get("needs", ())), needs_any=tuple(data.get("needs_any", ())),
                 requires=tuple(data.get("requires", ())), conflicts=tuple(data.get("conflicts", ())),
                 optional=bool(data.get("optional", False)), order=int(data.get("order", 100)),
                 embodiments=embodiments, knowledge=data.get("knowledge", ""),
                 probe=tuple((key, probe[key].strip()) for key in PROBE_KEYS if key in probe) if probe else (),
                 path=path.parent, interface=interface)


_CACHE: dict[tuple, dict[str, Skill]] = {}


def load_skills(root: Path = SKILLS_ROOT, user: bool = True) -> dict[str, Skill]:
    """Every skill under `root`, in prompt order; for the built-in skills, also the
    packages' (each one's skills/ folder, paths.roots), unless `user` is false."""
    root = Path(root).resolve()
    folders = (base / "skills" for base in roots()[1:]) if user and root == SKILLS_ROOT.resolve() else ()
    extra = tuple(folder.resolve() for folder in folders if folder.is_dir())
    key = (root, extra, tuple(KINDS))
    if key not in _CACHE:
        built_in = _load_root(root)
        _CACHE[key] = _with_user_skills(built_in, extra) if extra else built_in
    return _CACHE[key]


def _with_user_skills(built_in: dict, folders) -> dict:
    """The built-in skills and the packages' that check:
    a valid skill.toml, a name and exports of its own (beside the skills it may be enabled
    with), and the skills it requires or conflicts with among them all; one that does not
    is left out with the reason in USER_PROBLEMS, and so are the skills that require it."""
    candidates = {}
    for folder in folders:
        for path in sorted(Path(folder).glob("*/skill.toml")):
            try:
                skill = _skill(path)
                if skill.name in built_in or skill.name in candidates:
                    raise ValueError(f"a skill named {skill.name} is there already")
            except (ValueError, KeyError, OSError, tomllib.TOMLDecodeError) as error:
                USER_PROBLEMS[str(path.parent)] = str(error)
                continue
            candidates[skill.name] = skill
    changed = True
    while changed:
        changed = False
        for skill in list(candidates.values()):
            others = {**built_in, **{name: other for name, other in candidates.items() if name != skill.name}}
            clash = sorted({name for other in others.values() for name in _shared_exports(skill, other)})
            missing = (set(skill.requires) | set(skill.conflicts)) - set(others) - {skill.name}
            problem = f"exports {clash}, which other skills export" if clash else                 f"names unknown skills {sorted(missing)}" if missing else None
            if problem:
                USER_PROBLEMS[str(skill.path)] = problem
                del candidates[skill.name]
                changed = True
    for skill in candidates.values():
        USER_PROBLEMS.pop(str(skill.path), None)
    skills = {**built_in, **candidates}
    return {skill.name: skill for skill in sorted(skills.values(), key=lambda s: (s.order, s.name))}


def _shared_exports(a: Skill, b: Skill) -> set[str]:
    if b.name in a.conflicts or a.name in b.conflicts:
        return set()
    return {name for kind in set(a.embodiments) & set(b.embodiments)
            for name in set(a.for_embodiment(kind).exports) & set(b.for_embodiment(kind).exports)}


def _load_root(root: Path) -> dict[str, Skill]:
    """The skills under one root, checked strictly (names, exports, references)."""
    by_name = {path.parent.name: _skill(path) for path in sorted(root.glob("*/skill.toml"))}
    if not by_name:
        raise ValueError(f"No skills under {root}")

    owners = {}
    for skill in by_name.values():
        for name in skill.exports:
            owners.setdefault(name, []).append(skill)
    duplicates = sorted(name for name, of in owners.items()
                        if any(name in _shared_exports(a, b)
                               for i, a in enumerate(of) for b in of[i + 1:]))
    if duplicates:
        raise ValueError(f"Names exported by more than one skill that may be enabled together: {duplicates}")
    for skill in by_name.values():
        # Optional built-ins may declare conflicts with skills supplied by packages.
        references = skill.requires if skill.optional and root == SKILLS_ROOT.resolve() else (*skill.requires, *skill.conflicts)
        missing = set(references) - by_name.keys()
        if missing:
            raise ValueError(f"Skill {skill.name} names unknown skills {sorted(missing)}")
    return dict(sorted(by_name.items(), key=lambda pair: (pair[1].order, pair[0])))


def skills_for_layers(layers: dict | None, root: Path = SKILLS_ROOT, *, embodiment: str = "none") -> list[str]:
    """The skills of the interface layers given as switches ({"learned": bool, ...} over
    LAYER_DEFAULTS) for an embodiment kind, without the optional ones."""
    layers = {**LAYER_DEFAULTS, **(layers or {})}
    unknown = set(layers) - set(LAYERS)
    if unknown:
        raise ValueError(f"Unknown runtime layers: {sorted(unknown)}")
    return [name for name, skill in load_skills(root).items()
            if embodiment in skill.embodiments and not skill.optional
            and (skill.layer == "base" or layers[skill.layer])]


def probes(root: Path = SKILLS_ROOT) -> list[str]:
    """The skills that probe a body (a [probe] table), one an embodiment kind or more."""
    return [name for name, skill in load_skills(root).items() if skill.probe]


def available_services(options: dict) -> set[str]:
    """Service kinds a kernel's options provide: the segmenter, vision, pointer, VLM and
    verifier configs, and at least one policy, world model or MCP server."""
    kinds = {kind for kind in ("segmenter", "vision", "pointer", "vlm", "verifier") if options.get(kind)}
    if options.get("policies"):
        kinds.add("policy")
    if options.get("world_models"):
        kinds.add("world_model")
    if options.get("mcp"):
        kinds.add("mcp")
    return kinds


@dataclass
class Resolution:
    """The outcome of `resolve`: the enabled skills in prompt order, and each dropped
    skill with the reason."""

    enabled: list[str]
    dropped: dict[str, str]

    def to_dict(self) -> dict:
        """The resolution as a plain dict."""
        return {"enabled": list(self.enabled), "dropped": dict(self.dropped)}


def resolve(requested, services: set[str], *, strict: bool = False, root: Path = SKILLS_ROOT,
            embodiment: str = "none") -> Resolution:
    """The requested skills that can run on this embodiment kind with these services. A
    skill is dropped when it does not run on the embodiment, a service it needs is missing
    or a skill it requires is not enabled (repeated until nothing changes); the
    embodiment's required skills are always enabled. strict: dropping is an error
    (evaluation runs must not run a smaller system than the one they name)."""
    if embodiment not in KINDS:
        raise ValueError(f"Unknown embodiment kind {embodiment!r}; kinds are {sorted(KINDS)}")
    known = load_skills(root)
    requested = list(dict.fromkeys(requested))
    unknown = [name for name in requested if name not in known]
    if unknown:
        raise ValueError(f"Unknown skills {unknown}; known: {sorted(known)}")
    dropped = {name: f"does not run on the {embodiment} embodiment" for name in requested
               if embodiment not in known[name].embodiments}
    wanted = ({name for name in requested if name not in dropped}
              | {name for name, skill in known.items() if skill.required and embodiment in skill.embodiments})
    clashes = sorted({tuple(sorted((name, other))) for name in wanted for other in known[name].conflicts
                      if other in wanted})
    if clashes:
        raise ValueError("Skills that cannot be enabled together (they export the same names): "
                         + "; ".join(f"{a} and {b}" for a, b in clashes))
    changed = True
    while changed:
        changed = False
        for name in [n for n in known if n in wanted]:
            skill = known[name]
            reason = None
            missing = [kind for kind in skill.needs if kind not in services]
            if missing:
                reason = f"no {' or '.join(missing)} service"
            elif skill.needs_any and not set(skill.needs_any) & services:
                reason = f"needs one of the services {', '.join(skill.needs_any)}"
            else:
                off = [other for other in skill.requires if other not in wanted]
                if off:
                    reason = f"requires the skills {', '.join(off)}"
            if reason is not None:
                if skill.required:
                    raise ValueError(f"Required skill {name} cannot run: {reason}")
                wanted.discard(name)
                dropped[name] = reason
                changed = True
    if strict and dropped:
        raise ValueError("Skills the system names cannot run here: "
                         + "; ".join(f"{name} ({reason})" for name, reason in dropped.items()))
    return Resolution([name for name in known if name in wanted], dropped)


def _import(spec: str):
    module, _, attribute = spec.partition(":")
    value = importlib.import_module(module)
    return getattr(value, attribute) if attribute else value


# Skills whose module this interpreter cannot import (a kernel in an environment without
# their dependencies): {name: why}. They are left out of the session, never fatal.
UNAVAILABLE: dict[str, str] = {}


def _mixin(skill: Skill):
    try:
        return _import(skill.mixin)
    except ImportError as error:
        UNAVAILABLE[skill.name] = f"{type(error).__name__}: {error}"
        print(f"skill {skill.name} left out: it cannot be imported here ({UNAVAILABLE[skill.name]})",
              file=sys.stderr, flush=True)
        return None


def _unavailable(skill: str, export: str, why: str):
    def call(*args, **kwargs):
        raise RuntimeError(f"{export}() of skill {skill} cannot run in this kernel: {why}")

    call.__name__ = export
    return call


def mixins(root: Path = SKILLS_ROOT, *, embodiment: str = "none", knowledge: str = "handwritten") -> list[type]:
    """The mixin class of every skill for an embodiment kind, imported, in the skills'
    order (the session's method resolution order); with knowledge "learned", none of the
    handwritten ones (their modules are not imported). A skill whose module cannot be
    imported in this interpreter is left out (UNAVAILABLE says why)."""
    if knowledge not in KNOWLEDGE:
        raise ValueError(f"knowledge is one of {list(KNOWLEDGE)}, not {knowledge!r}")
    found = [_mixin(skill.for_embodiment(embodiment)) for skill in load_skills(root).values() if embodiment in skill.embodiments
             and not (knowledge == "learned" and skill.knowledge == "handwritten")]
    return [mixin for mixin in found if mixin is not None]


def handwritten(root: Path = SKILLS_ROOT) -> list[str]:
    """The skills that are knowledge of an environment written by hand."""
    return [name for name, skill in load_skills(root).items() if skill.knowledge == "handwritten"]


def namespace(session, names, root: Path = SKILLS_ROOT) -> dict:
    """The kernel namespace of a session with the skills `names` enabled: each skill's
    exports(session) when its module defines one, else the session attributes it
    exports."""
    known = load_skills(root)
    result = {}
    for name in names:
        skill = known[name].for_embodiment(getattr(session, "embodiment", None))
        if name in UNAVAILABLE:
            # Enabled, but not importable here: each call says why instead of a NameError.
            result.update({export: _unavailable(name, export, UNAVAILABLE[name]) for export in skill.exports})
            continue
        module = _import(skill.mixin.partition(":")[0])
        values = module.exports(session) if hasattr(module, "exports") else {
            export: getattr(session, export) for export in skill.exports}
        if set(values) != set(skill.exports):
            raise ValueError(f"Skill {name}: exports() returned {sorted(values)}, skill.toml lists "
                             f"{sorted(skill.exports)}")
        result.update(values)
    return result


def reporters(names, root: Path = SKILLS_ROOT) -> list:
    """The turn reports of the skills `names`, in skill order: each skill module's
    turn_report(session) -> {"text", "images"} or None, which the session calls after
    every program (EpisodeCore.drain)."""
    known = load_skills(root)
    found = []
    for name in names:
        if name in UNAVAILABLE:
            continue
        module = _import(known[name].mixin.partition(":")[0])
        if hasattr(module, "turn_report"):
            found.append(module.turn_report)
    return found


def exported_names(root: Path = SKILLS_ROOT) -> dict[str, tuple[str, ...]]:
    """Every exported name and the skills that export it (more than one only for
    skills that conflict)."""
    names = {}
    for skill in load_skills(root).values():
        for export in skill.exports:
            names[export] = (*names.get(export, ()), skill.name)
    return names
