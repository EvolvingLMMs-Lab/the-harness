"""The app package's commands:

    harness app                    the session host (started when none runs) and the app's
                                   address; the desktop shell's window when it is installed
    harness app --no-window        only the address
    harness timeline [RUN]         a run's timeline in the terminal, followed while it is
                                   written (RUN: an episode directory, a conversation or a
                                   session; default the newest session of the host)
    harness timeline --overlay     the same in the overlay window on top of the screen

No command opens a web browser: the address is printed for the user to open."""
import argparse
import sys

from . import overlay, shell


def app(arguments=None) -> int:
    parser = argparse.ArgumentParser(prog="harness app", description="The Harness app: the session host's "
                                     "address (with its session key), and the desktop window when it is installed")
    parser.add_argument("--no-window", action="store_true", help="print the address only, even with the desktop "
                        "shell installed")
    args = parser.parse_args(arguments)
    from harness.host import Host

    host = Host.connect(log=lambda message: print(message, file=sys.stderr))
    address = host.page()
    window = None if args.no_window else shell.open_window(address)
    print(address)
    if window is None and not args.no_window:
        print("Open this address in a browser. The agent keeps working when the page is closed.", file=sys.stderr)
    return 0


def _newest_session(host) -> str:
    rows = host.sessions(all=True, limit=1)
    if not rows:
        raise ValueError("the session host has no session yet: give a run")
    return rows[0].id


def timeline(arguments=None) -> int:
    parser = argparse.ArgumentParser(prog="harness timeline", description="A run's timeline: when the model, its "
                                     "programs, sub-agents and the environment were busy")
    parser.add_argument("run", nargs="?", help="an episode directory, a conversation, or a session (SESSION or "
                        "SESSION/AGENT); default: the newest session of the session host")
    parser.add_argument("--overlay", action="store_true", help="in a window on top of the screen (the desktop shell)")
    overlay.arguments(parser)
    args = parser.parse_args(arguments)
    from harness.host import Host, resolve_run

    try:
        if args.overlay:
            host = Host.connect()
            overlay.for_session(args.run or None, overlay.options(args), host=host)
            return 0
        name = args.run
        if not name:
            host = Host.connect(start=False)
            if host is None:
                raise ValueError("no session host runs: give a run (an episode directory or a conversation)")
            name = _newest_session(host)
        directory = resolve_run(name)
    except ValueError as error:
        print(f"harness timeline: {error}", file=sys.stderr)
        return 2
    from harness.tui import timeline as follow

    return int(follow(directory) or 0)
