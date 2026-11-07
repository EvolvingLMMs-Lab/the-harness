"""Environments: where a service's model or a benchmark's simulator runs, installed the
first time a run needs it and never before.

A service manifest (services/<name>.toml) or a benchmark (benches/<name>/bench.toml)
describes its environment in an [environment] table:

    [environment]
    python = "3.11"                                  the Python version
    requirements = ["torch==2.7.0", "timm==1.0.30"]  pinned requirements (pip syntax)
    indexes = ["https://download.pytorch.org/whl/cu128"]
    constraints = "environment/lock/pip-freeze.txt"  pins every install respects
    sources = [{ source = "sam3", install = "editable", no_deps = true }]
    commands = [["{python}", "-m", "pip", "check"]]  run after the installs, in order
    imports = ["torch", "sam3"]                      the check that it works

or names another environment to run in: `environment = "openwam"` (that service's) or
`environment = "robodojo"` (that benchmark's). Each environment is a virtual
environment of its own under HOME/envs/<name>/<hash>/, the hash taken over everything
that decides what is installed, so a manifest whose environment changes gets a new one
and an unchanged one is reused. A source is checked out once at its pinned commit
under HOME/sources/ (third_party/sources.toml names the shared ones) and shared by every
environment that uses it.

uv builds them when it is on PATH (`uv venv --python X` fetches the Python version
itself); without it, a python<X> on PATH and pip do. A deploy (or $HARNESS_ENVIRONMENTS)
with environments = "project" installs none: every service and worker runs in the
interpreter of the harness itself, the development environment of a checkout
(environment/setup.sh), which has everything.
"""

import contextlib
from dataclasses import dataclass, field
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib

from ..core import format as formats
from ..core.procs import file_lock, service_environment
from ..paths import ROOT, home, third_party


# The keys of an [environment] table.
ENVIRONMENT_KEYS = {
    "python": "the Python version, e.g. \"3.11\"",
    "requirements": "pinned requirements, in pip syntax (\"-r FILE\" names a file of a source)",
    "indexes": "package indexes besides the default one (e.g. PyTorch's CUDA wheels)",
    "constraints": "pins every install of the environment respects: a file of the harness "
                   "(environment/lock/pip-freeze.txt) or a list",
    "sources": "checkouts at fixed commits, and how to install each: [{ source or repo + rev, nested, install, "
               "subdirectory, no_deps, flags }]",
    "commands": "commands run after the installs, in order: argv lists, or { run, env, cwd } "
                "({python}, {env}, {root}, {home} and the sources' checkouts such as {robodojo} are filled in)",
    "env": "environment variables of the installs and commands",
    "overrides": "versions that win over what a package declares (isaacsim-kernel's websockets==12.0 next to "
                 "17.1): kept out of the constraints, forced after the installs",
    "imports": "modules that must import once it is installed (the check)",
}
# The keys of one entry of `sources`.
SOURCE_KEYS = {
    "source": "a source of third_party/sources.toml (its url, revision and nested checkouts)",
    "repo": "or a git URL ...",
    "rev": "... and the full commit to check out",
    "nested": "nested checkouts to fetch at the revisions sources.toml gives (default none)",
    "install": "none (default: only checked out), editable or package",
    "subdirectory": "install what is in this subdirectory of the checkout",
    "no_deps": "install without its dependencies (they are in requirements)",
    "flags": "further pip flags, e.g. --no-build-isolation",
}
INSTALLS = ("none", "editable", "package")
SOURCES_FILE = ROOT / "third_party" / "sources.toml"
ENVIRONMENTS_ENV = "HARNESS_ENVIRONMENTS"
RECORD = "harness-env.json"


def validate(spec, where: str) -> None:
    """Raise ValueError when an [environment] table (or the name of another one) is not
    one ENVIRONMENT_KEYS describes."""
    if isinstance(spec, str):
        return
    if not isinstance(spec, dict):
        raise ValueError(f"{where}: environment is a table or the name of another environment")
    unknown = set(spec) - set(ENVIRONMENT_KEYS)
    if unknown:
        raise ValueError(f"{where}: environment has unknown keys {sorted(unknown)}")
    if not isinstance(spec.get("python", ""), str) or not spec.get("python"):
        raise ValueError(f"{where}: environment needs a python version (python = \"3.11\")")
    for entry in spec.get("sources", []):
        unknown = set(entry) - set(SOURCE_KEYS)
        if unknown:
            raise ValueError(f"{where}: a source has unknown keys {sorted(unknown)}")
        if bool(entry.get("source")) == bool(entry.get("repo")):
            raise ValueError(f"{where}: a source names either source or repo (with rev)")
        if entry.get("repo") and len(str(entry.get("rev", ""))) != 40:
            raise ValueError(f"{where}: a source repo needs rev, a full commit")
        if entry.get("source") and entry["source"] not in shared_sources():
            raise ValueError(f"{where}: no source {entry['source']!r} in {SOURCES_FILE.name}; "
                             f"known: {sorted(shared_sources())}")
        if entry.get("install", "none") not in INSTALLS:
            raise ValueError(f"{where}: a source's install is one of {INSTALLS}")
    for command in spec.get("commands", []):
        if not (isinstance(command, list) or (isinstance(command, dict) and "run" in command)):
            raise ValueError(f"{where}: a command is an argv list or {{ run = [...], env, cwd }}")


def shared_sources() -> dict:
    """third_party/sources.toml: the checkouts several environments share, by name."""
    with SOURCES_FILE.open("rb") as handle:
        return tomllib.load(handle)


def mode(deploy=None) -> str:
    """"own" (each service and benchmark in an environment of its own, installed on first
    use) or "project" (everything in the harness's own interpreter): $HARNESS_ENVIRONMENTS,
    else the deploy's `environments`, else own."""
    value = os.environ.get(ENVIRONMENTS_ENV) or getattr(deploy, "environments", None) or "own"
    if value not in ("own", "project"):
        raise ValueError(f"environments must be own or project, not {value!r}")
    return value


# -- sources ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class Source:
    """A checkout: where it is, the URL and commit, and its nested checkouts (path ->
    commit). `managed`: the harness checks it out (under HOME/sources); otherwise it is the
    user's (a deploy's or $HARNESS_<NAME>_ROOT, or a checkout's third_party/) and is used
    as it is."""

    name: str
    path: Path
    url: str
    rev: str
    nested: tuple = ()
    managed: bool = True


def source(entry: dict, deploy=None) -> Source:
    """The checkout of one `sources` entry (or a name of sources.toml)."""
    if isinstance(entry, str):
        entry = {"source": entry}
    if entry.get("repo"):
        url, rev = entry["repo"], entry["rev"]
        name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        return Source(name=name, path=home() / "sources" / f"{name}-{rev[:12]}", url=url, rev=rev)
    name = entry["source"]
    known = shared_sources()[name]
    folder = Path(known.get("path", name)).name
    wanted = set(entry.get("nested", ()))
    nested = tuple((path, rev) for path, rev in known.get("nested", {}).items() if path in wanted)
    path = Path(getattr(deploy, name)) if name == "robodojo" and deploy is not None else third_party(folder)
    managed = path == home() / "sources" / folder
    return Source(name=name, path=path, url=known["url"], rev=known["revision"], nested=nested, managed=managed)


def _git(*args, cwd=None, log=None):
    # Large files in git LFS (images of READMEs, sample data) are not code: never fetched.
    base = service_environment(log=(lambda line: log.write(line + "\n")) if log else None)
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, encoding="utf-8", errors="replace",
                            env={**base, "GIT_LFS_SKIP_SMUDGE": "1"})
    if log:
        log.write(f"$ git {' '.join(args)}\n{result.stdout}{result.stderr}")
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()[-500:]}")
    return result.stdout.strip()


def _fetch(path: Path, url: str, rev: str, log) -> None:
    """Make `path` a git checkout of `url` at `rev` (fetching only that commit)."""
    if not (path / ".git").exists():
        path.mkdir(parents=True, exist_ok=True)
        _git("init", "-q", cwd=path, log=log)
        _git("remote", "add", "origin", url, cwd=path, log=log)
    else:
        with contextlib.suppress(RuntimeError):
            if _git("rev-parse", "HEAD", cwd=path, log=log) == rev:
                return
    for attempt in range(4):
        try:
            _git("fetch", "-q", "--depth", "1", "origin", rev, cwd=path, log=log)
            break
        except RuntimeError:
            if attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))  # a dropped connection: try again
    _git("-c", "advice.detachedHead=false", "checkout", "-q", "--force", rev, cwd=path, log=log)


def checkout(item: Source, log) -> Path:
    """Check a source out at its commit (and its nested checkouts at theirs) unless it is
    there already; a source that is not managed must exist and is used as it is."""
    if not item.managed:
        if not item.path.is_dir():
            raise RuntimeError(f"{item.name}: no checkout at {item.path}")
        return item.path
    marker = item.path / ".harness-source.json"
    state = {"url": item.url, "rev": item.rev, "nested": dict(item.nested)}
    with _locked(home() / "locks" / f"source-{item.path.name}.lock"):
        try:
            done = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            done = {}
        if done.get("url") == item.url and done.get("rev") == item.rev and \
                all(done.get("nested", {}).get(path) == rev for path, rev in item.nested):
            return item.path
        _fetch(item.path, item.url, item.rev, log)
        for path, rev in item.nested:
            url = _git("config", "-f", ".gitmodules", f"submodule.{path}.url", cwd=item.path, log=log)
            _fetch(item.path / path, url, rev, log)
        marker.write_text(json.dumps({**done, **state, "nested": {**done.get("nested", {}), **dict(item.nested)}}),
                          encoding="utf-8")
    return item.path


# -- environments ----------------------------------------------------------------------------

@dataclass
class Environment:
    """One environment as resolved: the name it is installed under, its table, the
    sources it uses, and its directory under HOME/envs (named by its hash)."""

    name: str
    spec: dict
    sources: list = field(default_factory=list)
    hash: str = ""

    @property
    def directory(self) -> Path:
        return home() / "envs" / self.name / self.hash

    @property
    def python(self) -> Path:
        """Its interpreter."""
        return self.directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def installed(self) -> dict | None:
        """The record of a finished install (version, hash, time), or None."""
        try:
            record = json.loads((self.directory / RECORD).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return record if record.get("hash") == self.hash else None

    def variables(self) -> dict:
        """Placeholders of its commands: python, env and each source's checkout by name."""
        return {"python": str(self.python), "env": str(self.directory), "root": str(ROOT), "home": str(home()),
                **{item.name: str(item.path) for item in self.sources}}


def _package(requirement: str) -> str:
    """The normalized package name of a requirement ("Foo_Bar[x]==1" -> "foo-bar")."""
    return re.split(r"[^A-Za-z0-9._-]", requirement.strip(), maxsplit=1)[0].lower().replace("_", "-")


def _constraints(spec) -> list[str]:
    """The pins of an environment, without those of the packages it overrides."""
    value = spec.get("constraints") or []
    if isinstance(value, str):
        # A file of the core or of a package (environment/lock/pip-freeze.txt is local-models').
        from ..paths import find

        found = find(value)
        lines = (found[0] if found else ROOT / value).read_text(encoding="utf-8").splitlines()
        value = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    overridden = {_package(item) for item in spec.get("overrides", [])}
    return [line for line in value if _package(line) not in overridden]


def resolve(name: str, spec, deploy=None, *, benches=None, services=None) -> Environment:
    """The environment of a service or benchmark called `name` with table `spec` (or the
    name of another service's or benchmark's environment)."""
    if isinstance(spec, str):
        if services is not None and spec in services and services[spec].environment is not None:
            target = services[spec]
            return resolve(spec, target.environment, deploy, benches=benches, services=services)
        from ..bench import bench_specs

        benches = benches if benches is not None else bench_specs()
        if spec in benches:
            return resolve(spec, benches[spec].environment, deploy, benches=benches, services=services)
        raise ValueError(f"{name}: environment {spec!r} names no service or benchmark with an environment")
    validate(spec, name)
    sources = [source(entry, deploy) for entry in spec.get("sources", [])]
    digest = hashlib.sha256(json.dumps({
        "spec": spec, "constraints": _constraints(spec),
        "sources": [(item.url, item.rev, list(item.nested)) for item in sources],
    }, sort_keys=True).encode()).hexdigest()[:12]
    return Environment(name=name, spec=spec, sources=sources, hash=digest)


def _render(value, variables):
    if isinstance(value, str):
        for key, item in variables.items():
            value = value.replace("{" + key + "}", item)
        return value
    if isinstance(value, list):
        return [_render(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, variables) for key, item in value.items()}
    return value


def _interpreter(version: str) -> str | None:
    """A Python of `version` on this machine (without uv): this one, or python<version>."""
    if f"{sys.version_info[0]}.{sys.version_info[1]}" == version:
        return sys.executable
    return shutil.which(f"python{version}")


@contextlib.contextmanager
def _locked(path: Path):
    """One install of an environment at a time on this machine (Windows too)."""
    with file_lock(path):
        yield


def install(environment: Environment, *, log=print) -> Environment:
    """Install `environment` unless it is installed: check out its sources, create the
    virtual environment, install the requirements and sources under its constraints, run
    its commands and check its imports, then write its record. The output goes to
    HOME/logs/install-<name>.log; a failure raises RuntimeError naming it."""
    if environment.installed():
        return environment
    logs = home() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f"install-{environment.name}.log"
    with _locked(home() / "locks" / f"env-{environment.name}.lock"), open(path, "a", encoding="utf-8") as out:
        if environment.installed():
            return environment
        out.write(f"\n=== {time.strftime('%F %T')} {environment.name} {environment.hash}\n")
        out.flush()
        started = time.monotonic()
        log(f"{environment.name}: installing its environment ({environment.directory}); log {path}")
        try:
            _install(environment, out)
        except Exception as error:
            out.write(f"FAILED: {error}\n")
            raise RuntimeError(f"{environment.name}: its environment did not install ({error}); see {path}") \
                from None
        log(f"{environment.name}: environment installed in {formats.duration(time.monotonic() - started)}")
    return environment


def on_first_use(environment: Environment, what: str, *, log=print) -> Environment:
    """A frontend's environment (the terminal chat's prompt_toolkit and rich, pywebview, Playwright), installed when first needed with one line to `log`."""
    if environment.installed() is None:
        log(f"harness: installing {what} once, into {environment.directory} (log: {home() / 'logs' / f'install-{environment.name}.log'})")
        install(environment, log=lambda message: None)
    return environment


def _install(environment: Environment, out) -> None:
    spec = environment.spec
    directory = environment.directory
    if directory.exists():
        shutil.rmtree(directory)  # an install that did not finish
    directory.parent.mkdir(parents=True, exist_ok=True)
    for item in environment.sources:
        checkout(item, out)
    variables = environment.variables()
    base = service_environment(log=lambda line: out.write(line + "\n"))
    run_env = {**base, **_render(spec.get("env", {}), variables), "VIRTUAL_ENV": str(directory),
               "PATH": os.pathsep.join([str(environment.python.parent), base.get("PATH", "")])}
    # The new environment, not the one the harness runs in (Isaac Lab's installer, for
    # one, prefers an active conda environment).
    for name in ("PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"):
        run_env.pop(name, None)
    if spec.get("indexes"):
        run_env["PIP_EXTRA_INDEX_URL"] = " ".join(spec["indexes"])
    # Wheels of a GB (torch, Isaac Sim) on a slow link outlast uv's 30 s default.
    run_env.setdefault("UV_HTTP_TIMEOUT", "300")

    def run(argv, cwd=None, env=None):
        argv = [str(item) for item in argv]
        out.write(f"$ {' '.join(argv)}\n")
        out.flush()
        result = subprocess.run(argv, cwd=cwd, env=env or run_env, stdout=out, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            raise RuntimeError(f"{argv[0]} {' '.join(argv[1:4])} ... exited with {result.returncode}")

    uv = shutil.which("uv")
    version = spec["python"]
    if uv:
        run([uv, "venv", "--seed", "--python", version, directory])
    else:
        python = _interpreter(version)
        if python is None:
            raise RuntimeError(f"no Python {version} here: install uv (it fetches Python versions) or "
                               f"python{version}")
        run([python, "-m", "venv", directory])
    constraints = directory / "constraints.txt"
    constraints.write_text("\n".join(_constraints(spec)) + "\n", encoding="utf-8")
    run_env["PIP_CONSTRAINT"] = str(constraints)
    run_env["UV_CONSTRAINT"] = str(constraints)

    overrides = directory / "overrides.txt"
    overrides.write_text("".join(f"{line}\n" for line in spec.get("overrides", [])), encoding="utf-8")
    run_env["UV_OVERRIDE"] = str(overrides)  # for the commands' own uv installs too (Isaac Lab's)

    def pip(*arguments):
        indexes = [flag for url in spec.get("indexes", []) for flag in ("--extra-index-url", url)]
        if uv:
            argv = [uv, "pip", "install", "--python", environment.python, "--index-strategy", "unsafe-best-match",
                    "--override", overrides, *indexes, *arguments]
        else:
            argv = [environment.python, "-m", "pip", "install", "--disable-pip-version-check", *indexes, *arguments]
        # An index that times out once in a while should not cost the whole install:
        # the same installs again (what is in place stays), twice.
        for attempt in range(3):
            try:
                return run(argv)
            except RuntimeError:
                if attempt == 2:
                    raise
                out.write("(again in 30 s)\n")
                time.sleep(30)

    if spec.get("requirements"):
        # "-r FILE" names a requirements file (of a source: {robodojo}/...).
        pip(*[part for item in _render(spec["requirements"], variables)
              for part in (item.split(None, 1) if item.startswith("-r ") else [item])])
    for entry, item in zip(spec.get("sources", []), environment.sources):
        kind = entry.get("install", "none")
        if kind == "none":
            continue
        target = item.path / entry["subdirectory"] if entry.get("subdirectory") else item.path
        pip(*(["--no-deps"] if entry.get("no_deps") else []), *entry.get("flags", []),
            *(["-e"] if kind == "editable" else []), target)
    for command in spec.get("commands", []):
        if isinstance(command, dict):
            run(_render(command["run"], variables), cwd=_render(command.get("cwd"), variables),
                env={**run_env, **_render(command.get("env", {}), variables)})
        else:
            run(_render(command, variables))
    if spec.get("overrides"):
        pip("--no-deps", *spec["overrides"])
    if spec.get("imports"):
        run([environment.python, "-c", "; ".join(f"import {name}" for name in spec["imports"])])
    (directory / RECORD).write_text(json.dumps({
        "name": environment.name, "hash": environment.hash, "python": version, "installed": time.time(),
        "sources": {item.name: item.rev for item in environment.sources}, "spec": spec}, indent=1), encoding="utf-8")
