"""Where the user's timeline overlays are on the screen: the app package's windows on top
of the screen (harness timeline --overlay), which are the user's and not part of what an
agent works on, so the computer's pictures of the screen paint them over (rects) and its
window lists leave them out (their TITLE)."""

import os
import subprocess
import sys

# The title the app package's overlay window has (harness_app/overlay_window.py).
TITLE = "Harness timeline"


def rects() -> list[tuple[int, int, int, int]]:
    """Where overlays are open on the screen (x, y, width, height), in the calling process's
    screen units (a DPI-aware process on Windows: pixels, as the computer worker's
    screenshots; macOS: points; X11: pixels), for pictures of the screen that leave them
    out. Windows by their title; X11 through xdotool when it is installed; macOS through
    Quartz when it imports. Empty when none is open or this platform cannot say."""
    try:
        if sys.platform == "win32":
            return _rects_windows()
        if sys.platform == "darwin":
            return _rects_macos()
        return _rects_x11()
    except Exception:  # a picture of the screen goes on without the overlay's place
        return []


def _rects_windows():
    from harness_computer.desktop import windows

    return [window["rect"] for window in windows.top_windows() if window["title"] == TITLE]


def _rects_x11():
    import shutil

    if not os.environ.get("DISPLAY") or not shutil.which("xdotool"):
        return []
    windows = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", f"^{TITLE}$"], capture_output=True,
                             encoding="utf-8", errors="replace", timeout=2).stdout.split()
    found = []
    for window in windows:
        shell = subprocess.run(["xdotool", "getwindowgeometry", "--shell", window], capture_output=True,
                               encoding="utf-8", errors="replace", timeout=2).stdout
        values = dict(line.split("=", 1) for line in shell.splitlines() if "=" in line)
        found.append(tuple(int(values[key]) for key in ("X", "Y", "WIDTH", "HEIGHT")))
    return found


def _rects_macos():
    import Quartz

    found = []
    for info in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        if info.get("kCGWindowName") == TITLE:
            bounds = info["kCGWindowBounds"]
            found.append(tuple(int(bounds[key]) for key in ("X", "Y", "Width", "Height")))
    return found
