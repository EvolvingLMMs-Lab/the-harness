"""Where the harness finds its own files, and where it keeps what it installs.

ROOT is the core's own content, a folder of the package (harness/builtin/: configs/,
skills/, services/, prompts/, benches/, environment/, scripts/ and
third_party/sources.toml), the same in a source checkout and in an installed wheel.
CHECKOUT_ROOT is the repository of a source checkout (None once installed): its
packages/ are developed in place and its third_party/ holds benchmarks' checkouts. Paths
recorded in locks and traces are relative to ROOT or to their package, so they read the
same everywhere.

Packages hold the rest, each folder laid out as ROOT is (skills/, benches/,
embodiments/, services/, prompts/, configs/...): a checkout's packages/<name>/, and the
installed ones that are enabled (HARNESS_PACKAGE_ROOTS, which harness.packages sets).
roots() is ROOT and then them; content is looked up in each in turn (find, locate).

HOME ($HARNESS_HOME, default ~/.cache/harness; the dev channel's is ~/.cache/harness-dev,
channel.py) holds what the harness installs on first use: envs/<name>/<hash>/ (the environment of a service or benchmark), sources/ (checkouts
at pinned commits: a benchmark's, with its assets), weights/, services/ (pid files and
logs of started services), deploy/ (the placement it chose itself) and logs/.
"""

import os
from pathlib import Path
import sys

from . import channel


PACKAGE = Path(__file__).resolve().parent


ROOT = PACKAGE / "builtin"


def _checkout() -> Path | None:
    checkout = PACKAGE.parents[1]
    # A kernel's sandbox shows only parts of a checkout (src/, packages/).
    if PACKAGE.parent.name == "src" and (checkout / "packages").is_dir():
        return checkout
    return None


CHECKOUT_ROOT = _checkout()
# The core's built-in skills and benches import as skills.<name> and benches.<name>, here
# as in the processes it starts (import_roots).
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
# Whether this is a source checkout (a git repository can be exported, `third_party/` is
# the developer's).
CHECKOUT = CHECKOUT_ROOT is not None
if CHECKOUT:
    # A checkout develops its packages: their skills, benches and modules import as the
    # core's do, in this process and in the tests.
    for _manifest in sorted((CHECKOUT_ROOT / "packages").glob("*/package.toml")):
        if str(_manifest.parent) not in sys.path:
            sys.path.append(str(_manifest.parent))
HOME_ENV = "HARNESS_HOME"
DATA_ENV = "HARNESS_DATA"
PACKAGES_ENV = "HARNESS_PACKAGE_ROOTS"


def home() -> Path:
    """The directory of what the harness installs ($HARNESS_HOME, default ~/.cache/harness,
    the channel's own on another channel: ~/.cache/harness-dev)."""
    return Path(os.path.expanduser(os.environ.get(HOME_ENV) or channel.tag("~/.cache/harness"))).resolve()


def data() -> Path:
    """The directory of what the app keeps for its user ($HARNESS_DATA, default ~/.harness,
    the channel's own on another channel: ~/.harness-dev): conversations/, config.toml (the
    model, its key and the settings: settings.py) and logs/."""
    return Path(os.path.expanduser(os.environ.get(DATA_ENV) or channel.tag("~/.harness"))).resolve()


_PACKAGES: dict = {}


def packages() -> list:
    """The packages this process uses (manifest.Package), one per name, each package.toml
    read once (until packages_changed()): a checkout's packages/<name>/ (a source checkout
    develops them all), then the installed ones that are enabled (HARNESS_PACKAGE_ROOTS,
    which harness.packages sets; before that, the user's list). When a checkout's package
    and an installed one have the same name, the checkout's wins: its folder is on
    sys.path first (above), so its modules are the ones this process imports, and its
    skills, benches and prompts must be the ones it finds. One that does not load is left
    out (harness list says why). The user's list is kept only once it was read: a module
    that asks while the harness is still being imported (the embodiment kinds of
    config/__init__.py) gets the packages without it, and the next call reads it."""
    named = os.environ.get(PACKAGES_ENV)
    key = (named, os.environ.get(DATA_ENV))
    if key not in _PACKAGES:
        from .packages.manifest import load

        folders = sorted(path.parent for path in (CHECKOUT_ROOT / "packages").glob("*/package.toml")) \
            if CHECKOUT else []
        folders += [Path(item) for item in (named or "").split(os.pathsep) if item]
        loaded = []
        for folder in folders:
            try:
                loaded.append(load(folder))
            except ValueError:
                continue
        enabled = _enabled() if named is None else []
        found = {}
        for package in loaded + (enabled or []):
            found.setdefault(package.name, package)
        if enabled is None:
            return list(found.values())
        _PACKAGES.clear()
        _PACKAGES[key] = list(found.values())
    return _PACKAGES[key]


def packages_changed() -> None:
    """Read the packages again on the next packages(): one was installed, removed, enabled
    or disabled (harness.packages.activate)."""
    _PACKAGES.clear()


def package_roots() -> list[Path]:
    """The folders of the packages this process uses (packages())."""
    return [package.path for package in packages()]


def _enabled() -> list | None:
    """The user's enabled packages, before harness.packages.activate() has named them in
    HARNESS_PACKAGE_ROOTS (a command a package brings is parsed first); None when they
    cannot be read now (the harness is still being imported, or a broken configuration
    file, which the package commands report)."""
    try:
        from .packages.manager import Packages

        return Packages().enabled()
    except Exception:
        return None


def roots() -> list[Path]:
    """Where content is looked up, in order: ROOT, then each package (package_roots)."""
    return [ROOT, *package_roots()]


def find(relative) -> list[Path]:
    """`relative` (a path as it is under ROOT: "benches", "configs/models/x.toml") in
    every root that has it."""
    return [root / relative for root in roots() if (root / relative).exists()]


def locate(path) -> Path:
    """`path` when it exists; else, for a path under ROOT or a package, the same relative
    path in the first root that has it (a configuration in one package naming a prompt
    another one holds); else `path`."""
    path = Path(path)
    if path.exists():
        return path
    absolute = path.resolve()
    for base in roots():
        try:
            relative = absolute.relative_to(base.resolve())
        except ValueError:
            continue
        found = find(relative)
        if found:
            return found[0]
    return path


def import_roots() -> list[str]:
    """What another process (a service, a worker, a kernel) puts on PYTHONPATH to import
    the harness and its benches and skills, and nothing else: ROOT, and the directory of
    the harness package (a checkout's src/; for an installed wheel, a directory under
    HOME that links to the package alone, so a service's environment never sees the
    packages installed next to it), and likewise the core's dependencies (DEPENDENCIES).
    Then each package's folder (package_roots), and the .deps of each of its skills (their
    requirements)."""
    packages = package_roots()
    deps = [str(deps) for root in packages for deps in sorted(root.glob("skills/*/.deps")) if deps.is_dir()]
    return list(dict.fromkeys(_package_roots() + _dependency_roots() + [str(root) for root in packages] + deps))


# The core's dependencies (pyproject.toml), which every process that imports the core imports
# with it: the Agent Space Protocol's SDK (standard library only, like the core).
DEPENDENCIES = ("agent_space",)


def _dependency_roots() -> list[str]:
    """For each of DEPENDENCIES, a directory that holds that package alone: where it was
    imported from when that directory holds nothing else (a kernel's link folder), else a
    link under HOME."""
    import importlib.util

    roots = []
    for name in DEPENDENCIES:
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.submodule_search_locations:
            continue
        package = Path(list(spec.submodule_search_locations)[0])
        holder = package.parent
        if all(item.name == name or item.name.startswith((".", "__")) for item in holder.iterdir()):
            roots.append(str(holder))
            continue
        link_root = home() / "python-deps"
        _link(package.resolve(), link_root / name)
        roots.append(str(link_root))
    return list(dict.fromkeys(roots))


def _link(target: Path, link: Path) -> None:
    """`link` points at the directory `target` (a symbolic link, or on Windows a junction)."""
    if link.exists() and link.resolve() == target.resolve():
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.is_file():
        link.unlink()
    elif link.exists() or os.path.lexists(link):
        os.rmdir(link)  # a junction (including a dangling one): removed without what it points to
    try:
        link.symlink_to(target, target_is_directory=True)
    except FileExistsError:
        if not (link.exists() and link.resolve() == target.resolve()):
            raise
    except OSError:
        if os.name != "nt":
            raise
        # A symbolic link needs a privilege a Windows user may lack; a junction does not.
        import _winapi

        try:
            _winapi.CreateJunction(str(target), str(link))
        except FileExistsError:
            if not (link.exists() and link.resolve() == target.resolve()):
                raise


def _package_roots() -> list[str]:
    if CHECKOUT:
        return [str(ROOT), str(PACKAGE.parent)]
    # The link folder this process was imported through already (a kernel's, whose HOME is
    # an empty one of its own): it holds the harness package alone.
    imported = Path(os.path.abspath(__file__)).parent.parent
    if not any(item.name != PACKAGE.name for item in imported.iterdir()):
        return [str(ROOT), str(imported)]
    link_root = home() / "python"
    _link(PACKAGE, link_root / PACKAGE.name)
    return [str(ROOT), str(link_root)]


def third_party(name: str) -> Path:
    """A benchmark's checkout: $HARNESS_<NAME>_ROOT, else a source
    checkout's third_party/<name> when it is there, else where the harness checks it out
    (HOME/sources/<name>)."""
    variable = os.environ.get(f"HARNESS_{name.upper()}_ROOT")
    if variable:
        return Path(os.path.expanduser(variable))
    if CHECKOUT and (CHECKOUT_ROOT / "third_party" / name).exists():
        return CHECKOUT_ROOT / "third_party" / name
    return home() / "sources" / name


def python_path(*extra) -> str:
    """PYTHONPATH for another process: import_roots(), then `extra` (empty items left out)."""
    return os.pathsep.join(import_roots() + [str(item) for item in extra if item])


# What of an installed package did not check (a bench, a service manifest), by file:
# {path: why}. Such a part is left out where all of them are read, and the package is listed
# with the problem (harness list), so that one stale package never blocks the others.
_CONTENT_PROBLEMS: dict[str, str] = {}


def content_problem(path, reason: str) -> None:
    _CONTENT_PROBLEMS[str(Path(path).resolve())] = reason


def content_problems(folder=None) -> dict:
    """{path: why} of the parts left out (those inside `folder` when given)."""
    if folder is None:
        return dict(_CONTENT_PROBLEMS)
    root = Path(folder).resolve()
    return {path: why for path, why in _CONTENT_PROBLEMS.items() if Path(path).is_relative_to(root)}
