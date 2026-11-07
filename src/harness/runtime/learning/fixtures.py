"""Host dispatch and byte snapshots for package-owned learning fixtures."""

from importlib import import_module
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tempfile
import time
import tomllib

from harness.bench import bench_spec
from harness.core import sha256
from harness.paths import PACKAGE, packages


BUNDLES = Path("/opt/harness-fixtures")
MAX_BUNDLE = 2 * 1024 ** 3


class Budget:
    def __init__(self, seconds, cancelled):
        self.deadline = time.monotonic() + min(45.0, seconds)
        self.cancelled = cancelled

    def remaining(self, reserve=0):
        if self.cancelled():
            raise RuntimeError("conversation cancelled its fixture")
        seconds = self.deadline - time.monotonic() - reserve
        if seconds <= 0:
            raise TimeoutError("fixture deadline expired")
        return seconds


def _copy(source, target, budget):
    digest = hashlib.sha256()
    while True:
        budget.remaining(reserve=1)
        block = source.read(1024 * 1024)
        if not block:
            return digest.hexdigest()
        if target is not None:
            target.write(block)
        digest.update(block)


def _unpack(bundle, root, budget):
    """Extract a curated, self-contained runtime. Never create links or special files."""
    seen, size = set(), 0
    with tarfile.open(bundle, "r:") as archive:
        for entry in archive:
            budget.remaining(reserve=1)
            path = PurePosixPath(entry.name)
            if (not path.parts or "\\" in entry.name or ":" in entry.name
                    or path.parts[0] not in ("usr", "opt", "lib", "lib64", "etc")
                    or ".." in path.parts or path in seen or not (entry.isdir() or entry.isreg())):
                raise ValueError("unsafe member in fixture bundle")
            seen.add(path)
            target = root.joinpath(*path.parts)
            if entry.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            size += entry.size
            if size > MAX_BUNDLE:
                raise ValueError("fixture runtime bundle is too large")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(entry) as source, target.open("xb") as output:
                _copy(source, output, budget)
            target.chmod(0o755 if entry.mode & 0o111 else 0o644)


def _sources(roots, budget, output=None):
    files = {}
    for prefix, root in roots.items():
        for path in sorted(root.rglob("*")):
            budget.remaining(reserve=1)
            relative = path.relative_to(root)
            if (path.suffix not in (".py", ".toml", ".txt") or not path.is_file()
                    or any(part.startswith(".") for part in relative.parts)):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("fixture runtime source must be a regular file in its package")
            key = f"{prefix}/{relative.as_posix()}"
            with path.open("rb") as source:
                if not stat.S_ISREG(path.stat().st_mode):
                    raise ValueError("fixture runtime source must be a regular file")
                if output is None:
                    files[key] = _copy(source, None, budget)
                else:
                    target = output / key
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as snapshot:
                        files[key] = _copy(source, snapshot, budget)
    return files


def configured(profile):
    """Read the host's fixture inventory, outside the model-facing runtime settings."""
    path = os.environ.get("HARNESS_LEARNING_FIXTURES")
    if not path or profile.get("physical") is not False:
        return ()
    with Path(path).open("rb") as stream:
        inventory = tomllib.load(stream)
    execution = profile.get("execution")
    rows = tuple({**config, "type": execution} for config in inventory.get(execution, ()))
    if any(not isinstance(config.get("skill"), str) for config in rows):
        raise ValueError("each fixture needs a skill selector")
    return rows


def _provider(execution):
    spec = bench_spec(execution)
    module = spec.factory.partition(":")[0].rpartition(".")[0]
    return spec, import_module(f"{module}.fixture")


def describe(inventory):
    descriptions = []
    for config in inventory:
        try:
            _, provider = _provider(config["type"])
            provider.supported()
            descriptions.append(provider.describe(config))
        except (ImportError, ValueError, RuntimeError):
            continue
    return descriptions


def verify(entry, config, budget, run):
    """Return the exact revision and a verdict produced by the package provider."""
    budget.remaining()
    spec, provider = _provider(config["type"])
    provider.supported()
    installed = {package.name: package for package in packages()}
    package = next(item for item in installed.values() if spec.path.is_relative_to(item.path))
    roots = {"core/harness": PACKAGE.resolve(),
             **{name: installed[name].path.resolve() for name in (package.name, *package.depends)}}
    plan = provider.prepare(config, entry)
    bundle = Path(config["bundle"]).resolve()
    expected = config["bundle_sha256"]
    bundle_root = Path(os.environ.get("HARNESS_FIXTURE_BUNDLES", BUNDLES)).resolve()
    if (not bundle.is_relative_to(bundle_root) or not bundle.is_file() or bundle.stat().st_size > MAX_BUNDLE
            or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)):
        raise ValueError("fixture needs a host-provisioned, SHA-256 pinned runtime bundle")

    with tempfile.TemporaryDirectory(prefix="harness-fixture-") as temp:
        directory = Path(temp)
        root = directory / "root"
        archive = directory / "runtime.tar"
        with bundle.open("rb") as source, archive.open("xb") as snapshot:
            if _copy(source, snapshot, budget) != expected:
                raise ValueError("fixture runtime bundle digest changed")
        files = _sources(roots, budget, root / "fixture")
        item = entry.revision(bindings=provider.bindings(plan, files))
        identity = sha256({"fixture": config, "bundle": expected, "sources": files})
        try:
            _unpack(archive, root, budget)
        except tarfile.TarError as error:
            raise ValueError("invalid fixture runtime bundle") from error
        result = provider.observe(config, plan, root, budget)
        if files != _sources(roots, budget):
            raise ValueError("fixture dependency sources changed during the trial")
    budget.remaining()
    return item, {**result, "run": run, "revision": item.revision,
                  "fixture_type": config["type"], "fixture_sha256": identity}
