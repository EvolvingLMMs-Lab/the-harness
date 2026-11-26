"""The system clipboard, for /copy and for pasting an image, through what each system ships
(as Claude Code does it): PowerShell on Windows, pbcopy and osascript on macOS, wl-copy and
wl-paste or xclip on Linux. Where none of them can reach the user's clipboard (a remote
shell, no such program), text is copied through the terminal instead (OSC 52)."""

import base64
import os
from pathlib import Path
import shutil
import subprocess
import sys

IMAGES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
POWERSHELL_COPY = "[Console]::InputEncoding = [Text.Encoding]::UTF8; Set-Clipboard -Value ([Console]::In.ReadToEnd())"
POWERSHELL_IMAGE = ("$f = Get-Clipboard -Format FileDropList; if ($f) { 'file:' + $f[0].FullName; exit }; "
                    "$i = Get-Clipboard -Format Image; if ($i) { $i.Save($args[0], "
                    "[System.Drawing.Imaging.ImageFormat]::Png); 'saved' }")


def _run(command, *, text=None, timeout=15):
    return subprocess.run(command, input=text, capture_output=True, timeout=timeout,
                          **({"encoding": "utf-8"} if text is not None else {}))


def copier(platform=None, environ=None):
    """The command that takes text on its input into the clipboard, or None."""
    platform, environ = platform or sys.platform, os.environ if environ is None else environ
    if environ.get("SSH_CONNECTION") or environ.get("SSH_TTY"):
        return None  # the clipboard there is not the one the user pastes from
    if platform == "win32":
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", POWERSHELL_COPY]
    if platform == "darwin":
        return ["pbcopy"]
    for command in (["wl-copy"] if environ.get("WAYLAND_DISPLAY") else [],
                    ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if command and shutil.which(command[0]):
            return command
    return None


def osc52(text: str, environ=None) -> str:
    """The escape sequence that asks the terminal to copy `text` (wrapped for tmux)."""
    environ = os.environ if environ is None else environ
    sequence = "\x1b]52;c;" + base64.b64encode(text.encode()).decode() + "\x07"
    if environ.get("TMUX"):
        return "\x1bPtmux;" + sequence.replace("\x1b", "\x1b\x1b") + "\x1b\\"
    return sequence


def copy(text: str, write, *, run=_run, command=None) -> str:
    """Copy `text`; how it went: "clipboard", or "terminal" when the terminal was asked to
    (`write` puts the escape sequence out)."""
    command = copier() if command is None else command
    if command:
        try:
            if run(command, text=text).returncode == 0:
                return "clipboard"
        except (OSError, subprocess.SubprocessError):
            pass
    write(osc52(text))
    return "terminal"


def image(directory, name: str, *, platform=None, run=_run) -> Path | None:
    """The image on the clipboard, as a file: saved as a PNG named `name` in `directory`, or
    the image file that was copied in a file manager. None when no image is there."""
    platform = platform or sys.platform
    target = Path(directory) / f"{name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if platform == "win32":
            done = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", POWERSHELL_IMAGE, str(target)])
            said = done.stdout.decode("utf-8", "replace").strip() if isinstance(done.stdout, bytes) else str(done.stdout).strip()
            if said.startswith("file:"):
                copied = Path(said[5:])
                return copied if copied.suffix.lower() in IMAGES and copied.is_file() else None
        elif platform == "darwin":
            run(["osascript", "-e", f'set f to (open for access POSIX file "{target}" with write permission)',
                 "-e", "write (the clipboard as «class PNGf») to f", "-e", "close access f"])
        else:
            command = ["wl-paste", "--type", "image/png"] if os.environ.get("WAYLAND_DISPLAY") and \
                shutil.which("wl-paste") else ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"]
            done = run(command)
            if done.returncode == 0 and done.stdout:
                target.write_bytes(done.stdout)
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return target if target.stat().st_size > 0 else None
    except OSError:
        return None
