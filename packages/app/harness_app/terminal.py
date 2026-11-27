"""Interactive local PTY terminal sessions for the desktop app and browser UI.

A single host-side protocol serves both the Tauri desktop shell and plain browser tabs:
  POST /api/app/terminal {action: "open", cwd?, cols?, rows?}   -> {id, cwd, shell, pty}
  POST /api/app/terminal {action: "input", id, data}            -> {ok: true}
  POST /api/app/terminal {action: "resize", id, cols, rows}     -> {ok: true}
  POST /api/app/terminal {action: "close", id}                  -> {ok: true}
  GET  /api/app/terminal?action=list                            -> {sessions: [...]}
  GET  /api/app/terminal?action=read&id=ID&after=N              -> {chunks, alive, exit_code}
  GET  /api/app/terminal?action=stream&id=ID&after=N            -> SSE stream of output chunks

Uses pywinpty on Windows when installed (falling back to a pipe subprocess) and stdlib
pty on POSIX. Every spawned shell is tracked and cleaned up on close or process exit.
"""
import atexit
import base64
from collections import deque
import ctypes
import json
import locale
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

MAX_CHUNKS = 2000
IDLE_TIMEOUT = 1800.0
KEEPALIVE_SECONDS = 15.0


def _oem_encoding() -> str:
    if os.name == "nt":
        try:
            cp = int(ctypes.windll.kernel32.GetOEMCP())
            if cp > 0:
                return f"cp{cp}"
        except Exception:
            pass
    return locale.getpreferredencoding(False) or "utf-8"


def _decode_console(raw: bytes, oem_enc: str = "utf-8") -> str:
    """Decode terminal output cleanly: prefer strict UTF-8 per line, falling back to
    Windows OEM codepage (e.g. cp936 on zh-CN Windows) so neither cmd.exe banners nor
    UTF-8 CLI tools produce mojibake."""
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    parts: list[str] = []
    for chunk in raw.splitlines(keepends=True):
        try:
            parts.append(chunk.decode("utf-8"))
        except UnicodeDecodeError:
            parts.append(chunk.decode(oem_enc, "replace"))
    return "".join(parts)


def _default_shell() -> list[str]:
    if os.name == "nt":
        for name in ("pwsh.exe", "powershell.exe", "cmd.exe"):
            found = shutil.which(name)
            if found:
                return [found, "-NoLogo"] if "powershell" in name or "pwsh" in name else [found]
        return ["cmd.exe"]
    shell = os.environ.get("SHELL") or shutil.which("bash") or shutil.which("zsh") or "/bin/sh"
    return [shell, "-i"]


class _ConPty:
    """Native Windows 10/11 ConPTY (CreatePseudoConsole) using pure stdlib ctypes.

    Gives packaged Windows builds a real interactive PowerShell/cmd PTY (live typing &
    paste echo, ANSI colors, Tab completion, arrow-key history, Ctrl+C interrupt, resize)
    with zero external native wheel dependencies."""

    def __init__(self, cmd: list[str], cwd: str, env: dict[str, str], cols: int, rows: int):
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not hasattr(k32, "CreatePseudoConsole"):
            raise OSError("Windows ConPTY is not available on this OS version")
        self._k32 = k32
        self._closed = False
        self._hpc = None
        self._in_w = None
        self._out_r = None
        self._hproc = None
        self._exit_code: int | None = None

        class _COORD(ctypes.Structure):
            _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

        class _STARTUPINFOEXW(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
                ("lpAttributeList", ctypes.c_void_p),
            ]

        class _PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
            ]

        self._COORD = _COORD
        k32.CreatePipe.argtypes = [ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p, wintypes.DWORD]
        k32.CreatePipe.restype = wintypes.BOOL
        k32.CreatePseudoConsole.argtypes = [_COORD, wintypes.HANDLE, wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        k32.CreatePseudoConsole.restype = ctypes.c_long
        k32.ResizePseudoConsole.argtypes = [wintypes.HANDLE, _COORD]
        k32.ResizePseudoConsole.restype = ctypes.c_long
        k32.ClosePseudoConsole.argtypes = [wintypes.HANDLE]
        k32.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
        k32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        k32.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
        k32.UpdateProcThreadAttribute.restype = wintypes.BOOL
        k32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
        k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(_STARTUPINFOEXW), ctypes.POINTER(_PROCESS_INFORMATION)]
        k32.CreateProcessW.restype = wintypes.BOOL
        k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        k32.ReadFile.restype = wintypes.BOOL
        k32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        k32.WriteFile.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.GetExitCodeProcess.restype = wintypes.BOOL

        in_r, in_w = wintypes.HANDLE(), wintypes.HANDLE()
        out_r, out_w = wintypes.HANDLE(), wintypes.HANDLE()
        if not k32.CreatePipe(ctypes.byref(in_r), ctypes.byref(in_w), None, 0):
            raise OSError(f"CreatePipe(in) failed: {ctypes.get_last_error()}")
        if not k32.CreatePipe(ctypes.byref(out_r), ctypes.byref(out_w), None, 0):
            k32.CloseHandle(in_r)
            k32.CloseHandle(in_w)
            raise OSError(f"CreatePipe(out) failed: {ctypes.get_last_error()}")

        hpc = wintypes.HANDLE()
        hr = k32.CreatePseudoConsole(_COORD(cols, rows), in_r, out_w, 0, ctypes.byref(hpc))
        k32.CloseHandle(in_r)
        k32.CloseHandle(out_w)
        if hr != 0:
            k32.CloseHandle(in_w)
            k32.CloseHandle(out_r)
            raise OSError(f"CreatePseudoConsole failed: 0x{hr & 0xFFFFFFFF:x}")

        attr_buf = None
        try:
            size = ctypes.c_size_t(0)
            k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            attr_buf = ctypes.create_string_buffer(size.value)
            if not k32.InitializeProcThreadAttributeList(attr_buf, 1, 0, ctypes.byref(size)):
                raise OSError(f"InitializeProcThreadAttributeList failed: {ctypes.get_last_error()}")
            if not k32.UpdateProcThreadAttribute(
                attr_buf, 0, 0x00020016, hpc.value, ctypes.sizeof(wintypes.HANDLE), None, None
            ):
                raise OSError(f"UpdateProcThreadAttribute failed: {ctypes.get_last_error()}")

            si = _STARTUPINFOEXW()
            si.cb = ctypes.sizeof(_STARTUPINFOEXW)
            si.dwFlags = 0x00000100  # STARTF_USESTDHANDLES (null handles attach cleanly to ConPTY)
            si.lpAttributeList = ctypes.addressof(attr_buf)
            pi = _PROCESS_INFORMATION()
            cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(cmd))
            env_str = "\0".join(f"{k}={v}" for k, v in env.items()) + "\0\0"
            env_buf = ctypes.create_unicode_buffer(env_str)
            flags = 0x00080000 | 0x00000400  # EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT
            if not k32.CreateProcessW(
                None, cmdline, None, None, False, flags, ctypes.byref(env_buf),
                cwd, ctypes.byref(si), ctypes.byref(pi)
            ):
                raise OSError(f"CreateProcessW failed: {ctypes.get_last_error()}")
            k32.CloseHandle(pi.hThread)
            self._hpc = hpc
            self._in_w = in_w
            self._out_r = out_r
            self._hproc = pi.hProcess
        except Exception:
            k32.ClosePseudoConsole(hpc)
            k32.CloseHandle(in_w)
            k32.CloseHandle(out_r)
            raise
        finally:
            if attr_buf is not None:
                k32.DeleteProcThreadAttributeList(attr_buf)

    def read(self, size: int = 4096) -> bytes:
        from ctypes import wintypes

        if self._closed or not self._out_r:
            return b""
        buf = ctypes.create_string_buffer(size)
        got = wintypes.DWORD(0)
        ok = self._k32.ReadFile(self._out_r, buf, size, ctypes.byref(got), None)
        if not ok or got.value == 0:
            return b""
        return buf.raw[:got.value]

    def write(self, data: bytes) -> None:
        from ctypes import wintypes

        if self._closed or not self._in_w or not data:
            return
        written = wintypes.DWORD(0)
        self._k32.WriteFile(self._in_w, data, len(data), ctypes.byref(written), None)

    def resize(self, cols: int, rows: int) -> None:
        if self._closed or not self._hpc:
            return
        self._k32.ResizePseudoConsole(self._hpc, self._COORD(cols, rows))

    def isalive(self) -> bool:
        from ctypes import wintypes

        if self._closed or not self._hproc:
            return False
        code = wintypes.DWORD(0)
        if not self._k32.GetExitCodeProcess(self._hproc, ctypes.byref(code)):
            return False
        if code.value == 259:  # STILL_ACTIVE
            return True
        self._exit_code = int(code.value)
        return False

    @property
    def exitstatus(self) -> int | None:
        self.isalive()
        return self._exit_code

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._hpc:
            try:
                self._k32.ClosePseudoConsole(self._hpc)
            except Exception:
                pass
            self._hpc = None
        if self._hproc:
            try:
                if self._exit_code is None:
                    self._k32.TerminateProcess(self._hproc, 0)
            except Exception:
                pass
            try:
                self._k32.CloseHandle(self._hproc)
            except Exception:
                pass
            self._hproc = None
        for attr in ("_in_w", "_out_r"):
            handle = getattr(self, attr, None)
            if handle:
                try:
                    self._k32.CloseHandle(handle)
                except Exception:
                    pass
                setattr(self, attr, None)


class TerminalSession:
    """One interactive shell process with a ring buffer of output chunks and live subscribers."""

    def __init__(self, cwd: Path, cols: int = 100, rows: int = 28, cmd: list[str] | None = None, label: str = ""):
        self.id = "term-" + uuid.uuid4().hex[:10]
        self.cwd = str(cwd)
        self.cols = max(20, min(400, int(cols or 100)))
        self.rows = max(5, min(200, int(rows or 28)))
        self.created = time.time()
        self.touched = self.created
        self.chunks: deque[tuple[int, str]] = deque(maxlen=MAX_CHUNKS)
        self._seq = 0
        self._cond = threading.Condition()
        self._closed = False
        self.exit_code: int | None = None
        self.pty_kind = "pipe"
        self.shell = ""
        self._custom_cmd = list(cmd) if cmd else None
        self._label = label
        self._proc = None
        self._winpty = None
        self._conpty: _ConPty | None = None
        self._master_fd: int | None = None
        self._oem_enc = _oem_encoding()
        self._start()

    def _start(self) -> None:
        cmd = self._custom_cmd or _default_shell()
        self.shell = self._label or Path(cmd[0]).name
        env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor",
               "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        if os.name == "nt":
            try:
                from winpty import PtyProcess

                self._winpty = PtyProcess.spawn(cmd, cwd=self.cwd, env=env, dimensions=(self.rows, self.cols))
                self.pty_kind = "winpty"
                threading.Thread(target=self._read_winpty, name=f"pty-{self.id}", daemon=True).start()
                return
            except Exception:
                self._winpty = None
            try:
                self._conpty = _ConPty(cmd, self.cwd, env, self.cols, self.rows)
                self.pty_kind = "conpty"
                threading.Thread(target=self._read_conpty, name=f"conpty-{self.id}", daemon=True).start()
                return
            except Exception:
                self._conpty = None
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            pipe_cmd = [shutil.which("cmd.exe") or "cmd.exe"]
            self.shell = Path(pipe_cmd[0]).name
            self._proc = subprocess.Popen(
                pipe_cmd, cwd=self.cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, bufsize=0, creationflags=flags,
            )
            threading.Thread(target=self._read_pipe, name=f"pipe-{self.id}", daemon=True).start()
            return

        import pty
        import fcntl
        import struct
        import termios

        master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))
        except OSError:
            pass
        try:
            self._proc = subprocess.Popen(
                cmd, cwd=self.cwd, env=env, stdin=slave, stdout=slave, stderr=slave,
                close_fds=True, start_new_session=True,
            )
        finally:
            os.close(slave)
        self._master_fd = master
        self.pty_kind = "pty"
        threading.Thread(target=self._read_posix, name=f"pty-{self.id}", daemon=True).start()

    def _push(self, text: str) -> None:
        if not text:
            return
        with self._cond:
            self._seq += 1
            self.chunks.append((self._seq, text))
            self.touched = time.time()
            self._cond.notify_all()

    def _finish(self, code: int | None) -> None:
        with self._cond:
            self.exit_code = code if code is not None else 0
            self._closed = True
            self._cond.notify_all()

    def _read_winpty(self) -> None:
        try:
            while not self._closed and self._winpty is not None:
                try:
                    data = self._winpty.read(4096)
                except EOFError:
                    break
                except OSError:
                    break
                if not data:
                    if not self._winpty.isalive():
                        break
                    time.sleep(0.02)
                    continue
                self._push(data if isinstance(data, str) else _decode_console(data, self._oem_enc))
        finally:
            code = getattr(self._winpty, "exitstatus", None) if self._winpty is not None else None
            self._finish(code)

    def _read_conpty(self) -> None:
        try:
            while not self._closed and self._conpty is not None:
                raw = self._conpty.read(4096)
                if not raw:
                    break
                self._push(_decode_console(raw, self._oem_enc))
        finally:
            code = self._conpty.exitstatus if self._conpty is not None else 0
            self._finish(code)

    def _read_pipe(self) -> None:
        try:
            stream = self._proc.stdout if self._proc else None
            while not self._closed and stream is not None:
                raw = stream.read(4096)
                if not raw:
                    break
                self._push(_decode_console(raw, self._oem_enc))
        finally:
            code = self._proc.poll() if self._proc else 0
            self._finish(code)

    def _read_posix(self) -> None:
        try:
            while not self._closed and self._master_fd is not None:
                try:
                    raw = os.read(self._master_fd, 4096)
                except OSError:
                    break
                if not raw:
                    break
                self._push(raw.decode("utf-8", "replace"))
        finally:
            code = self._proc.poll() if self._proc else 0
            self._finish(code)

    @property
    def alive(self) -> bool:
        if self._closed:
            return False
        if self._winpty is not None:
            try:
                return bool(self._winpty.isalive())
            except Exception:
                return False
        if self._conpty is not None:
            return self._conpty.isalive()
        if self._proc is not None:
            return self._proc.poll() is None
        return False

    def write(self, data: str) -> None:
        self.touched = time.time()
        if not self.alive:
            raise ValueError("terminal session has exited")
        if self._winpty is not None:
            self._winpty.write(data)
            return
        if self._conpty is not None:
            self._conpty.write(data.encode("utf-8"))
            return
        if self._master_fd is not None:
            os.write(self._master_fd, data.encode("utf-8"))
            return
        if self._proc is not None and self._proc.stdin is not None:
            payload = re.sub(r"\r(?!\n)", "\r\n", data) if os.name == "nt" else data
            try:
                encoded = payload.encode(self._oem_enc if os.name == "nt" else "utf-8")
            except UnicodeEncodeError:
                encoded = payload.encode("utf-8")
            self._proc.stdin.write(encoded)
            self._proc.stdin.flush()

    def resize(self, cols: int, rows: int) -> None:
        self.cols = max(20, min(400, int(cols or self.cols)))
        self.rows = max(5, min(200, int(rows or self.rows)))
        self.touched = time.time()
        if not self.alive:
            return
        if self._winpty is not None:
            try:
                self._winpty.setwinsize(self.rows, self.cols)
            except Exception:
                pass
        elif self._conpty is not None:
            try:
                self._conpty.resize(self.cols, self.rows)
            except Exception:
                pass
        elif self._master_fd is not None:
            try:
                import fcntl
                import struct
                import termios

                fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))
            except OSError:
                pass

    def read_after(self, after: int = 0) -> tuple[list[dict], bool, int | None]:
        with self._cond:
            rows = [{"seq": seq, "data": base64.b64encode(text.encode("utf-8")).decode("ascii")}
                    for seq, text in self.chunks if seq > after]
            return rows, self.alive, self.exit_code

    def stream(self, handler, after: int = 0) -> None:
        handler.answered = True
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "keep-alive")
        handler.end_headers()
        cursor = int(after or 0)
        last_ping = time.monotonic()
        try:
            while True:
                with self._cond:
                    pending = [(seq, text) for seq, text in self.chunks if seq > cursor]
                    alive = not self._closed
                    code = self.exit_code
                    if not pending and alive:
                        self._cond.wait(timeout=1.0)
                        pending = [(seq, text) for seq, text in self.chunks if seq > cursor]
                        alive = not self._closed
                        code = self.exit_code
                for seq, text in pending:
                    cursor = seq
                    payload = json.dumps({"seq": seq, "data": base64.b64encode(text.encode("utf-8")).decode("ascii")})
                    handler.wfile.write(f"id: {seq}\ndata: {payload}\n\n".encode("utf-8"))
                    handler.wfile.flush()
                    last_ping = time.monotonic()
                if not alive:
                    payload = json.dumps({"exit_code": code})
                    handler.wfile.write(f"event: exit\ndata: {payload}\n\n".encode("utf-8"))
                    handler.wfile.flush()
                    return
                if time.monotonic() - last_ping >= KEEPALIVE_SECONDS:
                    handler.wfile.write(b": keepalive\n\n")
                    handler.wfile.flush()
                    last_ping = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        if self._winpty is not None:
            try:
                self._winpty.close(force=True)
            except Exception:
                try:
                    self._winpty.terminate(force=True)
                except Exception:
                    pass
            self._winpty = None
        if self._conpty is not None:
            try:
                self._conpty.close()
            except Exception:
                pass
            self._conpty = None
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def describe(self) -> dict:
        return {"id": self.id, "cwd": self.cwd, "shell": self.shell, "pty": self.pty_kind,
                "cols": self.cols, "rows": self.rows, "alive": self.alive, "exit_code": self.exit_code}


_LOCK = threading.Lock()
_SESSIONS: dict[str, TerminalSession] = {}


def _prune() -> None:
    now = time.time()
    stale = [sid for sid, sess in _SESSIONS.items() if (not sess.alive and now - sess.touched > 60)
             or (now - sess.touched > IDLE_TIMEOUT)]
    for sid in stale:
        sess = _SESSIONS.pop(sid, None)
        if sess is not None:
            sess.close()


def open_session(cwd: Path | str | None = None, cols: int = 100, rows: int = 28,
                 cmd: list[str] | None = None, label: str = "") -> TerminalSession:
    folder = Path(cwd).expanduser().resolve() if cwd else Path.home()
    if not folder.is_dir():
        folder = Path.home()
    with _LOCK:
        _prune()
        if len(_SESSIONS) >= 12:
            oldest = min(_SESSIONS.values(), key=lambda s: s.touched)
            _SESSIONS.pop(oldest.id, None)
            oldest.close()
        sess = TerminalSession(folder, cols=cols, rows=rows, cmd=cmd, label=label)
        _SESSIONS[sess.id] = sess
        return sess


def get_session(session_id: str) -> TerminalSession:
    with _LOCK:
        sess = _SESSIONS.get(str(session_id or ""))
    if sess is None:
        raise ValueError(f"no terminal session {session_id!r}")
    return sess


def close_session(session_id: str) -> None:
    with _LOCK:
        sess = _SESSIONS.pop(str(session_id or ""), None)
    if sess is not None:
        sess.close()


def close_all() -> None:
    with _LOCK:
        items = list(_SESSIONS.values())
        _SESSIONS.clear()
    for sess in items:
        sess.close()


atexit.register(close_all)


def list_sessions() -> list[dict]:
    with _LOCK:
        _prune()
        return [sess.describe() for sess in _SESSIONS.values()]
