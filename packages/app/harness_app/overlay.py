"""The timeline overlay (extensions.overlay): one session's timeline in a small window on top
of the screen, drawn by the host's page /overlay (ui/static/overlay.html) and shown in the
desktop shell's overlay window (shell.py, `--overlay ADDRESS`).

    window = overlay.for_session(session, overlay.Options(corner="top-right"), host=host)
    overlay.close()

Options go to the page in its address; the shell reads corner, size, alpha and click_through
from it too."""
from dataclasses import asdict, dataclass
from urllib.parse import quote, urlencode

from . import shell

HOTKEY = "ctrl+alt+t"


@dataclass
class Options:
    corner: str = "bottom-right"
    width: int = 560
    height: int = 210
    seconds: float = 60.0
    alpha: float = 0.72
    click_through: bool = True
    hide: str = "agent"
    hotkey: str = HOTKEY
    keep_place: bool = True
    outside: str = ""


_WINDOW = {}


def address(url: str, token: str, run: str | None = None, options: Options | None = None) -> str:
    """The overlay page's address on the host at `url` for `run` (None: the newest session
    that runs, and the next one that starts)."""
    values = {"token": token, **{key: str(value).lower() if isinstance(value, bool) else value
                                 for key, value in asdict(options or Options()).items()}}
    if run:
        values["run"] = run
    return f"{url.rstrip('/')}/overlay?{urlencode(values, quote_via=quote)}"


def launch(url: str, token: str, run: str | None = None, options: Options | None = None, *, log=print):
    """Open the overlay window (the shell's) on `run`; returns its process."""
    close()
    window = shell.open_window(address(url, token, run, options), "--overlay")
    if window is None:
        raise ValueError("the timeline overlay is a window of the desktop shell, which is not installed; "
                         f"the page is at {address(url, token, run, options)}")
    _WINDOW["process"] = window
    return window


def for_session(session: str | None = None, options: Options | None = None, *, log=print, host=None):
    """The overlay following a session of the session host (`host`, else the user's)."""
    if host is None:
        from harness.host import Host

        host = Host.connect()
    return launch(host.url, host.token, session, options, log=log)


def for_runs(directory, options: Options | None = None, *, log=print):
    """The overlay of the runs a frontend follows: the newest session of the session host that
    runs, and the next one that starts (the page follows whichever is newest)."""
    from harness.host import Host

    host = Host.connect()
    return launch(host.url, host.token, None, options, log=log)


def close() -> bool:
    """Close the overlay window this process opened; whether there was one."""
    window = _WINDOW.pop("process", None)
    if window is None or window.poll() is not None:
        return False
    window.terminate()
    return True


def arguments(command) -> None:
    """The overlay's flags of a command (harness timeline --overlay)."""
    command.add_argument("--corner", choices=("top-left", "top-right", "bottom-left", "bottom-right"),
                         default=Options.corner)
    command.add_argument("--seconds", type=float, default=Options.seconds, help="seconds the overlay shows")


def options(args) -> Options:
    return Options(corner=args.corner, seconds=args.seconds)
