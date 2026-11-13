"""Instruction files (AGENTS.md): what the user and a project tell every conversation, as Codex
and Claude Code read them.

    user       $HARNESS_DATA/AGENTS.override.md, else $HARNESS_DATA/AGENTS.md (~/.harness/)
    project    from the project root down to the conversation's folder, one file per
               directory: the first non-empty of instructions.files (default
               AGENTS.override.md, AGENTS.md, CLAUDE.md), then that directory's
               CLAUDE.local.md. The root is the nearest ancestor of the folder holding one of
               instructions.root_markers (default .git); with none, the folder alone. The walk
               never goes above the root.
    below      a directory under the folder with its own file is read when a program first
               touches a file in it (nested()), once per conversation.

`@path` in a file imports another (relative to the importing file, ~ for home, at most four
hops, not inside code spans or fenced blocks), when it lies inside the project root or the
data directory; an import elsewhere is left as text with a warning. Block-level HTML
comments are left out.

The files read at the start share instructions.max_bytes (default 32768, as Codex's
project_doc_max_bytes; the user file has its own). A file a program's touch brings in is cut
at 40,000 characters (Claude Code). A file over 4 MiB is skipped. Where something is cut the
model is told how to read the rest, and the user is warned.

The model gets them in its opening message (block()), as Codex gives them; compaction keeps
that message (runtime/task/run.py). Settings: instructions.load (all, user, off), .files,
.root_markers, .max_bytes, .exclude (settings.py); harness run --bare loads none.
"""

from dataclasses import dataclass, field
import fnmatch
import os
from pathlib import Path
import re

from .paths import data

USER_FILES = ("AGENTS.override.md", "AGENTS.md")
DEFAULTS = {"load": "all", "files": "AGENTS.override.md, AGENTS.md, CLAUDE.md", "root_markers": ".git",
            "max_bytes": 32768, "exclude": ""}
LOCAL_FILE = "CLAUDE.local.md"
NESTED_CHARS = 40_000
SKIP_BYTES = 4 * 1024 * 1024
IMPORT_DEPTH = 4
SEPARATOR = "\n\n--- project-doc ---\n\n"

_FENCE = re.compile(r"^\s*(```|~~~)")
_IMPORT = re.compile(r"(?<![\w`@])@((?:\\ |[^\s`])+)")
_COMMENT = re.compile(r"^[ \t]*<!--.*?-->[ \t]*\n?", re.S | re.M)


@dataclass
class File:
    path: Path
    label: str            # how the model and the user see it: ~/..., or relative to the root
    text: str
    size: int             # bytes on disk
    cut: bool = False


@dataclass
class Loaded:
    folder: Path | None = None
    root: Path | None = None
    files: list[File] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (label, why)
    warnings: list[str] = field(default_factory=list)

    def record(self) -> dict:
        """What the trace keeps of it (the instructions record)."""
        return {"folder": str(self.folder) if self.folder else None, "root": str(self.root) if self.root else None,
                "files": [{"path": str(item.path), "label": item.label, "bytes": len(item.text.encode("utf-8")),
                           "size": item.size, **({"cut": True} if item.cut else {})} for item in self.files],
                **({"skipped": [{"label": label, "why": why} for label, why in self.skipped]} if self.skipped else {}),
                **({"warnings": list(self.warnings)} if self.warnings else {})}


def options(given=None) -> dict:
    """The instructions settings with their defaults; lists as lists."""
    values = {**DEFAULTS, **{key: value for key, value in (given or {}).items() if value is not None}}
    for key in ("files", "root_markers", "exclude"):
        if isinstance(values[key], str):
            values[key] = [item.strip() for item in values[key].split(",") if item.strip()]
        else:
            values[key] = [str(item) for item in values[key]]
    values["max_bytes"] = max(0, int(values["max_bytes"]))
    if values["load"] not in ("all", "user", "off"):
        raise ValueError("instructions.load is all, user or off")
    return values


def _label(path: Path, root: Path | None) -> str:
    if root is not None and path.is_relative_to(root):
        return path.relative_to(root).as_posix()
    home = Path.home()
    return "~/" + path.relative_to(home).as_posix() if path.is_relative_to(home) else path.as_posix()


def _excluded(path: Path, patterns) -> bool:
    text = path.as_posix()
    return any(fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(path.name, pattern) for pattern in patterns)


def _read(path: Path, label: str, loaded: Loaded) -> str | None:
    """The file's text, or None (absent, empty, too large, unreadable)."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > SKIP_BYTES:
        loaded.skipped.append((label, "over 4 MiB"))
        loaded.warnings.append(f"{label} is over 4 MiB and was not loaded")
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        loaded.skipped.append((label, f"unreadable: {error}"))
        return None
    text = _without_comments(text)
    if not text.strip():
        loaded.skipped.append((label, "empty"))
        return None
    return text


def _outside_code(text: str):
    """(line, inside_code) for each line: fenced blocks count as code."""
    fenced = False
    for line in text.splitlines(keepends=True):
        if _FENCE.match(line):
            fenced = not fenced
            yield line, True
            continue
        yield line, fenced


def _without_comments(text: str) -> str:
    """The text without block-level HTML comments; comments inside fenced blocks stay."""
    out, chunk = [], []
    for line, code in _outside_code(text):
        if code:
            if chunk:
                out.append(_COMMENT.sub("", "".join(chunk)))
                chunk = []
            out.append(line)
        else:
            chunk.append(line)
    if chunk:
        out.append(_COMMENT.sub("", "".join(chunk)))
    return "".join(out)


def _imports(text: str) -> list[str]:
    """The @paths a file imports: not inside code spans or fenced blocks."""
    found = []
    for line, code in _outside_code(text):
        if code:
            continue
        line = re.sub(r"`[^`]*`", "", line)
        found += [match.group(1).replace("\\ ", " ") for match in _IMPORT.finditer(line)]
    return found


def _imported(path: Path, text: str, allowed, loaded: Loaded, root: Path | None, depth: int = 1, seen=None) -> list[File]:
    """The files `text` (of `path`) imports, and theirs, as entries after it."""
    seen = seen if seen is not None else {path.resolve()}
    entries = []
    if depth > IMPORT_DEPTH:
        return entries
    for name in _imports(text):
        target = Path(os.path.expanduser(name))
        target = (target if target.is_absolute() else path.parent / target).resolve()
        if target in seen or not target.is_file():
            continue
        label = _label(target, root)
        if not any(target.is_relative_to(base) for base in allowed):
            loaded.warnings.append(f"{_label(path, root)} imports {name}, outside the project and "
                                   f"{_label(data(), None)}: not loaded")
            continue
        seen.add(target)
        body = _read(target, label, loaded)
        if body is None:
            continue
        entries.append(File(target, label, body, target.stat().st_size))
        entries += _imported(target, body, allowed, loaded, root, depth + 1, seen)
    return entries


def project_root(folder: Path, markers) -> Path | None:
    """The nearest ancestor of `folder` (itself included) holding one of `markers`; None without."""
    if not markers:
        return None
    for directory in (folder, *folder.parents):
        if any((directory / marker).exists() for marker in markers):
            return directory
    return None


def _directory_files(directory: Path, names, settings, root, loaded) -> list[File]:
    """The instruction file of one directory (the first of `names` with text), then its CLAUDE.local.md."""
    entries = []
    for name in names:
        path = directory / name
        if not path.is_file():
            continue
        label = _label(path, root)
        if _excluded(path, settings["exclude"]):
            loaded.skipped.append((label, "excluded (instructions.exclude)"))
            continue
        text = _read(path, label, loaded)
        if text is not None:
            entries.append(File(path, label, text, path.stat().st_size))
            break
    local = directory / LOCAL_FILE
    if LOCAL_FILE not in names and local.is_file() and not _excluded(local, settings["exclude"]):
        text = _read(local, _label(local, root), loaded)
        if text is not None:
            entries.append(File(local, _label(local, root), text, local.stat().st_size))
    allowed = [root or directory, data()]
    for entry in list(entries):
        entries[entries.index(entry) + 1:entries.index(entry) + 1] = _imported(
            entry.path, entry.text, allowed, loaded, root)
    return entries


def _budget(entries: list[File], limit: int, loaded: Loaded, what: str) -> list[File]:
    """`entries` within `limit` bytes: the one that crosses it is cut, those after it left out."""
    kept, left = [], limit
    for entry in entries:
        size = len(entry.text.encode("utf-8"))
        if left <= 0:
            loaded.skipped.append((entry.label, f"over the {limit}-byte budget (instructions.max_bytes)"))
            loaded.warnings.append(f"{entry.label} was not loaded: the {what} instructions reached "
                                   f"instructions.max_bytes ({limit} bytes)")
            continue
        if size > left:
            entry.text = entry.text.encode("utf-8")[:left].decode("utf-8", "ignore")
            entry.text += (f"\n(The rest of {entry.label} is not shown: {size - left} more bytes. "
                           "Read it with read_file when you need it.)")
            entry.cut = True
            loaded.warnings.append(f"{entry.label} was cut at {left} of {size} bytes (instructions.max_bytes)")
            size = left
        kept.append(entry)
        left -= size
    return kept


def load(folder, settings=None) -> Loaded:
    """The instruction files a conversation working in `folder` (None: no folder) reads at its start."""
    settings = options(settings)
    folder = Path(folder).expanduser().resolve() if folder else None
    loaded = Loaded(folder=folder)
    if settings["load"] == "off":
        return loaded
    limit = settings["max_bytes"]
    user = []
    for name in USER_FILES:
        path = data() / name
        if path.is_file() and not _excluded(path, settings["exclude"]):
            text = _read(path, _label(path, None), loaded)
            if text is not None:
                user = [File(path, _label(path, None), text, path.stat().st_size)]
                user += _imported(path, text, [data()], loaded, None)
                break
    if limit:
        loaded.files += _budget(user, limit, loaded, "user")
    if folder is None or settings["load"] == "user" or not limit:
        return loaded
    root = project_root(folder, settings["root_markers"])
    loaded.root = root or folder
    project = []
    for directory in _walk(loaded.root, folder):
        project += _directory_files(directory, settings["files"], settings, loaded.root, loaded)
    loaded.files += _budget(project, limit, loaded, "project")
    return loaded


def _walk(root: Path, folder: Path) -> list[Path]:
    """The directories from `root` down to `folder`, both included."""
    if root == folder:
        return [folder]
    relative = folder.relative_to(root)
    return [root, *(root / Path(*relative.parts[:index]) for index in range(1, len(relative.parts) + 1))]


def nested(folder, touched, settings, told: set) -> list[File]:
    """The instruction files of directories below `folder` down to `touched` (a file or a
    directory a program read, wrote or ran in) that the conversation has not been told of; each
    cut at NESTED_CHARS. `told` holds the directories already told and is updated."""
    settings = options(settings)
    if settings["load"] != "all" or folder is None:
        return []
    folder = Path(folder).resolve()
    target = (folder / touched).resolve() if not Path(touched).is_absolute() else Path(touched).resolve()
    if not target.is_relative_to(folder) or target == folder:
        return []
    directory = target if target.is_dir() else target.parent
    loaded = Loaded(folder=folder)
    entries = []
    for current in _walk(folder, directory)[1:]:
        if current in told:
            continue
        told.add(current)
        for entry in _directory_files(current, settings["files"], settings, folder, loaded):
            if len(entry.text) > NESTED_CHARS:
                entry.text = entry.text[:NESTED_CHARS] + (f"\n(The rest of {entry.label} is not shown. Read it with "
                                                          "read_file when you need it.)")
                entry.cut = True
            entries.append(entry)
    return entries


def block(loaded: Loaded) -> str:
    """The model's text: Codex's wrapper, the user's file first, each file under its path."""
    if not loaded.files:
        return ""
    user = [entry for entry in loaded.files if entry.path.is_relative_to(data())]
    project = [entry for entry in loaded.files if entry not in user]
    parts = ["\n\n".join(f"(from {entry.label})\n{entry.text.strip()}" for entry in user)] if user else []
    if project:
        parts.append("\n\n".join(f"(from {entry.label})\n{entry.text.strip()}" for entry in project))
    head = "# AGENTS.md instructions" + (f" for {loaded.folder}" if loaded.folder else "")
    return f"{head}\n\n<INSTRUCTIONS>\n{SEPARATOR.join(parts) if len(parts) > 1 else parts[0]}\n</INSTRUCTIONS>\n\n"


def told(entries: list[File]) -> str:
    """The note for files a program's touch brought in (nested())."""
    return "\n\n".join(f"Instructions for {entry.path.parent.as_posix()} (from {entry.label}):\n{entry.text.strip()}"
                       for entry in entries)
