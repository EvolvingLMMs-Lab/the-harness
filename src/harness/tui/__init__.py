"""The terminal chat (`harness` in a terminal): the conversation printed into
the terminal's own scrollback, under it one status line and a multiline input box, as in
the coding agents' terminals; pickers and the timeline open full screen and close back to
the chat (tui/chat.py, tui/views.py). Records are read as every frontend reads them
(transcript.py), commands come from the one table (terminal.COMMANDS).

prompt_toolkit (input, keys, pickers) and rich (Markdown, colour) draw it; neither is a
dependency of the harness. When this interpreter cannot import them, the first use
installs them pinned into an environment of their own (HOME/envs/tui/<hash>/,
environments.py) and adds its packages to this process's path, after its own.
"""

import importlib.util
import subprocess
import sys

from ..packages import environments

LIBRARIES = ["prompt_toolkit==3.0.52", "rich==15.0.0"]
# What LIBRARIES install, pinned.
PINS = ["wcwidth==0.2.14", "markdown-it-py==4.2.0", "mdurl==0.1.2", "pygments==2.21.0"]


def environment() -> environments.Environment:
    spec = {"python": f"{sys.version_info[0]}.{sys.version_info[1]}", "requirements": LIBRARIES,
            "constraints": PINS, "imports": ["prompt_toolkit", "rich"]}
    return environments.resolve("tui", spec)


def load(*, log=print) -> None:
    """Make prompt_toolkit and rich importable here: this interpreter's, else the TUI's
    environment's packages (installed first if need be) after this interpreter's own."""
    if all(importlib.util.find_spec(name) is not None for name in ("prompt_toolkit", "rich")):
        return
    env = environments.on_first_use(environment(), "prompt_toolkit and rich for the terminal chat", log=log)
    packages = subprocess.run([str(env.python), "-I", "-X", "utf8", "-c",
                               "import sysconfig; print(sysconfig.get_path('purelib'))"],
                              capture_output=True, encoding="utf-8", check=True).stdout.strip()
    sys.path.append(packages)
    importlib.invalidate_caches()


def chat(conversation=None, records=None, *, host=None, start=None, log=print):
    """The terminal chat with `conversation` (a RemoteConversation of the session `host`, or
    one in this process with its `records`), or with none until the first message, which
    `start(text, files, log)` turns into (host, conversation). Returns the conversation shown
    when the user leaves (None: none); the host's sessions go on."""
    load(log=log)
    from .chat import Chat

    return Chat(conversation, records, host=host, start=start).run()


def timeline(directory, *, log=print) -> int:
    """The timeline of the episode in `directory` (of a runs directory: its newest episode),
    full screen, followed while it is written."""
    from pathlib import Path

    from ..core.episodes import list_episodes

    directory = Path(directory)
    if not (directory / "events.jsonl").is_file():
        found = list_episodes(directory, limit=1)
        directory = directory / found[0]["run"] if found else directory
    load(log=log)
    from .views import follow_timeline

    return follow_timeline(directory)
