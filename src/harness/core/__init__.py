"""Building blocks shared by the runtime, the workers and the tools: the worker
protocol (contracts, robot client, worker server), traces, media, codecs, polling waits
and the HTTP helpers for model providers, the hashes records carry and the atomic file
write. Standard library only."""

import hashlib
import json
import os
from pathlib import Path
import tempfile


def canonical(value) -> str:
    """`value` as compact JSON with sorted keys (other objects as their str), so equal
    trees give the same text."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha256(value) -> str:
    """The hex sha256 of `value`'s canonical JSON."""
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def tree_hash(folder, paths) -> str:
    """A hash of files in `folder` (sorted `paths`): their names relative to it and their
    contents."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(Path(path).relative_to(folder).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(Path(path).read_bytes()).digest())
    return digest.hexdigest()


def atomic_write(path, data, *, private=False) -> None:
    """Write `data` (text as UTF-8, or bytes) to `path` at once: a temporary file in the
    same folder, then os.replace, so a reader finds the old file or the new one, never a
    part, and writers side by side each keep a whole file. The file is readable by the
    user only when `private` (it holds keys or tokens)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data.encode("utf-8") if isinstance(data, str) else data)
        try:
            os.chmod(temporary, 0o600 if private else 0o644)
        except OSError:
            pass
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
