"""What is installed, and for whom: the store, the user's list, a project's lock.

    HOME/packages/<name>/<version>-<sha8>/   an installed version, never changed once there
    <data>/config.toml [packages]             the user's packages (~/.harness/config.toml, settings.py)
    <project>/harness.toml [packages]         a project's packages: { name = "range" } or
                                              { name = { source = "...", range = "..." } }
    <project>/harness.lock                    what they resolved to: name, version, sha256, source

A project is the nearest folder above the working directory with a harness.toml that
has [packages]. Its packages are used only once the user trusted the project (they ran
`harness install` there); the trusted projects are listed in the user's config.toml.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import stat
import sys
import tomllib

from ..core import atomic_write


PROJECT_FILE = "harness.toml"
LOCK_FILE = "harness.lock"
LOCK_VERSION = 1


def _toml(path: Path) -> dict:
    try:
        with Path(path).open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path}: {error}") from None


@dataclass
class Record:
    """One installed package as a list or a lock records it."""

    name: str
    version: str
    sha256: str = ""
    source: str = "registry"
    range: str = ""
    path: str = ""
    link: bool = False
    trusted: bool = True
    enabled: bool = True

    def row(self) -> dict:
        return {"version": self.version, "sha256": self.sha256, "source": self.source, "range": self.range,
                "path": self.path, "link": self.link, "trusted": self.trusted, "enabled": self.enabled}


@dataclass
class UserList:
    """The user's packages: [packages] of config.toml (settings.py), with
    [packages.installed.<name>] for each one, the trusted projects, and whether the app's
    installed skills were made packages (addons_migrated)."""

    directory: Path
    packages: dict = field(default_factory=dict)
    trusted_projects: list = field(default_factory=list)
    migrated: bool = False

    @classmethod
    def read(cls, data: Path) -> "UserList":
        from .. import settings

        section = settings.read(data).get("packages") or {}
        packages = {}
        for name, row in (section.get("installed") or {}).items():
            fields = {k: row[k] for k in Record.__dataclass_fields__ if k in row and k != "name"}
            packages[name] = Record(name=name, **fields)
        return cls(Path(data), packages, list(section.get("trusted_projects", [])),
                   bool(section.get("addons_migrated", False)))

    @property
    def path(self) -> Path:
        from .. import settings

        return settings.path(self.directory)

    def write(self) -> None:
        from .. import settings

        def apply(data):
            section = data.setdefault("packages", {})
            section["addons_migrated"] = self.migrated
            section["trusted_projects"] = list(self.trusted_projects)
            section["installed"] = {name: self.packages[name].row() for name in sorted(self.packages)}

        settings.change(self.directory, apply)


@dataclass
class Project:
    """A folder with a harness.toml that has [packages], and its harness.lock."""

    root: Path

    @classmethod
    def find(cls, start=None) -> "Project | None":
        folder = Path(start or os.getcwd()).resolve()
        for candidate in (folder, *folder.parents):
            path = candidate / PROJECT_FILE
            if path.is_file():
                try:
                    if "packages" in _toml(path):
                        return cls(candidate)
                except ValueError:
                    return cls(candidate)
        return None

    @property
    def file(self) -> Path:
        return self.root / PROJECT_FILE

    @property
    def lock_file(self) -> Path:
        return self.root / LOCK_FILE

    def wanted(self) -> dict:
        """[packages] of harness.toml: {name: {"range", "source"}}."""
        out = {}
        for name, row in (_toml(self.file).get("packages") or {}).items():
            row = {"range": row} if isinstance(row, str) else dict(row)
            out[name] = {"range": str(row.get("range", "")), "source": str(row.get("source", ""))}
        return out

    def locked(self) -> dict[str, Record]:
        tree = _toml(self.lock_file)
        return {row["name"]: Record(name=row["name"], version=row["version"], sha256=row.get("sha256", ""),
                                    source=row.get("source", "registry"))
                for row in tree.get("package", [])}

    def set_wanted(self, wanted: dict) -> None:
        """Rewrite [packages] of harness.toml, keeping the rest of the file as it is."""
        from ..config import toml_key, toml_value

        lines = ["[packages]"]
        for name in sorted(wanted):
            row = wanted[name]
            item = row["range"] if not row.get("source") else \
                {k: v for k, v in (("source", row["source"]), ("range", row["range"])) if v}
            lines.append(f"{toml_key(name)} = {toml_value(item)}")
        text = self.file.read_text(encoding="utf-8") if self.file.is_file() else ""
        atomic_write(self.file, set_table(text, "packages", lines))

    def write_lock(self, records) -> None:
        from ..config import dumps

        rows = [{"name": r.name, "version": r.version, "sha256": r.sha256, "source": r.source}
                for r in sorted(records, key=lambda r: r.name)]
        comment = "harness.lock: the packages harness.toml resolved to (harness install). Check it in."
        atomic_write(self.lock_file, dumps({"version": LOCK_VERSION, "package": rows}, comment))


def set_table(text: str, table: str, lines: list[str]) -> str:
    """`text` (TOML) with table [table] replaced by `lines` (or appended)."""
    out, skipping, done = [], False, False
    for line in text.splitlines():
        header = line.strip()
        if header.startswith("[") and not header.startswith("[["):
            name = header.strip("[]").strip()
            if name == table or name.startswith(table + "."):
                if not done:
                    out += lines
                    done = True
                skipping = True
                continue
            skipping = False
        elif header.startswith("[["):
            skipping = False
        if not skipping:
            out.append(line)
    if not done:
        if out and out[-1].strip():
            out.append("")
        out += lines
    return "\n".join(out).rstrip("\n") + "\n"


def store_root() -> Path:
    from ..paths import home

    return home() / "packages"


def store_path(name: str, version: str, sha256: str) -> Path:
    return store_root() / name / f"{version}-{sha256[:8]}"


def freeze(folder: Path) -> None:
    """Make an installed version read-only (it never changes once installed)."""
    for current, _, files in os.walk(folder):
        for name in files:
            path = Path(current) / name
            path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def delete(folder: Path) -> None:
    """Remove an installed version (its files are read-only)."""
    def writable(function, path, _):
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        function(path)

    if Path(folder).exists():
        shutil.rmtree(folder, **({"onexc": writable} if sys.version_info >= (3, 12) else {"onerror": writable}))
