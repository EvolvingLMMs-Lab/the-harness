"""What an agent learned, shared as a package and installed from one.

A library (runtime/learning/library.py) travels in a package folder:

    <name>/
      package.toml          [package] name, version, summary
      libraries/<name>/     the library: notes, skills and reactive entries with their tests,
                            attachments and revisions, index.json (evidence, history, uses)
      README.md             what it holds and the line that installs it

share() writes that package from a library and sends it where the user says: a GitHub
repository, another git remote, an archive in a folder (a website's files) or on a
computer reached by scp. Left behind: memory entries (what the agent saw on this computer)
unless asked for, entries waiting under candidates/, failed and forgotten entries; and in
what goes, the places of this computer (a run's folder, the home folder) become names.

Installing such a package (manager.py) copies each of its libraries to
$HARNESS_HOME/libraries/<name>, where a run uses it by name (--library NAME) and keeps
learning in it. A later install of the package replaces that copy only while it is as it
was installed: once a run learned in it, it is kept.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

from ..paths import home
from ..runtime.learning.library import ADMISSIONS, INDEX, SECTIONS, TESTS, Library
from . import archive
from .manifest import NAME, load, write
from .versions import Version


ORIGIN = "origin.json"
SHARED_SECTIONS = ("notes", "skills", "reactive")
README_MARK = "<!-- written by harness share -->"
_REVISION = re.compile(r"^[0-9a-f]{64}$")
_GITHUB = re.compile(r"^(?:github:|https://github\.com/)([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?(?:#(.*))?$")
_SCP = re.compile(r"^(?:scp://)?([^@/\\\s]+@[^:/\\\s]+)[:/](.*)$")
# Index fields that hold a place of this computer (a run's folder): shared as its last name.
PLACE_KEYS = ("run", "runs", "directory", "path", "cwd")


def libraries_root() -> Path:
    return home() / "libraries"


def find_library(text) -> Path:
    """A library by its folder, or by its name under $HARNESS_HOME/libraries."""
    path = Path(os.path.expanduser(str(text)))
    if path.is_dir():
        return path.resolve()
    named = libraries_root() / str(text)
    if NAME.match(str(text).replace("_", "-")) and named.is_dir():
        return named
    raise ValueError(f"no library {text}: a library's folder, or a name under {libraries_root()}")


def package_name(text: str) -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", str(text).lower()).strip("-")[:64]
    if not NAME.match(name):
        raise ValueError(f"{text!r} does not give a package name: give one with --name (lowercase letters, "
                         "digits and hyphens)")
    return name


# -- installing -------------------------------------------------------------------------


def working_copy(package, name: str, *, root: Path | None = None, log=print) -> dict:
    """Copy the library `name` of an installed `package` to root/<name> (default
    $HARNESS_HOME/libraries), unless runs learned in the copy that is there.
    {"name", "path", "status": copied | updated | unchanged | kept, "version"}."""
    source = Path(package.path) / "libraries" / name
    root = Path(root or libraries_root())
    target = root / name
    shipped = Library(source).version()
    row = {"name": name, "path": str(target), "version": shipped}
    status = "copied"
    if target.exists():
        origin = _read_json(target / ORIGIN)
        current = Library(target).version() if target.is_dir() else None
        if current == shipped:
            _write_origin(target, package, shipped)
            return {**row, "status": "unchanged"}
        if origin.get("package") != package.name or origin.get("version") != current:
            log(f"library {name}: kept the one at {target}, which runs learned in (or which is not from "
                f"{package.name}); remove it and install again to take {package.name} {package.version}'s")
            return {**row, "status": "kept", "version": current}
        status = "updated"
    root.mkdir(parents=True, exist_ok=True)
    staging, old = root / f".{name}.installing", root / f".{name}.replaced"
    for leftover in (staging, old):
        shutil.rmtree(leftover, ignore_errors=True)
    # (copyfile: the store's files are read-only, the copy is learned in.)
    shutil.copytree(source, staging, copy_function=shutil.copyfile,
                    ignore=shutil.ignore_patterns(ORIGIN, "__pycache__", ".library.lock"))
    _write_origin(staging, package, shipped)
    if target.exists():
        target.rename(old)
    staging.rename(target)
    shutil.rmtree(old, ignore_errors=True)
    return {**row, "status": status}


def _write_origin(folder: Path, package, version: str) -> None:
    (folder / ORIGIN).write_text(json.dumps({"package": package.name, "package_version": package.version,
                                             "version": version}, indent=1) + "\n", encoding="utf-8")


def origin(folder) -> dict:
    """The package a library under $HARNESS_HOME/libraries was installed from ({} for one
    learned here)."""
    return _read_json(Path(folder) / ORIGIN)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


# -- what goes ---------------------------------------------------------------------------


def _places() -> list[str]:
    """How this computer's home folder is written, longest first."""
    found = {str(Path.home()), str(Path.home()).replace("\\", "/")}
    return sorted((place for place in found if len(place) > 3), key=len, reverse=True)


def _scrub(value, places, key=None):
    """`value` without this computer's places: a place field (PLACE_KEYS) that is an
    absolute path becomes its last name, the home folder inside any text becomes ~."""
    if isinstance(value, dict):
        return {name: _scrub(item, places, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, places, key) for item in value]
    if isinstance(value, str):
        if key in PLACE_KEYS and (os.path.isabs(value) or re.match(r"^[A-Za-z]:[\\/]", value)):
            return re.split(r"[\\/]", value.rstrip("\\/"))[-1]
        for place in places:
            value = value.replace(place, "~")
        return value
    return value


def _revisions(value) -> set:
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "revision" and isinstance(item, str) and _REVISION.match(item):
                found.add(item)
            else:
                found |= _revisions(item)
    elif isinstance(value, list):
        for item in value:
            found |= _revisions(item)
    return found


def collect(library, *, with_memory: bool = False) -> dict:
    """What of `library` goes: {"files": {relative path: bytes}, "entries": [{"file",
    "evidence", "origin"}], "warnings": [...]}."""
    library = Path(library)
    index = Library(library).index()
    sections = SHARED_SECTIONS + (("memory",) if with_memory else ())
    places = _places()
    keys = set()
    for section in sections:
        suffix = SECTIONS[section]
        keys |= {f"{section}/{path.name}" for path in (library / section).glob(f"*{suffix}")}
        keys |= {key for key, row in index.items() if key.startswith(f"{section}/") and isinstance(row, dict)
                 and row.get("revision")}
    keys = {key for key in keys
            if not (isinstance(index.get(key), dict) and (index[key].get("forgotten") or index[key].get("removed")
                                                          or index[key].get("evidence") == "failed"))}
    files, warnings = {}, []

    def add(path: Path):
        relative = path.relative_to(library).as_posix()
        data = path.read_bytes()
        files[relative] = data
        if any(place.encode() in data for place in places):
            warnings.append(f"{relative} names a place on this computer")

    for key in sorted(keys):
        section, _, filename = key.partition("/")
        stem = Path(filename).stem
        if (library / key).is_file():
            add(library / key)
        if section in ("skills", "reactive") and (library / TESTS / f"{stem}.py").is_file():
            add(library / TESTS / f"{stem}.py")
        attachments = library / section / f"{stem}.files"
        if attachments.is_dir():
            for path in sorted(attachments.rglob("*")):
                if path.is_file():
                    add(path)
    rows = {}
    for key, row in index.items():
        if not isinstance(row, dict):
            rows[key] = row
        elif key in keys:
            memory = row.get("memory")
            rows[key] = {**_scrub({name: item for name, item in row.items() if name != "memory"}, places),
                         **({"memory": memory} if memory is not None else {})}
    for revision in sorted(_revisions(rows)):
        path = library / ".revisions" / revision
        if path.is_file():
            files[f".revisions/{revision}"] = path.read_bytes()
    files[INDEX] = (json.dumps(rows, indent=1, sort_keys=True) + "\n").encode("utf-8")
    if (library / "library.toml").is_file():
        add(library / "library.toml")
    if (library / ADMISSIONS).is_file():
        lines = []
        for line in (library / ADMISSIONS).read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("section") in sections:
                lines.append(json.dumps(_scrub(record, places)))
        if lines:
            files[ADMISSIONS] = ("\n".join(lines) + "\n").encode("utf-8")
    entries = [{"file": key, "evidence": (index.get(key) or {}).get("evidence", "validated"),
                "origin": (index.get(key) or {}).get("origin", "hand")} for key in sorted(keys)]
    return {"files": files, "entries": entries, "warnings": warnings}


def build(library, folder: Path, *, name: str, version: str, summary: str = "", with_memory: bool = False,
          install: str = "") -> dict:
    """Write the package of `library` into `folder` (its libraries/<name> replaced, a README
    written unless the folder has one of its own). {"version": the library's version,
    "entries", "warnings"}."""
    folder = Path(folder)
    found = collect(library, with_memory=with_memory)
    target = folder / "libraries" / name
    shutil.rmtree(target, ignore_errors=True)
    for relative, data in found["files"].items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    counts = {section: sum(1 for entry in found["entries"] if entry["file"].startswith(f"{section}/"))
              for section in SECTIONS}
    summary = summary or ("What an agent learned: " + ", ".join(f"{count} {section}" for section, count in counts.items()
                                                                if count) if any(counts.values()) else "An empty library")
    write(folder, name=name, version=version, summary=summary)
    learned = Library(target).version()
    readme = folder / "README.md"
    if not readme.is_file() or README_MARK in readme.read_text(encoding="utf-8", errors="replace"):
        readme.write_text(_readme(name, version, summary, learned, found["entries"], install), encoding="utf-8")
    load(folder)
    return {"version": learned, "entries": found["entries"], "warnings": found["warnings"], "summary": summary}


def _readme(name, version, summary, learned, entries, install) -> str:
    rows = "\n".join(f"| `{entry['file']}` | {entry['evidence']} | {entry['origin']} |" for entry in entries)
    lines = [README_MARK, f"# {name}", "", summary + ".", "",
             "A library learned by an agent of [The Harness](https://harness.lmms-lab.com): what it learned, "
             "with the evidence each entry was admitted on.", "",
             "```sh", install or f"harness install <where this folder is>", f'harness run "your task" --library {name}',
             "```", "",
             f"Add `--learn-while-working` to keep learning in your copy ($HARNESS_HOME/libraries/{name}).", "",
             *([("Its tree of reflexes comes into a run not started: the model starts it with `start_reflex()` "
                 "when the agent is where the tree is for."), ""]
               if any(entry["file"].startswith("reactive/") for entry in entries) else []),
             f"Package {version}, library version `{learned[:12]}`.", ""]
    if entries:
        lines += ["| Entry | Evidence | Origin |", "|---|---|---|", rows, ""]
    return "\n".join(lines)


# -- sending -----------------------------------------------------------------------------


def destination(text: str) -> dict:
    """Where `harness share` sends a package: {"kind": github | git | scp | file, ...}."""
    text = str(text).strip()
    github = _GITHUB.match(text)
    if github:
        owner, repository, subdir = github.group(1), github.group(2), (github.group(3) or "").strip("/")
        return {"kind": "github", "owner": owner, "repository": repository, "subdir": subdir,
                "url": f"https://github.com/{owner}/{repository}.git"}
    if text.startswith(("git:", "git+")):
        url, _, subdir = text[4:].partition("#")
        return {"kind": "git", "url": url, "subdir": subdir.strip("/")}
    scp = _SCP.match(text)
    if scp and not re.match(r"^[A-Za-z]:[\\/]", text):
        return {"kind": "scp", "host": scp.group(1), "path": scp.group(2)}
    if re.match(r"^[a-z]+://", text):
        raise ValueError(f"{text}: share to github:OWNER/REPO, git:URL (any git remote), USER@HOST:FOLDER (scp) "
                         "or a folder or .tar.gz file on this computer")
    return {"kind": "file", "path": text}


def _archive_name(place: str, name: str) -> str:
    if not place:
        return f"{name}.tar.gz"
    return place if place.lower().endswith((".tar.gz", ".tgz")) else place.rstrip("/") + f"/{name}.tar.gz"


def _bump(previous: str | None) -> str:
    if not previous:
        return "0.1.0"
    version = Version.parse(previous)
    return f"{version.major}.{version.minor}.{version.patch + 1}"


def _previous(folder: Path, name: str) -> str | None:
    try:
        package = load(folder)
    except ValueError:
        return None
    return package.version if package.name == name else None


def _run(command, cwd=None, *, what=None):
    result = subprocess.run(command, cwd=cwd, capture_output=True, encoding="utf-8", errors="replace", timeout=600)
    if result.returncode:
        raise ValueError(f"{what or Path(command[0]).stem} failed: {(result.stderr or result.stdout).strip()[-400:]}")
    return result.stdout.strip()


def share(library, where: str, *, name: str | None = None, version: str | None = None, summary: str = "",
          with_memory: bool = False, private: bool = False, url: str = "", confirm=None, log=print) -> dict:
    """Send `library` (a folder, or a name under $HARNESS_HOME/libraries) as a package to
    `where` (destination()). `confirm(preview) -> bool` is asked before anything is sent:
    without it, or when it says no, nothing is ({"needs_consent": True, ...}). `url`: the
    web address of the folder an archive goes to, for the line that installs it."""
    library = find_library(library)
    name = package_name(name or library.name)
    if version is not None:
        version = str(Version.parse(version))
    target = destination(where)
    git = shutil.which("git")
    with tempfile.TemporaryDirectory(prefix="harness-share-") as temporary:
        temporary = Path(temporary)
        create = False
        if target["kind"] in ("github", "git"):
            if git is None:
                raise ValueError("sharing to a git repository needs git on this computer")
            clone = temporary / "repository"
            gh = shutil.which("gh") if target["kind"] == "github" else None
            if gh is not None:
                seen = subprocess.run([gh, "repo", "view", f"{target['owner']}/{target['repository']}"],
                                      capture_output=True, encoding="utf-8", errors="replace", timeout=120)
                create = seen.returncode != 0 and "could not resolve to a repository" in (seen.stderr or "").lower()
            if create:
                clone.mkdir()
            else:
                try:
                    _run([git, "clone", "--depth", "1", target["url"], str(clone)], what="git clone")
                except ValueError as error:
                    hint = (" Create the repository first, or install the GitHub CLI (gh) and log in to have it "
                            "created." if target["kind"] == "github" and gh is None else "")
                    raise ValueError(f"{error}.{hint}") from None
            folder = clone / target["subdir"] if target["subdir"] else clone
            folder.mkdir(parents=True, exist_ok=True)
            if (folder / "package.toml").is_file() and _previous(folder, name) is None:
                raise ValueError(f"{where} holds another package: share into a folder of it (#FOLDER), or give "
                                 "that package's name with --name")
            version = version or _bump(_previous(folder, name))
            if target["kind"] == "github" and not target["subdir"]:
                install = f"harness install https://github.com/{target['owner']}/{target['repository']}"
            elif target["kind"] == "github":
                install = f"harness install git:github.com/{target['owner']}/{target['repository']}#{target['subdir']}"
            else:
                install = f"harness install git:{target['url']}" + (f"#{target['subdir']}" if target["subdir"] else "")
        else:
            folder = temporary / name
            place = _archive_name(target["path"], name)
            previous = None
            if target["kind"] == "file" and Path(place).is_file():
                try:
                    previous = _previous(archive.unpack(Path(place), temporary / "previous"), name)
                except (ValueError, OSError, tarfile.TarError):
                    previous = None
            version = version or _bump(previous)
            web = f"{url.rstrip('/')}/{name}.tar.gz" if url else ""
            if target["kind"] == "file":
                install = f"harness install {web or Path(place).resolve()}"
            else:
                install = f"harness install {web or f'https://<your site>/<where {place} is served>'}"
        built = build(library, folder, name=name, version=version, summary=summary, with_memory=with_memory,
                      install=install)
        preview = {"library": str(library), "name": name, "version": version, "library_version": built["version"],
                   "destination": where, "entries": built["entries"], "warnings": built["warnings"],
                   "memory": with_memory, "install": install, **({"creates": "private" if private else "public"}
                                                                if create else {})}
        if confirm is None or not confirm(preview):
            return {**preview, "needs_consent": True}
        if target["kind"] in ("github", "git"):
            preview["sent"] = _push(git, clone, folder, target, name, version, built["summary"], create, private, log)
        else:
            packed = temporary / f"{name}.tar.gz"
            archive.build(folder, packed, prefix=name)
            if target["kind"] == "file":
                Path(place).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(packed, place)
                preview["sent"] = str(Path(place).resolve())
            else:
                scp = shutil.which("scp")
                if scp is None:
                    raise ValueError("sending to another computer needs scp on this one")
                remote = f"{target['host']}:{place}"
                _run([scp, "-q", str(packed), remote], what="scp")
                preview["sent"] = remote
        log(f"{name} {version}: sent to {preview['sent']}")
        return preview


def _push(git, clone, folder, target, name, version, summary, create, private, log) -> str:
    if create:
        gh = shutil.which("gh")
        log(f"creating the {'private' if private else 'public'} repository {target['owner']}/{target['repository']}")
        _run([gh, "repo", "create", f"{target['owner']}/{target['repository']}",
              "--private" if private else "--public", "--description", summary[:300]], what="gh repo create")
        _run([git, "init", "-q", "-b", "main"], clone, what="git init")
        _run([git, "remote", "add", "origin", target["url"]], clone, what="git remote")
    _run([git, "add", "-A", "--", str(folder.relative_to(clone)) if folder != clone else "."], clone, what="git add")
    if not _run([git, "status", "--porcelain"], clone):
        log(f"{name}: the repository already has this version of the library")
        return target["url"]
    _run([git, "commit", "-q", "-m", f"Share {name} {version}"], clone, what="git commit")
    _run([git, "push", "-q", "origin", "HEAD"], clone, what="git push")
    return target["url"]
