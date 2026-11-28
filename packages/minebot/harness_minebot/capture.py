"""The capture of the game window, kept running: one ffmpeg that writes the frames the
body's eyes read (5 a second; the reader keeps the recent ones). No video is recorded. When
it ends, or stops giving frames, it is ended and started again, and the log says so.

    python -m harness_minebot.capture <window title> <frames folder>

The window is taken by its title (Windows: gdigrab); on other systems there is no capture
yet, and a body there has no pictures.
"""

import glob
import os
import shutil
import subprocess
import sys
import time


QUIET = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
STALE = 5.0     # seconds without a new frame before the capture counts as stuck


def ffmpeg() -> str:
    """The ffmpeg on PATH, else the one of the worker's environment (imageio-ffmpeg)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def grab(title: str) -> list[str]:
    """ffmpeg's input arguments for the window `title` on this system."""
    if os.name != "nt":
        raise RuntimeError("the capture of a game window is there on Windows only: this body has no pictures")
    return ["-f", "gdigrab", "-draw_mouse", "0", "-framerate", "5", "-i", "title=" + title]


def newest_age(folder):
    times = []
    for path in glob.glob(os.path.join(folder, "*.jpg")):
        try:
            times.append(os.path.getmtime(path))
        except OSError:   # the reader removes old frames as it goes
            pass
    return time.time() - max(times) if times else None


def say(text):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), text, flush=True)


def main(title, folder):
    os.makedirs(folder, exist_ok=True)
    program, source = ffmpeg(), grab(title)
    number = 0
    while True:
        # Frame numbers go on from the newest kept one: the reader takes the highest.
        kept = [int(os.path.basename(path)[1:-4]) for path in glob.glob(os.path.join(folder, "f*.jpg"))]
        first = max(kept, default=0) + 1
        process = subprocess.Popen(
            [program, "-hide_banner", "-loglevel", "error", "-y", *source,
             "-map", "0:v", "-vf", "scale=854:-2", "-q:v", "5", "-f", "image2", "-start_number", str(first),
             os.path.join(folder, "f%09d.jpg")],
            stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=sys.stderr, **QUIET)
        started = time.time()
        say(f"capture {number} started (process {process.pid}, frames from {first})")
        while True:
            time.sleep(1)
            code = process.poll()
            age = newest_age(folder)
            if code is not None:
                say(f"capture {number} ended by itself with code {code} after {time.time() - started:.0f} s")
                break
            if time.time() - started > 15 and (age is None or age > STALE):
                say(f"capture {number} gave no frame for {age if age is None else round(age, 1)} s after "
                    f"{time.time() - started:.0f} s: ended and started again")
                process.kill()
                process.wait(timeout=10)
                break
        number += 1
        time.sleep(1)


if __name__ == "__main__":
    main(*sys.argv[1:3])
