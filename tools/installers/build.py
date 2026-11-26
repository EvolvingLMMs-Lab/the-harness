"""Build the desktop installers of this computer's system: the Tauri shell (packages/app/shell)
with a bundled Python runtime (python-build-standalone), the Harness wheel installed in it, the
package folders the app needs, which the shell installs on its first start, and the `harness`
command for terminals (runtime/bin, which the installers put on the PATH).

    python tools/installers/build.py                      # this system's installers
    python tools/installers/build.py --bundles nsis,msi   # only these (Windows)
    python tools/installers/build.py --stage-only         # the runtime only, no Tauri build

Windows gives .exe (NSIS) and .msi, macOS .app and .dmg, Linux AppImage and .deb, under
packages/app/shell/src-tauri/target/release/bundle/. Needs Rust, Node.js and, on Linux,
WebKitGTK 4.1 and libayatana-appindicator (the release workflow installs them).

The shell's updater checks GitHub Releases against its own key (separate from code signing):
TAURI_UPDATER_PUBKEY (or tools/installers/updater.pub) is put into the build, and with
TAURI_SIGNING_PRIVATE_KEY set the build also signs the update bundles. Without the private
key the installers are built without update bundles. Never commit a private key.
"""

import argparse
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
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "packages" / "app" / "shell"
RUNTIME = SHELL / "src-tauri" / "runtime"
LAUNCHER = SHELL / "launcher"
WORK = ROOT / "build" / "installers"

# python-build-standalone: one release, pinned with each archive's SHA-256 (its SHA256SUMS).
PYTHON = "3.12.16"
RELEASE = "20261124"
ARCHIVES = {
    "x86_64-pc-windows-msvc": "96694b50dcfde13d56e40346ddaa552a9cd650290e9b933cecf83c1d82226960",
    "x86_64-unknown-linux-gnu": "7e1adaea26c959d13aa1120be1ae62a1ea1bb52adcb382679fffe9217e22adff",
    "aarch64-unknown-linux-gnu": "518e24b37e356775d82d5609cd9d48e27e211381a39ae416381ba696bf76c25c",
    "aarch64-apple-darwin": "9d6d9d0d85feda3f9cb4eb3e048f0fed21ed280feda087927eaa4fbc7124826f",
    "x86_64-apple-darwin": "6d7ef4efa1adf65f312e6e865040ce03ef8a4bd7e1b45415193295c9ffc0dbdd",
}
# The package folders the app needs at its first start; the rest install on first use.
PACKAGES = ("agent", "app", "workspace", "computer", "browser", "qq")
BUNDLES = {"win32": "nsis,msi", "darwin": "app,dmg", "linux": "appimage,deb"}


def target() -> str:
    machine = platform.machine().lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def version() -> str:
    text = (ROOT / "src" / "harness" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def run(command, **options):
    print("+", " ".join(map(str, command)), flush=True)
    subprocess.run([str(word) for word in command], check=True, **options)


def download(triple: str) -> Path:
    name = f"cpython-{PYTHON}+{RELEASE}-{triple}-install_only_stripped.tar.gz"
    archive = WORK / "cache" / name
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVES[triple]:
        archive.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/astral-sh/python-build-standalone/releases/download/{RELEASE}/{name}"
        print(f"downloading {url}", flush=True)
        with urllib.request.urlopen(url, timeout=300) as answer, open(archive, "wb") as out:
            shutil.copyfileobj(answer, out)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != ARCHIVES[triple]:
        archive.unlink()
        raise SystemExit(f"{name}: SHA-256 {digest} is not the pinned {ARCHIVES[triple]}")
    return archive


def wheel() -> Path:
    out = WORK / "wheel"
    shutil.rmtree(out, ignore_errors=True)
    run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", out, ROOT])
    return next(out.glob("the_harness-*.whl"))


def command(triple: str) -> None:
    """runtime/bin/harness: the `harness` command for terminals, which runs the harness with
    runtime/python. Windows: a small program (packages/app/shell/launcher), built here; macOS:
    a script. Linux needs none here: the .deb installs /usr/bin/harness (tauri.conf.json) and
    an AppImage has no command."""
    python = RUNTIME / "python"
    # The console script pip made names the Python of this build by its full path: it runs
    # nowhere else, so the app's runtime has the launcher only.
    for script in (python / "Scripts" / "harness.exe", python / "bin" / "harness"):
        script.unlink(missing_ok=True)
    folder = RUNTIME / "bin"
    if "windows" in triple:
        run(["cargo", "build", "--release", "--target", triple, "--manifest-path", LAUNCHER / "Cargo.toml"])
        folder.mkdir()
        shutil.copy2(LAUNCHER / "target" / triple / "release" / "harness.exe", folder / "harness.exe")
    elif "apple" in triple:
        folder.mkdir()
        shutil.copyfile(SHELL / "src-tauri" / "macos" / "harness", folder / "harness")
        (folder / "harness").chmod(0o755)
    else:
        return
    run([folder / ("harness.exe" if "windows" in triple else "harness"), "--version"],
        env={**os.environ, "HARNESS_DATA": str(WORK / "probe-data"), "HARNESS_HOME": str(WORK / "probe-home")})


def stage(triple: str, packages) -> None:
    """runtime/python with the wheel installed in it, runtime/packages and runtime/bin."""
    for item in RUNTIME.iterdir():
        if item.name != "README.txt":
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    with tarfile.open(download(triple)) as archive:
        archive.extractall(RUNTIME, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    python = RUNTIME / "python" / ("python.exe" if "windows" in triple else "bin/python3")
    run([python, "-m", "pip", "install", "--no-cache-dir", "--no-warn-script-location",
         "--disable-pip-version-check", wheel()])
    probe = {**os.environ, "HARNESS_DATA": str(WORK / "probe-data"), "HARNESS_HOME": str(WORK / "probe-home")}
    run([python, "-m", "harness", "--version"], env=probe)
    # The terminal chat's libraries at the harness's own pins (harness.tui), so the harness
    # command opens at once in a terminal, offline too; a pip install gets them on first use.
    pins = subprocess.run([str(python), "-c", "from harness import tui; print(' '.join(tui.LIBRARIES + tui.PINS))"],
                          env=probe, capture_output=True, text=True, check=True).stdout.split()
    run([python, "-m", "pip", "install", "--no-cache-dir", "--no-warn-script-location", "--disable-pip-version-check",
         "--no-deps", *pins])
    # The app package's shell/ is this desktop shell (with this runtime in it), not part of the package.
    skip = shutil.ignore_patterns("tests", "__pycache__", "node_modules", "*.pyc", ".pytest_cache", "shell", "target")
    for name in packages:
        source = ROOT / "packages" / name
        if (source / "package.toml").is_file():
            shutil.copytree(source, RUNTIME / "packages" / name, ignore=skip)
        else:
            print(f"warning: packages/{name} has no package.toml; not bundled", flush=True)
    command(triple)


def public_key() -> str:
    key = os.environ.get("TAURI_UPDATER_PUBKEY", "").strip()
    file = Path(__file__).with_name("updater.pub")
    if not key and file.is_file():
        key = file.read_text(encoding="utf-8").strip()
    return key


def tauri(triple: str, bundles: str) -> Path:
    signing = bool(os.environ.get("TAURI_SIGNING_PRIVATE_KEY"))
    config = {"version": version(), "plugins": {"updater": {"pubkey": public_key()}},
              "bundle": {"createUpdaterArtifacts": signing and bool(public_key())}}
    if not config["bundle"]["createUpdaterArtifacts"]:
        print("note: no updater key pair given; building without update bundles", flush=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as file:
        json.dump(config, file)
    try:
        # The Tauri CLI pinned in package.json, matching the tauri crate of Cargo.lock.
        windows = sys.platform == "win32"
        run(["npm", "install", "--no-audit", "--no-fund"], cwd=SHELL, shell=windows)
        run(["npx", "tauri", "build", "--bundles", bundles, "--target", triple, "--config", file.name], cwd=SHELL,
            shell=windows)
    finally:
        os.unlink(file.name)
    return SHELL / "src-tauri" / "target" / triple / "release" / "bundle"


def main(argv=None) -> int:
    parsed = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parsed.add_argument("--target", default=target(), choices=sorted(ARCHIVES),
                        help="the system to build for: this one (a bundled Python runs during the build)")
    parsed.add_argument("--bundles", help=f"Tauri bundle kinds (default {BUNDLES})")
    parsed.add_argument("--packages", nargs="*", default=list(PACKAGES), help="package folders to bundle")
    parsed.add_argument("--stage-only", action="store_true", help="prepare the runtime, do not build")
    given = parsed.parse_args(argv)
    if given.target != target():
        raise SystemExit(f"build {given.target} on that system: the bundled Python runs during the build")
    stage(given.target, given.packages)
    if given.stage_only:
        return 0
    platform_key = "linux" if sys.platform.startswith("linux") else sys.platform
    bundle = tauri(given.target, given.bundles or BUNDLES[platform_key])
    print(f"installers: {bundle}")
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and path.suffix in (".exe", ".msi", ".dmg", ".AppImage", ".deb", ".sig", ".gz"):
            print(f"  {path.relative_to(bundle)}  {path.stat().st_size // (1024 * 1024)} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
