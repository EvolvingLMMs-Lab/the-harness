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

import os
from pathlib import Path
import shutil
import sys
import tempfile

from ..core import tree_hash
from ..paths import data as data_dir
from . import archive, sources, state
from .addons import find_skills
from .manifest import Package, load, write
from .registry import Registry, RegistryError, configured, harness_fits
from .resolve import ResolveError, resolve


AUTO_INSTALL = ("official", "ask", "off")
SINGULAR = {"kinds": "kind", "embodiments": "embodiment", "skills": "skill", "benches": "bench",
            "services": "service", "prompts": "prompt", "profiles": "profile", "experiments": "experiment",
            "agent_skills": "Agent Skill", "settings": "settings section", "config_keys": "configuration key",
            "commands": "command", "agents": "agent"}


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
                zip_bytes: bytes | None = None, embodiment: str | None = None, log=print) -> dict:
        """Install packages by source text (sources.py), or `zip_bytes` (an archive the app
        was given). Packages from outside the registry need `consent(found) -> bool`
        (found: describe() of each); without it nothing changes and {"needs_trust": True,
        "found": [...]} comes back. With `project`, the project's harness.toml and
        harness.lock are written (and with no specs, the project's packages are
        installed and the project trusted). With `embodiment`, a folder's skills are
        taken only when they run on it (the app's agent: desktop). Returns
        {"installed": [...], "problems": [...]}."""
        specs = [str(spec) for spec in specs]
        target = self.project() if project else None
        if project and target is None:
            target = state.Project(Path(self.cwd or os.getcwd()).resolve())
        with tempfile.TemporaryDirectory(prefix="harness-package-") as temporary:
            temporary = Path(temporary)
            requests, local, problems = {}, [], []
            if project and not specs:
                for name, row in target.wanted().items():
                    specs.append(row["source"] or (f"{name}@{row['range']}" if row["range"] else name))
                if not specs:
                    raise ValueError(f"{target.file}: [packages] names no package")
            for index, spec in enumerate(specs):
                source = sources.parse(spec)
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
            records = self.user().packages if target is None else target.locked()
            have = {name: record.version for name, record in records.items() if name not in requests}
            plan = resolve(requests, self.registry if requests or any(p.depends for p, _, _ in local) else _NoRegistry(),
                           harness=harness_version(), have=have,
                           fixed={package.name: (package.version, package.depends) for package, _, _ in local},
                           depends_of=lambda name, version: self._installed_depends(records, name, version))
            done = []
            for package, origin, source in local:
                done.append(self._store_local(package, origin, link=link and source is not None
                                              and source.kind == "path" and Path(source.path).is_dir(),
                                              python=python, log=log))
            for name, version in plan.items():
                if any(name == package.name for package, _, _ in local):
                    continue
                record = records.get(name)
                if record is not None and record.version == version and                         (Path(record.path or state.store_path(name, version, record.sha256)) / "package.toml").is_file():
                    continue
                done.append(self._store_registry(name, version, temporary / f"registry-{name}", python=python,
                                                 log=log, range_=requests.get(name, "")))
        if target is not None:
            self._write_project(target, done, requests, local)
            self.trust_project(target)
        else:
            user = self.user()
            for record in done:
                old = user.packages.get(record.name)
                if old is not None and not record.range and old.range:
                    record.range = old.range
                user.packages[record.name] = record
            user.write()
        self.changed()
        return {"installed": [{"name": r.name, "version": r.version, "source": r.source, "path": r.path}
                              for r in done], "problems": problems}

    def _installed_depends(self, records, name, version):
        record = records.get(name)
        if record is None or record.version != version:
            return None
        try:
            return load(record.path or state.store_path(name, version, record.sha256)).depends
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

    def _fits(self, package: Package) -> None:
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
        return state.Record(name, version, entry["sha256"], "registry" if self.registry.official
                            else f"registry:{self.registry.base}", range=range_, path=str(target))

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

    def _write_project(self, project: state.Project, done, requests, local) -> None:
        wanted = project.wanted()
        for name, range_ in requests.items():
            wanted[name] = {"range": range_, "source": wanted.get(name, {}).get("source", "")}
        for package, origin, _ in local:
            wanted[package.name] = {"range": "", "source": origin.split("#sha256=")[0]}
        locked = project.locked()
        for record in done:
            locked[record.name] = record
        project.set_wanted(wanted)
        project.write_lock(locked.values())

    def trust_project(self, project: state.Project) -> None:
        user = self.user()
        if str(project.root) not in user.trusted_projects:
            user.trusted_projects.append(str(project.root))
            user.write()

    def remove(self, names, *, project: bool = False, log=print) -> list[str]:
        """Remove packages (from the user's list, or the project's); their stored
        versions go when nothing else uses them."""
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
        self.collect(log=log)
        self.changed()
        return names

    def collect(self, *, log=print) -> None:
        """Delete stored versions the user's list and this project's lock no longer use."""
        used = {Path(record.path).resolve() for record in self.user().packages.values() if record.path}
        project = self.project()
        if project is not None:
            used |= {state.store_path(n, r.version, r.sha256).resolve() for n, r in project.locked().items()}
        root = state.store_root()
        for folder in sorted(root.glob("*/*")) if root.is_dir() else []:
            if folder.is_dir() and folder.resolve() not in used:
                state.delete(folder)
        for folder in sorted(root.glob("*")) if root.is_dir() else []:
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()

    def update(self, names=(), *, project: bool = False, log=print) -> dict:
        """Update registry packages (all, or `names`) to the highest version in the range
        they were installed with that works with this harness."""
        records = self.project().locked() if project and self.project() else self.user().packages
        names = [str(name) for name in names] or sorted(records)
        unknown = [name for name in names if name not in records]
        if unknown:
            raise ValueError(f"no installed package {', '.join(unknown)}")
        specs = []
        wanted = self.project().wanted() if project and self.project() else {}
        for name in names:
            record = records[name]
            if not record.source.startswith("registry"):
                log(f"{name}: installed from {record.source}; install it again to update it")
                continue
            range_ = wanted.get(name, {}).get("range", "") if project else record.range
            latest = self.registry.pick(name, range_)
            if latest != record.version:
                specs.append(f"{name}@=={latest}")
        if not specs:
            log("everything is up to date")
            return {"installed": [], "problems": []}
        result = self.install(specs, project=project, log=log)
        if not project:
            user = self.user()
            for name in names:
                if name in user.packages and name in records:
                    user.packages[name].range = records[name].range
            user.write()
        return result

    def enable(self, name: str, on: bool) -> None:
        user = self.user()
        if name not in user.packages:
            raise ValueError(f"no installed package {name}")
        user.packages[name].enabled = bool(on)
        user.write()
        self.changed()

    # -- first use ---------------------------------------------------------------------

    def ensure(self, what: str, name: str, *, ask=None, log=print) -> Package:
        """The enabled package that provides `name` among its `what` (skills, embodiments,
        benches, services, kinds, commands); when none does, the registry's package that
        provides it, installed as packages.auto_install says. MissingPackage otherwise."""
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
        mode = self.auto_install()
        if mode == "off":
            raise MissingPackage(f"the {singular} {name} is in the package {choice}: harness install {choice} "
                                 "(packages.auto_install is off)")
        if mode == "ask" and not (ask and ask({"package": choice, "what": singular, "name": name,
                                               "registry": self.registry.base})):
            raise MissingPackage(f"the {singular} {name} needs the package {choice}, which was not installed")
        log(f"the {singular} {name} is in the package {choice}: installing it")
        self.install([choice], log=log)
        package = self.provider(what, name)
        if package is None:
            raise MissingPackage(f"{choice} was installed but does not provide the {singular} {name}")
        return package

    # -- the running process -----------------------------------------------------------

    def changed(self) -> None:
        """Make this process see the packages as they are now."""
        activate(self)


def activate(packages: Packages | None = None) -> Packages:
    """Make the enabled packages load in this process and in the processes it starts
    (HARNESS_PACKAGE_ROOTS, which paths.package_roots() reads: their skills, benches,
    prompts and modules); first, on the first start since packages, turn the app's
    installed skills into packages (migrate.py)."""
    from ..paths import PACKAGES_ENV, packages_changed
    from .migrate import migrate

    packages = packages or Packages()
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
