"""package.toml: what a package is, and what it provides, found by convention.

A package is a folder with package.toml at its root:

    [package]
    name = "example"
    version = "0.1.0"
    summary = "One line that says what the package gives"
    harness = ">=0.57,<2"             # the harness versions it works with
    depends = { other = ">=0.1,<1" }  # other packages, by name and range
    platforms = ["windows", "macos", "linux"]

    [provides]
    commands = { check-run = "benches.example.check:main" }
    host = "harness_example.host"      # what it adds to the session host (harness/extensions.py)
    workspaces = ["example"]           # the --workspace values that host gives

Everything else it provides is found in its folders and files (CONVENTION): skills/,
embodiments/, benches/, services/, prompts/, configs/profiles/, configs/experiments/, agent-skills/,
kinds.toml, settings.toml and config_keys.toml; docs/ (README, guides, CHANGELOG.md)
and tests/ go with it. [provides] may also list names of the found kinds to say
what the package is for; a listed name that is not there is an error. The registry's
index carries the result, so the harness can find the package that provides an
embodiment, a bench, a skill or a service it lacks (packages/manager.py ensure()).
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
import sys
import tomllib

from .versions import Version, check_range


FILE = "package.toml"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
PLATFORMS = ("windows", "macos", "linux")
# The keys of [package].
PACKAGE_KEYS = {
    "name": "the package's name: lowercase letters, digits and hyphens (its folder's name under packages/)",
    "version": "its version, MAJOR.MINOR.PATCH (a published version never changes)",
    "summary": "one line: what it lets the agent do",
    "harness": "the harness versions it works with, a range such as \">=0.57,<2\" (default: any)",
    "depends": "other packages it needs: { name = \"range\" }",
    "platforms": f"where it runs, among {', '.join(PLATFORMS)} (default: all)",
    "homepage": "a URL for people",
    "license": "its license (SPDX), when it is not the repository's",
}
# What a package provides, and where each is found (CONVENTION) or declared ([provides]).
PROVIDES = {
    "kinds": "embodiment kinds and their sessions: the tables of kinds.toml",
    "embodiments": "embodiments/<name>/embodiment.toml",
    "skills": "skills/<name>/skill.toml",
    "benches": "benches/<name>/bench.toml",
    "services": "services/<name>.toml",
    "prompts": "prompts/<name>.md and prompts/<name>/",
    "profiles": "configs/profiles/<name>.toml: agent configurations (an experiment's agent = \"<name>\")",
    "experiments": "configs/experiments/<name>.toml",
    "agent_skills": "agent-skills/<name>/SKILL.md (Agent Skills)",
    "pages": "ui/static/<name>.html: the pages of the app",
    "settings": "the sections of settings.toml (the app's settings)",
    "config_keys": "the keys of config_keys.toml (an agent's configuration keys and what they do)",
    "commands": "CLI commands, declared only: { name = \"module:function\" }",
    "agents": "kinds of sub-agent that another agent runs (another harness's CLI), declared only: "
              "{ name = \"module:Class\" } (runtime/task/delegation.py)",
    "host": "what it adds to the session host and its frontends, declared only: a module of the package "
            "(harness/extensions.py)",
    "workspaces": "where a conversation can work (the values of --workspace) that its host gives, declared "
                  "only: [\"project\"]; the registry's index carries them, so the harness finds the package "
                  "of an environment it lacks",
}


def platform() -> str:
    """This computer's platform, as PLATFORMS names it."""
    return "windows" if sys.platform.startswith("win") else "macos" if sys.platform == "darwin" else "linux"


def _toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _names(folder: Path, pattern: str) -> list[str]:
    return sorted(path.parent.name for path in folder.glob(pattern))


def discover(folder: Path) -> dict[str, list[str]]:
    """What a package folder provides, by convention (PROVIDES; commands are declared)."""
    folder = Path(folder)
    found = {
        "kinds": sorted(_toml(folder / "kinds.toml")) if (folder / "kinds.toml").is_file() else [],
        "embodiments": _names(folder, "embodiments/*/embodiment.toml"),
        "skills": _names(folder, "skills/*/skill.toml"),
        "benches": _names(folder, "benches/*/bench.toml"),
        "services": sorted(path.stem for path in folder.glob("services/*.toml")),
        "prompts": sorted({path.stem for path in folder.glob("prompts/*.md")}
                          | {path.name for path in folder.glob("prompts/*") if path.is_dir()
                             and not path.name.startswith((".", "__"))}),
        "profiles": sorted(path.stem for path in folder.glob("configs/profiles/*.toml")),
        "experiments": sorted(path.stem for path in folder.glob("configs/experiments/*.toml")),
        "agent_skills": _names(folder, "agent-skills/*/SKILL.md"),
        "pages": sorted(path.stem for path in folder.glob("ui/static/*.html")),
        "settings": sorted(_toml(folder / "settings.toml")) if (folder / "settings.toml").is_file() else [],
        "config_keys": sorted(_toml(folder / "config_keys.toml")) if (folder / "config_keys.toml").is_file()
        else [],
    }
    return found


@dataclass(frozen=True)
class Package:
    """A package as its package.toml declares it, with what it provides (PROVIDES)."""

    name: str
    version: str
    summary: str = ""
    harness: str = ""
    depends: dict = field(default_factory=dict)
    platforms: tuple = PLATFORMS
    homepage: str = ""
    license: str = ""
    provides: dict = field(default_factory=dict)
    commands: dict = field(default_factory=dict)
    agents: dict = field(default_factory=dict)
    path: Path = field(default=None, compare=False)

    def folder(self, kind: str) -> Path:
        """Where the package keeps one kind of what it provides (skills/, agent-skills/...)."""
        return self.path / kind.replace("_", "-")

    def runs_here(self) -> bool:
        return platform() in self.platforms

    def index_entry(self) -> dict:
        """What the registry's index says of this version (registry.py), without its file."""
        return {"harness": self.harness, "depends": dict(self.depends), "platforms": list(self.platforms),
                "provides": {key: list(value) for key, value in self.provides.items()}}


def load(folder) -> Package:
    """The package in `folder` (its package.toml checked, its resources found); ValueError
    says what is wrong."""
    folder = Path(folder)
    path = folder / FILE
    if not path.is_file():
        raise ValueError(f"{folder}: no {FILE}")
    try:
        data = _toml(path)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path}: {error}") from None
    unknown = set(data) - {"package", "provides"}
    if unknown:
        raise ValueError(f"{path}: unknown tables {sorted(unknown)} (package.toml has [package] and [provides])")
    meta = data.get("package") or {}
    unknown = set(meta) - set(PACKAGE_KEYS)
    if unknown:
        raise ValueError(f"{path}: unknown [package] keys {sorted(unknown)}")
    name = str(meta.get("name", ""))
    if not NAME.match(name):
        raise ValueError(f"{path}: name {name!r} is not lowercase letters, digits and hyphens")
    if "version" not in meta:
        raise ValueError(f"{path}: no version")
    version = str(Version.parse(meta["version"]))
    try:
        harness = check_range(meta.get("harness", ""))
        depends = {str(key): check_range(value) for key, value in dict(meta.get("depends", {})).items()}
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from None
    for other in depends:
        if not NAME.match(other) or other == name:
            raise ValueError(f"{path}: depends names {other!r}, not another package")
    platforms = tuple(meta.get("platforms", PLATFORMS))
    if not platforms or set(platforms) - set(PLATFORMS):
        raise ValueError(f"{path}: platforms are among {PLATFORMS}")
    declared = data.get("provides") or {}
    unknown = set(declared) - set(PROVIDES)
    if unknown:
        raise ValueError(f"{path}: unknown [provides] keys {sorted(unknown)}")
    found = discover(folder)
    for key, names in declared.items():
        if key in ("commands", "host", "agents", "workspaces"):
            continue
        missing = sorted(set(names) - set(found[key]))
        if missing:
            raise ValueError(f"{path}: [provides] {key} names {missing}, which {folder.name} does not have "
                             f"({PROVIDES[key]})")
    commands = {str(key): str(value) for key, value in dict(declared.get("commands", {})).items()}
    for command, target in commands.items():
        module, _, function = target.partition(":")
        if not module or not function or not (folder / module.split(".")[0]).is_dir():
            raise ValueError(f"{path}: command {command} is \"module:function\" with a module in the package "
                             f"(e.g. benches.{name.replace('-', '_')}.commands:main), not {target!r}")
    agents = {str(key): str(value) for key, value in dict(declared.get("agents", {})).items()}
    for kind, target in agents.items():
        module, _, attribute = target.partition(":")
        if not module or not attribute or not (folder / module.split(".")[0]).is_dir():
            raise ValueError(f"{path}: agent {kind} is \"module:Class\" with a module in the package, not {target!r}")
    host = str(declared.get("host") or "")
    if host and not (folder / host.split(".")[0]).is_dir():
        raise ValueError(f"{path}: host is a module of the package (e.g. harness_{name.replace('-', '_')}.host), "
                         f"not {host!r}")
    workspaces = declared.get("workspaces", [])
    if not isinstance(workspaces, list) or not all(isinstance(kind, str) and NAME.match(kind) for kind in workspaces):
        raise ValueError(f"{path}: workspaces is a list of names (lowercase letters, digits and hyphens)")
    if workspaces and not host:
        raise ValueError(f"{path}: workspaces are what the package's host gives: declare host too")
    provides = {key: tuple(found[key]) for key in found if found[key]}
    if commands:
        provides["commands"] = tuple(sorted(commands))
    if agents:
        provides["agents"] = tuple(sorted(agents))
    if host:
        provides["host"] = (host,)
    if workspaces:
        provides["workspaces"] = tuple(sorted(workspaces))
    return Package(name=name, version=version, summary=str(meta.get("summary", "")), harness=harness,
                   depends=depends, platforms=platforms, homepage=str(meta.get("homepage", "")),
                   license=str(meta.get("license", "")), provides=provides, commands=commands,
                   agents=agents, path=folder.resolve())


def write(folder: Path, *, name: str, version: str = "0.1.0", summary: str = "", **extra) -> Path:
    """Write a package.toml (a folder of skills becoming a package of its own)."""
    from ..config import dumps

    package = {"name": name, "version": version, "summary": summary,
               **{key: str(value) for key, value in extra.items() if value}}
    path = Path(folder) / FILE
    path.write_text(dumps({"package": package}), encoding="utf-8")
    return path
