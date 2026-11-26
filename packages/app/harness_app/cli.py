"""The app package's commands:

    harness app                    the session host (started when none runs) and the app's
                                   address; the desktop shell's window when it is installed
    harness app --no-window        only the address

No command opens a web browser: the address is printed for the user to open."""
import argparse
import sys

from . import shell


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
