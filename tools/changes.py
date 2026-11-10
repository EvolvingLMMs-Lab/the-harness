"""Change notes and versions.

A pull request changes no version. A change people would notice comes with a change note,
`changes/<name>.md` (`private/changes/` for private packages):

    ---
    core: minor
    computer: patch
    ---
    What changed, in a sentence or two, for the people who use it.
    <!-- zh -->
    可选：中文说明。

The header names what changed (`core` or a package under packages/) and how much
(`patch` a fix, `minor` a new capability or changed behaviour; before 1.0 a breaking change is
`minor` too). An empty header (`---` twice) says the change needs no note (tests, refactors).

A release gathers the notes:

    python tools/release.py prepare [--dry-run]

raises each named component's version by its largest level, adds the notes to the changelogs
(the Chinese changelog marks notes without Chinese text as untranslated) and removes them.
Its pull request is titled "Release X.Y.Z" and is the only kind that changes a version or a
changelog:

    python tools/release.py check-pr --base origin/main [--title "..."]

checks that for a pull request (the title defaults to $PR_TITLE).
"""

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parent.parent
LEVELS = ("patch", "minor", "major")
CORE_VERSION = "src/harness/__init__.py"
CORE_LOG = "docs/src/content/docs/changelog.md"
CORE_LOG_ZH = "docs/src/content/docs/zh-cn/changelog.md"
NOTES, PRIVATE_NOTES = "changes", "private/changes"
UNTRANSLATED = "<!-- untranslated -->"
ZH = "<!-- zh -->"
RELEASE_TITLE = re.compile(r"(^|:\s*)Release\b")


@dataclass
class Note:
    path: str
    levels: dict
    text: str
    zh: str
    private: bool


def parse(path: str, content: str) -> Note:
    """A change note from its text; ValueError when it is not one."""
    lines = content.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---" or "---" not in [line.strip() for line in lines[1:]]:
        raise ValueError(f"{path}: starts with a header between two --- lines")
    end = 1 + [line.strip() for line in lines[1:]].index("---")
    levels = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        name, colon, level = line.partition(":")
        if not colon:
            raise ValueError(f"{path}: header lines are `name: level`, not {line.strip()!r}")
        levels[name.strip().strip("\"'")] = level.strip().strip("\"'")
    body = "\n".join(lines[end + 1:])
    text, _, zh = body.partition(ZH)
    return Note(path, levels, " ".join(text.split()), " ".join(zh.split()),
                path.replace("\\", "/").startswith(PRIVATE_NOTES + "/"))


def components(root: Path) -> tuple[dict, dict]:
    """The public and the private packages: name -> folder."""
    def under(folder):
        return {path.name: path for path in sorted(folder.iterdir()) if (path / "package.toml").is_file()} \
            if folder.is_dir() else {}
    return under(root / "packages"), under(root / "private" / "packages")


def core_version(text: str) -> str:
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


def package_version(text: str) -> tuple[str, str]:
    package = tomllib.loads(text).get("package", {})
    return package.get("version", ""), package.get("harness", "")


def current(root: Path, name: str, public: dict, private: dict) -> str:
    if name == "core":
        return core_version((root / CORE_VERSION).read_text(encoding="utf-8"))
    folder = public.get(name) or private[name]
    return package_version((folder / "package.toml").read_text(encoding="utf-8"))[0]


def problems_of(note: Note, root: Path, public: dict, private: dict) -> list[str]:
    problems = []
    if note.levels and not note.text:
        problems.append(f"{note.path}: says what changed below its header")
    for name, level in note.levels.items():
        if level not in LEVELS:
            problems.append(f"{note.path}: {name}'s level is patch or minor, not {level!r}")
        if note.private:
            if name not in private:
                problems.append(f"{note.path}: a note in {PRIVATE_NOTES}/ names a private package, not {name!r}")
                continue
        elif name in private:
            problems.append(f"{note.path}: {name} is private; its note goes in {PRIVATE_NOTES}/")
            continue
        elif name != "core" and name not in public:
            problems.append(f"{note.path}: no component {name!r} (core or a folder under packages/)")
            continue
        if level == "major" and current(root, name, public, private).startswith("0."):
            problems.append(f"{note.path}: before 1.0 a breaking change of {name} is `minor`")
    return problems


def notes_in(root: Path) -> list[Note]:
    found = []
    for folder in (NOTES, PRIVATE_NOTES):
        for path in sorted((root / folder).glob("*.md")) if (root / folder).is_dir() else []:
            if path.name != "README.md":
                found.append(parse(f"{folder}/{path.name}", path.read_text(encoding="utf-8")))
    return found


def raised(version: str, level: str) -> str:
    major, minor, patch = (int(part) for part in re.match(r"(\d+)\.(\d+)\.(\d+)", version).groups())
    return {"major": f"{major + 1}.0.0", "minor": f"{major}.{minor + 1}.0", "patch": f"{major}.{minor}.{patch + 1}"}[level]


def _write(path: Path, text: str, like: bytes) -> None:
    """Writes `text` (with \\n) with the line ends `like` has."""
    path.write_bytes(text.replace("\n", "\r\n" if b"\r\n" in like else "\n").encode("utf-8"))


def add_section(path: Path, version: str, entries: list[str], title: str = "") -> None:
    """Puts `## version` with its entries above the newest section of the changelog at `path`."""
    raw = path.read_bytes() if path.is_file() else b""
    text = raw.decode("utf-8").replace("\r\n", "\n") if raw else f"{title}\n\n"
    section = f"## {version}\n\n" + "".join(f"- {entry}\n" for entry in entries) + "\n"
    match = re.search(r"^## ", text, re.M)
    text = text[:match.start()] + section + text[match.start():] if match else text.rstrip("\n") + "\n\n" + section
    _write(path, text.rstrip("\n") + "\n", raw)


def prepare(root: Path = ROOT, *, dry_run: bool = False, log=print) -> dict:
    """The release's versions, {component: (old, new)}; unless dry_run, written with the
    changelogs, and the notes removed. ValueError when a note does not check."""
    public, private = components(root)
    notes = notes_in(root)
    problems = [problem for note in notes for problem in problems_of(note, root, public, private)]
    if problems:
        raise ValueError("\n".join(problems))
    levels, entries = {}, {}
    for note in notes:
        for name, level in note.levels.items():
            levels[name] = max(levels.get(name, level), level, key=LEVELS.index)
            entries.setdefault(name, []).append(note)
    versions = {name: (current(root, name, public, private), "") for name in sorted(levels, key=lambda n: (n != "core", n))}
    versions = {name: (old, raised(old, levels[name])) for name, (old, _) in versions.items()}
    for name, (old, new) in versions.items():
        log(f"{name}: {old} -> {new} ({len(entries[name])} note{'s' if len(entries[name]) != 1 else ''})")
    untranslated = [note.path for note in entries.get("core", []) if not note.zh]
    if untranslated:
        log(f"translate in {CORE_LOG_ZH} (marked {UNTRANSLATED}): " + ", ".join(untranslated))
    if dry_run:
        return versions
    for name, (old, new) in versions.items():
        if name == "core":
            path = root / CORE_VERSION
            raw = path.read_bytes()
            _write(path, re.sub(r'^__version__ = "[^"]+"', f'__version__ = "{new}"',
                                raw.decode("utf-8").replace("\r\n", "\n"), count=1, flags=re.M), raw)
            add_section(root / CORE_LOG, new, [note.text for note in entries[name]])
            add_section(root / CORE_LOG_ZH, new, [note.zh or f"{note.text} {UNTRANSLATED}" for note in entries[name]])
        else:
            folder = public.get(name) or private[name]
            path = folder / "package.toml"
            raw = path.read_bytes()
            _write(path, re.sub(r'^version = "[^"]+"', f'version = "{new}"',
                                raw.decode("utf-8").replace("\r\n", "\n"), count=1, flags=re.M), raw)
            add_section(folder / "CHANGELOG.md", new, [note.text for note in entries[name]], "# Changelog")
    for note in notes:
        (root / note.path).unlink()
    return versions


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, encoding="utf-8", check=True).stdout


def _at(root: Path, base: str, path: str) -> str | None:
    result = subprocess.run(["git", "show", f"{base}:./{path}"], cwd=root, capture_output=True, encoding="utf-8")
    return result.stdout if result.returncode == 0 else None


CHANGELOG = re.compile(r"^(docs/src/content/docs/(zh-cn/)?changelog\.md|(private/)?packages/[^/]+/CHANGELOG\.md)$")
CODE = re.compile(r"^(src/|(private/)?packages/[^/]+/)")


def is_code(path: str) -> bool:
    return bool(CODE.match(path)) and "/tests/" not in f"/{path}" and not path.endswith(".md")


def check_pr(base: str, title: str = "", root: Path = ROOT) -> list[str]:
    """What is wrong with the changes from `base` (merge base) to HEAD under `root`."""
    rows = [line.split("\t") for line in _git(root, "diff", "--relative", "--no-renames", "--name-status",
                                                 f"{base}...HEAD").splitlines() if line]
    changed = {path: status for status, path in rows}
    public, private = components(root)
    notes = [path for path, status in changed.items() if status != "D" and path.endswith(".md")
             and path.rsplit("/", 1)[0] in (NOTES, PRIVATE_NOTES) and not path.endswith("/README.md")]
    problems = []
    for path in notes:
        try:
            problems += problems_of(parse(path, (root / path).read_text(encoding="utf-8")), root, public, private)
        except ValueError as error:
            problems.append(str(error))
    if RELEASE_TITLE.search(title or ""):
        zh = root / CORE_LOG_ZH
        if zh.is_file() and UNTRANSLATED in zh.read_text(encoding="utf-8"):
            problems.append(f"{CORE_LOG_ZH}: translate the notes marked {UNTRANSLATED} before the release")
        return problems
    release = "a release pull request (titled \"Release X.Y.Z\", from `python tools/release.py prepare`)"
    for path, status in sorted(changed.items()):
        if status == "M" and CHANGELOG.match(path):
            problems.append(f"{path}: changelogs change only in {release}; add a change note instead")
        if status != "M" or not (path == CORE_VERSION or path.endswith("/package.toml")):
            continue
        before, after = _at(root, base, path), (root / path).read_text(encoding="utf-8")
        if before is None:
            continue
        if path == CORE_VERSION:
            if core_version(before) != core_version(after):
                problems.append(f"{path}: versions change only in {release}; add a change note instead")
        elif package_version(before) != package_version(after):
            problems.append(f"{path}: its version and harness range change only in {release}; "
                            "add a change note instead")
    code = [path for path in sorted(changed) if is_code(path)]
    if code and not notes:
        problems.append(f"{', '.join(code[:3])}{' and more' if len(code) > 3 else ''}: a code change comes with a "
                        f"change note in {NOTES}/ (see {NOTES}/README.md); one with an empty header when "
                        "people would not notice it")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="release.py", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="raise the versions and write the changelogs from the notes")
    prepare_parser.add_argument("--dry-run", action="store_true", help="only say what it would do")
    check_parser = commands.add_parser("check-pr", help="check a pull request's notes and versions")
    check_parser.add_argument("--base", required=True, help="the branch it merges into, e.g. origin/main")
    check_parser.add_argument("--title", default=os.environ.get("PR_TITLE", ""),
                              help="its title (default $PR_TITLE)")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        try:
            versions = prepare(dry_run=args.dry_run)
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        if not versions:
            print("no change notes: nothing to release")
        elif not args.dry_run:
            print("next: review the changelogs, open a pull request titled "
                  f"\"Release {versions.get('core', ('', ''))[1] or ', '.join(f'{n} {v[1]}' for n, v in versions.items())}\"")
        return 0
    problems = check_pr(args.base, args.title)
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print("change notes and versions: ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
