"""latest.json for the desktop shell's updater (a static file on GitHub Releases): for each
system the update bundle the build signed and its signature.

    python tools/installers/latest.py VERSION FOLDER --base https://github.com/OWNER/REPO/releases/download/vX.Y.Z

FOLDER holds the release's files (the .sig files beside their bundles). Windows updates with
the NSIS installer (an .msi install with the .msi), macOS with the .app.tar.gz, Linux with the
AppImage (a .deb install with the .deb); a bundle without its signature is left out (the
updater installs only bundles signed with the updater key, and refuses one whose signature
does not match).
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

# (latest.json's platform key, how the bundle's file name ends). The updater looks for
# {os}-{arch}-{installer} first, then {os}-{arch}: an .msi install updates with the .msi and a
# .deb install with the .deb; the plain keys are the NSIS installer and the AppImage.
BUNDLES = (("windows-x86_64", "_x64-setup.exe"), ("windows-x86_64-nsis", "_x64-setup.exe"),
           ("windows-x86_64-msi", "_x64_en-US.msi"), ("darwin-aarch64", "_aarch64.app.tar.gz"),
           ("darwin-x86_64", "_x64.app.tar.gz"), ("linux-x86_64", "_amd64.AppImage"),
           ("linux-x86_64-appimage", "_amd64.AppImage"), ("linux-x86_64-deb", "_amd64.deb"),
           ("linux-aarch64", "_aarch64.AppImage"), ("linux-aarch64-appimage", "_aarch64.AppImage"),
           ("linux-aarch64-deb", "_arm64.deb"))


def latest(version: str, folder: Path, base: str) -> dict:
    platforms = {}
    files = {path.name: path for path in folder.rglob("*") if path.is_file()}
    for key, ending in BUNDLES:
        for name, path in files.items():
            if name.endswith(ending) and f"{name}.sig" in files:
                platforms[key] = {"signature": files[f"{name}.sig"].read_text(encoding="utf-8").strip(),
                                  "url": f"{base.rstrip('/')}/{name.replace(' ', '.')}"}
                break
    return {"version": version, "notes": f"The Harness {version}",
            "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "platforms": platforms}


def main(argv=None) -> int:
    parsed = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parsed.add_argument("version")
    parsed.add_argument("folder", type=Path)
    parsed.add_argument("--base", required=True, help="the release's download address")
    parsed.add_argument("--out", type=Path, default=Path("latest.json"))
    given = parsed.parse_args(argv)
    found = latest(given.version, given.folder, given.base)
    if not found["platforms"]:
        print("no signed update bundles: latest.json not written", file=sys.stderr)
        return 0
    given.out.write_text(json.dumps(found, indent=2) + "\n", encoding="utf-8")
    print(f"{given.out}: {', '.join(found['platforms'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
