"""A saved ACP Registry catalog, with explicit installation of pinned distributions."""

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen
import zipfile

from harness.sdk import atomic_write, home


URL = "https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"
ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,100}")


def root():
    return home() / "acp-registry"


def refresh():
    with urlopen(URL, timeout=30) as response:
        catalog = response.read(4 * 1024 * 1024 + 1)
    if len(catalog) > 4 * 1024 * 1024:
        raise ValueError("ACP Registry catalog is too large")
    found = json.loads(catalog)
    if not str(found.get("version", "")).startswith("1.") or not isinstance(found.get("agents"), list):
        raise ValueError("unsupported ACP Registry schema")
    atomic_write(root() / "catalog.json", catalog)
    return len(found["agents"])


def catalog():
    path = root() / "catalog.json"
    rows = json.loads(path.read_text(encoding="utf-8"))["agents"] if path.is_file() else []
    return {row["id"]: row for row in rows if ID.fullmatch(row.get("id", ""))}


def distribution(row):
    variants = row.get("distribution") or {}
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(platform.machine().lower(), platform.machine().lower())
    system = "windows" if os.name == "nt" else sys.platform
    binary = (variants.get("binary") or {}).get(f"{system}-{machine}")
    if binary:
        return "binary", binary
    for kind in ("npx", "uvx"):
        if variants.get(kind):
            return kind, variants[kind]
    return None, {}


def _path(directory, name):
    target = (directory / name).resolve()
    if directory.resolve() not in target.parents:
        raise ValueError("registry archive path escapes the installation directory")
    return target


def installed(identifier):
    if not ID.fullmatch(identifier):
        return None
    path = root() / "installed" / f"{identifier}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _binary(spec, directory):
    url, checksum = spec["archive"], spec.get("sha256")
    if not url.startswith("https://") or checksum and not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
        raise ValueError("invalid ACP archive URL or checksum")
    archive = directory / ".distribution"
    digest = hashlib.sha256()
    size = 0
    with urlopen(url, timeout=45) as response, archive.open("wb") as output:
        if not response.url.startswith("https://"):
            raise ValueError("an ACP archive redirected outside HTTPS")
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 1024 * 1024 * 1024:
                raise ValueError("ACP distribution is too large")
            digest.update(chunk)
            output.write(chunk)
    if checksum and digest.hexdigest() != checksum.lower():
        raise ValueError("ACP distribution checksum did not match")
    unpacked = directory / "files"
    unpacked.mkdir()
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zipped:
            if sum(item.file_size for item in zipped.infolist()) > 2 * 1024**3:
                raise ValueError("expanded ACP distribution is too large")
            for item in zipped.infolist():
                target = _path(unpacked, item.filename)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(item) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    if item.external_attr >> 16 & 0o111:
                        target.chmod(0o755)
    else:
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            if sum(item.size for item in members) > 2 * 1024**3:
                raise ValueError("expanded ACP distribution is too large")
            for item in members:
                if item.name in (".", "./") and item.isdir():
                    continue
                _path(unpacked, item.name)
                if not (item.isfile() or item.isdir()):
                    raise ValueError("ACP distribution contains a non-file archive entry")
                tar.extract(item, unpacked, filter="data")
    archive.unlink()
    executable = _path(unpacked, spec["cmd"])
    if not executable.is_file():
        raise ValueError("ACP distribution did not contain its executable")
    executable.chmod(0o755)
    return [str(executable), *spec.get("args", [])]


def _require(name):
    executable = shutil.which(name)
    if executable is None:
        raise ValueError(f"{name} is required to install this ACP agent")
    return executable


def _npm(spec, directory):
    package = spec["package"]
    if not re.fullmatch(r"(?:@[\w.-]+/)?[\w.-]+@\d+\.\d+\.\d+(?:[-+][\w.+-]+)?", package):
        raise ValueError("the Registry npm distribution must name an exact version")
    node = _require("node")
    npm = Path(_require("npm")).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    argv = [node, str(npm)] if npm.is_file() else [_require("npm")]
    subprocess.run([*argv, "install", "--prefix", str(directory), "--", package], check=True, timeout=300)
    package_name = package.rsplit("@", 1)[0]
    package_dir = directory / "node_modules" / package_name
    bins = json.loads((package_dir / "package.json").read_text(encoding="utf-8")).get("bin") or {}
    executable = bins if isinstance(bins, str) else bins.get(package_name.rsplit("/", 1)[-1])
    if not executable and len(bins) == 1:
        executable = next(iter(bins.values()))
    if not executable:
        raise ValueError("the Registry npm package has no unambiguous executable")
    return [node, str(_path(package_dir, executable)), *spec.get("args", [])]


def _uv(spec, directory):
    package = spec["package"]
    if not re.fullmatch(r"[\w.-]+==\d[\w.+-]*", package):
        raise ValueError("the Registry uvx distribution must name an exact version")
    name = package.split("==", 1)[0]
    bin_dir = directory / "bin"
    env = {**os.environ, "UV_TOOL_DIR": str(directory / "tools"), "UV_TOOL_BIN_DIR": str(bin_dir)}
    subprocess.run([_require("uv"), "tool", "install", "--no-config", "--from", package, name],
                   check=True, timeout=300, env=env)
    executable = bin_dir / (name + ".exe" if os.name == "nt" else name)
    if not executable.is_file():
        raise ValueError("the Registry uvx package did not provide its executable")
    return [str(executable), *spec.get("args", [])]


def install(identifier):
    row = catalog().get(identifier)
    if row is None:
        raise ValueError("refresh the ACP Registry and give a known agent ID")
    kind, spec = distribution(row)
    if kind is None:
        raise ValueError("this agent has no distribution for the current platform")
    cache = root() / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=f"{identifier}-", dir=cache)).resolve()
    try:
        argv = {"binary": _binary, "npx": _npm, "uvx": _uv}[kind](spec, directory)
        values = {"argv": argv, "registry_env": spec.get("env") or {}, "version": row["version"]}
        atomic_write(root() / "installed" / f"{identifier}.json", json.dumps(values), private=True)
    except BaseException:
        shutil.rmtree(directory)
        raise
    return values["version"]
