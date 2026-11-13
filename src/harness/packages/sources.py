"""Where a package comes from: the text `harness install` takes, and fetching it.

    minecraft, minecraft@^0.1       the registry (registry.py), the highest version in range
    git:github.com/x/y@ref#subdir   a git repository at a branch, tag or commit, a folder of it
    git+https://host/x/y.git@ref    the same with a full URL
    https://github.com/x/y/tree/ref/subdir   a folder of a GitHub repository
    https://host/x.tar.gz (.tgz, .tar, .zip) an archive
    ./folder, ~/x.zip, C:\\x        a folder or an archive on this computer

A folder or archive without package.toml but with skills (skills/<name>/skill.toml, a
skill.toml or a SKILL.md somewhere in it) is taken as one package per skill
(manager.py), as the app's "Add a skill" took them.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess

from . import archive
from .versions import check_range


ARCHIVES = (".tar.gz", ".tgz", ".tar", ".zip")
GITHUB_TREE = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/tree/([^/]+)/?(.*)$")
REGISTRY_NAME = re.compile(r"^([a-z0-9][a-z0-9-]{0,63})(?:@(.+))?$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass(frozen=True)
class Source:
    """A parsed source: kind is registry, git, url or path."""

    kind: str
    text: str
    name: str = ""
    range: str = ""
    url: str = ""
    ref: str = ""
    subdir: str = ""
    path: str = ""

    @property
    def official(self) -> bool:
        return self.kind == "registry"


def parse(text, *, base: Path | None = None) -> Source:
    """The source `text` names; ValueError when it names none."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("give a package name, a git URL, an archive URL or a folder")
    original = text
    force_path = text.startswith("path:")
    if force_path:
        text = text[5:]
        if not text:
            raise ValueError("path: needs a folder or archive path")
    elif text.startswith("url:"):
        text = text[4:]
        if not text.startswith(("https://", "http://")):
            raise ValueError("url: needs an HTTP or HTTPS archive URL")
    if not force_path and (text.startswith("git:") or text.startswith("git+")):
        rest = text[4:]
        rest = rest if rest.startswith(("https://", "http://", "ssh://", "git@", "file://")) else f"https://{rest}"
        rest, _, subdir = rest.partition("#")
        # The ref follows the last @ after the host (git@host:x/y has its own @).
        head, at, ref = rest.rpartition("@")
        if at and "/" in head.split("://")[-1] and "/" not in ref:
            rest = head
        else:
            ref = ""
        return Source("git", text, url=rest, ref=ref, subdir=subdir.strip("/"))
    if not force_path and re.match(r"^https?://", text):
        github = GITHUB_TREE.match(text)
        if github:
            return Source("git", text, url=f"https://github.com/{github.group(1)}/{github.group(2)}",
                          ref=github.group(3), subdir=github.group(4).strip("/"))
        if text.lower().split("?")[0].endswith(ARCHIVES):
            return Source("url", text, url=text)
        if text.lower().split("?")[0].endswith(".git"):
            return Source("git", text, url=text)
        raise ValueError(f"{text}: a URL of an archive ({', '.join(ARCHIVES)}) or of a git repository (.git)")
    local = Path(os.path.expanduser(text))
    if base is not None and not local.is_absolute():
        local = base / local
    # A bare name is the registry's even when a folder of that name is here (./name is the folder).
    looks_local = force_path or text.startswith((".", "/", "\\", "~")) or re.match(r"^[A-Za-z]:[\\/]", text) or os.sep in text \
        or "/" in text or text.lower().endswith(ARCHIVES)
    if looks_local:
        if not local.exists():
            raise ValueError(f"{text}: no such folder or file")
        if local.is_file() and not local.name.lower().endswith(ARCHIVES):
            raise ValueError(f"{text}: a folder or an archive ({', '.join(ARCHIVES)})")
        return Source("path", original, path=str(local.resolve()))
    match = REGISTRY_NAME.match(text)
    if not match:
        raise ValueError(f"{text}: not a package name (lowercase letters, digits, hyphens), a URL or a folder")
    return Source("registry", text, name=match.group(1), range=check_range(match.group(2) or ""))


def fetch(source: Source, into: Path, *, timeout: float = 300.0, log=print) -> tuple[Path, str]:
    """The files of a git, url or path source in a folder (under `into`, except a local
    folder, which is read where it is); returns the folder and the source as a lock
    records it (a git source with its commit)."""
    into = Path(into)
    if source.kind == "path":
        path = Path(source.path)
        if path.is_dir():
            return path, f"path:{path}"
        return archive.unpack(path, into / "unpacked"), f"path:{path}"
    if source.kind == "url":
        from ..core.http import open_url

        log(f"downloading {source.url}")
        with open_url(source.url, timeout=timeout) as response:
            data = response.read(archive.MAX_BYTES + 1)
        if len(data) > archive.MAX_BYTES:
            raise ValueError(f"{source.url}: larger than {archive.MAX_BYTES >> 20} MB")
        import hashlib

        return archive.unpack(data, into / "unpacked"), f"url:{source.url}#sha256={hashlib.sha256(data).hexdigest()}"
    if source.kind == "git":
        return _git(source, into, timeout, log)
    raise ValueError(f"{source.text}: a registry package is fetched by the registry")


def _git(source: Source, into: Path, timeout: float, log) -> tuple[Path, str]:
    git = shutil.which("git")
    if git is None:
        raise ValueError("installing from git needs git on this computer; use an archive URL instead")
    target = into / "repo"

    def run(*args, cwd=None):
        result = subprocess.run([git, *args], cwd=cwd, capture_output=True, encoding="utf-8", errors="replace",
                                timeout=timeout)
        if result.returncode:
            raise ValueError(f"git {args[0]} failed: {(result.stderr or result.stdout).strip()[-300:]}")
        return result.stdout.strip()

    log(f"cloning {source.url}" + (f" at {source.ref}" if source.ref else ""))
    if source.ref and COMMIT.match(source.ref):
        run("clone", "--filter=blob:none", "--no-checkout", source.url, str(target))
        run("checkout", "--quiet", source.ref, cwd=target)
    else:
        run("clone", "--depth", "1", *(["--branch", source.ref] if source.ref else []), source.url, str(target))
    commit = run("rev-parse", "HEAD", cwd=target)
    folder = (target / source.subdir).resolve()
    if target.resolve() not in [folder, *folder.parents] or not folder.is_dir():
        raise ValueError(f"no folder {source.subdir} in {source.url}")
    return folder, f"git:{source.url}@{commit}" + (f"#{source.subdir}" if source.subdir else "")
