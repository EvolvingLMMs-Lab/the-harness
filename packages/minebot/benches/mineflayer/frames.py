"""The body's first-person pictures, read from the folder the one capture of the game window
writes into: frames numbered in order (f000000001.jpg, ...), several a second; a frame's time
is its file's time. The newest frame, and the seconds before a moment as one grid. Nothing
here grabs the window.

Reading the newest frame costs the same however many frames are kept: the number of the last
one seen is remembered and only the ones after it are looked for. Frames older than
KEEP_FRAMES back are removed as newer ones are found.
"""

import glob
import os
import re
import subprocess
import tempfile
import time

NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
KEEP_FRAMES = 4500          # at 5 a second: the last 15 minutes
KEPT_MINUTES = 15
NAME = "f%09d.jpg"
_last = {}                  # folder -> the number of the newest frame seen


def _ffmpeg():
    """The ffmpeg on PATH, else the one of the worker's environment (imageio-ffmpeg)."""
    global _program
    if _program is None:
        import shutil

        _program = shutil.which("ffmpeg")
        if _program is None:
            import imageio_ffmpeg

            _program = imageio_ffmpeg.get_ffmpeg_exe()
    return _program


_program = None


def _folder(folder):
    folder = folder or os.environ.get("MINEFLAYER_FRAMES")
    if not folder:
        raise RuntimeError("the worker was not told where the first-person frames are (its `frames` option, or $MINEFLAYER_FRAMES)")
    return folder


def _path(folder, number):
    return os.path.join(folder, NAME % number)


def _advance(folder):
    """The number of the newest frame in the folder (0: none), found from the last one seen."""
    number = _last.get(folder, 0)
    if number and not os.path.exists(_path(folder, number)):
        number = 0          # the capture began again: its numbers start over
    if not number:
        found = [int(match.group(1)) for match in (re.fullmatch(r"f(\d{9})\.jpg", name) for name in os.listdir(folder)) if match] \
            if os.path.isdir(folder) else []
        number = max(found, default=0)
    while os.path.exists(_path(folder, number + 1)):
        number += 1
        old = _path(folder, number - KEEP_FRAMES)
        if number > KEEP_FRAMES and os.path.exists(old):
            try:
                os.remove(old)
            except OSError:
                pass
    _last[folder] = number
    return number


def _whole(path):
    try:
        with open(path, "rb") as file:
            data = file.read()
    except OSError:
        return None
    return data if data[-2:] == b"\xff\xd9" else None   # a JPEG written to its end


def newest(max_age=1.0, folder=None):
    """The newest whole frame as (JPEG bytes, its age in seconds), or (None, None) when none
    is younger than `max_age`."""
    folder = _folder(folder)
    number = _advance(folder)
    now = time.time()
    for candidate in (number, number - 1):   # the last one may still be being written
        if candidate < 1:
            break
        path = _path(folder, candidate)
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if age > max_age:
            break
        data = _whole(path)
        if data is not None:
            return data, age
    return None, None


def at(moment, folder=None):
    """The kept frame nearest before `moment` (a time), as JPEG bytes; None when none is kept
    from the 2 seconds before it."""
    rows = recent(2.0, moment, folder)
    for _, path in reversed(rows):
        data = _whole(path)
        if data is not None:
            return data
    return None


def recent(seconds=None, until=None, folder=None):
    """The kept frames up to `until` (now), the last `seconds` of them: [(moment, path)], oldest first."""
    folder = _folder(folder)
    until = time.time() if until is None else until
    rows = []
    for path in glob.glob(os.path.join(folder, "f*.jpg")):
        try:
            moment, size = os.path.getmtime(path), os.path.getsize(path)
        except OSError:
            continue
        if size > 0 and moment <= until and (seconds is None or moment >= until - seconds):
            rows.append((moment, path))
    return sorted(rows)


def grid(seconds=8, until=None, count=6, folder=None, columns=3):
    """`count` frames spread over the `seconds` before `until`, in reading order, as one JPEG:
    (bytes, [seconds before `until` of each tile]); (None, []) without frames."""
    until = time.time() if until is None else until
    rows = recent(seconds, until, folder)
    if not rows:
        return None, []
    step = max(1.0, len(rows) / float(count))
    chosen = sorted({rows[min(len(rows) - 1, int(round(index * step)))] for index in range(min(count, len(rows)))})
    lines = -(-len(chosen) // columns)
    with tempfile.TemporaryDirectory() as work:
        listing = os.path.join(work, "list.txt")
        with open(listing, "w", encoding="utf-8") as file:
            for _, path in chosen:
                file.write("file '" + path.replace("\\", "/") + "'\nduration 1\n")
        output = os.path.join(work, "grid.jpg")
        subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing,
                        "-vf", f"scale=640:-2,tile={min(columns, len(chosen))}x{lines}", "-frames:v", "1", "-q:v", "5",
                        output], check=True, **NO_WINDOW)
        with open(output, "rb") as file:
            return file.read(), [round(until - moment, 1) for moment, _ in chosen]
