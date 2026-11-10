"""Release a package version to the registry, after a release PR raised its version and
CHANGELOG from the change notes (tools/changes.py):

    python tools/release.py prepare [--dry-run]       # the release PR's versions and changelogs
    python tools/release.py check-pr --base origin/main  # a PR changes no version unless a release
    python tools/release.py workspace --registry ../registry [--commit]
    python tools/release.py core --registry ../registry [--tests] [--commit]

`core` releases a pre-release build of the harness itself instead (the current source version, for
testers without access to the repository; PyPI has the releases): it builds the wheel,
checks it with twine, installs it into a new virtual environment with a clean HOME, runs
the harness from there (import, harness doctor, harness install of a package from the
registry; with --tests also the core's tests with that interpreter) and adds the wheel
under core/ (pip install <registry>/core/<wheel>).

For a package:

1. checks it (tools/check.py) and that this harness is in its `harness` range;
2. refuses a version the registry has already (published versions never change);
3. builds its file and installs it from a copy of the registry with a clean HOME (an
   empty HARNESS_HOME and data directory), then runs its tests/ there;
4. adds it to the registry directory (a worktree of this repository's `registry` branch,
   which only grows): the file,
   README.md, CHANGELOG.md and its entry in index.json; with --commit, commits that;
5. says how to put the registry on the site (docs: deno task registry, then deploy).

Exit status 0 when it was published.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from check import PACKAGES, check, packages_in  # noqa: E402


def _run(command, env, cwd=None, log=print) -> None:
    log("+ " + " ".join(str(part) for part in command))
    result = subprocess.run([str(part) for part in command], env=env, cwd=cwd, capture_output=True,
                            encoding="utf-8", errors="replace")
    if result.stdout.strip():
        log(result.stdout.rstrip())
    if result.returncode:
        raise RuntimeError(f"{command[2] if len(command) > 2 else command[0]} failed:\n{result.stderr.rstrip()}")


def clean_install(folder: Path, registry: Path, *, test: bool = True, log=print) -> Path:
    """Install the package from a copy of `registry` with it added, in a clean HOME, and run
    its tests; returns where it was installed (inside a temporary directory that is
    removed afterwards, so only the success matters)."""
    from harness.packages.manifest import load
    from harness.packages.registry import publish

    package = load(folder)
    with tempfile.TemporaryDirectory(prefix="harness-release-") as temporary:
        temporary = Path(temporary)
        copy = temporary / "registry"
        if (registry / "index.json").is_file():
            shutil.copytree(registry, copy, ignore=shutil.ignore_patterns(".git"))
        else:
            copy.mkdir()
        publish(copy, folder, log=lambda message: None)
        env = {**os.environ, "HARNESS_HOME": str(temporary / "home"), "HARNESS_DATA": str(temporary / "data"),
               "HARNESS_REGISTRY": str(copy), "PYTHONUTF8": "1"}
        env.pop("HARNESS_PACKAGE_ROOTS", None)
        _run([sys.executable, "-m", "harness", "install", f"{package.name}@=={package.version}"], env, log=log)
        listed = subprocess.run([sys.executable, "-m", "harness", "list", "--json"], env=env, capture_output=True,
                                encoding="utf-8", check=True).stdout
        row = next(row for row in json.loads(listed) if row["name"] == package.name)
        if row.get("problem"):
            raise RuntimeError(f"{package.name} installed, but: {row['problem']}")
        installed = Path(row["path"])
        if test and (installed / "tests").is_dir():
            env["PYTHONPATH"] = os.pathsep.join([str(installed), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            _run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], env, cwd=installed, log=log)
        return installed


def release_core(registry: Path, *, tests: bool = False, log=print) -> dict:
    """Build, check, install cleanly and publish the harness's own wheel (see the module's
    docstring); returns what publish_core wrote."""
    from harness.packages.registry import publish_core

    root = HERE.parent
    with tempfile.TemporaryDirectory(prefix="harness-core-") as temporary:
        temporary = Path(temporary)
        _run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--quiet", "-w", temporary / "dist", root],
             dict(os.environ), log=log)
        wheel = next((temporary / "dist").glob("the_harness-*.whl"))
        _run([sys.executable, "-m", "twine", "check", "--strict", wheel], dict(os.environ), log=log)
        _run([sys.executable, "-m", "venv", temporary / "venv"], dict(os.environ), log=log)
        bindir = temporary / "venv" / ("Scripts" if os.name == "nt" else "bin")
        python = bindir / ("python.exe" if os.name == "nt" else "python")
        env = {key: value for key, value in os.environ.items() if not key.startswith(("HARNESS_", "PYTHONPATH"))}
        env.update({"HARNESS_HOME": str(temporary / "home"), "HARNESS_DATA": str(temporary / "data"),
                    "PYTHONUTF8": "1"})
        _run([python, "-m", "pip", "install", "--quiet", wheel], env, log=log)
        _run([python, "-c", "import harness, harness.sdk, harness.packages; print(harness.__version__)"], env,
             cwd=temporary, log=log)
        # doctor exits 1 while no model is set up; it must run.
        doctor = subprocess.run([python, "-m", "harness", "doctor", "--json"], env=env, cwd=temporary,
                                capture_output=True, text=True)
        if doctor.returncode not in (0, 1) or '"packages"' not in doctor.stdout:
            raise RuntimeError(f"harness doctor failed:\n{doctor.stderr[-2000:]}")
        if (registry / "index.json").is_file():
            listed = json.loads((registry / "index.json").read_text(encoding="utf-8"))["packages"]
            if listed:
                name = sorted(listed)[0]
                _run([python, "-m", "harness", "install", name], {**env, "HARNESS_REGISTRY": str(registry)},
                     cwd=temporary, log=log)
        if tests:
            _run([python, "-m", "unittest", "discover", "-s", "tests"], {**env, "PYTHONPATH": str(root / "src")},
                 cwd=root, log=log)
        registry.mkdir(parents=True, exist_ok=True)
        return publish_core(registry, wheel, log=log)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["prepare"], ["check-pr"]):
        # Versions and changelogs from the change notes (tools/changes.py).
        from changes import main as changes
        return changes(argv)
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("name", help="the package (its folder under packages/), or core: the harness's own wheel")
    parser.add_argument("--root", type=Path, default=PACKAGES)
    parser.add_argument("--registry", type=Path, default=Path(os.environ.get("HARNESS_REGISTRY_DIR", "../registry")),
                        help="a worktree of the registry branch (default $HARNESS_REGISTRY_DIR, else ../registry)")
    parser.add_argument("--no-test", action="store_true", help="install it, but do not run its tests")
    parser.add_argument("--commit", action="store_true", help="commit the registry checkout afterwards")
    parser.add_argument("--tests", action="store_true", help="core: also run the core's tests with the wheel's "
                                                             "interpreter")
    args = parser.parse_args(argv)
    # Absolute: the core's checks run the harness from a temporary directory.
    args.registry = args.registry.resolve()
    if args.name == "core":
        try:
            row = release_core(args.registry, tests=args.tests)
        except (RuntimeError, ValueError, StopIteration, subprocess.CalledProcessError) as error:
            print(f"the harness did not release: {error}", file=sys.stderr)
            return 1
        if args.commit:
            subprocess.run(["git", "add", "-A"], cwd=args.registry, check=True)
            subprocess.run(["git", "commit", "-m", f"Publish the harness {row['version']}"], cwd=args.registry,
                           check=True)
        print(f"published the harness {row['version']}: {row['file']} ({row['sha256'][:12]}); testers: "
              f"pip install https://harness.lmms-lab.com/registry/{row['file']}")
        return 0

    from harness import __version__
    from harness.packages.manifest import load
    from harness.packages.registry import harness_fits, publish

    everything = packages_in(args.root)
    if args.name not in everything:
        print(f"no package {args.name} under {args.root}", file=sys.stderr)
        return 1
    folder = everything[args.name]
    problems = check(folder, everything)
    if problems:
        print("\n".join([f"{args.name} does not check:", *problems]), file=sys.stderr)
        return 1
    package = load(folder)
    if not harness_fits({"harness": package.harness}, __version__):
        print(f"{package.name} {package.version} is for harness {package.harness}; this is {__version__}",
              file=sys.stderr)
        return 1
    index = args.registry / "index.json"
    published = json.loads(index.read_text(encoding="utf-8"))["packages"] if index.is_file() else {}
    if package.version in (published.get(package.name) or {}).get("versions", {}):
        print(f"{package.name} {package.version} is published already: raise its version (and CHANGELOG.md)",
              file=sys.stderr)
        return 1
    try:
        clean_install(folder, args.registry, test=not args.no_test)
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"{package.name} {package.version} did not install cleanly: {error}", file=sys.stderr)
        return 1
    args.registry.mkdir(parents=True, exist_ok=True)
    row = publish(args.registry, folder)
    if args.commit:
        subprocess.run(["git", "add", "-A"], cwd=args.registry, check=True)
        subprocess.run(["git", "commit", "-m", f"Publish {package.name} {package.version}"], cwd=args.registry,
                       check=True)
    print(f"published {package.name} {package.version}: {row['file']} ({row['sha256'][:12]})")
    print("put it on the site: cd docs && deno task build && "
          f"deno task registry {args.registry.resolve()} && deno task deploy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
