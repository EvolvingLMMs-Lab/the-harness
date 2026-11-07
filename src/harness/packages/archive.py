"""Package files: a deterministic tar.gz of a package folder, and unpacking one safely.

The same folder always gives the same bytes (files sorted, times, owners and modes
normalised, gzip without a name or time), so a published file's sha256 can be checked
against a rebuild. Unpacking refuses links, absolute paths, paths that leave the
folder and archives larger than MAX_FILES files or MAX_BYTES.
"""

import gzip
import hashlib
import io
import os
from pathlib import Path
import tarfile
import zipfile


MAX_FILES, MAX_BYTES = 20000, 200 * 1024 * 1024
# Never part of a package file.
SKIP_DIRS = {".git", "__pycache__", ".deps", ".pytest_cache", ".mypy_cache", "node_modules", ".venv"}
SKIP_SUFFIXES = (".pyc", ".pyo")
SKIP_FILES = {".DS_Store", ".installed.json"}


def files(folder: Path) -> list[Path]:
    """The files of a package folder that go into its package file, sorted."""
    folder = Path(folder)
    out = []
    for current, directories, names in os.walk(folder):
        directories[:] = sorted(name for name in directories if name not in SKIP_DIRS)
        for name in sorted(names):
            path = Path(current) / name
            if name in SKIP_FILES or name.endswith(SKIP_SUFFIXES) or path.is_symlink():
                continue
            out.append(path)
    return sorted(out, key=lambda path: path.relative_to(folder).as_posix())


def build(folder: Path, out: Path, *, prefix: str | None = None) -> str:
    """Write `folder` as a deterministic tar.gz at `out`, its files under `prefix/`
    (default the folder's name); returns its sha256."""
    folder = Path(folder)
    prefix = prefix or folder.name
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        directories = set()
        for path in files(folder):
            relative = path.relative_to(folder).as_posix()
            parents = relative.split("/")[:-1]
            for depth in range(len(parents) + 1):
                directory = "/".join([prefix, *parents[:depth]])
                if directory not in directories:
                    directories.add(directory)
                    tar.addfile(_info(directory, tarfile.DIRTYPE, 0o755))
            data = path.read_bytes()
            executable = os.access(path, os.X_OK) and os.name != "nt"
            tar.addfile(_info(f"{prefix}/{relative}", tarfile.REGTYPE, 0o755 if executable else 0o644, len(data)),
                        io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0, compresslevel=9) as handle:
        handle.write(raw.getvalue())
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(compressed.getvalue())
    return hashlib.sha256(compressed.getvalue()).hexdigest()


def _info(name: str, kind, mode: int, size: int = 0) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type, info.mode, info.size, info.mtime = kind, mode, size, 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def _inside(root: Path, name: str) -> Path:
    target = (root / name).resolve()
    if name.startswith(("/", "\\")) or ":" in name.split("/")[0] or (target != root and root not in target.parents):
        raise ValueError(f"the archive has a path outside it: {name}")
    return target


def unpack(path_or_bytes, into: Path) -> Path:
    """Unpack a .tar.gz, .tgz, .tar or .zip (a path or its bytes) into `into`; returns the
    folder that holds package.toml or the skills (the single top-level folder when there
    is one, else `into`)."""
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    root = into.resolve()
    data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else Path(path_or_bytes).read_bytes()
    if data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES or sum(member.file_size for member in members) > MAX_BYTES:
                raise ValueError("the archive is too large for a package")
            for member in members:
                _inside(root, member.filename)
            archive.extractall(root)
    else:
        try:
            tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
        except tarfile.TarError:
            raise ValueError("not a .tar.gz, .tar or .zip file") from None
        with tar:
            members = tar.getmembers()
            if len(members) > MAX_FILES or sum(member.size for member in members) > MAX_BYTES:
                raise ValueError("the archive is too large for a package")
            for member in members:
                if not (member.isfile() or member.isdir()):
                    raise ValueError(f"the archive has a link or a device: {member.name}")
                _inside(root, member.name)
            for member in members:
                target = _inside(root, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source:
                    target.write_bytes(source.read())
                if member.mode & 0o111 and os.name != "nt":
                    target.chmod(0o755)
    entries = [path for path in root.iterdir() if not path.name.startswith(".") and path.name != "__MACOSX"]
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else root
