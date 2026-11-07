"""Files fetched by their hash: a download or copy that is kept only when its hash is the
expected one, and the hash of a file read in blocks (never whole into memory).

    digest(path, algorithm="sha256") -> hex
    fetch_verified(source, target, expected, algorithm="sha256", log=None) -> target

`source` is a URL (http, https, file) or a local path. The bytes go to `<target>.part`,
hashed as they are written, and take the target's name only when the hash matches; a
target already there with the expected hash is not fetched again.
"""

import hashlib
import os
from pathlib import Path

from ..core.http import open_url

BLOCK = 1 << 20


def digest(path, algorithm: str = "sha256") -> str:
    hasher = hashlib.new(algorithm)
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(BLOCK), b""):
            hasher.update(block)
    return hasher.hexdigest()


def fetch_verified(source, target, expected: str | None, algorithm: str = "sha256", log=None,
                   timeout: float = 120.0) -> Path:
    """`target` with the bytes of `source`, checked against `expected` (any hash when it is
    None). A download with another hash is removed and raises ValueError."""
    target = Path(target)
    if expected and target.is_file() and digest(target, algorithm) == expected:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    hasher = hashlib.new(algorithm)
    url = str(source).startswith(("http://", "https://", "file:"))
    if url and log is not None:
        log(f"downloading {source}")
    try:
        with (open_url(str(source), timeout=timeout) if url else open(source, "rb")) as response, \
                partial.open("wb") as handle:
            for block in iter(lambda: response.read(BLOCK), b""):
                hasher.update(block)
                handle.write(block)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    got = hasher.hexdigest()
    if expected and got != expected:
        partial.unlink()
        raise ValueError(f"{source}: {algorithm} {got} is not the pinned {expected}")
    os.replace(partial, target)
    return target

