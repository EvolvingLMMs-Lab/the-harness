"""Attach a POSIX terminal to a hosted PTY through the existing session API."""

import codecs
import os
import re
import select
import sys
import threading
from urllib.parse import quote


def replay_text(records):
    """Replay drawing, but never ask the local terminal historical device queries.

    The remote client may no longer be waiting for those replies. Forwarding them
    would insert terminal responses into its current input buffer instead.
    """
    text = "".join(str(r.get("text") or "") for r in records if r.get("event") == "terminal_output")
    text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", text)
    text = re.sub(r"\x1b[P^_].*?\x1b\\", "", text, flags=re.DOTALL)
    return re.sub(r"\x1b\[[0-?]*[ -/]*[nct]|\x1bZ", "", text)


def attach(conversation, host):
    """Forward native terminal bytes; Ctrl-] detaches without stopping the session.

    PTY output is terminal data, not Markdown or a line-oriented transcript.
    Raw records remain the source of truth, including across reconnects.
    """
    import termios
    import tty

    input_fd, output_fd = sys.stdin.fileno(), sys.stdout.fileno()
    if not os.isatty(input_fd) or not os.isatty(output_fd):
        raise ValueError("attaching a hosted PTY requires an interactive terminal")
    stopped = threading.Event()
    failures = []
    resize = getattr(conversation, "terminal_resize", None)
    agent = getattr(conversation, "agent", None)
    if isinstance(agent, dict) and not (agent.get("capabilities") or {}).get("terminal_resize"):
        resize = None  # An older host can still attach without the new capability.
    previous_size = None
    history = host.get(f"/api/events?run={quote(conversation.run, safe='')}&after=-1") or []
    cursor = max((r["seq"] for r in history), default=-1)

    def write(text):
        data = text.encode("utf-8")
        while data and not stopped.is_set():
            data = data[os.write(output_fd, data):]

    def receive():
        try:
            write(replay_text(history))
            for record in conversation.records(after=cursor, stop=stopped):
                if record.get("event") == "terminal_output":
                    write(str(record.get("text") or ""))
        except Exception as error:
            failures.append(error)
        finally:
            stopped.set()

    print("Connected to hosted terminal. Ctrl-] detaches.\r", flush=True)
    original = termios.tcgetattr(input_fd)
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    reader = threading.Thread(target=receive, daemon=True, name="terminal-output")
    try:
        tty.setraw(input_fd)
        reader.start()
        while not stopped.is_set():
            if resize is not None:
                size = os.get_terminal_size(output_fd)
                if size.columns > 0 and size.lines > 0 and size != previous_size:
                    try:
                        resize(size.columns, size.lines)
                    except (OSError, RuntimeError, ValueError):
                        # A resize can race the remote program's normal exit. Keep
                        # forwarding its output; resizing is an optional capability.
                        resize = None
                    else:
                        previous_size = size
            if not select.select([input_fd], [], [], .1)[0]:
                continue
            data = os.read(input_fd, 4096)
            if not data:
                break
            before, detach, _ = data.partition(b"\x1d")
            text = decoder.decode(before)
            if text:
                conversation.terminal_input(text)
            if detach:
                break
    finally:
        stopped.set()
        termios.tcsetattr(input_fd, termios.TCSADRAIN, original)
        os.write(output_fd, b"\x1b[0m\x1b[?25h\x1b[?2004l\r\n")
    if failures:
        raise failures[0]
