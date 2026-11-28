"""What the app package gives the session host (the core calls these by name,
harness/extensions.py, and imports nothing of this package):

    pages    the app at / (ui/static/)
    api      /api/app/<name> beside the core's own /api/app/... routes:
               elsewhere  GET: the OpenClaw and Hermes agents on this computer; POST {kind}:
                          bring one over as a new identity (the agent package's take.py)
               persona    an identity's persona files (IDENTITY.md, SOUL.md, USER.md, MEMORY.md);
                          POST {identity, file, text} writes one
               skill      a skill's own files (SKILL.md and its program) for What it learned
               place      what a place chat works in: its folder's changes (git diff) and files
               about      the version, the identity's fingerprint and where its files are
               update     the desktop app's own update (update.py): what the page shows, and
                          the desktop shell's reports and the owner's Restart to update
    focus    bring the desktop shell's window to the front

The page reads and writes only the host's API; the agent's life runs in the host whether
or not a page is open."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

from .shell import focus  # noqa: F401  (extensions.focus)
from . import terminal as _terminal
from .attachments import serve_attachment as attachments
from .overview import overview
from .update import update

pages = {"/": "index.html"}

STATIC = Path(__file__).resolve().parents[1] / "ui" / "static"
PERSONA = ("IDENTITY.md", "SOUL.md", "USER.md", "MEMORY.md")
# Bytes of a diff the Changes tab shows.
DIFF_LIMIT = 400_000


def _one(body, key, default=None):
    value = body.get(key, default)
    return value[0] if isinstance(value, list) else value


def _agent(name):
    """The agent package's API handler `name`, or None when that package is not here."""
    from harness.extensions import hosts

    for package, module in hosts():
        if package.name == "agent":
            return (getattr(module, "api", None) or {}).get(name)
    return None


def _life(server, identity):
    service = (getattr(server, "background", None) or {}).get("agent")
    if service is None:
        return None
    try:
        return service.life(identity)
    except Exception:
        return None


def _identity_row(server, identity):
    rows = (_agent("identities") or (lambda server, body: []))(server, {})
    chosen = identity or next((row["id"] for row in rows if row.get("current")), None)
    row = next((row for row in rows if row["id"] == chosen), None)
    if row is None:
        raise ValueError(f"no identity {chosen!r}")
    return row


def _elsewhere() -> list:
    try:
        from harness_agent.take import found_elsewhere
    except ImportError:
        return []
    return found_elsewhere()


def elsewhere(server, body):
    """The OpenClaw and Hermes agents on this computer ("bring it over"); POST {kind}: a new
    identity from one: persona, memory and skills, never its channel tokens or keys."""
    kind = _one(body, "kind")
    if kind:
        from harness_agent.take import import_from

        return import_from(str(kind))
    return {"found": _elsewhere()}


def persona(server, body):
    row = _identity_row(server, _one(body, "identity"))
    folder = Path(row["folder"])
    if body.get("file") is not None and body.get("text") is not None:
        name = str(body["file"])
        if name not in PERSONA:
            raise ValueError(f"a persona file is one of {', '.join(PERSONA)}")
        (folder / name).write_text(str(body["text"]), encoding="utf-8")
    return {"identity": row["id"], "folder": f"agents/{row['id']}/",
            "files": [{"name": name, "text": (folder / name).read_text(encoding="utf-8")
                       if (folder / name).is_file() else ""} for name in PERSONA]}


def skill(server, body):
    """GET {identity, name}: the files of one of the identity's skills, as What it learned shows
    them when the item is opened."""
    row = _identity_row(server, _one(body, "identity"))
    name = Path(str(_one(body, "name") or "")).name
    folder = Path(row["folder"]) / "skills" / name
    if not name or not folder.is_dir():
        raise ValueError(f"no skill {name!r}")
    files = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix in (".md", ".py") and path.stat().st_size < 64_000:
            files.append({"name": path.name, "text": path.read_text(encoding="utf-8", errors="replace")})
    return {"name": name, "files": files}


def _place_folder(server, identity, chat):
    life = _life(server, identity)
    if life is None:
        return None
    meta = life.chats.meta(chat)
    place = life.places.get(meta.get("place")) if meta.get("place") else None
    row = getattr(place, "row", None) or {}
    folder = row.get("folder") if row.get("kind") == "folder" else None
    if folder and (meta.get("copy") or {}).get("folder"):
        folder = meta["copy"]["folder"]  # this chat works in an isolated copy of the project
    return Path(folder) if folder and Path(folder).is_dir() else None


def folders(server, body):
    """GET {path}: the folders inside `path` on this computer, to choose a project from as an
    editor's "Open Folder" lists them: {path, parent, folders: [{name, path, git}], roots}.
    Without `path`: the home folder. Hidden folders are left out; `git` says a repository
    starts there. `roots`: the home folder and, on Windows, the drives."""
    import os
    import string

    from harness.sdk import Problem

    given = str(_one(body, "path") or "").strip()
    here = Path(given).expanduser() if given else Path.home()
    if not here.is_dir():
        raise Problem(f"there is no folder {given!r}", "give the path of a folder that exists", code="no_folder")
    here = here.resolve()
    rows = []
    try:
        for item in sorted(here.iterdir(), key=lambda entry: entry.name.lower()):
            try:
                if item.name.startswith((".", "$")) or not item.is_dir():
                    continue
                rows.append({"name": item.name, "path": str(item), "git": (item / ".git").exists()})
            except OSError:
                continue
            if len(rows) >= 500:
                break
    except OSError as error:
        raise Problem(f"{here} cannot be read: {error.strerror or error}", "choose another folder",
                      code="folder_unreadable") from None
    roots = [str(Path.home())]
    if os.name == "nt":
        roots += [f"{letter}:\\" for letter in string.ascii_uppercase if Path(f"{letter}:\\").exists()]
    return {"path": str(here), "parent": str(here.parent) if here.parent != here else None, "folders": rows,
            "git": (here / ".git").exists(), "roots": roots}


def place(server, body):
    """GET {identity, chat}: the folder the chat's place works in, its changes and its files."""
    identity = _identity_row(server, _one(body, "identity"))["id"]
    folder = _place_folder(server, identity, _one(body, "chat") or "main")
    if folder is None:
        return {"folder": None, "diff": "", "files": []}
    diff = ""
    try:
        diff = subprocess.run(["git", "-C", str(folder), "diff", "HEAD"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=15).stdout[:DIFF_LIMIT]
    except (OSError, subprocess.SubprocessError):
        diff = ""
    files = []
    for path in sorted(folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:300]:
        if path.name.startswith("."):
            continue
        files.append({"name": path.name, "dir": path.is_dir(), "size": None if path.is_dir() else path.stat().st_size,
                      "modified": path.stat().st_mtime})
    return {"folder": folder.name, "diff": diff, "files": files}


# Which `harness` a new terminal runs (shell.command): asking another install for its
# version takes a second or two, so a request is answered with what was found last and the
# answer is found again in the background.
_COMMAND = {"found": None, "at": 0.0, "busy": False}
COMMAND_SECONDS = 60.0


def _command():
    """What shell.command() found last (None the first time, and where the desktop shell's
    part of this package is not there), found again behind the request when it is old."""
    import threading
    import time

    from . import shell

    find = getattr(shell, "command", None)
    if find is None:
        return None

    def refresh():
        try:
            _COMMAND["found"] = find()
        except Exception:  # noqa: BLE001 - the page shows the version without it
            pass
        finally:
            _COMMAND.update(at=time.time(), busy=False)

    if not _COMMAND["busy"] and time.time() - _COMMAND["at"] > COMMAND_SECONDS:
        _COMMAND["busy"] = True
        threading.Thread(target=refresh, name="which-harness", daemon=True).start()
    return _COMMAND["found"]


def about(server, body):
    from harness import __version__

    try:  # the build's own version on a channel that numbers its builds (0.87.0-dev.412)
        from harness import channel

        __version__ = channel.version()
    except ImportError:  # a core from before channels
        pass
    row = _identity_row(server, _one(body, "identity"))
    downloads = Path.home() / "Downloads"
    fingerprint = None
    try:
        from harness_agent.state import Identity

        fingerprint = Identity(row["id"], create=False).to_dict(verbose=True).get("fingerprint")
    except Exception:
        fingerprint = None
    return {"version": __version__, "identity": row["id"], "name": row.get("name"), "fingerprint": fingerprint,
            "folder": f"agents/{row['id']}/", "save_to": str(downloads if downloads.is_dir() else Path.home()),
            # The `harness` a new terminal runs ({path, mine, version, fix, ...}); null until it was found.
            "command": _command()}


_SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", "target", ".mypy_cache"})
_FILE_LIMIT = 512 * 1024
_LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".jsx": "javascript", ".json": "json", ".toml": "ini", ".yaml": "yaml", ".yml": "yaml", ".md": "markdown",
    ".rs": "rust", ".go": "go", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".java": "java",
    ".sh": "bash", ".ps1": "powershell", ".css": "css", ".html": "xml", ".xml": "xml", ".sql": "sql",
}


def _safe_inside(root: Path, rel: str) -> Path:
    base = root.resolve()
    target = (base / str(rel or "").lstrip("/\\")).resolve()
    if target != base and base not in target.parents:
        raise ValueError("path must stay inside the project folder")
    return target


def _git_run(folder: Path, *args: str) -> subprocess.CompletedProcess:
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=15, stdin=subprocess.DEVNULL, **flags)


def _git_status_map(folder: Path) -> dict[str, str]:
    try:
        res = _git_run(folder, "status", "--porcelain", "-uall")
    except (OSError, subprocess.SubprocessError):
        return {}
    if res.returncode != 0:
        return {}
    out = {}
    for line in res.stdout.splitlines():
        if len(line) < 4:
            continue
        code = line[:2].strip() or "M"
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip().strip('"')
        norm = path.replace("\\", "/")
        if not norm or norm.endswith("/"):
            continue
        out[norm] = code
    return out


def _place_ssh(server, identity, chat) -> dict | None:
    life = _life(server, identity)
    if life is None:
        return None
    meta = life.chats.meta(chat)
    place = life.places.get(meta.get("place")) if meta.get("place") else None
    row = getattr(place, "row", None) or {}
    return dict(row) if row.get("kind") == "ssh" else None


def _ssh_client(ssh_row: dict):
    from harness.sdk import Problem, ssh as harness_ssh

    try:
        return harness_ssh.POOL.get(ssh_row)
    except harness_ssh.SshError as err:
        raise Problem(str(err), err.fix, code=err.code) from None


def _ssh_call(ssh_row: dict, method: str, params: dict | None = None, *, timeout: float = 15.0) -> dict:
    from harness.sdk import Problem, ssh as harness_ssh

    try:
        return harness_ssh.POOL.get(ssh_row).call(method, params or {}, timeout=timeout)
    except harness_ssh.SshError as err:
        raise Problem(str(err), err.fix, code=err.code) from None


def ssh_hosts(server, body):
    """GET: list SSH Host aliases parsed from ~/.ssh/config (including recursive Include)."""
    from harness.sdk import ssh as harness_ssh

    return {"hosts": harness_ssh.parse_ssh_config()}


def ssh_probe(server, body):
    """POST {host, user?, port?, path?, identity?}: verify SSH connectivity, remote $HOME, OS,
    and return previously opened folders on this host (Cursor Remote-SSH step 1)."""
    from harness.sdk import Problem, ssh as harness_ssh

    try:
        spec = harness_ssh.normalize_spec(
            _one(body, "host") or _one(body, "target") or "",
            user=_one(body, "user"),
            port=_one(body, "port"),
            folder=_one(body, "path") or _one(body, "folder") or "~",
            target=_one(body, "target"),
        )
    except ValueError as err:
        raise Problem(str(err), "enter a valid SSH host or ~/.ssh/config alias", code="bad_ssh_host") from None
    # Force a fresh probe if the user just finished authenticating in terminal
    if body.get("fresh"):
        harness_ssh.POOL.drop(spec)
    info = _ssh_call(spec, "probe", {"path": spec["folder"]}, timeout=18.0)
    recent: list[str] = []
    try:
        row = _identity_row(server, _one(body, "identity"))
        life = _life(server, row["id"])
        if life is not None:
            for pl in (getattr(life, "places", None) or {}).values():
                if getattr(pl, "kind", None) == "ssh" and pl.row.get("target") == spec["target"]:
                    f = str(pl.row.get("folder") or "").strip()
                    if f and f not in recent:
                        recent.append(f)
    except Exception:
        pass
    return {"ok": True, "spec": spec, "recent_folders": recent, **info}


def ssh_browse(server, body):
    """GET/POST {host, user?, port?, path?, hidden?}: browse remote directories (including
    arbitrary paths like /pfs/... and directory symlinks) for the Remote Folder Picker."""
    from harness.sdk import Problem, ssh as harness_ssh

    try:
        spec = harness_ssh.normalize_spec(
            _one(body, "host") or _one(body, "target") or "",
            user=_one(body, "user"),
            port=_one(body, "port"),
            folder=_one(body, "path") or "~",
            target=_one(body, "target"),
        )
    except ValueError as err:
        raise Problem(str(err), "enter a valid SSH host or ~/.ssh/config alias", code="bad_ssh_host") from None
    hidden = str(_one(body, "hidden") or "").lower() in ("1", "true", "yes")
    got = _ssh_call(spec, "browse", {"path": spec["folder"], "hidden": hidden}, timeout=15.0)
    return {"target": spec["target"], "host": spec["host"], "port": spec.get("port"), **got}


def place_tree(server, body):
    """GET {identity, chat, path?}: lazy directory listing inside a chat's project/worktree or SSH project."""
    identity = _identity_row(server, _one(body, "identity"))["id"]
    chat = _one(body, "chat") or "main"
    ssh_row = _place_ssh(server, identity, chat)
    if ssh_row is not None:
        rel = str(_one(body, "path") or "").strip().replace("\\", "/").strip("/")
        got = _ssh_call(ssh_row, "tree", {"root": ssh_row.get("folder", "~"), "path": rel}, timeout=15.0)
        title = ssh_row.get("title") or f"{got.get('folder') or '~'} @ {ssh_row.get('target')}"
        return {"folder": title, "root": f"ssh://{ssh_row.get('target')}:{got.get('root') or ssh_row.get('folder')}",
                "path": got.get("path", rel), "entries": got.get("entries", []), "ssh": True}
    root = _place_folder(server, identity, chat)
    if root is None:
        return {"folder": None, "root": None, "path": "", "entries": []}
    rel = str(_one(body, "path") or "").strip().replace("\\", "/")
    target = _safe_inside(root, rel)
    if not target.is_dir():
        raise ValueError(f"not a directory: {rel!r}")
    status = _git_status_map(root)
    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name in _SKIP_DIRS:
            continue
        item_rel = item.relative_to(root.resolve()).as_posix()
        is_dir = item.is_dir()
        st = status.get(item_rel, "")
        if is_dir and not st:
            prefix = item_rel + "/"
            if any(k.startswith(prefix) for k in status):
                st = "M"
        try:
            stat = item.stat()
            size = None if is_dir else stat.st_size
            mtime = stat.st_mtime
        except OSError:
            size, mtime = None, 0
        entries.append({"name": item.name, "path": item_rel, "dir": is_dir, "size": size,
                        "modified": mtime, **({"status": st} if st else {})})
        if len(entries) >= 500:
            break
    return {"folder": root.name, "root": str(root), "path": rel, "entries": entries}


def place_file(server, body):
    """GET {identity, chat, path}: read a text file inside a chat's project/worktree or SSH project."""
    identity = _identity_row(server, _one(body, "identity"))["id"]
    chat = _one(body, "chat") or "main"
    rel = str(_one(body, "path") or "").strip().replace("\\", "/").strip("/")
    if not rel:
        raise ValueError("path is required")
    ssh_row = _place_ssh(server, identity, chat)
    if ssh_row is not None:
        got = _ssh_call(ssh_row, "read", {"root": ssh_row.get("folder", "~"), "path": rel, "mode": "viewer"}, timeout=15.0)
        return {**got, "full_path": f"ssh://{ssh_row.get('target')}:{got.get('full_path') or rel}", "ssh": True}
    root = _place_folder(server, identity, chat)
    if root is None:
        raise ValueError("this chat has no project folder")
    target = _safe_inside(root, rel)
    if not target.is_file():
        raise ValueError(f"no file {rel!r}")
    size = target.stat().st_size
    raw = target.read_bytes()[:_FILE_LIMIT]
    if b"\x00" in raw[:4096]:
        return {"path": rel, "name": target.name, "full_path": str(target), "binary": True,
                "size": size, "text": "", "lines": 0, "truncated": False, "language": ""}
    text = raw.decode("utf-8", errors="replace")
    return {"path": rel, "name": target.name, "full_path": str(target), "binary": False,
            "size": size, "text": text, "lines": text.count("\n") + (1 if text else 0),
            "truncated": size > _FILE_LIMIT, "language": _LANG_BY_EXT.get(target.suffix.lower(), "")}


def place_search(server, body):
    """GET {identity, chat, q}: fuzzy path search inside a chat's project (local or SSH) for @ mentions."""
    identity = _identity_row(server, _one(body, "identity"))["id"]
    chat = _one(body, "chat") or "main"
    query = str(_one(body, "q") or "").strip().lower()
    ssh_row = _place_ssh(server, identity, chat)
    if ssh_row is not None:
        title = str(ssh_row.get("title") or "").removeprefix("ssh · ").strip() or (
            f"{ssh_row.get('target')}:{ssh_row.get('folder') or '~'}"
        )
        try:
            got = _ssh_call(ssh_row, "search", {"root": ssh_row.get("folder", "~"), "query": query, "limit": 40}, timeout=8.0)
        except Exception:
            return {"folder": title, "matches": [], "ssh": True}
        return {"folder": got.get("folder") or title, "matches": got.get("matches", []), "ssh": True}
    root = _place_folder(server, identity, chat)
    if root is None:
        return {"folder": None, "matches": []}
    base = root.resolve()
    matches, queue, visited = [], [base], 0
    while queue and visited < 2000 and len(matches) < 40:
        cur = queue.pop(0)
        try:
            children = sorted(cur.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            continue
        for item in children:
            if item.name in _SKIP_DIRS or item.name.startswith("."):
                continue
            visited += 1
            rel = item.relative_to(base).as_posix()
            is_dir = item.is_dir()
            if not query or query in rel.lower():
                matches.append({"path": rel, "name": item.name, "dir": is_dir})
                if len(matches) >= 40:
                    break
            if is_dir and visited < 1500:
                queue.append(item)
    return {"folder": root.name, "matches": matches}


def place_changes(server, body):
    """GET {identity, chat}: structured per-file git diff + worktree status (local or SSH).
    POST {action: revert, identity, chat, path}: revert one file in the project/worktree/SSH repo."""
    identity = _identity_row(server, _one(body, "identity"))["id"]
    chat = _one(body, "chat") or "main"
    ssh_row = _place_ssh(server, identity, chat)
    if ssh_row is not None:
        action = _one(body, "action")
        if action == "revert":
            rel = str(_one(body, "path") or "").strip().replace("\\", "/")
            if not rel:
                raise ValueError("path is required")
            got = _ssh_call(ssh_row, "git_revert", {"root": ssh_row.get("folder", "~"), "path": rel}, timeout=15.0)
        else:
            got = _ssh_call(ssh_row, "git_changes", {"root": ssh_row.get("folder", "~")}, timeout=15.0)
        return {**got, "ssh": True}
    root = _place_folder(server, identity, chat)
    if root is None:
        return {"folder": None, "branch": "", "files": [], "worktree": {"is_worktree": False}}
    action = _one(body, "action")
    if action == "revert":
        rel = str(_one(body, "path") or "").strip().replace("\\", "/")
        if not rel:
            raise ValueError("path is required")
        target = _safe_inside(root, rel)
        status = _git_status_map(root)
        if status.get(rel) == "??":
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        else:
            res = _git_run(root, "checkout", "HEAD", "--", rel)
            if res.returncode != 0:
                res2 = _git_run(root, "checkout", "--", rel)
                if res2.returncode != 0:
                    raise ValueError((res2.stderr or res.stderr or "git checkout failed").strip()[:300])
    branch = ""
    try:
        br = _git_run(root, "rev-parse", "--abbrev-ref", "HEAD")
        if br.returncode == 0:
            branch = br.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    status = _git_status_map(root)
    files = []
    for rel, code in sorted(status.items()):
        diff_text = ""
        added = removed = 0
        if code == "??":
            target = _safe_inside(root, rel)
            if target.is_file():
                try:
                    raw = target.read_bytes()[:65536]
                    if b"\x00" not in raw[:2048]:
                        lines = raw.decode("utf-8", errors="replace").splitlines()
                        added = len(lines)
                        diff_text = f"diff --git a/{rel} b/{rel}\nnew file\n@@ -0,0 +1,{added} @@\n" + "\n".join("+" + l for l in lines)
                except OSError:
                    pass
        else:
            try:
                d = _git_run(root, "diff", "HEAD", "--", rel)
                if d.returncode != 0:
                    d = _git_run(root, "diff", "--", rel)
                diff_text = (d.stdout or "")[:DIFF_LIMIT]
                for ln in diff_text.splitlines():
                    if ln.startswith("+") and not ln.startswith("+++"):
                        added += 1
                    elif ln.startswith("-") and not ln.startswith("---"):
                        removed += 1
            except (OSError, subprocess.SubprocessError):
                pass
        files.append({"path": rel, "status": code, "added": added, "removed": removed, "diff": diff_text})
    worktree = {"is_worktree": False}
    life = _life(server, identity)
    if life is not None:
        try:
            from harness_agent import places as agent_places

            worktree = agent_places.worktree_status(life.chats.meta(chat))
        except Exception:
            pass
    return {"folder": root.name, "root": str(root), "branch": branch, "files": files, "worktree": worktree}


def terminal(server, body):
    """Interactive PTY terminal sessions: open, input, resize, close, list, read, stream."""
    action = str(_one(body, "action") or "list")
    if action == "list":
        return {"sessions": _terminal.list_sessions()}
    if action == "open":
        from harness.sdk import ssh as harness_ssh

        cwd = _one(body, "cwd")
        ssh_cmd = None
        label = ""
        ssh_auth = body.get("ssh_auth")
        if isinstance(ssh_auth, dict) and (ssh_auth.get("target") or ssh_auth.get("host")):
            spec = harness_ssh.normalize_spec(
                ssh_auth.get("host") or ssh_auth.get("target"),
                user=ssh_auth.get("user"),
                port=ssh_auth.get("port"),
                target=ssh_auth.get("target"),
            )
            ssh_cmd = harness_ssh.auth_terminal_cmd(spec["target"], spec.get("port"))
            label = f"ssh · {spec['target']}"
        elif not cwd:
            try:
                identity = _identity_row(server, _one(body, "identity"))["id"]
                chat = _one(body, "chat") or "main"
                ssh_row = _place_ssh(server, identity, chat)
                if ssh_row is not None:
                    ssh_cmd = harness_ssh.interactive_terminal_cmd(ssh_row)
                    label = f"ssh · {ssh_row.get('target')}"
                else:
                    folder = _place_folder(server, identity, chat)
                    cwd = str(folder) if folder else None
            except Exception:
                cwd = None
        sess = _terminal.open_session(cwd, cols=int(_one(body, "cols") or 100), rows=int(_one(body, "rows") or 28),
                                      cmd=ssh_cmd, label=label)
        return sess.describe()
    sid = str(_one(body, "id") or "")
    if action == "input":
        _terminal.get_session(sid).write(str(body.get("data") or ""))
        return {"ok": True}
    if action == "resize":
        _terminal.get_session(sid).resize(int(body.get("cols") or 100), int(body.get("rows") or 28))
        return {"ok": True}
    if action == "close":
        _terminal.close_session(sid)
        return {"ok": True}
    if action == "read":
        sess = _terminal.get_session(sid)
        chunks, alive, code = sess.read_after(int(_one(body, "after") or 0))
        return {"id": sid, "chunks": chunks, "alive": alive, "exit_code": code}
    if action == "stream":
        sess = _terminal.get_session(sid)
        after = int(_one(body, "after") or 0)
        return lambda handler: sess.stream(handler, after=after)
    raise ValueError("terminal action is open, input, resize, close, list, read or stream")


def open_path(server, body):
    """POST {path, editor?}: open a local file or folder in OS file manager or editor (VS Code)."""
    raw = str(_one(body, "path") or "").strip()
    if not raw:
        raise ValueError("path is required")
    target = Path(raw).expanduser().resolve()
    if not target.exists():
        raise ValueError(f"not found: {raw}")
    editor = str(_one(body, "editor") or "").strip().lower()
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    if editor == "code":
        code_bin = shutil.which("code") or shutil.which("code.cmd")
        if code_bin:
            subprocess.Popen([code_bin, str(target)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **flags)
            return {"ok": True, "opened_with": "code"}
    if os.name == "nt":
        os.startfile(str(target))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", str(target)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "opened_with": "system"}


def pick_folder(server, body):
    """POST {initial?, title?}: invoke modern native OS folder dialog; returns {path, cancelled, supported}."""
    from . import dialogs

    initial = str(_one(body, "initial") or "").strip()
    title = str(_one(body, "title") or "Open folder").strip() or "Open folder"
    return dialogs.pick_folder(initial=initial, title=title)


def rules(server, body):
    """GET/POST {identity, chat?, scope?, file?, text?}: read or edit Global, Project, and Persona rule files."""
    from harness import paths as harness_paths

    row = _identity_row(server, _one(body, "identity"))
    chat = _one(body, "chat") or "main"
    identity_dir = Path(row["folder"])
    global_dir = harness_paths.home()
    project_dir = _place_folder(server, row["id"], chat)

    if body.get("file") is not None and (body.get("text") is not None or body.get("action") == "delete"):
        scope = str(body.get("scope") or "")
        name = Path(str(body.get("file"))).name
        if scope == "global" and name == "AGENTS.md":
            global_dir.mkdir(parents=True, exist_ok=True)
            (global_dir / name).write_text(str(body["text"]), encoding="utf-8")
        elif scope == "persona" and name in PERSONA:
            (identity_dir / name).write_text(str(body["text"]), encoding="utf-8")
        elif scope == "memory" and name.endswith(".md") and not name.startswith("."):
            mem_dir = identity_dir / "memory"
            mem_dir.mkdir(parents=True, exist_ok=True)
            target = (mem_dir / name).resolve()
            if mem_dir.resolve() not in target.parents:
                raise ValueError(f"invalid memory file {name!r}")
            if body.get("action") == "delete":
                target.unlink(missing_ok=True)
            else:
                target.write_text(str(body["text"]), encoding="utf-8")
            try:
                from harness_agent.state import Identity

                Identity(row["id"], root=identity_dir.parent, create=False).rebuild_memory_index()
            except Exception:
                pass
        elif scope == "project" and name in ("AGENTS.md", "CLAUDE.md"):
            if project_dir is None:
                raise ValueError("this chat has no project folder")
            (project_dir / name).write_text(str(body["text"]), encoding="utf-8")
        else:
            raise ValueError(f"cannot write rule {name!r} in scope {scope!r}")

    def _entry(scope, folder, name, *, title=None, readonly=False):
        path = folder / name
        exists = path.is_file()
        return {"scope": scope, "name": name, "path": str(path), "exists": exists,
                **({"title": title} if title else {}),
                **({"readonly": True} if readonly else {}),
                "text": path.read_text(encoding="utf-8", errors="replace") if exists else ""}

    items = [_entry("global", global_dir, "AGENTS.md")]
    if project_dir is not None:
        for name in ("AGENTS.md", "CLAUDE.md"):
            items.append(_entry("project", project_dir, name))
    for name in PERSONA:
        items.append(_entry("persona", identity_dir, name, readonly=(name == "MEMORY.md")))
    mem_dir = identity_dir / "memory"
    if mem_dir.is_dir():
        mem_rows = []
        for path in sorted(mem_dir.glob("*.md")):
            raw = path.read_text(encoding="utf-8", errors="replace")
            title, updated = path.stem, path.stat().st_mtime
            if raw.startswith("---\n"):
                head, _, _ = raw[4:].partition("\n---\n")
                for line in head.splitlines():
                    k, _, v = line.partition(":")
                    ks = k.strip()
                    if ks == "key":
                        try:
                            title = str(json.loads(v.strip()))
                        except ValueError:
                            title = v.strip()
                    elif ks == "updated":
                        try:
                            updated = float(json.loads(v.strip()))
                        except (ValueError, TypeError):
                            pass
            mem_rows.append((updated, _entry("memory", mem_dir, path.name, title=title)))
        mem_rows.sort(key=lambda pair: -pair[0])
        items.extend(entry for _, entry in mem_rows)
    return {"identity": row["id"], "project": project_dir.name if project_dir else None, "files": items}


def _artifacts_dir(server, identity_id: str, chat: str) -> Path:
    row = _identity_row(server, identity_id)
    chat_id = str(chat or "main").strip() or "main"
    if "/" in chat_id or "\\" in chat_id or ".." in chat_id:
        raise ValueError("invalid chat id")
    return Path(row["folder"]) / "sessions" / chat_id / "artifacts"


def artifacts(server, body):
    """GET {identity, chat}: list local Markdown artifacts for a chat, newest first."""
    directory = _artifacts_dir(server, _one(body, "identity"), _one(body, "chat") or "main")
    if not directory.is_dir():
        return {"artifacts": []}
    rows = []
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() != ".md":
            continue
        try:
            st = path.stat()
            text = path.read_text(encoding="utf-8", errors="replace")[:4096]
        except OSError:
            continue
        title = path.name
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("#"):
                title = s.lstrip("#").strip()[:120] or path.name
                break
        rows.append({"name": path.name, "title": title, "path": str(path), "size": st.st_size, "updated": st.st_mtime})
    rows.sort(key=lambda r: -r["updated"])
    return {"artifacts": rows}


def artifact(server, body):
    """GET {identity, chat, name}: read one local Markdown artifact of a chat."""
    directory = _artifacts_dir(server, _one(body, "identity"), _one(body, "chat") or "main")
    name = str(_one(body, "name") or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name or not name.lower().endswith(".md"):
        raise ValueError("artifact name must be a plain .md filename")
    target = (directory / name).resolve()
    if directory.resolve() not in target.parents or not target.is_file():
        raise ValueError(f"artifact not found: {name}")
    st = target.stat()
    text = target.read_text(encoding="utf-8", errors="replace")
    return {"name": target.name, "path": str(target), "text": text, "size": st.st_size, "updated": st.st_mtime}


api = {"elsewhere": elsewhere, "persona": persona, "rules": rules, "skill": skill, "place": place,
       "place_tree": place_tree, "place_file": place_file, "place_search": place_search,
       "place_changes": place_changes, "terminal": terminal, "open_path": open_path, "pick_folder": pick_folder,
       "ssh_hosts": ssh_hosts, "ssh_probe": ssh_probe, "ssh_browse": ssh_browse,
       "artifacts": artifacts, "artifact": artifact, "attachments": attachments,
       "overview": overview, "folders": folders, "about": about, "update": update}
