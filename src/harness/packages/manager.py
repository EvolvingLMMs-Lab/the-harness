"""The package manager: install, remove, update, list, search and describe packages,
and install on first use what a run needs.

Packages come from the registry (registry.py), a git repository, an archive URL or a
folder (sources.py). A registry package is trusted; one from anywhere else runs code
nobody reviewed, so it is installed only after the user saw what it provides, which
services it would start and what it would install (describe()) and agreed (`consent`).
A folder of skills without package.toml (what the app's "Add a skill" took) becomes
one package per skill.

Each installed version lives in the store (state.py), unchanged. The user's packages
are listed in [packages] of <data>/config.toml; `project=True` writes a project's harness.toml and
harness.lock instead. A run uses the enabled packages: the user's, and a trusted
project's locked ones in their place.

`packages.auto_install` (the app's settings) decides what happens when a run needs an
embodiment, a bench, a skill or a service no enabled package provides (ensure()):
official installs the registry's package that provides it, ask asks first, off stops
with the command that would install it.
"""

import contextlib
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import threading

from ..core import tree_hash
from ..core.procs import file_lock
from ..paths import data as data_dir
from . import archive, sources, state
from .addons import find_skills
from .manifest import Package, load, platform, write
from .registry import Registry, RegistryError, configured, harness_fits
from .resolve import ResolveError, resolve
from .versions import check_range, satisfies


AUTO_INSTALL = ("official", "ask", "off")
SINGULAR = {"kinds": "kind", "embodiments": "embodiment", "skills": "skill", "benches": "bench",
            "services": "service", "prompts": "prompt", "profiles": "profile", "experiments": "experiment",
            "agent_skills": "Agent Skill", "settings": "settings section", "config_keys": "configuration key",
            "commands": "command", "agents": "agent"}


class PackageBusy(RuntimeError):
    """Another thread or process is already changing this shared package store."""


_MUTATIONS = threading.local()


@contextlib.contextmanager
def _package_lock():
    """Try a store transaction without queuing; reentrant in its calling thread."""
    path = state.store_root().parent / "locks" / "packages.lock"
    # Include pid so a child forked inside a transaction cannot inherit permission
    # to bypass the parent's OS lock. New threads have their own held set.
    key = (os.getpid(), str(path.resolve()))
    held = getattr(_MUTATIONS, "held", None)
    if held is None:
        held = _MUTATIONS.held = set()
    if key in held:
        yield
        return
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(file_lock(path, blocking=False))
        except BlockingIOError:
            raise PackageBusy("another package operation is running; this request was not queued. "
                              "Wait for it to finish, then retry the package command or task.") from None
        held.add(key)
        try:
            yield
        finally:
            held.remove(key)


class MissingPackage(RuntimeError):
    """A run needs something no enabled package provides, and it was not installed."""


def harness_version() -> str:
    from .. import __version__

    return __version__


class Packages:
    """The packages of one user (`data`, default ~/.harness) and of the project of
    `cwd` (default the working directory)."""

    def __init__(self, data=None, *, cwd=None, registry: Registry | None = None):
        self.data = Path(data or data_dir())
        self.cwd = cwd
        self._registry = registry
        self.problems: dict[str, str] = {}
        self.on_change = None

    # -- configuration -----------------------------------------------------------------

    def settings(self) -> dict:
        from ..settings import Settings

        return Settings(self.data).get().get("packages", {})

    def auto_install(self) -> str:
        mode = os.environ.get("HARNESS_AUTO_INSTALL") or self.settings().get("auto_install", "official")
        return mode if mode in AUTO_INSTALL else "official"

    @property
    def registry(self) -> Registry:
        if self._registry is None:
            self._registry = Registry(configured(self.settings().get("registry", "")))
        return self._registry

    def _registry_identity(self) -> str:
        return "registry" if self.registry.official else f"registry:{self.registry.base}"

    @staticmethod
    def _is_registry(record) -> bool:
        return record.source == "registry" or record.source.startswith("registry:")

    def _published_record(self, name, record):
        # Reading the index is intentionally outside missing-name/version handling:
        # an unavailable registry must retain its real I/O error, not look like new content.
        package = self.registry.packages().get(name, {})
        return package.get("versions", {}).get(record.version)

    def _registry_matches(self, name, record) -> bool:
        """Registry identity includes byte-identical mirrors of a locked archive."""
        if not self._is_registry(record):
            return False
        if record.source == self._registry_identity():
            return True
        entry = self._published_record(name, record)
        return bool(entry and record.sha256) and entry["sha256"] == record.sha256

    def _use_installed(self, name, record, requests) -> bool:
        # Registry-backed active nodes follow the configured registry/content.
        # An unrequested development source remains an explicit owner choice.
        return self._registry_matches(name, record) if self._is_registry(record) else name not in requests

    @staticmethod
    def _record_folder(name, record) -> Path:
        return Path(record.path) if record.path else state.store_path(name, record.version, record.sha256)

    @staticmethod
    def _quote_spec(spec, *, windows=None) -> str:
        if windows is None:
            windows = os.name == "nt"
        return f'"{spec}"' if windows else shlex.quote(spec)

    def _repair_command(self, name, record, *, project, requested=(), records=None) -> str:
        scope = " --project" if project else ""
        target = self.project() if project else None
        if self._is_registry(record) and (not project or target is not None):
            names = list(dict.fromkeys([*sorted(requested), name]))
            names = [item for item in names if records is None or item in records]
            return f"harness install --update{scope}" + (" " + " ".join(names) if names else "")
        range_ = target.wanted().get(name, {}).get("range", "") if target is not None else record.range
        range_ = check_range(range_)
        spec = f"{name}@{range_}" if range_ else name
        return f"harness install{scope} {self._quote_spec(spec)}"

    def _require_locked_content(self, name, record, *, project=True, requested=(), records=None) -> None:
        if not self._is_registry(record):
            return
        matches = self._registry_matches(name, record)
        if matches and not (self._record_folder(name, record) / "package.toml").is_file():
            # Same-address caches can be restored offline, but when files are
            # missing the selected archive must still be the recorded content.
            entry = self._published_record(name, record)
            matches = bool(entry and record.sha256) and entry["sha256"] == record.sha256
        if not matches:
            command = self._repair_command(name, record, project=project, requested=requested, records=records)
            retry = ("; then retry the original command" if records is not None
                     and any(item not in records for item in requested) else "")
            raise ResolveError(f"the configured registry cannot restore locked {name} {record.version} "
                               f"with its recorded content; run {command} to explicitly select this registry "
                               f"while preserving recorded ranges{retry}")

    def user(self) -> state.UserList:
        return state.UserList.read(self.data)

    def project(self) -> state.Project | None:
        return state.Project.find(self.cwd)

    def project_trusted(self, project: state.Project | None = None) -> bool:
        project = project or self.project()
        return project is not None and str(project.root) in self.user().trusted_projects

    # -- what is installed -------------------------------------------------------------

    def records(self) -> dict[str, tuple[state.Record, str]]:
        """{name: (record, "user" or "project")}: a trusted project's locked packages in
        place of the user's of the same name."""
        out = {name: (record, "user") for name, record in self.user().packages.items()}
        project = self.project()
        if project is not None and self.project_trusted(project):
            for name, record in project.locked().items():
                record.path = str(state.store_path(name, record.version, record.sha256))
                out[name] = (record, "project")
        return out

    def enabled(self) -> list[Package]:
        """The packages a run uses (installed, enabled, loading cleanly); why the others
        do not load is in `problems`."""
        self.problems = {}
        out = []
        for name, (record, _) in sorted(self.records().items()):
            if not record.enabled:
                continue
            try:
                package = load(record.path)
                if package.name != name:
                    raise ValueError(f"{record.path} holds {package.name}, not {name}")
                self._fits(package)
                out.append(package)
            except ValueError as error:
                self.problems[name] = str(error)
        return out

    def installed(self) -> list[dict]:
        """Every installed package: name, version, source, where, whether it is enabled
        and trusted, what it provides, and its problem when it does not load."""
        rows = []
        loaded = {package.name: package for package in self.enabled()}
        for name, (record, scope) in sorted(self.records().items()):
            package = loaded.get(name)
            if package is None and name not in self.problems:
                try:
                    package = load(record.path)
                except ValueError as error:
                    self.problems[name] = str(error)
            rows.append({"name": name, "version": record.version, "scope": scope, "source": record.source,
                         "path": record.path, "link": record.link, "enabled": record.enabled,
                         "trusted": record.trusted, "summary": package.summary if package else "",
                         "provides": {k: list(v) for k, v in (package.provides if package else {}).items()},
                         **({"problem": self.problems[name]} if name in self.problems else {})})
        return rows

    def available(self) -> list[Package]:
        """The packages a run here may use: a source checkout's and the enabled ones,
        as paths.packages() finds them (a checkout's wins over an installed one)."""
        from ..paths import packages

        return packages()

    def provider(self, what: str, name: str) -> Package | None:
        """The package a run here may use (available) that provides `name` among its `what`."""
        for package in self.available():
            if name in package.provides.get(what, ()):
                return package
        return None

    # -- describe and find -------------------------------------------------------------

    def describe(self, package: Package) -> dict:
        """What installing a package brings: what it provides, the services it can start,
        the environments it installs, the commands it adds, what it depends on."""
        environments, services = [], []
        for path in sorted(package.path.glob("services/*.toml")):
            services.append(path.stem)
            spec = state._toml(path)
            if isinstance(spec.get("environment"), dict):
                environments.append({"for": f"service {path.stem}",
                                     "requirements": spec["environment"].get("requirements", [])})
        for path in sorted(package.path.glob("benches/*/bench.toml")):
            spec = state._toml(path)
            if isinstance(spec.get("environment"), dict):
                environments.append({"for": f"bench {path.parent.name}",
                                     "requirements": spec["environment"].get("requirements", [])})
        requirements = {}
        for path in sorted(package.path.glob("skills/*/skill.toml")):
            wanted = state._toml(path).get("requirements", [])
            if wanted:
                requirements[path.parent.name] = list(wanted)
        return {"name": package.name, "version": package.version, "summary": package.summary,
                "harness": package.harness, "depends": dict(package.depends), "platforms": list(package.platforms),
                "provides": {k: list(v) for k, v in package.provides.items()}, "services": services,
                "environments": environments, "skill_requirements": requirements,
                "commands": dict(package.commands), "code": any(package.path.rglob("*.py"))}

    def search(self, query: str = "") -> list[dict]:
        installed = {name: record.version for name, (record, _) in self.records().items()}
        return [{**row, "installed": installed.get(row["name"], "")} for row in self.registry.search(query)]

    def info(self, name: str) -> dict:
        """A package: the installed version's description and the registry's versions."""
        out = {"name": name}
        record = self.records().get(name)
        if record is not None:
            out["installed"] = {"version": record[0].version, "scope": record[1], "source": record[0].source,
                                "path": record[0].path}
            try:
                out.update(self.describe(load(record[0].path)))
            except ValueError as error:
                out["problem"] = str(error)
        try:
            entry = self.registry.packages().get(name)
        except RegistryError as error:
            entry, out["registry_problem"] = None, str(error)
        if entry is not None:
            out["registry"] = self.registry.base
            out.setdefault("summary", entry.get("summary", ""))
            out["versions"] = [{"version": version, "harness": entry["versions"][version].get("harness", ""),
                                "published": entry["versions"][version].get("published", ""),
                                "fits": harness_fits(entry["versions"][version], harness_version())}
                               for version in self.registry.versions(name)]
            if "provides" not in out and out["versions"]:
                top = entry["versions"][out["versions"][-1]["version"]]
                out.update({key: top.get(key) for key in ("provides", "depends", "platforms", "harness")})
        if record is None and entry is None:
            raise ValueError(f"no package {name}: not installed, and not in {self.registry.base}")
        return out

    # -- install, remove, update -------------------------------------------------------

    def install(self, specs=(), *, project: bool = False, consent=None, link: bool = False, python=None,
                zip_bytes: bytes | None = None, embodiment: str | None = None, log=print, _automatic=False) -> dict:
        """Install packages by source text (sources.py), or `zip_bytes` (an archive the app
        was given). Packages from outside the registry need `consent(found) -> bool`
        (found: describe() of each); without it nothing changes and {"needs_trust": True,
        "found": [...]} comes back. With `project`, the project's harness.toml and
        harness.lock are written (and with no specs, the project's packages are
        installed and the project trusted). With `embodiment`, a folder's skills are
        taken only when they run on it (the kind the app's agent works in). Returns
        {"installed": [...], "problems": [...]}."""
        with tempfile.TemporaryDirectory(prefix="harness-package-") as temporary:
            prepared = self._prepare(specs, Path(temporary), project=project, consent=consent,
                                     zip_bytes=zip_bytes, embodiment=embodiment, log=log)
            if prepared.get("needs_trust"):
                return prepared
            with _package_lock():
                result = self._install(prepared, link=link, python=python, log=log,
                                       declare=prepared.get("wanted") is None, automatic=_automatic)
        # A top-level mutation releases its store lock before notifying the host.
        # A nested callback mutation can still be in its outer transaction.
        self.changed()
        return result

    def _prepare(self, specs, temporary: Path, *, project=False, consent=None,
                 zip_bytes=None, embodiment=None, log=print) -> dict:
        """Fetch and inspect sources and obtain trust without holding the store lock."""
        specs = [str(spec) for spec in specs]
        target = self.project() if project else None
        if project and target is None:
            target = state.Project(Path(self.cwd or os.getcwd()).resolve())
        requests, local, problems = {}, [], []
        wanted = target.wanted() if project and not specs else None
        if wanted is not None:
            for name, row in wanted.items():
                specs.append(row["source"] or (f"{name}@{row['range']}" if row["range"] else name))
            if not specs:
                raise ValueError(f"{target.file}: [packages] names no package")
        for index, spec in enumerate(specs):
            source = sources.parse(spec, base=target.root if wanted is not None else None)
            if source.kind == "registry":
                requests[source.name] = source.range
                continue
            folder, origin = sources.fetch(source, temporary / str(index), log=log)
            found, more = self._packages_in(folder, temporary / f"wrap{index}", embodiment)
            problems += more
            local += [(package, origin, source) for package in found]
        if zip_bytes is not None:
            folder = archive.unpack(zip_bytes, temporary / "zip")
            found, more = self._packages_in(folder, temporary / "wrapzip", embodiment)
            problems += more
            local += [(package, "upload", None) for package in found]
        if not requests and not local:
            raise ValueError("no package found (a folder with package.toml, skill.toml or SKILL.md)"
                             + (f": {'; '.join(problems)}" if problems else ""))
        if local:
            found = [self.describe(package) for package, _, _ in local]
            if consent is None or not consent(found):
                return {"needs_trust": True, "found": found, "problems": problems}
        for package, _, _ in local:
            self._fits(package)
        return {"target": target, "requests": requests, "local": local,
                "problems": problems, "temporary": temporary, "wanted": wanted}

    def _install(self, prepared, *, link=False, python=None, log=print, declare=True, automatic=False) -> dict:
        """Resolve and publish prepared sources while holding the store transaction."""
        target, requests, local = prepared["target"], prepared["requests"], prepared["local"]
        problems, temporary = prepared["problems"], prepared["temporary"]
        if prepared.get("wanted") is not None and target.wanted() != prepared["wanted"]:
            raise ResolveError(f"{target.file} changed while preparing its packages; "
                               "run harness install --project again to review the current requests")
        records = self.user().packages if target is None else target.locked()
        restoring = prepared.get("wanted") is not None
        if restoring:
            for name in requests:
                if name in records:
                    self._require_locked_content(name, records[name], requested=(name,), records=records)
        have = {name: record.version for name, record in records.items()
                if name not in requests or restoring}
        try:
            plan = resolve(requests, self.registry if requests or any(p.depends for p, _, _ in local) else _NoRegistry(),
                           harness=harness_version(), have=have,
                           fixed={package.name: (package.version, package.depends) for package, _, _ in local},
                           depends_of=lambda name, version: self._installed_depends(records, name, version),
                           use_installed=lambda name, version: (name in records and records[name].version == version
                                                                and self._use_installed(name, records[name], requests)))
        except ResolveError as error:
            if prepared.get("wanted") is not None:
                raise ResolveError(f"{error}. For changed ranges, run harness install --update --project. "
                                   "For a package removed from harness.toml, also remove its lock entry "
                                   "with harness remove --project NAME, then retry.") from None
            raise
        explicit = set(requests) | {package.name for package, _, _ in local}
        declared = target.wanted() if target is not None else {}
        reusable = set()
        local_names = {package.name for package, _, _ in local}
        # Check the entire selected plan before any local package is staged/stored.
        for name, version in plan.items():
            self._runtime_fits(name, version)
            record = records.get(name)
            recorded_range = declared.get(name, {}).get("range", "") if target is not None else (record.range if record else "")
            if (not declare or name not in explicit) and recorded_range and not satisfies(version, recorded_range):
                raise ResolveError(f"{name} {version} would violate its recorded range {recorded_range}; "
                                   f"choose compatible packages or explicitly install {name} with the intended range")
            if name not in local_names and self._preflight(name, version, record, requests,
                                                          project=target is not None,
                                                          restoring=automatic or target is not None and (restoring or name not in explicit),
                                                          repair_names=explicit, repair_records=records):
                reusable.add(name)
        done = []
        for package, origin, source in local:
            done.append(self._store_local(package, origin, link=link and source is not None
                                          and source.kind == "path" and Path(source.path).is_dir(),
                                          python=python, log=log))
        for name, version in plan.items():
            if any(name == package.name for package, _, _ in local):
                continue
            if name in reusable:
                continue
            done.append(self._store_registry(name, version, temporary / f"registry-{name}", python=python,
                                             log=log, range_=requests.get(name, "")))
        for record in done:
            old = records.get(record.name)
            if old is not None:
                record.enabled = old.enabled
                if self._is_registry(old) and (record.version, record.sha256) == (old.version, old.sha256):
                    record.source = old.source  # Keep official/portable locks when restoring from a mirror.
        if target is not None:
            self._write_project(target, done, requests, local, declare=declare)
            self._trust_project(target)
        else:
            user = self.user()
            for record in done:
                old = user.packages.get(record.name)
                if record.name not in explicit and old is not None and not record.range and old.range:
                    record.range = old.range
                user.packages[record.name] = record
            user.write()
        return {"installed": [{"name": r.name, "version": r.version, "source": r.source, "path": r.path}
                              for r in done], "problems": problems}

    def _preflight(self, name, version, record, requests, *, project, restoring=False,
                   repair_names=(), repair_records=None) -> bool:
        """Validate reused/registry packages without writing anything; return record reuse."""
        if restoring and record is not None:
            self._require_locked_content(name, record, project=project,
                                         requested=repair_names, records=repair_records)
        folder = self._record_folder(name, record) if record else None
        reuse = (record is not None and record.version == version
                 and self._use_installed(name, record, requests)
                 and (folder / "package.toml").is_file())
        if record is not None and not self._is_registry(record) and name not in requests and not reuse:
            command = self._repair_command(name, record, project=project)
            raise ResolveError(f"{name} is installed from {record.source} and cannot be reused; "
                               f"repair that source or explicitly select the registry with {command}")
        try:
            if reuse:
                self._fits(load(folder))
            else:
                entry = self.registry.entry(name, version)
                if not harness_fits(entry, harness_version()):
                    raise ResolveError(f"{name} {version} works with harness {entry.get('harness')}, "
                                       f"this is {harness_version()}")
                if entry.get("platforms") and platform() not in entry["platforms"]:
                    raise ResolveError(f"{name} runs on {', '.join(entry['platforms'])}, not here")
                cached = state.store_path(name, version, entry["sha256"])
                if (cached / "package.toml").is_file():
                    self._fits(load(cached))
        except ValueError as error:
            command = "harness install --update" + (" --project" if project else "")
            raise ResolveError(f"{error}; run {command} to select compatible packages, "
                               "or use a compatible harness core/platform") from None
        return reuse

    def _installed_depends(self, records, name, version):
        record = records.get(name)
        if record is None or record.version != version:
            return None
        try:
            return load(self._record_folder(name, record)).depends
        except ValueError:
            return None

    def _packages_in(self, folder: Path, wrap: Path, embodiment=None) -> tuple[list[Package], list[str]]:
        """The package a folder is, or the packages its skills become (one per skill)."""
        if (folder / "package.toml").is_file():
            return [load(folder)], []
        from harness.runtime.execution.skills import SKILLS_ROOT, load_skills

        built_in = set(load_skills(SKILLS_ROOT, user=False))
        found, problems = find_skills(folder)
        packages = []
        for skill in found:
            if skill["name"] in built_in:
                problems.append(f"{skill['name']}: a built-in skill has this name")
                continue
            if embodiment and skill["format"] == "harness" and embodiment not in skill["embodiments"]:
                problems.append(f"{skill['name']}: a skill for {', '.join(skill['embodiments'])}; the app's agent "
                                f"works on this computer (embodiments must include {embodiment})")
                continue
            root = wrap / skill["name"]
            kind = "skills" if skill["format"] == "harness" else "agent-skills"
            shutil.copytree(skill["folder"], root / kind / skill["name"],
                            ignore=shutil.ignore_patterns(".git", "__pycache__", ".deps"))
            write(root, name=skill["name"], summary=skill["summary"])
            try:
                packages.append(load(root))
            except ValueError as error:
                problems.append(str(error))
        return packages, problems

    def _runtime_fits(self, name: str, version: str) -> None:
        # computer 0.8 introduced the dispatch protocol used by this core. Older
        # immutable archives declare a broad core range that predates that change.
        if name == "computer" and satisfies(harness_version(), ">=0.82") and not satisfies(version, ">=0.8"):
            raise ResolveError(f"computer {version} is incompatible with harness {harness_version()}; "
                               "if browser is installed, run harness install computer@^0.8 browser together; "
                               "otherwise run harness install computer@^0.8. Add --project for project packages")

    def _fits(self, package: Package) -> None:
        self._runtime_fits(package.name, package.version)
        if not harness_fits({"harness": package.harness}, harness_version()):
            raise ResolveError(f"{package.name} {package.version} works with harness {package.harness}, "
                               f"this is {harness_version()}")
        if not package.runs_here():
            raise ResolveError(f"{package.name} runs on {', '.join(package.platforms)}, not here")

    def _store_local(self, package: Package, origin: str, *, link: bool, python, log) -> state.Record:
        if link:
            log(f"{package.name} {package.version}: linked to {package.path}")
            self._requirements(package.path, python, log)
            return state.Record(package.name, package.version, "", origin, path=str(package.path), link=True)
        digest = tree_hash(package.path, archive.files(package.path))
        target = state.store_path(package.name, package.version, digest)
        self._copy_in(package.path, target, python, log)
        log(f"{package.name} {package.version}: installed from {origin}")
        return state.Record(package.name, package.version, digest, origin, path=str(target))

    def _store_registry(self, name, version, temporary: Path, *, python, log, range_="") -> state.Record:
        entry = self.registry.entry(name, version)
        if not harness_fits(entry, harness_version()):
            raise ResolveError(f"{name} {version} works with harness {entry.get('harness')}, this is "
                               f"{harness_version()}")
        target = state.store_path(name, version, entry["sha256"])
        if not (target / "package.toml").is_file():
            folder, _ = self.registry.download(name, version, temporary, log=log)
            package = load(folder)
            if (package.name, package.version) != (name, version):
                raise RegistryError(f"{self.registry.base}: the file of {name} {version} holds "
                                    f"{package.name} {package.version}")
            self._fits(package)
            self._copy_in(folder, target, python, log)
        log(f"{name} {version}: installed")
        return state.Record(name, version, entry["sha256"], self._registry_identity(),
                            range=range_, path=str(target))

    def _copy_in(self, folder: Path, target: Path, python, log) -> None:
        if (target / "package.toml").is_file():
            return
        staging = target.with_name(target.name + ".partial")
        state.delete(staging)
        shutil.copytree(folder, staging, ignore=shutil.ignore_patterns(".git", "__pycache__", ".deps",
                                                                       "*.pyc", ".installed.json"))
        try:
            self._requirements(staging, python, log)
        except Exception:
            state.delete(staging)
            raise
        state.freeze(staging)
        state.delete(target)
        staging.rename(target)

    def _requirements(self, folder: Path, python, log) -> None:
        """Each skill's pip requirements, in its own .deps folder (on the kernel's path)."""
        import subprocess

        for path in sorted(Path(folder).glob("skills/*/skill.toml")):
            wanted = list(state._toml(path).get("requirements", []))
            if not wanted or (path.parent / ".deps").is_dir():
                continue
            log(f"{path.parent.name}: installing {', '.join(wanted)}")
            interpreter = python() if callable(python) else python
            result = subprocess.run([interpreter or sys.executable, "-X", "utf8", "-m", "pip", "install", "--quiet",
                                     "--disable-pip-version-check", "--target", str(path.parent / ".deps"), *wanted],
                                    capture_output=True, encoding="utf-8", errors="replace", timeout=1800)
            if result.returncode:
                shutil.rmtree(path.parent / ".deps", ignore_errors=True)
                raise ValueError(f"{path.parent.name}: its requirements did not install: "
                                 f"{(result.stderr or result.stdout).strip()[-400:]}")

    def _write_project(self, project: state.Project, done, requests, local, *, declare=True) -> None:
        # Installation declares direct dependencies; an update only changes the lock.
        if declare:
            wanted = project.wanted()
            for name, range_ in requests.items():
                wanted[name] = {"range": range_, "source": ""}
            for package, origin, _ in local:
                wanted[package.name] = {"range": "", "source": origin.split("#sha256=")[0]}
            project.set_wanted(wanted)
        locked = project.locked()
        for record in done:
            locked[record.name] = record
        project.write_lock(locked.values())

    def trust_project(self, project: state.Project) -> None:
        with _package_lock():
            self._trust_project(project)

    def _trust_project(self, project: state.Project) -> None:
        user = self.user()
        if str(project.root) not in user.trusted_projects:
            user.trusted_projects.append(str(project.root))
            user.write()

    def remove(self, names, *, project: bool = False, log=print) -> list[str]:
        """Remove packages from the user's list or the project, retaining shared cache files."""
        with _package_lock():
            result = self._remove(names, project=project, log=log)
        self.changed()
        return result

    def _remove(self, names, *, project=False, log=print) -> list[str]:
        names = [str(name) for name in names]
        if project:
            target = self.project()
            if target is None:
                raise ValueError("no harness.toml with [packages] here or above")
            wanted, locked = target.wanted(), target.locked()
            missing = [name for name in names if name not in wanted and name not in locked]
            if missing:
                raise ValueError(f"the project has no package {', '.join(missing)}")
            for name in names:
                wanted.pop(name, None)
                locked.pop(name, None)
            target.set_wanted(wanted)
            target.write_lock(locked.values())
        else:
            user = self.user()
            missing = [name for name in names if name not in user.packages]
            if missing:
                raise ValueError(f"no installed package {', '.join(missing)}")
            dependents = {other.name: sorted(set(other.depends) & set(names)) for other in self.enabled()
                          if other.name not in names and set(other.depends) & set(names)}
            if dependents:
                raise ValueError("still needed: " + "; ".join(f"{name} depends on {', '.join(of)}"
                                                             for name, of in sorted(dependents.items())))
            for name in names:
                user.packages.pop(name)
            user.write()
        return names

    def collect(self, candidates=(), *, log=print) -> None:
        """Retain immutable cache entries, which may serve other data directories.

        HARNESS_HOME is independent of HARNESS_DATA. Neither this user list nor
        its trusted project locks account for every owner of a shared store entry,
        so absence from these records cannot justify deleting that entry.
        """

    def update(self, names=(), *, project: bool = False, log=print) -> dict:
        """Update registry packages (all, or `names`) to the highest version in the range
        they were installed with that works with this harness."""
        with _package_lock():
            result = self._update(names, project=project, log=log)
        if result["installed"]:
            self.changed()
        return result

    def _update(self, names=(), *, project=False, log=print, required=None) -> dict:
        target = self.project() if project else None
        if project and target is None:
            raise ValueError("no harness.toml with [packages] here or above")
        records = target.locked() if target is not None else self.user().packages
        names = [str(name) for name in names] or sorted(records)
        unknown = [name for name in names if name not in records]
        if unknown:
            raise ValueError(f"no installed package {', '.join(unknown)}")
        requests = {}
        wanted = target.wanted() if target is not None else {}
        for name in names:
            record = records[name]
            if not record.source.startswith("registry"):
                log(f"{name}: installed from {record.source}; install it again to update it")
                continue
            requests[name] = wanted.get(name, {}).get("range", "") if project else record.range
        if requests:
            # An explicit update must see publications newer than this manager's
            # cached index; search/list polling keeps its existing cache policy.
            self.registry.index(refresh=True)
            plan = resolve(requests, self.registry, harness=harness_version(),
                           have={name: record.version for name, record in records.items() if name not in requests},
                           depends_of=lambda name, version: self._installed_depends(records, name, version),
                           use_installed=lambda name, version: (name in records and records[name].version == version
                                                                and self._use_installed(name, records[name], requests)))
        else:
            plan = {}
        if required is not None:
            package, what, capability = required
            selected = plan.get(package)
            if selected is None or capability not in self.registry.entry(package, selected).get("provides", {}).get(what, []):
                command = "harness install" + (" --project" if project else "")
                raise MissingPackage(f"{package} cannot provide the {SINGULAR.get(what, what)} {capability} "
                                     f"within its compatible recorded range {requests.get(package) or 'any'}; "
                                     f"explicitly choose the intended version/range with {command} {package}@RANGE")
        for name, version in plan.items():
            self._runtime_fits(name, version)
        if not any(name not in records or version != records[name].version
                   or not self._use_installed(name, records[name], requests)
                   or not (self._record_folder(name, records[name]) / "package.toml").is_file()
                   for name, version in plan.items()):
            log("everything is up to date within its compatible version ranges")
            return {"installed": [], "problems": []}
        # Reinstall the declared requests: resolution updates the lock, while the
        # user's range and any source declarations stay intact in harness.toml.
        with tempfile.TemporaryDirectory(prefix="harness-package-") as temporary:
            return self._install({"target": target, "requests": requests,
                                  "local": [], "problems": [], "temporary": Path(temporary)},
                                 log=log, declare=False, automatic=required is not None)

    def enable(self, name: str, on: bool) -> None:
        with _package_lock():
            self._enable(name, on)
        self.changed()

    def _enable(self, name: str, on: bool) -> None:
        user = self.user()
        if name not in user.packages:
            raise ValueError(f"no installed package {name}")
        user.packages[name].enabled = bool(on)
        user.write()

    # -- first use ---------------------------------------------------------------------

    def ensure(self, what: str, name: str, *, ask=None, log=print) -> Package:
        """The enabled package that provides `name` among its `what` (skills, embodiments,
        benches, services, kinds, commands); when none does, the registry's package that
        provides it, installed as packages.auto_install says. MissingPackage otherwise."""
        package = self.provider(what, name)
        if package is not None:
            return package
        # Reusing an owner's already installed capability is activation, not an
        # installation decision: refresh it before off/ask or registry-source gates.
        for ready in self.enabled():
            if name in ready.provides.get(what, ()):
                self.changed()
                package = self.provider(what, name)
                if package is not None:
                    return package
        singular = SINGULAR.get(what, what)
        if self.auto_install() == "off":
            raise MissingPackage(f"no installed package provides the {singular} {name}; "
                                 f"select and install its package with harness install "
                                 f"(packages.auto_install is off)")
        try:
            candidates = self.registry.providers(what, name)
        except RegistryError as error:
            raise MissingPackage(f"no installed package provides the {singular} {name}, and {error}") from None
        if not candidates:
            raise MissingPackage(f"no package provides the {singular} {name} (registry {self.registry.base})")
        choice = name if name in candidates else candidates[0]
        installed = self.records().get(choice)
        if installed is not None:
            record, scope = installed
            if not record.enabled:
                raise MissingPackage(f"{choice} is disabled; enable it explicitly in Packages before retrying")
            if not self._is_registry(record):
                self.enabled()  # Include the actual load failure when the development source is broken.
                detail = self.problems.get(choice, f"it does not provide the {singular} {name}")
                command = self._repair_command(choice, record, project=scope == "project")
                raise MissingPackage(f"{choice} is installed from {record.source}: {detail}; repair that source "
                                     f"or explicitly select the registry with {command}")
            if not self._registry_matches(choice, record):
                command = self._repair_command(choice, record, project=scope == "project")
                raise MissingPackage(f"{choice} is installed from {record.source}; explicitly select the "
                                     f"configured registry with {command} before retrying")
        mode = self.auto_install()
        if mode == "off":
            raise MissingPackage(f"the {singular} {name} is in the package {choice}: harness install {choice} "
                                 "(packages.auto_install is off)")
        if mode == "ask" and not (ask and ask({"package": choice, "what": singular, "name": name,
                                               "registry": self.registry.base})):
            raise MissingPackage(f"the {singular} {name} needs the package {choice}, which was not installed")
        if installed is not None:
            log(f"the {singular} {name} is in {choice}: checking its compatible recorded range")
            with _package_lock():
                self._update([choice], project=scope == "project", log=log, required=(choice, what, name))
            self.changed()
        else:
            log(f"the {singular} {name} is in the package {choice}: installing it")
            self.install([choice], log=log, _automatic=True)
        package = self.provider(what, name)
        if package is None:
            raise MissingPackage(f"{choice} was installed but does not provide the {singular} {name}")
        return package

    # -- the running process -----------------------------------------------------------

    def changed(self) -> None:
        """Make this process see the packages as they are now (then on_change, when set:
        the session host's account of what it loaded)."""
        activate(self)
        if self.on_change is not None:
            self.on_change()


def activate(packages: Packages | None = None) -> Packages:
    """Make the enabled packages load in this process and in the processes it starts
    (HARNESS_PACKAGE_ROOTS, which paths.package_roots() reads: their skills, benches,
    prompts and modules); first, on the first start since packages, turn the app's
    installed skills into packages (migrate.py)."""
    from ..paths import PACKAGES_ENV, packages_changed
    from .migrate import ADDONS, migrate

    packages = packages or Packages()
    # Ordinary reads/startup must not wait for an unrelated long installation.
    # migrate() checks again under the lock before publishing any legacy records.
    if (packages.data / ADDONS).is_dir() and not packages.user().migrated:
        with _package_lock():
            migrate(packages)
    enabled = packages.enabled()
    os.environ[PACKAGES_ENV] = os.pathsep.join(str(package.path) for package in enabled)
    packages_changed()
    for package in enabled:
        if str(package.path) not in sys.path:
            sys.path.append(str(package.path))
    try:
        from harness.runtime.execution import skills

        skills._CACHE.clear()
    except ImportError:
        pass
    return packages


class _NoRegistry:
    """Resolution without the registry: packages from other sources that need nothing."""

    base = "(no registry needed)"

    def versions(self, name):
        raise RegistryError(f"{name} would come from the registry")

    def packages(self):
        return {}

    def entry(self, name, version):
        raise RegistryError(f"{name} would come from the registry")
