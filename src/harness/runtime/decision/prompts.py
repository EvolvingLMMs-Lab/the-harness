"""System prompts assembled from a prompt pack for the skills a run enables.

A pack is a directory of Markdown sections (prompts/core, a package's prompts/<name>). Its
pack.toml lists the sections in order; a section with `skills` is included only when
one of them is enabled:

    sections = [
      { file = "core.md" },
      { file = "learned.md", skills = ["vla", "wam"] },
      { file = "rules_learned.md", skills = ["vla"], optional = true },
    ]

A section { installed = true } is the skills a user installed (the app) that are on: each
Harness skill's summary, calls and prompt.md, and each Agent Skill's name and description
(runtime.installed_skills, runtime.agent_skills).

Inside a section, lines can be kept for some skills only:

    <!-- if: pointing, segmentation -->      kept when all named skills are enabled
    ...
    <!-- else -->                            kept otherwise (optional)
    ...
    <!-- end -->

Markers may also name features of the connection (FEATURES, and those a kind's package
names in its kinds.toml: native_features, which hold under the native contract, and
prompt_features, which always hold): step_limit when the episode's step limit is reported
(core/contract.py), channels when the bench's embodiment declares channels (inputs in
groups that units claim: runtime/tick.py), look when the environment has views and the
model looks at them on its own demand (no runtime.cameras: runtime/task/run.py), senses
when the kind says its environment computes values the model defines, and pauses when it
says its environment pauses a call for a unit of higher priority instead of ending it
(runtime/tick.py). think_while_acting never holds (the model's turn is always its own
now): a pack's text for it is left out. The marker lines themselves never reach the
model, so a prompt with every skill and feature enabled is the pack's text without them. The API documentation stays in the pack
because it describes one embodiment (its frames, reach and numbers); the skills'
code is the same for every embodiment.
"""

from pathlib import Path
import re
import tomllib

from harness.paths import locate


# Sections of a pack without pack.toml (the layout before packs had one).
DEFAULT_SECTIONS = (
    {"file": "core.md"},
    {"file": "learned.md", "skills": ["vla", "wam"]},
    {"file": "reactive.md", "skills": ["reactive"]},
    {"file": "events.md"},
    {"file": "handlers.md", "skills": ["handlers"]},
    {"file": "rules.md"},
    {"file": "rules_learned.md", "skills": ["vla"], "optional": True},
    {"file": "rules_reactive.md", "skills": ["reactive"], "optional": True},
    {"file": "rules_handlers.md", "skills": ["handlers"], "optional": True},
)
# Features of the connection that prompt text may depend on (not skills).
# `look`: the environment has views and the model looks on demand (look, watch): the
# configuration declares no standing watch (runtime.cameras).
# `machine`: programs are not isolated (runtime.isolation false): they run on the machine as
# its user, under the user's approvals (runtime/safety/permissions.py).
FEATURES = ("step_limit", "channels", "think_while_acting", "vision_service", "look", "senses", "pauses", "machine")


def features_for(runtime: dict, channels: bool = False, *, embodiment=None) -> set[str]:
    """The prompt features of a runtime configuration (its observation contract), and
    `channels` when the embodiment declares channels."""
    from harness.embodiments import KINDS

    kind = KINDS[embodiment] if embodiment is not None else None
    features = set(kind.prompt_features if kind else ())
    if runtime.get("contract", "native") == "native":
        features.add("step_limit")
        if kind:
            features.update(kind.native_features)
    if runtime.get("vision"):
        features.add("vision_service")
    if "cameras" not in runtime and kind is not None and kind.cameras:
        features.add("look")
    if not runtime.get("isolation", True):
        features.add("machine")
    return features | ({"channels"} if channels else set())


_MARK = re.compile(r"^\s*<!--\s*(if:\s*(?P<skills>[\w,\s]+?)|(?P<else>else)|(?P<end>end))\s*-->\s*$")


def pack(directory: Path) -> dict:
    """The pack's settings: sections and the exported names it leaves undocumented."""
    path = Path(directory) / "pack.toml"
    if not path.is_file():
        return {"sections": [dict(section) for section in DEFAULT_SECTIONS], "undocumented": []}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    unknown = set(data) - {"sections", "undocumented"}
    if unknown or not data.get("sections"):
        raise ValueError(f"{path}: needs `sections` (and may have `undocumented`); unknown keys {sorted(unknown)}")
    return {"sections": [dict(section) for section in data["sections"]],
            "undocumented": list(data.get("undocumented", []))}


def sections(directory: Path) -> list[dict]:
    """The pack's sections in order ({"file", and optionally "skills", "optional"}):
    pack.toml's, or DEFAULT_SECTIONS without one. A section { pack = "../core" } stands
    for that pack's sections (the core's page first, then the package's own), their files
    named by absolute path."""
    out = []
    for section in pack(directory)["sections"]:
        if "pack" not in section:
            out.append(section)
            continue
        other = locate(Path(directory) / section["pack"]).resolve()
        out += [{**inner, "file": str(locate(other / inner["file"]).resolve()), "included": True}
                for inner in sections(other)]
    return out


def select(text: str, skills) -> str:
    """Keep the lines of `text` whose if/else markers hold for the enabled `skills`."""
    enabled = set(skills)
    stack = []  # (condition holds, in the else branch)
    out = []
    for number, line in enumerate(text.split("\n"), 1):
        match = _MARK.match(line)
        if match is None:
            if all(holds != in_else for holds, in_else in stack):
                out.append(line)
            continue
        if match.group("skills") is not None:
            names = [name.strip() for name in match.group("skills").split(",") if name.strip()]
            stack.append((all(name in enabled for name in names), False))
        elif match.group("else"):
            if not stack or stack[-1][1]:
                raise ValueError(f"line {number}: <!-- else --> without an open <!-- if: ... -->")
            stack[-1] = (stack[-1][0], True)
        else:
            if not stack:
                raise ValueError(f"line {number}: <!-- end --> without an open <!-- if: ... -->")
            stack.pop()
    if stack:
        raise ValueError("an <!-- if: ... --> block is not closed with <!-- end -->")
    return "\n".join(out)


def marked_skills(text: str) -> set[str]:
    """Skills named in the markers of `text`."""
    names = set()
    for line in text.split("\n"):
        match = _MARK.match(line)
        if match and match.group("skills"):
            names |= {name.strip() for name in match.group("skills").split(",") if name.strip()}
    return names


def installed_section(skills, installed=(), agent_skills=None, *, embodiment=None) -> str:
    """The installed section: of the Harness skills a user installed (`installed`, names)
    those enabled, each with its summary, calls and prompt.md; then the Agent Skills
    ({name: {"description", "path"}}), each by name and description."""
    from harness.runtime.execution.skills import load_skills

    known = load_skills()
    parts = []
    for name in installed:
        skill = known.get(name)
        if skill is None or name not in set(skills):
            continue
        skill = skill.for_embodiment(embodiment)
        text = f"Skill {name} (installed by the user): {skill.summary}\n  calls: "
        text += ", ".join(f"{call}()" for call in skill.public) + "\n"
        extra = skill.path / "prompt.md"
        if extra.is_file():
            text += extra.read_text(encoding="utf-8").strip() + "\n"
        parts.append(text)
    if agent_skills:
        parts.append("Skills the user installed (read one with read_skill(name) before a task it covers):\n"
                     + "".join(f"  {name}: {row['description']}\n" for name, row in agent_skills.items()))
    return "".join(f"\n{part}" for part in parts)


def assemble_prompt(directory: Path, skills, overrides: dict | None = None,
                    features=(), installed=(), agent_skills=None, *, embodiment=None,
                    own: bool = False, only=None) -> str:
    """The pack's sections for the enabled `skills` and connection `features`, joined.
    `overrides` maps a section name (file stem) to another file, e.g. another
    embodiment's core section; `installed` and `agent_skills` fill the installed section
    (installed_section). `own`: only what the pack itself says of its environment, without
    the page it starts from, the core's shared sections and the installed section (an
    environment attached to a conversation that has those already). `only`: just the
    sections that one of these skills switches on (a skill switched on while a
    conversation runs)."""
    from harness.paths import ROOT

    directory = Path(directory)
    enabled = set(skills) | set(features)
    parts = []
    for section in sections(directory):
        if own and (section.get("included") or section.get("installed")
                    or ROOT.resolve() in locate(directory / section["file"]).resolve().parents):
            continue
        if only is not None and not set(section.get("skills") or ()) & set(only):
            continue
        if section.get("installed"):
            text = installed_section(skills, installed, agent_skills, embodiment=embodiment)
            if text:
                parts.append(text.rstrip("\n"))
            continue
        name = Path(section["file"]).stem
        wanted = section.get("skills")
        if wanted and not set(skills) & set(wanted):
            continue
        # A section of another pack may be another package's (paths.locate).
        path = locate(Path((overrides or {}).get(name) or directory / section["file"]))
        if not path.is_file():
            if section.get("optional"):
                continue
            raise ValueError(f"Prompt section {path} is missing")
        parts.append(select(path.read_text(encoding="utf-8"), enabled).rstrip("\n"))
    return "\n".join(parts) + "\n"


def mentions(text: str, name: str) -> bool:
    """Whether the prompt refers to an API name: a call or an attribute for functions and
    objects (`recall(`, `library.propose(`), the bare word for constants (upper case) and
    classes (ClosedLoop)."""
    bare = name.isupper() or name[:1].isupper()
    pattern = rf"(?<![\w.]){re.escape(name)}\b" if bare else rf"(?<![\w.]){re.escape(name)}(\(|\.[A-Za-z_])"
    return re.search(pattern, text) is not None


# These calls are present in EpisodeCore even with no reactive skills enabled.
CORE_RULE_CALLS = {"set_reflex", "drop_reflex", "reflexes", "run_controller", "at_priority", "until"}


def documentation_gaps(directory: Path, skills, exported: dict, features=()) -> dict:
    """What the assembled prompt gets wrong about the API: `missing` are functions of
    enabled skills it never shows being called (except those the pack lists as
    undocumented), `stray` are names of disabled skills it still mentions.
    `exported` maps each exported name to its skill, or to the skills that export it."""
    text = assemble_prompt(directory, skills, features=features)
    enabled = set(skills)
    skip = set(pack(directory)["undocumented"])
    public = {name: {owner} if isinstance(owner, str) else set(owner)
              for name, owner in exported.items() if not name.startswith("_")}
    enabled.add("core")
    public.update({name: {"core"} for name in CORE_RULE_CALLS})
    missing = sorted(name for name, owners in public.items()
                     if owners & enabled and not name.isupper() and name not in skip and not mentions(text, name))
    stray = sorted(name for name, owners in public.items() if not owners & enabled and mentions(text, name))
    return {"missing": missing, "stray": stray}
