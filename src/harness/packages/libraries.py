"""What an agent learned, shared as a package and installed from one.

A library (runtime/learning/library.py) travels in a package folder:

    <name>/
      package.toml          [package] name, version, summary
      libraries/<name>/     the library: notes, skills and reactive entries with their tests,
                            attachments and revisions, index.json (evidence, history, uses)
      README.md             what it holds and the line that installs it

share() writes that package from a library and sends it where the user says: a GitHub
repository, another git remote, an archive in a folder (a website's files) or on a
computer reached by scp. Left behind: memory entries (what the agent saw on this computer)
unless asked for, entries waiting under candidates/, failed and forgotten entries; and in
what goes, the places of this computer (a run's folder, the home folder) become names.

Installing such a package (manager.py) copies each of its libraries to
$HARNESS_HOME/libraries/<name>, where a run uses it by name (--library NAME) and keeps
learning in it. A later install of the package replaces that copy only while it is as it
was installed: once a run learned in it, it is kept.
"""

import json
from pathlib import Path
import shutil

from ..paths import home
from ..runtime.learning.library import Library


ORIGIN = "origin.json"


def libraries_root() -> Path:
    return home() / "libraries"


# -- installing -------------------------------------------------------------------------


def working_copy(package, name: str, *, root: Path | None = None, log=print) -> dict:
    """Copy the library `name` of an installed `package` to root/<name> (default
    $HARNESS_HOME/libraries), unless runs learned in the copy that is there.
    {"name", "path", "status": copied | updated | unchanged | kept, "version"}."""
    source = Path(package.path) / "libraries" / name
    root = Path(root or libraries_root())
    target = root / name
    shipped = Library(source).version()
    row = {"name": name, "path": str(target), "version": shipped}
    status = "copied"
    if target.exists():
        origin = _read_json(target / ORIGIN)
        current = Library(target).version() if target.is_dir() else None
        if current == shipped:
            _write_origin(target, package, shipped)
            return {**row, "status": "unchanged"}
        if origin.get("package") != package.name or origin.get("version") != current:
            log(f"library {name}: kept the one at {target}, which runs learned in (or which is not from "
                f"{package.name}); remove it and install again to take {package.name} {package.version}'s")
            return {**row, "status": "kept", "version": current}
        status = "updated"
    root.mkdir(parents=True, exist_ok=True)
    staging, old = root / f".{name}.installing", root / f".{name}.replaced"
    for leftover in (staging, old):
        shutil.rmtree(leftover, ignore_errors=True)
    # (copyfile: the store's files are read-only, the copy is learned in.)
    shutil.copytree(source, staging, copy_function=shutil.copyfile,
                    ignore=shutil.ignore_patterns(ORIGIN, "__pycache__", ".library.lock"))
    _write_origin(staging, package, shipped)
    if target.exists():
        target.rename(old)
    staging.rename(target)
    shutil.rmtree(old, ignore_errors=True)
    return {**row, "status": status}


def _write_origin(folder: Path, package, version: str) -> None:
    (folder / ORIGIN).write_text(json.dumps({"package": package.name, "package_version": package.version,
                                             "version": version}, indent=1) + "\n", encoding="utf-8")


def origin(folder) -> dict:
    """The package a library under $HARNESS_HOME/libraries was installed from ({} for one
    learned here)."""
    return _read_json(Path(folder) / ORIGIN)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
