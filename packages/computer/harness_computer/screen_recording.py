"""Recordings of a screen with the time of every frame, kept beside a run's trace so that a
replay (harness replay RUN --export video) shows what the screen showed at each moment of
the run.

ffmpeg grabs the screen, or a part of it, into `screen.mkv` in the run's directory. Its
frames carry the wall clock (`-use_wallclock_as_timestamps 1`, kept with `-copyts`), the
clock the trace's records use, so a frame at time t is what the screen showed at t; frames
come at up to `fps` a second and none is made up. `screen.json` says what was recorded:
the display, the part of it, and the time of the first frame.

X11 displays (a virtual screen such as Xvfb's :99, or this computer's) use x11grab;
Windows uses gdigrab. ffmpeg is the one on PATH, else the imageio-ffmpeg package's.
"""

import json
from pathlib import Path
import re
import subprocess
import sys
import time

from harness.sdk import FRAMES, ffmpeg, probe  # noqa: F401  (ffmpeg: the recorder's, and its callers')

VIDEO = "screen.mkv"
INFO = "screen.json"




def passthrough(executable: str) -> list[str]:
    """ffmpeg's option that keeps each frame's time as it came: -fps_mode (5.1 on), -vsync
    before."""
    result = subprocess.run([executable, "-hide_banner", "-version"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    match = re.search(r"version n?(\d+)\.(\d+)", result.stdout)
    old = match is not None and (int(match.group(1)), int(match.group(2))) < (5, 1)
    return ["-vsync", "0"] if old else ["-fps_mode", "passthrough"]


def command(executable: str, path: Path, display: str | None = None, area=None, fps: int = 15,
            platform: str = sys.platform, keep=("-fps_mode", "passthrough"), pointer: bool | None = None) -> list[str]:
    """ffmpeg's command line that records `area` (x, y, width, height; None: all of it) of
    X display `display` (Windows: of the desktop) into `path`, each frame stamped with the
    wall clock (`keep`: passthrough() of this ffmpeg); with the pointer drawn when `pointer`
    (None: on this computer's own screen, not on a display named)."""
    clock = ["-use_wallclock_as_timestamps", "1", "-framerate", str(int(fps))]
    if platform.startswith("win"):
        place = []
        if area:
            x, y, width, height = area
            place = ["-offset_x", str(x), "-offset_y", str(y), "-video_size", f"{width}x{height}"]
        grab = ["-f", "gdigrab", *clock, *place, "-draw_mouse", "1", "-i", "desktop"]
    elif display or platform.startswith("linux"):
        source = display or ":0"
        size = []
        if area:
            x, y, width, height = area
            source = f"{source}+{x},{y}"
            size = ["-video_size", f"{width}x{height}"]
        # A display of its own (a virtual screen) where only background browsers work: its
        # pointer is nobody's, so it is not drawn; a desktop's is the agent's and the user's.
        drawn = (not display) if pointer is None else pointer
        grab = ["-f", "x11grab", *clock, *size, "-draw_mouse", "1" if drawn else "0", "-i", source]
    else:
        raise RuntimeError(f"recording the screen is not supported on {platform} yet")
    # Even sizes for yuv420p; the frames keep their times (no frames are made up).
    return [executable, "-hide_banner", "-loglevel", "error", "-y", *grab,
            "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", *keep, "-copyts", "-f", "matroska", str(path)]


def first_frame(path: Path, executable: str | None = None) -> float | None:
    """The time (wall clock) of a recording's first frame, from its frames' own times."""
    info = probe(path, executable)
    return info["start"] if info.get("start_from") == FRAMES else None


class Recording:
    """A recording that runs until stop()."""

    def __init__(self, directory: Path, display: str | None = None, area=None, fps: int = 15,
                 pointer: bool | None = None):
        executable = ffmpeg()
        if executable is None:
            raise RuntimeError("recording the screen needs ffmpeg (on PATH, or the imageio-ffmpeg package)")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / VIDEO
        self.executable = executable
        self.info = {"video": VIDEO, "display": display, "area": list(area) if area else None, "fps": int(fps),
                     "clock": "wall", "start": None, "stop": None}
        self.started = time.time()
        self.process = subprocess.Popen(command(executable, self.path, display, area, fps, keep=passthrough(executable),
                                                pointer=pointer),
                                        stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self._write()

    def alive(self) -> bool:
        return self.process.poll() is None

    def stop(self, seconds: float = 10.0) -> dict:
        """End the recording (ffmpeg finishes the file) and return what screen.json says."""
        if self.process.poll() is None:
            try:
                # ffmpeg's own way to stop: q on its input.
                self.process.stdin.write(b"q")
                self.process.stdin.close()
            except OSError:
                pass
            try:
                self.process.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=seconds)
        error = (self.process.stderr.read() or b"").decode("utf-8", "replace").strip() if self.process.stderr else ""
        self.info.update(stop=time.time(), start=first_frame(self.path, self.executable))
        if error and self.info["start"] is None:
            self.info["error"] = error[-400:]
        self._write()
        return dict(self.info)

    def _write(self):
        (self.directory / INFO).write_text(json.dumps(self.info, indent=2), encoding="utf-8")


def find(directory: Path) -> dict | None:
    """A run's recording: screen.json with the video's path, or None."""
    directory = Path(directory)
    try:
        info = json.loads((directory / INFO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    video = directory / str(info.get("video") or VIDEO)
    if not video.is_file():
        return None
    if info.get("start") is None:
        info["start"] = first_frame(video)
    return {**info, "path": str(video)}
