"""Unified SSH config parser, persistent remote JSON-RPC bridge, and terminal helpers.

Design (first principles, aligned with Cursor / VS Code Remote-SSH):
  - One stdlib-only remote Python 3 JSON-RPC agent injected over a single persistent
    `ssh -T` stdin/stdout pipe per `(target, port)` (zero remote installation, zero files
    written to `$HOME`, immune to Windows CreateProcessW quoting bugs and non-POSIX
    default shells like fish/csh/tcsh).
  - Hydrates the user's real remote login-shell PATH/environment once on connect so remote
    commands (`git`, `gh`, `python`, `conda`, `uv`, `node`, etc.) work out of the box.
  - Shared by BOTH the Agent `ssh` workspace (`packages/workspace`) and the App workbench
    (`packages/app`: remote folder picker, files, `@` search, git diff/revert, overview).
"""
from __future__ import annotations

import atexit
import base64
import glob
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid

DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_RPC_TIMEOUT = 30.0
IDLE_TTL_SECONDS = 600.0
_BAD_HOST_CHARS = set(" \t\r\n;|&`$\x00")


class SshError(RuntimeError):
    """Structured SSH failure with machine-readable `code` and actionable `fix`."""

    def __init__(self, message: str, *, code: str = "ssh_error", fix: str = "", detail: str = ""):
        super().__init__(message)
        self.code = code
        self.fix = fix
        self.detail = detail


def classify_ssh_error(stderr: str, returncode: int | None = None) -> SshError:
    """Turn raw OpenSSH stderr into a structured, user-actionable SshError."""
    raw = (stderr or "").strip()
    low = raw.lower()
    if "harness_no_python" in low:
        return SshError(
            "Remote host does not have Python 3 in PATH",
            code="no_python3",
            fix="Install python3 on the remote host (e.g. apt install python3) and retry.",
            detail=raw,
        )
    if "host key verification failed" in low or "remote host identification has changed" in low or "are you sure you want to continue connecting" in low:
        return SshError(
            "SSH host key is not trusted yet",
            code="host_key_unknown",
            fix="Open the SSH terminal to verify and save the host fingerprint, then retry.",
            detail=raw,
        )
    if any(tok in low for tok in ("permission denied", "authentication failed", "no more authentication methods", "too many authentication failures", "passphrase")):
        return SshError(
            "SSH authentication failed (key, passphrase, password, or 2FA required)",
            code="auth_required",
            fix="Sign in via the built-in SSH terminal or configure key-based auth / ssh-agent, then retry.",
            detail=raw,
        )
    if any(tok in low for tok in ("could not resolve hostname", "name or service not known", "nodename nor servname")):
        return SshError(
            "Could not resolve SSH hostname",
            code="dns_failed",
            fix="Check the host address or ~/.ssh/config alias and your network/VPN connection.",
            detail=raw,
        )
    if "connection refused" in low:
        return SshError(
            "SSH connection refused by remote host",
            code="connection_refused",
            fix="Verify sshd is running on the remote host and the port is correct.",
            detail=raw,
        )
    if any(tok in low for tok in ("operation timed out", "connection timed out", "timed out")):
        return SshError(
            "SSH connection timed out",
            code="timeout",
            fix="Check network reachability, firewall, VPN, or ProxyJump settings.",
            detail=raw,
        )
    first_line = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    msg = first_line or f"SSH connection failed (exit {returncode})"
    return SshError(msg, code="ssh_error", fix="Check your SSH config or test connecting in the terminal.", detail=raw)


def parse_ssh_config(config_path: Path | None = None) -> list[dict]:
    """Parse ~/.ssh/config including recursive `Include` directives.

    Returns deduplicated non-wildcard Host aliases in declaration order:
    `[{host, hostname, user, port, proxy_jump, identity_file}]`.
    """
    root_path = (config_path or (Path.home() / ".ssh" / "config")).expanduser()
    ssh_dir = root_path.parent
    visited: set[Path] = set()
    entries: list[dict] = []
    by_alias: dict[str, dict] = {}

    def _parse_file(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in visited or not resolved.is_file():
            return
        visited.add(resolved)
        try:
            lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        current: list[dict] = []
        for raw in lines:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            key, val = parts[0].lower(), parts[1].strip()
            if key == "include":
                for pattern in val.split():
                    p = os.path.expanduser(pattern)
                    if not os.path.isabs(p):
                        p = str(ssh_dir / p)
                    for match in sorted(glob.glob(p)):
                        _parse_file(Path(match))
                continue
            if key == "match":
                current = []
                continue
            if key == "host":
                current = []
                for alias in val.split():
                    if any(ch in alias for ch in "*?!") or alias.startswith("!"):
                        continue
                    item = by_alias.get(alias)
                    if item is None:
                        item = {"host": alias, "hostname": "", "user": "", "port": None,
                                "proxy_jump": "", "identity_file": ""}
                        by_alias[alias] = item
                        entries.append(item)
                    current.append(item)
            elif current:
                if key == "hostname":
                    for item in current:
                        if not item["hostname"]:
                            item["hostname"] = val
                elif key == "user":
                    for item in current:
                        if not item["user"]:
                            item["user"] = val
                elif key == "port" and val.isdigit():
                    for item in current:
                        if item["port"] is None:
                            item["port"] = int(val)
                elif key == "proxyjump":
                    for item in current:
                        if not item["proxy_jump"]:
                            item["proxy_jump"] = val
                elif key == "identityfile":
                    for item in current:
                        if not item["identity_file"]:
                            item["identity_file"] = val

    _parse_file(root_path)
    return entries


def normalize_spec(host: str, *, user: str | None = None, port: int | str | None = None,
                   folder: str | None = None, target: str | None = None) -> dict:
    """Validate and normalize an SSH connection spec `{host, user, port, target, folder}`.

    Respects `~/.ssh/config` aliases: if `port` is omitted (None/""/0), leaves `port=None`
    so OpenSSH resolves Port/User/ProxyJump from `~/.ssh/config` natively.
    """
    raw_host = str(host or target or "").strip()
    raw_user = str(user or "").strip()
    raw_port = port
    if not raw_host or any(ch in raw_host for ch in _BAD_HOST_CHARS):
        raise ValueError("an SSH project needs a valid host (e.g. user@server or ~/.ssh/config alias)")
    if "@" in raw_host and not raw_user:
        raw_user, raw_host = raw_host.split("@", 1)
    if raw_user and any(ch in raw_user for ch in _BAD_HOST_CHARS):
        raise ValueError("SSH user contains invalid characters")
    # Handle [ipv6]:port or host:port when port not separately given
    m_v6 = re.match(r"^\[([^\]]+)\]:(\d{1,5})$", raw_host)
    if m_v6:
        raw_host = m_v6.group(1)
        if raw_port in (None, "", 0):
            raw_port = int(m_v6.group(2))
    elif ":" in raw_host and raw_host.count(":") == 1:
        h_part, p_part = raw_host.rsplit(":", 1)
        if p_part.isdigit():
            raw_host = h_part.strip()
            if raw_port in (None, "", 0):
                raw_port = int(p_part)
    if not raw_host or any(ch in raw_host for ch in _BAD_HOST_CHARS):
        raise ValueError("an SSH project needs a valid host (e.g. user@server or ~/.ssh/config alias)")
    parsed_port = int(raw_port) if raw_port not in (None, "", 0) else None
    if parsed_port is not None and not (1 <= parsed_port <= 65535):
        raise ValueError("SSH port must be between 1 and 65535")
    norm_folder = str(folder or "~").strip() or "~"
    norm_target = f"{raw_user}@{raw_host}" if raw_user else raw_host
    spec: dict = {"host": raw_host, "target": norm_target, "folder": norm_folder}
    if raw_user:
        spec["user"] = raw_user
    if parsed_port is not None:
        spec["port"] = parsed_port
    return spec


def interactive_terminal_cmd(spec: dict) -> list[str]:
    """Build an interactive PTY `ssh -tt` command that lands in `spec['folder']` and starts
    the user's login shell safely regardless of whether the remote default shell is bash,
    zsh, fish, csh, or sh, and without Windows quoting corruption."""
    ssh_bin = shutil.which("ssh") or "ssh"
    cmd = [ssh_bin, "-tt", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3"]
    if spec.get("port"):
        cmd += ["-p", str(spec["port"])]
    target = str(spec.get("target") or spec.get("host") or "")
    folder = str(spec.get("folder") or "~")
    # Pass remote folder via base64 so spaces, quotes, $, ~, and Windows CreateProcessW
    # argument quoting can NEVER corrupt the path or fail under fish/csh.
    b64_folder = base64.b64encode(folder.encode("utf-8")).decode("ascii")
    remote_script = (
        "sh -c '"
        f"D=$(printf %s {b64_folder} | base64 -d 2>/dev/null || echo ~); "
        "case \"$D\" in \"~\") D=\"$HOME\";; \"~/\"*) D=\"$HOME/${D#~/}\";; esac; "
        "cd \"$D\" 2>/dev/null || cd \"$HOME\"; "
        "S=\"${SHELL:-/bin/sh}\"; [ -x \"$S\" ] || S=/bin/sh; "
        "exec \"$S\" -l'"
    )
    cmd += [target, remote_script]
    return cmd


def auth_terminal_cmd(target: str, port: int | None = None) -> list[str]:
    """Interactive SSH login command for completing first-time host key / password / 2FA auth."""
    ssh_bin = shutil.which("ssh") or "ssh"
    cmd = [ssh_bin, "-tt"]
    if port:
        cmd += ["-p", str(port)]
    cmd.append(str(target))
    return cmd


# Self-contained stdlib-only Python 3 remote JSON-RPC agent.
# Injected on stdin line 1 (base64); lines 2..N are JSON-RPC requests.
_REMOTE_AGENT_SCRIPT = r'''
import hashlib, json, math, os, platform, shutil, signal, subprocess, sys, tempfile, threading, time, uuid
from pathlib import Path
try:
    import pwd
except ImportError:
    pwd = None

_OUT = sys.stdout
sys.stdout = sys.stderr
_OUT_LOCK = threading.Lock()
_SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", "target", ".mypy_cache"})
_LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".jsx": "javascript", ".json": "json", ".toml": "ini", ".yaml": "yaml", ".yml": "yaml", ".md": "markdown",
    ".rs": "rust", ".go": "go", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".java": "java",
    ".sh": "bash", ".ps1": "powershell", ".css": "css", ".html": "xml", ".xml": "xml", ".sql": "sql",
}
_OUTPUT_LIMIT = 16 * 1024 * 1024
_PROCESS_LIMIT = 16
_DIFF_LIMIT = 400_000
_FILE_LIMIT = 512 * 1024

def _send(obj):
    line = json.dumps(obj, ensure_ascii=False, default=str) + "\n"
    with _OUT_LOCK:
        _OUT.write(line)
        _OUT.flush()

def _load_login_env():
    env = dict(os.environ)
    shell = env.get("SHELL") or ""
    if not shell:
        try:
            shell = (pwd.getpwuid(os.getuid()).pw_shell if pwd is not None else "") or "/bin/sh"
        except Exception:
            shell = "/bin/sh"
    base_name = os.path.basename(shell)
    if base_name in ("bash", "zsh", "sh", "ksh", "dash"):
        try:
            probe_py = sys.executable or "python3"
            res = subprocess.run(
                [shell, "-lc", f'"{probe_py}" -c "import json,os;print(\'__HENV__\'+json.dumps(dict(os.environ)))"'],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=3.0, errors="replace"
            )
            if res.returncode == 0 and "__HENV__" in res.stdout:
                raw = res.stdout.split("__HENV__", 1)[1].strip().splitlines()[0]
                loaded = json.loads(raw)
                if isinstance(loaded, dict) and loaded.get("PATH"):
                    env.update({str(k): str(v) for k, v in loaded.items()})
        except Exception:
            pass
    home = os.path.expanduser("~")
    extras = [
        os.path.join(home, ".local", "bin"),
        os.path.join(home, ".cargo", "bin"),
        os.path.join(home, "bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
    ]
    cur_path = env.get("PATH", "")
    parts = [p for p in cur_path.split(os.pathsep) if p]
    for ex in extras:
        if os.path.isdir(ex) and ex not in parts:
            parts.append(ex)
    env["PATH"] = os.pathsep.join(parts)
    return env, shell

BASE_ENV, USER_SHELL = _load_login_env()
_UMASK = os.umask(0o022)
os.umask(_UMASK)
_TMP_DIR = Path(tempfile.mkdtemp(prefix="harness-ssh-"))
_PROCS = {}
_PROCS_LOCK = threading.RLock()

def _expand_path(raw):
    text = str(raw or "~").strip() or "~"
    if text == "~":
        return Path.home()
    if text.startswith("~/"):
        return Path.home() / text[2:]
    return Path(os.path.expanduser(text))

def _resolve_root(root_raw):
    p = _expand_path(root_raw)
    try:
        return p.resolve(strict=True)
    except OSError:
        raise ValueError(f"remote directory does not exist: {root_raw}")

def _safe_inside(root, rel):
    base = root.resolve()
    raw = str(rel or "").strip().replace("\\", "/")
    if not raw or raw == ".":
        return base
    # Allow relative paths or absolute paths that resolve inside root
    cand = Path(raw) if raw.startswith("/") else (base / raw)
    target = cand.resolve()
    if target != base and base not in target.parents:
        raise ValueError("file path leaves the bound target")
    return target

def _digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def _window(path, offset=0, limit=12000):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 64000:
        raise ValueError("offset must be nonnegative and limit between 1 and 64000 bytes")
    with path.open("rb") as f:
        f.seek(offset)
        raw = f.read(limit)
        size = os.fstat(f.fileno()).st_size
    if offset + len(raw) < size:
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as err:
            if err.reason == "unexpected end of data" and err.start > 0:
                raw = raw[:err.start]
    end = offset + len(raw)
    return {"text": raw.decode("utf-8", errors="replace"), "offset": offset, "next_offset": end,
            "bytes": size, "truncated": end < size}

def _run_tool(cwd, argv, timeout=8.0):
    try:
        return subprocess.run(argv, cwd=str(cwd), env=BASE_ENV, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None

def _git_status_map(root):
    res = _run_tool(root, ["git", "status", "--porcelain", "-uall"], timeout=5.0)
    if res is None or res.returncode != 0:
        return {}
    out = {}
    for ln in res.stdout.splitlines():
        if len(ln) < 4:
            continue
        code = ln[:2].strip() or "M"
        rel = ln[3:].strip()
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1].strip()
        rel = rel.strip('"').replace("\\", "/")
        if rel and not rel.endswith("/"):
            out[rel] = code
    return out

def _git_info(root):
    empty = {"is_git": False, "branch": "", "dirty_count": 0, "diff_added": 0, "diff_removed": 0}
    inside = _run_tool(root, ["git", "rev-parse", "--is-inside-work-tree"], timeout=3.0)
    if inside is None or inside.returncode != 0 or inside.stdout.strip().lower() != "true":
        return empty
    br = _run_tool(root, ["git", "branch", "--show-current"], timeout=3.0)
    branch = br.stdout.strip() if br and br.returncode == 0 else ""
    if not branch:
        br2 = _run_tool(root, ["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=3.0)
        branch = br2.stdout.strip() if br2 and br2.returncode == 0 else ""
    st = _git_status_map(root)
    dirty = len(st)
    added = removed = 0
    if dirty:
        ns = _run_tool(root, ["git", "diff", "HEAD", "--numstat"], timeout=5.0)
        if ns is None or ns.returncode != 0:
            ns = _run_tool(root, ["git", "diff", "--numstat"], timeout=5.0)
        if ns and ns.returncode == 0:
            for ln in ns.stdout.splitlines():
                parts = ln.split("\t")
                if len(parts) >= 2:
                    if parts[0].isdigit():
                        added += int(parts[0])
                    if parts[1].isdigit():
                        removed += int(parts[1])
        untracked = [k for k, v in st.items() if v == "??"][:20]
        for rel in untracked:
            p = root / rel
            if p.is_file() and not p.is_symlink():
                try:
                    raw = p.read_bytes()[:65536]
                    if b"\x00" not in raw[:2048]:
                        added += len(raw.splitlines())
                except OSError:
                    pass
    return {"is_git": True, "branch": branch, "dirty_count": dirty, "diff_added": added, "diff_removed": removed}

def _git_changes(root):
    info = _git_info(root)
    if not info["is_git"]:
        return {"folder": root.name, "root": str(root), "branch": "", "files": [], "worktree": {"is_worktree": False}}
    st = _git_status_map(root)
    files = []
    for rel, code in sorted(st.items()):
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
            d = _run_tool(root, ["git", "diff", "HEAD", "--", rel], timeout=8.0)
            if d is None or d.returncode != 0:
                d = _run_tool(root, ["git", "diff", "--", rel], timeout=8.0)
            diff_text = (d.stdout if d else "")[:_DIFF_LIMIT]
            for ln in diff_text.splitlines():
                if ln.startswith("+") and not ln.startswith("+++"):
                    added += 1
                elif ln.startswith("-") and not ln.startswith("---"):
                    removed += 1
        files.append({"path": rel, "status": code, "added": added, "removed": removed, "diff": diff_text})
    return {"folder": root.name, "root": str(root), "branch": info["branch"], "files": files, "worktree": {"is_worktree": False}}

class _RemoteProc:
    def __init__(self, command, cwd, env, timeout, scope):
        self.id = uuid.uuid4().hex
        self.scope = scope
        self.command = command
        self.cwd = str(cwd)
        self.timeout = timeout
        self.output = _TMP_DIR / (self.id + ".log")
        self.output.touch()
        self.started = time.monotonic()
        self.ended = None
        self.reason = None
        self.cleanup_error = None
        self.lock = threading.RLock()
        self.done = threading.Event()
        if isinstance(command, str) and command:
            argv = (["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
                    if os.name == "nt" else ["/bin/sh", "-c", command])
        elif isinstance(command, list) and command and all(isinstance(x, str) for x in command):
            argv = command
        else:
            raise ValueError("command must be a nonempty argv list or shell string")
        merged_env = {**BASE_ENV, **{str(k): str(v) for k, v in (env or {}).items()}}
        popts = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                 if os.name == "nt" else {"start_new_session": True})
        self.process = subprocess.Popen(
            argv, cwd=str(cwd), env=merged_env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **popts
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        threading.Thread(target=self._watch, daemon=True).start()

    def _read(self):
        try:
            with self.output.open("ab", buffering=0) as out:
                total = 0
                while True:
                    chunk = self.process.stdout.read1(8192)
                    if not chunk:
                        break
                    rem = max(0, _OUTPUT_LIMIT - total)
                    if rem:
                        out.write(chunk[:rem])
                    total += len(chunk)
                    if total > _OUTPUT_LIMIT:
                        self.stop("output_limit")
                        break
        except OSError as err:
            self.cleanup_error = str(err)
            self.stop("output_error")
        finally:
            try:
                self.process.stdout.close()
            except Exception:
                pass

    def _kill_group(self):
        try:
            if hasattr(os, "killpg"):
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                self.process.kill()
        except OSError as err:
            self.cleanup_error = str(err)

    def stop(self, reason="cancelled"):
        with self.lock:
            if self.ended is None:
                self.reason = self.reason or reason
                self._kill_group()

    def _watch(self):
        try:
            try:
                self.process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                self.stop("timeout")
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            self._kill_group()
            self.reader.join(5)
        except OSError as err:
            self.cleanup_error = str(err)
        finally:
            self.ended = time.monotonic()
            self.done.set()

    def result(self):
        size = self.output.stat().st_size if self.output.exists() else 0
        return {
            "process_id": self.id, "scope": self.scope,
            "status": "running" if self.ended is None else "unknown" if self.process.poll() is None else self.reason or "exited",
            "exit_code": self.process.poll(), "stop_requested": self.reason,
            "cwd": self.cwd, "command": self.command, "timeout": self.timeout,
            "seconds": round((self.ended or time.monotonic()) - self.started, 3),
            "output": _window(self.output, max(0, size - 6000), 6000),
            "ready": self.done.is_set(),
            "cleanup": {"scope": "process_group", "error": self.cleanup_error},
        }

def _handle(req):
    m = req.get("method")
    p = req.get("params") or {}
    if m == "probe":
        home = str(Path.home())
        out = {
            "home": home, "os": platform.system(), "arch": platform.machine(),
            "shell": USER_SHELL, "user": BASE_ENV.get("USER") or "", "hostname": platform.node(),
            "git": bool(shutil.which("git", path=BASE_ENV.get("PATH"))),
            "gh": bool(shutil.which("gh", path=BASE_ENV.get("PATH"))),
        }
        if p.get("path"):
            cand = _expand_path(p["path"])
            exists = cand.exists()
            is_dir = cand.is_dir()
            out["path"] = str(cand.resolve()) if exists else str(cand)
            out["path_exists"] = exists
            out["path_is_dir"] = is_dir
        return out
    if m == "browse":
        raw = p.get("path") or "~"
        target = _expand_path(raw)
        if not target.exists():
            raise ValueError(f"path does not exist: {raw}")
        if not target.is_dir():
            raise ValueError(f"not a directory: {raw}")
        try:
            shown = Path(os.path.abspath(str(target)))
        except OSError:
            shown = target
        try:
            real = target.resolve()
        except OSError:
            real = shown
        rows = []
        show_hidden = bool(p.get("hidden"))
        try:
            items = sorted(shown.iterdir(), key=lambda x: x.name.lower())
        except OSError as err:
            raise ValueError(f"cannot read directory {shown}: {err.strerror or err}")
        for item in items:
            name = item.name
            if not show_hidden and name.startswith("."):
                continue
            try:
                is_link = item.is_symlink()
                is_dir = item.is_dir()
            except OSError:
                continue
            if not is_dir:
                continue
            is_git = False
            try:
                is_git = (item / ".git").exists()
            except OSError:
                pass
            rows.append({"name": name, "path": str(item), "git": is_git, "symlink": is_link})
            if len(rows) >= 500:
                break
        parent = str(shown.parent) if shown.parent != shown else None
        is_git_here = False
        try:
            is_git_here = (shown / ".git").exists()
        except OSError:
            pass
        return {
            "path": str(shown), "realpath": str(real), "parent": parent,
            "home": str(Path.home()), "is_git": is_git_here, "folders": rows,
        }
    if m == "tree":
        root = _resolve_root(p["root"])
        rel = str(p.get("path") or "").strip().replace("\\", "/").strip("/")
        target = _safe_inside(root, rel)
        if not target.is_dir():
            raise ValueError(f"not a directory: {rel!r}")
        status = _git_status_map(root)
        entries = []
        for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if item.name in _SKIP_DIRS:
                continue
            item_rel = item.relative_to(root).as_posix()
            try:
                is_dir = item.is_dir()
            except OSError:
                continue
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
    if m == "read":
        root = _resolve_root(p["root"])
        target = _safe_inside(root, p["path"])
        if not target.is_file():
            raise ValueError(f"no file {p['path']!r}")
        if p.get("mode") == "viewer":
            size = target.stat().st_size
            raw = target.read_bytes()[:_FILE_LIMIT]
            is_bin = b"\x00" in raw[:4096]
            text = "" if is_bin else raw.decode("utf-8", errors="replace")
            return {"path": str(target.relative_to(root).as_posix()), "name": target.name, "full_path": str(target),
                    "binary": is_bin, "size": size, "text": text, "lines": text.count("\n") + (1 if text else 0),
                    "truncated": size > _FILE_LIMIT, "language": _LANG_BY_EXT.get(target.suffix.lower(), "")}
        offset = int(p.get("offset", 0))
        limit = int(p.get("limit", 12000))
        return {**_window(target, offset, limit), "sha256": _digest(target)}
    if m == "write":
        root = _resolve_root(p["root"])
        target = _safe_inside(root, p["path"])
        actual = _digest(target) if target.exists() else None
        if actual != p.get("expected"):
            return {"status": "error", "error": "conflict", "message": "file changed; read before replacing", "sha256": actual}
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(str(p["text"]).encode("utf-8"))
                stream.flush()
                try:
                    os.fsync(stream.fileno())
                except OSError:
                    pass
            try:
                os.chmod(tmp, target.stat().st_mode if target.exists() else (0o666 & ~_UMASK))
            except OSError:
                pass
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
        return {"path": str(target), "sha256": _digest(target)}
    if m == "search":
        root = _resolve_root(p["root"])
        query = str(p.get("query") or "").strip().lower()
        limit = int(p.get("limit") or 40)
        matches, q, visited = [], [root], 0
        while q and visited < 3000 and len(matches) < limit:
            cur = q.pop(0)
            try:
                children = sorted(cur.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except OSError:
                continue
            for item in children:
                if item.name in _SKIP_DIRS or item.name.startswith("."):
                    continue
                visited += 1
                try:
                    is_dir = item.is_dir()
                except OSError:
                    continue
                rel = item.relative_to(root).as_posix()
                if not query or query in rel.lower():
                    matches.append({"path": rel, "name": item.name, "dir": is_dir})
                    if len(matches) >= limit:
                        break
                if is_dir and not item.is_symlink() and visited < 2000:
                    q.append(item)
        return {"folder": root.name, "matches": matches}
    if m == "git_info":
        root = _resolve_root(p["root"])
        return _git_info(root)
    if m == "git_changes":
        root = _resolve_root(p["root"])
        return _git_changes(root)
    if m == "git_revert":
        root = _resolve_root(p["root"])
        rel = str(p.get("path") or "").strip().replace("\\", "/")
        if not rel:
            raise ValueError("path is required")
        target = _safe_inside(root, rel)
        st = _git_status_map(root)
        if st.get(rel) == "??":
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        else:
            r1 = _run_tool(root, ["git", "checkout", "HEAD", "--", rel], timeout=10.0)
            if r1 is None or r1.returncode != 0:
                r2 = _run_tool(root, ["git", "checkout", "--", rel], timeout=10.0)
                if r2 is None or r2.returncode != 0:
                    err = (r2.stderr if r2 else "") or (r1.stderr if r1 else "") or "git checkout failed"
                    raise ValueError(err.strip()[:300])
        return _git_changes(root)
    if m == "prs":
        root = _resolve_root(p["root"])
        if not shutil.which("gh", path=BASE_ENV.get("PATH")):
            return {"prs": []}
        res = _run_tool(root, ["gh", "pr", "list", "--limit", "20", "--json", "number,title,state,url,headRefName"], timeout=6.0)
        if res is None or res.returncode != 0 or not res.stdout.strip():
            return {"prs": []}
        try:
            rows = json.loads(res.stdout)
        except ValueError:
            return {"prs": []}
        if not isinstance(rows, list):
            return {"prs": []}
        return {"prs": [
            {"number": r.get("number"), "title": str(r.get("title") or ""), "state": str(r.get("state") or "OPEN"),
             "url": str(r.get("url") or ""), "branch": str(r.get("headRefName") or "")}
            for r in rows if isinstance(r, dict)
        ]}
    if m == "proc_start":
        root = _resolve_root(p["root"])
        seconds = float(p.get("timeout", 120))
        if not math.isfinite(seconds) or not 0 < seconds <= 3600:
            raise ValueError("timeout must be between 0 and 3600 seconds")
        with _PROCS_LOCK:
            if sum(not pr.done.is_set() for pr in _PROCS.values()) >= _PROCESS_LIMIT:
                raise ValueError("task process limit reached")
            cwd = _safe_inside(root, p.get("cwd", "."))
            pr = _RemoteProc(p["command"], cwd, p.get("env"), seconds, p.get("scope") or "execution")
            _PROCS[pr.id] = pr
            return pr.result()
    if m == "proc_poll":
        with _PROCS_LOCK:
            pr = _PROCS[p["process_id"]]
        return pr.result()
    if m == "proc_output":
        with _PROCS_LOCK:
            pr = _PROCS[p["process_id"]]
        return _window(pr.output, int(p.get("offset", 0)), int(p.get("limit", 12000)))
    if m == "proc_cancel":
        with _PROCS_LOCK:
            pr = _PROCS[p["process_id"]]
        pr.stop(str(p.get("reason") or "cancelled"))
        pr.done.wait(5)
        return pr.result()
    if m == "proc_release":
        ids = p.get("ids")
        with _PROCS_LOCK:
            targets = [(_pid, _PROCS[_pid]) for _pid in (ids if ids is not None else list(_PROCS)) if _pid in _PROCS]
        for _, pr in targets:
            pr.stop("session_closed")
        deadline = time.monotonic() + 8
        for _, pr in targets:
            pr.done.wait(max(0, deadline - time.monotonic()))
        out = {}
        with _PROCS_LOCK:
            for pid, pr in targets:
                out[pid] = pr.result()
                _PROCS.pop(pid, None)
        return {"processes": out}
    raise ValueError(f"unknown rpc method {m!r}")

_send({
    "ready": True, "home": str(Path.home()), "os": platform.system(), "arch": platform.machine(),
    "shell": USER_SHELL, "user": BASE_ENV.get("USER") or "", "hostname": platform.node(),
})

try:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        rid = None
        try:
            req = json.loads(line)
            rid = req.get("id")
            res = _handle(req)
            _send({"id": rid, "ok": True, "result": res})
        except Exception as err:
            _send({"id": rid, "ok": False, "error": type(err).__name__, "message": str(err)})
finally:
    with _PROCS_LOCK:
        for pr in list(_PROCS.values()):
            pr.stop("bridge_closed")
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
'''

_AGENT_B64 = base64.b64encode(_REMOTE_AGENT_SCRIPT.encode("utf-8")).decode("ascii")
_REMOTE_BOOTSTRAP = (
    "sh -c '"
    "P=\"\"; "
    "for c in python3 python /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do "
    "command -v \"$c\" >/dev/null 2>&1 && { P=\"$c\"; break; }; "
    "done; "
    "[ -n \"$P\" ] || { echo HARNESS_NO_PYTHON >&2; exit 127; }; "
    "exec \"$P\" -u -c \"import base64,sys;exec(base64.b64decode(sys.stdin.readline()))\"'"
)


def _default_spawn(target: str, port: int | None) -> subprocess.Popen:
    ssh_bin = shutil.which("ssh") or "ssh"
    cmd = [
        ssh_bin, "-T",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={DEFAULT_CONNECT_TIMEOUT}",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
    ]
    if port:
        cmd += ["-p", str(port)]
    cmd += [target, _REMOTE_BOOTSTRAP]
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **flags,
    )


class SshClient:
    """Thread-safe persistent JSON-RPC client over one SSH connection."""

    def __init__(self, target: str, port: int | None = None, *, spawn_fn=None):
        self.target = str(target)
        self.port = int(port) if port else None
        self._spawn_fn = spawn_fn or _default_spawn
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._pending: dict[str, queue.Queue] = {}
        self._stderr_lines: list[str] = []
        self._ready_info: dict = {}
        self._last_used = time.monotonic()
        self._closed = False

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start_locked(self) -> None:
        self._stop_proc_locked()
        self._stderr_lines = []
        proc = self._spawn_fn(self.target, self.port)
        self._proc = proc
        ready_q: queue.Queue = queue.Queue(maxsize=1)

        def _read_stderr():
            try:
                assert proc.stderr is not None
                for ln in proc.stderr:
                    self._stderr_lines.append(ln.rstrip("\r\n"))
                    if len(self._stderr_lines) > 80:
                        self._stderr_lines = self._stderr_lines[-80:]
            except Exception:
                pass

        def _read_stdout():
            sent_ready = False
            try:
                assert proc.stdout is not None
                for ln in proc.stdout:
                    ln = ln.strip()
                    if not ln or not ln.startswith("{"):
                        continue
                    try:
                        msg = json.loads(ln)
                    except ValueError:
                        continue
                    if not sent_ready and msg.get("ready"):
                        sent_ready = True
                        ready_q.put(("ok", msg))
                        continue
                    rid = msg.get("id")
                    if rid:
                        with self._lock:
                            slot = self._pending.pop(rid, None)
                        if slot is not None:
                            slot.put(msg)
            except Exception:
                pass
            finally:
                rc = proc.poll()
                if not sent_ready:
                    ready_q.put(("eof", rc))
                err_msg = {"ok": False, "error": "SshDisconnected", "message": "SSH connection closed"}
                with self._lock:
                    if self._proc is proc:
                        pending = list(self._pending.values())
                        self._pending.clear()
                    else:
                        pending = []
                for slot in pending:
                    slot.put(err_msg)

        threading.Thread(target=_read_stderr, name=f"ssh-err-{self.target}", daemon=True).start()
        threading.Thread(target=_read_stdout, name=f"ssh-out-{self.target}", daemon=True).start()

        try:
            assert proc.stdin is not None
            proc.stdin.write(_AGENT_B64 + "\n")
            proc.stdin.flush()
        except OSError as err:
            self._stop_proc_locked()
            raise classify_ssh_error("\n".join(self._stderr_lines) or str(err), proc.poll()) from None

        try:
            kind, payload = ready_q.get(timeout=DEFAULT_CONNECT_TIMEOUT + 5)
        except queue.Empty:
            self._stop_proc_locked()
            raise classify_ssh_error("\n".join(self._stderr_lines) or "connection timed out", proc.poll()) from None

        if kind != "ok":
            # Give stderr reader a brief moment to collect final lines
            time.sleep(0.05)
            self._stop_proc_locked()
            raise classify_ssh_error("\n".join(self._stderr_lines), payload)

        self._ready_info = dict(payload)
        self._last_used = time.monotonic()

    def _stop_proc_locked(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
        except Exception:
            pass
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass

    def ensure_connected(self) -> dict:
        with self._lock:
            if self._closed:
                raise SshError("SSH client is closed", code="closed")
            if not self._alive():
                self._start_locked()
            self._last_used = time.monotonic()
            return dict(self._ready_info)

    def call(self, method: str, params: dict | None = None, *, timeout: float = DEFAULT_RPC_TIMEOUT,
             retry_on_disconnect: bool = True) -> dict:
        for attempt in range(2 if retry_on_disconnect else 1):
            self.ensure_connected()
            rid = uuid.uuid4().hex
            slot: queue.Queue = queue.Queue(maxsize=1)
            with self._lock:
                proc = self._proc
                if proc is None or proc.poll() is not None:
                    if attempt == 0 and retry_on_disconnect:
                        continue
                    raise SshError("SSH connection is not active", code="disconnected")
                self._pending[rid] = slot
            payload = json.dumps({"id": rid, "method": method, "params": params or {}}, ensure_ascii=False) + "\n"
            try:
                with self._write_lock:
                    assert proc.stdin is not None
                    proc.stdin.write(payload)
                    proc.stdin.flush()
            except OSError:
                with self._lock:
                    self._pending.pop(rid, None)
                    self._stop_proc_locked()
                if attempt == 0 and retry_on_disconnect:
                    continue
                raise SshError("SSH connection dropped while sending request", code="disconnected") from None

            try:
                reply = slot.get(timeout=timeout)
            except queue.Empty:
                with self._lock:
                    self._pending.pop(rid, None)
                raise SshError(f"SSH RPC {method!r} timed out after {timeout:.0f}s", code="timeout") from None

            self._last_used = time.monotonic()
            if reply.get("ok"):
                return reply.get("result") or {}
            if reply.get("error") == "SshDisconnected" and attempt == 0 and retry_on_disconnect:
                with self._lock:
                    self._stop_proc_locked()
                continue
            err_type = str(reply.get("error") or "Error")
            msg = str(reply.get("message") or f"remote {method} failed")
            if err_type == "ValueError":
                raise ValueError(msg)
            if err_type == "PermissionError":
                raise SshError(msg, code="permission_denied")
            if err_type == "FileNotFoundError":
                raise SshError(msg, code="path_not_found")
            raise SshError(msg, code="remote_error")
        raise SshError(f"SSH RPC {method!r} failed", code="disconnected")

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop_proc_locked()


class SshPool:
    """Process-wide pool of persistent SshClient instances keyed by `(target, port)`."""

    def __init__(self, *, spawn_fn=None):
        self._lock = threading.RLock()
        self._clients: dict[tuple[str, int | None], SshClient] = {}
        self._spawn_fn = spawn_fn

    def get(self, spec: dict) -> SshClient:
        target = str(spec.get("target") or spec.get("host") or "").strip()
        port = int(spec["port"]) if spec.get("port") not in (None, "", 0) else None
        key = (target, port)
        with self._lock:
            now = time.monotonic()
            stale = [k for k, c in self._clients.items()
                     if k != key and (not c._alive() or (now - c._last_used) > IDLE_TTL_SECONDS)]
            for k in stale:
                self._clients.pop(k).close()
            client = self._clients.get(key)
            if client is None or client._closed:
                client = SshClient(target, port, spawn_fn=self._spawn_fn)
                self._clients[key] = client
            return client

    def drop(self, spec: dict) -> None:
        target = str(spec.get("target") or spec.get("host") or "").strip()
        port = int(spec["port"]) if spec.get("port") not in (None, "", 0) else None
        with self._lock:
            client = self._clients.pop((target, port), None)
        if client is not None:
            client.close()

    def close_all(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for c in clients:
            c.close()


POOL = SshPool()
atexit.register(POOL.close_all)
