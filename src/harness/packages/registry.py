"""The package registry: an index of published versions and their files.

A registry is an https base or a directory on this computer, laid out as

    index.json                                   the only file that ever changes
    <name>/<version>/<name>-<version>.tar.gz     the package file (archive.py), never replaced
    <name>/<version>/README.md, CHANGELOG.md     for the site's /packages pages
    core/the_harness-<version>-py3-none-any.whl  pre-release builds of the harness itself
                                                 (index.json "core"), for testers:
                                                 pip install <registry>/core/<file>

index.json:

    {"schema": 1, "updated": "<ISO time>",
     "packages": {"<name>": {"summary": "...", "latest": "0.1.0",
        "versions": {"0.1.0": {"file": "<name>/0.1.0/<name>-0.1.0.tar.gz", "sha256": "...", "size": 123,
                               "harness": ">=0.57,<2", "depends": {}, "platforms": [...],
                               "provides": {"skills": [...], ...}, "readme": "...", "changelog": "...",
                               "published": "<ISO time>", "yanked": false}}}}}

The official registry is https://harness.lmms-lab.com/registry (the `registry` branch of
this repository, published with the site). $HARNESS_REGISTRY (or the packages.registry
setting) names another: a mirror, a local copy for a machine without internet access,
a directory for tests or offline installs. Whichever is configured is trusted as the official one. The index is cached
under HOME/registry/ for CACHE_SECONDS and used from there when the registry cannot be
reached; a package file is checked against the index's sha256 before it is unpacked.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

from ..paths import home
from . import archive
from .fetch import digest
from .versions import Version, best, latest, satisfies


OFFICIAL = "https://harness.lmms-lab.com/registry"
REGISTRY_ENV = "HARNESS_REGISTRY"
SCHEMA = 1
CACHE_SECONDS = 600
INDEX = "index.json"


class RegistryError(RuntimeError):
    pass


def configured(setting: str = "") -> str:
    """The registry in use: $HARNESS_REGISTRY, else the packages.registry setting, else
    the official one."""
    return (os.environ.get(REGISTRY_ENV) or setting or OFFICIAL).strip()


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Registry:
    def __init__(self, base: str | None = None):
        self.base = (base or configured()).rstrip("/\\")
        self.local = not self.base.startswith(("https://", "http://"))
        self._index = None
        key = hashlib.sha256(self.base.encode()).hexdigest()[:12]
        self.cache = home() / "registry" / key

    @property
    def official(self) -> bool:
        return self.base == OFFICIAL

    def __repr__(self):
        return f"Registry({self.base})"

    def _read(self, relative: str, timeout: float = 60.0) -> bytes:
        if self.local:
            path = Path(os.path.expanduser(self.base)) / relative
            if not path.is_file():
                raise RegistryError(f"{path}: not there")
            return path.read_bytes()
        from urllib.error import URLError
        from ..core.http import open_url

        try:
            with open_url(f"{self.base}/{relative}", timeout=timeout) as response:
                return response.read()
        except (URLError, OSError) as error:
            raise RegistryError(f"{self.base}/{relative}: {error}") from None

    def index(self, *, refresh: bool = False) -> dict:
        """The registry's index (from the cache while it is fresh, and when the registry
        cannot be reached)."""
        if self._index is not None and not refresh:
            return self._index
        cached = self.cache / INDEX
        fresh = cached.is_file() and time.time() - cached.stat().st_mtime < CACHE_SECONDS
        if self.local or refresh or not fresh:
            try:
                data = json.loads(self._read(INDEX, timeout=20.0))
                check_index(data, self.base)
                if not self.local:
                    self.cache.mkdir(parents=True, exist_ok=True)
                    cached.write_text(json.dumps(data), encoding="utf-8")
                self._index = data
                return data
            except (RegistryError, ValueError) as error:
                if self.local or not cached.is_file():
                    raise RegistryError(f"the registry {self.base} cannot be read: {error}") from None
        self._index = json.loads(cached.read_text(encoding="utf-8"))
        return self._index

    def packages(self) -> dict:
        return self.index().get("packages", {})

    def versions(self, name: str) -> list[str]:
        """The published versions of a package that are not withdrawn (yanked), lowest first."""
        entry = self.packages().get(name) or {}
        return sorted((version for version, row in entry.get("versions", {}).items() if not row.get("yanked")),
                      key=Version.parse)

    def entry(self, name: str, version: str) -> dict:
        try:
            return self.packages()[name]["versions"][version]
        except KeyError:
            raise RegistryError(f"{self.base} has no {name} {version}") from None

    def pick(self, name: str, *ranges) -> str:
        """The highest published version of `name` in every range."""
        if name not in self.packages():
            raise RegistryError(f"no package {name} in {self.base}")
        version = best(self.versions(name), *ranges)
        if version is None:
            raise RegistryError(f"no version of {name} in {' and '.join(r or 'any' for r in ranges)} "
                                f"(published: {', '.join(self.versions(name)) or 'none'})")
        return version

    def download(self, name: str, version: str, into: Path, *, log=print) -> tuple[Path, str]:
        """Unpack one version's package file into `into`, checked against the index;
        returns its folder and sha256. A file once downloaded is kept by its sha256."""
        row = self.entry(name, version)
        expected = row["sha256"]
        kept = home() / "downloads" / f"{expected}.tar.gz"
        if kept.is_file() and digest(kept) == expected:
            data = kept.read_bytes()
        else:
            log(f"downloading {name} {version}")
            data = self._read(row["file"], timeout=300.0)
            if hashlib.sha256(data).hexdigest() != expected:
                raise RegistryError(f"{name} {version}: the file's sha256 is not the index's; not installed")
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_bytes(data)
        return archive.unpack(data, Path(into)), expected

    def providers(self, what: str, name: str) -> list[str]:
        """The packages whose latest version provides `name` among its `what` (skills,
        embodiments, benches, services, kinds, commands...)."""
        out = []
        for package, entry in sorted(self.packages().items()):
            versions = self.versions(package)
            top = latest(versions)
            if top and name in entry["versions"][top].get("provides", {}).get(what, []):
                out.append(package)
        return out

    def search(self, query: str = "") -> list[dict]:
        """The packages whose name, summary or provided names have `query` in them."""
        query = query.lower().strip()
        rows = []
        for name, entry in sorted(self.packages().items()):
            top = latest(self.versions(name))
            if top is None:
                continue
            provides = entry["versions"][top].get("provides", {})
            words = " ".join([name, entry.get("summary", ""), *[" ".join(v) for v in provides.values()]]).lower()
            if query in words:
                rows.append({"name": name, "version": top, "summary": entry.get("summary", ""),
                             "provides": provides, "platforms": entry["versions"][top].get("platforms", [])})
        return rows


def check_index(data, where: str = "index.json") -> None:
    """ValueError when `data` is not an index of SCHEMA."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("packages"), dict):
        raise ValueError(f"{where}: not a registry index of schema {SCHEMA}")
    for name, entry in data["packages"].items():
        for version, row in (entry.get("versions") or {}).items():
            Version.parse(version)
            for key in ("file", "sha256"):
                if not row.get(key):
                    raise ValueError(f"{where}: {name} {version} has no {key}")


def harness_fits(row: dict, version: str) -> bool:
    """Whether a published version works with harness `version` (its `harness` range)."""
    return satisfies(_release(version), row.get("harness", ""))


def _release(version: str) -> str:
    # A development build (0.57.0-preview, 1.0.0-rc.1) is checked as its release.
    parsed = Version.parse(version)
    return f"{parsed.major}.{parsed.minor}.{parsed.patch}"


def publish_core(directory: Path, wheel: Path, *, log=print) -> dict:
    """Add a build of the harness itself (its wheel) to a registry directory under core/,
    with its sha256 in index.json ("core": {"latest", "versions": {version: {"file",
    "sha256", "size", "published"}}}). A version already published is refused."""
    import re

    directory, wheel = Path(directory), Path(wheel)
    match = re.match(r"^the_harness-([^-]+)-py3-none-any\.whl$", wheel.name)
    if not match:
        raise RegistryError(f"{wheel.name}: not a wheel of the harness (the_harness-<version>-py3-none-any.whl)")
    version = match.group(1)
    index_path = directory / INDEX
    data = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else \
        {"schema": SCHEMA, "updated": now(), "packages": {}}
    check_index(data, str(index_path))
    core = data.setdefault("core", {"versions": {}})
    if version in core["versions"]:
        raise RegistryError(f"the harness {version} is published already; raise its version")
    target = directory / "core" / wheel.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wheel, target)
    row = {"file": f"core/{wheel.name}", "sha256": digest(target), "size": target.stat().st_size,
           "published": now()}
    core["versions"][version] = row
    core["latest"] = version
    data["updated"] = now()
    index_path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"published the harness {version} ({row['sha256'][:12]})")
    return {"version": version, **row}


def publish(directory: Path, package_folder: Path, *, log=print) -> dict:
    """Add a package folder's version to a registry directory: its package file,
    README and CHANGELOG under <name>/<version>/, and its entry in index.json. A version
    already published is refused (published versions never change)."""
    from .manifest import load

    directory = Path(directory)
    package = load(package_folder)
    index_path = directory / INDEX
    data = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else \
        {"schema": SCHEMA, "updated": now(), "packages": {}}
    check_index(data, str(index_path))
    entry = data["packages"].setdefault(package.name, {"summary": package.summary, "versions": {}})
    if package.version in entry["versions"]:
        raise RegistryError(f"{package.name} {package.version} is published already; raise its version")
    folder = directory / package.name / package.version
    if folder.exists():
        raise RegistryError(f"{folder} exists already, but the index does not list it; remove it by hand")
    file = folder / f"{package.name}-{package.version}.tar.gz"
    digest = archive.build(package.path, file, prefix=package.name)
    row = {"file": file.relative_to(directory).as_posix(), "sha256": digest, "size": file.stat().st_size,
           **package.index_entry(), "published": now(), "yanked": False}
    for name, key in (("README.md", "readme"), ("CHANGELOG.md", "changelog")):
        source = package.path / name
        if not source.is_file():
            source = package.path / "docs" / name
        if source.is_file():
            shutil.copyfile(source, folder / name)
            row[key] = (folder / name).relative_to(directory).as_posix()
    entry["versions"][package.version] = row
    entry["summary"] = package.summary
    entry["latest"] = latest([v for v, r in entry["versions"].items() if not r.get("yanked")]) or package.version
    data["updated"] = now()
    data["packages"] = dict(sorted(data["packages"].items()))
    index_path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"published {package.name} {package.version} ({digest[:12]})")
    return {"name": package.name, "version": package.version, **row}
