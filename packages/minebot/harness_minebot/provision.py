"""What the body needs installed, put under $HARNESS_HOME/minebot the first time it is
used and never into the package:

    node-v<version>-<system>-<machine>/   Node, from nodejs.org, checked against the release's
                                          own checksum (NODE, ARCHIVES)
    modules-<hash>/node_modules/          the body's libraries, as body/package-lock.json pins
                                          them (npm ci); <hash> is that file's, so another
                                          version of the package gets its own

Nothing of the game is installed, downloaded or started: the body joins a server that is
there. `harness minebot setup` does this ahead of time; `status()` says what is there.
"""

import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

from harness.sdk import file_lock

from .config import BODY, install_dir


NODE = "24.12.0"
# The release's own SHASUMS256.txt, for the archives this package uses.
ARCHIVES = {
    ("windows", "x64"): ("node-v24.12.0-win-x64.zip", "9c125f61ae947b52e779095830f9cac267846a043ef7192183c84016aaad2812"),
    ("windows", "arm64"): ("node-v24.12.0-win-arm64.zip", "b05e7e066f813d35ad3cd9c24eedaee074c012ac7e00071297608fdd2e948ae3"),
    ("linux", "x64"): ("node-v24.12.0-linux-x64.tar.xz", "bdebee276e58d0ef5448f3d5ac12c67daa963dd5e0a9bb621a53d1cefbc852fd"),
    ("linux", "arm64"): ("node-v24.12.0-linux-arm64.tar.xz", "a06d42807fb500f7459e5f3fa6cb431447352826ee6f07e14adfeec58a1b3210"),
    ("macos", "x64"): ("node-v24.12.0-darwin-x64.tar.gz", "b82ea4c62fd08e250cab59d625e75d77cc5b0a3d60c6698ebee4545c88a169c5"),
    ("macos", "arm64"): ("node-v24.12.0-darwin-arm64.tar.gz", "319f221adc5e44ff0ed57e8a441b2284f02b8dc6fc87b8eb92a6a93643fd8080"),
}
BASE = f"https://nodejs.org/dist/v{NODE}/"
DONE = ".installed"


def machine(system=None, cpu=None) -> tuple[str, str]:
    """This computer as ARCHIVES names it: (windows | linux | macos, x64 | arm64)."""
    system = system or sys.platform
    cpu = (cpu or platform.machine()).lower()
    name = "windows" if system.startswith("win") else "macos" if system == "darwin" else "linux"
    return name, "arm64" if cpu in ("arm64", "aarch64") else "x64"


def archive(key=None) -> tuple[str, str]:
    key = key or machine()
    if key not in ARCHIVES:
        raise RuntimeError(f"no Node release is listed for {key[0]} on {key[1]}")
    return ARCHIVES[key]


def node_dir(key=None) -> Path:
    name = archive(key)[0]
    return install_dir() / name.removesuffix(".zip").removesuffix(".tar.xz").removesuffix(".tar.gz")


def node(key=None) -> Path:
    key = key or machine()
    return node_dir(key) / ("node.exe" if key[0] == "windows" else "bin/node")


def npm(key=None) -> Path:
    key = key or machine()
    return node_dir(key) / ("node_modules" if key[0] == "windows" else "lib/node_modules") / "npm" / "bin" / "npm-cli.js"


def lock_hash() -> str:
    return hashlib.sha256((BODY / "package-lock.json").read_bytes()).hexdigest()[:12]


def modules_dir() -> Path:
    return install_dir() / f"modules-{lock_hash()}"


def node_path() -> str:
    """NODE_PATH for the body's processes: where its libraries are."""
    return str(modules_dir() / "node_modules")


def _download(name: str, digest: str, target: Path, log) -> None:
    log(f"minebot: downloading {BASE}{name}")
    got = hashlib.sha256()
    request = urllib.request.Request(BASE + name, headers={"User-Agent": "the-harness"})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as out:
        while chunk := response.read(1 << 20):
            got.update(chunk)
            out.write(chunk)
    if got.hexdigest() != digest:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"{name}: what was downloaded is not the release (its checksum is {got.hexdigest()}, "
                           f"the release's is {digest}); nothing was installed")


def _long(path: Path) -> str:
    """`path` as Windows takes one longer than 260 characters (the archive's own paths are deep)."""
    return "\\\\?\\" + str(path.resolve()) if os.name == "nt" else str(path)


def _unpack(file: Path, into: Path, name: str) -> None:
    if name.endswith(".zip"):
        with zipfile.ZipFile(file) as bundle:
            bundle.extractall(_long(into))
    else:
        with tarfile.open(file) as bundle:
            bundle.extractall(into, filter="tar")


def install_node(log=print) -> Path:
    """Node, unless it is there."""
    if node().is_file():
        return node()
    name, digest = archive()
    root = install_dir()
    root.mkdir(parents=True, exist_ok=True)
    part = root / (name + ".part")
    try:
        _download(name, digest, part, log)
        staging = root / "unpacking"
        shutil.rmtree(_long(staging), ignore_errors=True)
        _unpack(part, staging, name)
        shutil.rmtree(_long(node_dir()), ignore_errors=True)
        os.rename(_long(staging / node_dir().name), _long(node_dir()))
        shutil.rmtree(_long(staging), ignore_errors=True)
    finally:
        part.unlink(missing_ok=True)
    if not node().is_file():
        raise RuntimeError(f"{name} was unpacked, and {node()} is not in it")
    return node()


def install_modules(log=print) -> Path:
    """The body's libraries as the lockfile pins them, unless they are there."""
    folder = modules_dir()
    if (folder / DONE).is_file():
        return folder
    shutil.rmtree(folder, ignore_errors=True)   # an install that did not finish
    folder.mkdir(parents=True)
    for name in ("package.json", "package-lock.json"):
        shutil.copyfile(BODY / name, folder / name)
    record = install_dir() / "install.log"
    log(f"minebot: installing the body's libraries into {folder} (log: {record})")
    env = {**os.environ, "PATH": os.pathsep.join([str(node().parent), os.environ.get("PATH", "")])}
    with record.open("ab") as out:
        out.write(f"\n=== {time.strftime('%F %T')} npm ci in {folder}\n".encode())
        out.flush()
        done = subprocess.run([str(node()), str(npm()), "ci", "--omit=dev", "--no-audit", "--no-fund"], cwd=folder, env=env,
                              stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                              **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    if done.returncode != 0 or not (folder / "node_modules" / "mineflayer").is_dir():
        raise RuntimeError(f"the body's libraries did not install (npm ci ended with {done.returncode}); see {record}")
    (folder / DONE).write_text(time.strftime("%F %T"), encoding="utf-8")
    return folder


def ensure(log=print) -> dict:
    """Everything the body needs, installed unless it is there: {"node", "modules"}."""
    install_dir().mkdir(parents=True, exist_ok=True)
    with file_lock(install_dir() / "install.lock"):
        return {"node": str(install_node(log)), "modules": str(install_modules(log))}


def status() -> list[dict]:
    """What is installed: [{"what", "installed", "where"}]."""
    return [{"what": f"Node {NODE}", "installed": node().is_file(), "where": str(node_dir())},
            {"what": "the body's libraries", "installed": (modules_dir() / DONE).is_file(), "where": str(modules_dir())}]
