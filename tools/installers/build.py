"""Build the desktop installers of this computer's system: the Tauri shell (packages/app/shell)
with a bundled Python runtime (python-build-standalone), the Harness wheel installed in it, and
the package folders the app needs, which the shell installs on its first start.

    python tools/installers/build.py                      # this system's installers
    python tools/installers/build.py --bundles nsis,msi   # only these (Windows)
    python tools/installers/build.py --stage-only         # the runtime only, no Tauri build
    python tools/installers/build.py --channel dev --build-number 412   # a build of the dev channel

Windows gives .exe (NSIS) and .msi, macOS .app and .dmg, Linux AppImage and .deb, under
packages/app/shell/src-tauri/target/release/bundle/. Needs Rust, Node.js and, on Linux,
WebKitGTK 4.1 and libayatana-appindicator (the release workflow installs them).

The shell's updater checks GitHub Releases against its own key (separate from code signing):
TAURI_UPDATER_PUBKEY (or tools/installers/updater.pub) is put into the build, and with
TAURI_SIGNING_PRIVATE_KEY set the build also signs the update bundles. Without the private
key the installers are built without update bundles. Never commit a private key.

A channel is decided here and nowhere else. The stable channel is the release: The Harness.
The dev channel (--channel dev) is an app of its own beside it, as VS Code Insiders is beside
VS Code: The Harness Dev, version CORE-dev.N (N: --build-number, the CI run's number), its
own identifier, icon, terminal command (harness-dev), data (~/.harness-dev) and update
address (the files of the prerelease tagged dev). The build puts the channel into the Tauri
configuration (what the shell and the installers are named) and into runtime/channel (what
the harness and the shell read at run time: harness/channel.py); a dev build is always
signed, since it lives on its updates.
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
STABLE = "stable"
CHANNELS = (STABLE, "dev")
REPOSITORY = "https://github.com/EvolvingLMMs-Lab/the-harness"


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


def build_version(channel: str = STABLE, number: int | None = None) -> str:
    """The version of a channel's build: the core's on the stable channel, else
    CORE-CHANNEL.NUMBER (0.87.0-dev.412), whose builds follow each other by that number."""
    if channel == STABLE:
        return version()
    if number is None or number < 1:
        raise SystemExit(f"--channel {channel} needs --build-number (the CI run's number)")
    return f"{version()}-{channel}.{number}"


def names(channel: str) -> dict:
    """What a channel's app is called: its product name, the shell's binary, the terminal
    command and the identifier, as harness/channel.py derives them at run time."""
    if channel == STABLE:
        return {"product": "The Harness", "binary": "the-harness", "command": "harness",
                "identifier": "com.lmms-lab.harness"}
    return {"product": f"The Harness {channel.capitalize()}", "binary": f"the-harness-{channel}",
            "command": f"harness-{channel}", "identifier": f"com.lmms-lab.harness.{channel}"}


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


def stage(triple: str, packages, channel: str = STABLE, number: int | None = None) -> None:
    """runtime/python with the wheel installed in it, and runtime/packages; for another
    channel than the stable one, runtime/channel (its name, then the build's version)."""
    for item in RUNTIME.iterdir():
        if item.name != "README.txt":
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    if channel != STABLE:
        (RUNTIME / "channel").write_text(f"{channel}\n{build_version(channel, number)}\n", encoding="utf-8")
    with tarfile.open(download(triple)) as archive:
        archive.extractall(RUNTIME, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    python = RUNTIME / "python" / ("python.exe" if "windows" in triple else "bin/python3")
    run([python, "-m", "pip", "install", "--no-cache-dir", "--no-warn-script-location",
         "--disable-pip-version-check", wheel()])
    run([python, "-m", "harness", "--version"], env={**os.environ, "HARNESS_DATA": str(WORK / "probe-data"),
                                                     "HARNESS_HOME": str(WORK / "probe-home")})
    # The app package's shell/ is this desktop shell (with this runtime in it), not part of the package.
    skip = shutil.ignore_patterns("tests", "__pycache__", "node_modules", "*.pyc", ".pytest_cache", "shell", "target")
    for name in packages:
        source = ROOT / "packages" / name
        if (source / "package.toml").is_file():
            shutil.copytree(source, RUNTIME / "packages" / name, ignore=skip)
        else:
            print(f"warning: packages/{name} has no package.toml; not bundled", flush=True)


def public_key() -> str:
    key = os.environ.get("TAURI_UPDATER_PUBKEY", "").strip()
    file = Path(__file__).with_name("updater.pub")
    if not key and file.is_file():
        key = file.read_text(encoding="utf-8").strip()
    return key


def launcher(channel: str) -> str:
    """The .deb's terminal command of a channel (linux/harness is the stable one's), written
    under target/ and named in the configuration: where it is, from src-tauri."""
    called = names(channel)
    text = (SHELL / "src-tauri" / "linux" / "harness").read_text(encoding="utf-8")
    text = text.replace("/usr/bin/the-harness", f"/usr/bin/{called['binary']}").replace(
        "/usr/lib/The Harness/", f"/usr/lib/{called['product']}/")
    file = SHELL / "src-tauri" / "target" / "channel" / called["command"]
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8", newline="\n")
    return f"target/channel/{called['command']}"


def configuration(channel: str = STABLE, number: int | None = None) -> dict:
    """What this build puts over tauri.conf.json: the version and the updater's key, and for
    another channel than the stable one everything that makes it an app of its own (name,
    binary, identifier, icon, where its updates are, its terminal command in the .deb)."""
    signing = bool(os.environ.get("TAURI_SIGNING_PRIVATE_KEY"))
    config = {"version": build_version(channel, number), "plugins": {"updater": {"pubkey": public_key()}},
              "bundle": {"createUpdaterArtifacts": signing and bool(public_key())}}
    if channel == STABLE:
        return config
    called = names(channel)
    icons = f"icons/{channel}"
    config.update(productName=called["product"], mainBinaryName=called["binary"], identifier=called["identifier"])
    config["plugins"]["updater"]["endpoints"] = [f"{REPOSITORY}/releases/download/{channel}/latest.json"]
    config["bundle"].update(
        icon=[f"{icons}/{name}" for name in ("48x48.png", "64x64.png", "128x128.png", "256x256.png", "512x512.png",
                                              "icon.icns", "icon.ico")],
        windows={"nsis": {"installerIcon": f"{icons}/icon.ico", "uninstallerIcon": f"{icons}/icon.ico"}},
        # null takes the stable command out of this build's .deb (a JSON merge patch)
        linux={"deb": {"files": {"/usr/bin/harness": None, f"/usr/bin/{called['command']}": launcher(channel)}}})
    return config


def tauri(triple: str, bundles: str, channel: str = STABLE, number: int | None = None) -> Path:
    config = configuration(channel, number)
    if not config["bundle"]["createUpdaterArtifacts"]:
        if channel != STABLE:
            raise SystemExit(f"a {channel} build is always signed: give TAURI_SIGNING_PRIVATE_KEY and the updater's "
                             "public key (TAURI_UPDATER_PUBKEY or tools/installers/updater.pub)")
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


def name_mac_update(bundle: Path, triple: str) -> None:
    """Tauri names the .app's update bundle without its architecture (The Harness.app.tar.gz);
    latest.py finds each system's bundle by it, as it does the other systems' files: give it
    one (The Harness_aarch64.app.tar.gz), with its signature beside it."""
    arch = {"aarch64-apple-darwin": "aarch64", "x86_64-apple-darwin": "x64"}.get(triple)
    if not arch:
        return
    for path in sorted((bundle / "macos").glob("*.app.tar.gz")):
        named = path.with_name(f"{path.name[:-len('.app.tar.gz')]}_{arch}.app.tar.gz")
        path.rename(named)
        signature = path.with_name(path.name + ".sig")
        if signature.exists():
            signature.rename(named.with_name(named.name + ".sig"))


def main(argv=None) -> int:
    parsed = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parsed.add_argument("--target", default=target(), choices=sorted(ARCHIVES),
                        help="the system to build for: this one (a bundled Python runs during the build)")
    parsed.add_argument("--bundles", help=f"Tauri bundle kinds (default {BUNDLES})")
    parsed.add_argument("--packages", nargs="*", default=list(PACKAGES), help="package folders to bundle")
    parsed.add_argument("--stage-only", action="store_true", help="prepare the runtime, do not build")
    parsed.add_argument("--channel", default=STABLE, choices=CHANNELS,
                        help="stable (the release), or dev: an app of its own beside it (The Harness Dev)")
    parsed.add_argument("--build-number", type=int, help="the number of a dev build (the CI run's number)")
    given = parsed.parse_args(argv)
    if given.target != target():
        raise SystemExit(f"build {given.target} on that system: the bundled Python runs during the build")
    build_version(given.channel, given.build_number)  # refused before anything is staged
    stage(given.target, given.packages, given.channel, given.build_number)
    if given.stage_only:
        return 0
    platform_key = "linux" if sys.platform.startswith("linux") else sys.platform
    bundle = tauri(given.target, given.bundles or BUNDLES[platform_key], given.channel, given.build_number)
    name_mac_update(bundle, given.target)
    print(f"installers: {bundle}")
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and path.suffix in (".exe", ".msi", ".dmg", ".AppImage", ".deb", ".sig", ".gz"):
            print(f"  {path.relative_to(bundle)}  {path.stat().st_size // (1024 * 1024)} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
