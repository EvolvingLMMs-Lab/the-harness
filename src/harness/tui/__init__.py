"""The terminal chat (`harness` in a terminal): the conversation printed into
the terminal's own scrollback, under it one status line and a multiline input box, as in
the coding agents' terminals; pickers and the timeline open full screen and close back to
the chat (tui/chat.py, tui/views.py). Records are read as every frontend reads them
(transcript.py), commands come from the one table (terminal.COMMANDS).

prompt_toolkit (input, keys, pickers) and rich (Markdown, colour) draw it; neither is a
dependency of the harness. When this interpreter lacks their declared pins, the first use
installs them pinned into an environment of their own (HOME/envs/tui/<hash>/,
environments.py) and gives those pinned packages precedence in this process's path.
"""

import importlib.util
from importlib import metadata
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


def _compatible() -> bool:
    """Check only the six declared distributions, without running pip or importing UI code."""
    for requirement in LIBRARIES + PINS:
        name, version = requirement.split("==", 1)
        try:
            if metadata.version(name) != version:
                return False
        except metadata.PackageNotFoundError:
            return False
    return all(importlib.util.find_spec(name) is not None for name in ("prompt_toolkit", "rich"))


def load(*, log=print) -> None:
    """Use the pinned TUI libraries here, preparing the managed environment if needed."""
    if _compatible():
        return
    modules = ("prompt_toolkit", "rich", "wcwidth", "markdown_it", "mdurl", "pygments")
    if any(name in sys.modules for name in modules):
        raise RuntimeError("incompatible terminal libraries are already loaded; restart harness in a clean "
                           "Python environment, or install its terminal pins with "
                           f"{sys.executable} -m pip install " + " ".join(LIBRARIES + PINS))
    env = environments.on_first_use(environment(), "prompt_toolkit and rich for the terminal chat", log=log)
    packages = subprocess.run([str(env.python), "-I", "-X", "utf8", "-c",
                               "import sysconfig; print(sysconfig.get_path('purelib'))"],
                              capture_output=True, encoding="utf-8", check=True).stdout.strip()
    # The managed versions must precede incompatible importable libraries in the
    # host interpreter. Appending would leave the incompatible copies selected.
    sys.path.insert(0, packages)
    importlib.invalidate_caches()
    if not _compatible():
        raise RuntimeError(f"terminal libraries in {env.directory} do not match the declared pins; "
                           "remove that managed environment and restart harness to rebuild it")


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
