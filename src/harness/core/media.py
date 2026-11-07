"""Videos: action videos beside an episode trace, and the one ffmpeg and probe() every package uses."""

import datetime
import re
import subprocess
import shutil
from pathlib import Path

from .codec import decode_data_url

_VIDEO_PREFIX = "data:video/mp4;base64,"
# A first frame's time past this (2001 on) is a wall-clock time: a recording made with
# -use_wallclock_as_timestamps and -copyts (the computer package's screen recordings).
_WALL_CLOCK = 1e9
# probe()'s start_from for a start read from the frames' own (wall-clock) times.
FRAMES = "its frames' times"


def ffmpeg() -> str | None:
    """The ffmpeg on PATH, else the imageio-ffmpeg package's, else None."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def probe(path, executable: str | None = None) -> dict:
    """A video as ffmpeg reads it: `duration` (its length in seconds), `size` [width, height],
    `fps`, and `start`, the wall-clock time (epoch seconds) of its first frame, with
    `start_from` saying how that is known: the frames' own times (ffmpeg's start: when it is
    a wall-clock time; its Duration then counts from 0, so the length is the difference),
    else the file's creation_time tag, else the file's time minus its length (a recorder
    closes the file as the recording ends). {"error": ...} when there is no ffmpeg or it
    cannot read the file."""
    path = Path(path)
    executable = executable or ffmpeg()
    if executable is None:
        return {"error": "no ffmpeg (on PATH, or the imageio-ffmpeg package)"}
    if not path.is_file():
        return {"error": f"no file {path}"}
    result = subprocess.run([executable, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    text = result.stderr
    match = re.search(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)", text)
    if not match:
        return {"error": f"ffmpeg cannot read {path.name}: {text.strip().splitlines()[-1:] or 'no output'}"}
    duration = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    first = re.search(r"start:\s*([0-9.]+)", text)
    start, start_from = None, None
    if first and float(first.group(1)) > _WALL_CLOCK:
        start, start_from = float(first.group(1)), FRAMES
        duration -= start
    created = re.search(r"creation_time\s*:\s*(\S+)", text)
    if start is None and created:
        try:
            start = datetime.datetime.fromisoformat(created.group(1).replace("Z", "+00:00")).timestamp()
            start_from = "its creation_time tag"
        except ValueError:
            pass
    if start is None:
        start, start_from = path.stat().st_mtime - duration, "the file's time minus its length"
    size = re.search(r"Video: .*?, (\d{2,5})x(\d{2,5})", text)
    rate = re.search(r"(\d+(?:\.\d+)?) fps", text)
    return {"duration": duration, "start": start, "start_from": start_from,
            "size": [int(size.group(1)), int(size.group(2))] if size else None,
            "fps": float(rate.group(1)) if rate else None, "ffmpeg": executable}


def decode_video_data_url(value: str) -> bytes:
    if not isinstance(value, str) or not value.startswith(_VIDEO_PREFIX):
        raise ValueError("Video must be an MP4 data URL")
    payload = decode_data_url(value)
    if len(payload) < 12 or payload[4:8] != b"ftyp":
        raise ValueError("Video payload is not an MP4")
    return payload


def write_episode_videos(directory: Path, videos: dict) -> dict[str, str]:
    """Write one whole-episode MP4 per camera and return paths relative to the episode directory."""
    if not videos:
        return {}
    folder = directory / "videos"
    folder.mkdir(exist_ok=True)
    written = {}
    for camera, url in videos.items():
        if not isinstance(camera, str) or not camera or "/" in camera or camera in (".", ".."):
            raise ValueError("Video camera name is not a single path segment")
        name = f"episode-{camera}.mp4"
        (folder / name).write_bytes(decode_video_data_url(url))
        written[camera] = f"videos/{name}"
    return written
