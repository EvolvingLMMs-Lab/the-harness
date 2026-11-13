"""A conversation's records as lines for a terminal (harness run, harness replay, a session's
last lines), each after the path of its lane on the timeline (core/lanes.py: model, e0,
e0/e2, env); and the commands the user gives a conversation, one table for the terminal
chat (tui/) and harness run rpc."""

from typing import NamedTuple

from harness.runtime.safety.input import REMEMBER as KEPT
from .transcript import TextTranscript as Printer, item_lines as item_lines, record_lines as record_lines


class Command(NamedTuple):
    """A word the user gives a conversation: its `method`, called with `fixed` and the values
    for `takes` (a terminal gives the words after it to the first); `words`, `note`: its help.
    One without a method is the terminal chat's own (tui/chat.py do_<name>)."""

    method: str = ""
    fixed: dict = {}
    takes: tuple = ()
    words: str = ""
    note: str = ""


# The commands, the same in the terminal chat (/pause, ...) and harness run rpc
# ({"type": "pause"}, those with a method).
COMMANDS = {
    "help": Command(note="the commands and keys"),
    "new": Command(note="a new conversation with nothing of this one (this one goes on, and /resume comes back to it)"),
    "clear": Command(note="the same as /new"),
    "resume": Command(note="pick an earlier conversation and go on with it, in its own session"),
    "sessions": Command(note="the sessions that run: switch to one"),
    "host": Command(words="[stop]", note="the session host: how it runs; stop: end it (and what runs in it)"),
    "environment": Command(note="where this conversation works; choose where the next one does"),
    "model": Command(note="pick an enabled model for new conversations"),
    "models": Command(note="edit the local model list"),
    "effort": Command(words="[LEVEL]", note="choose a reasoning effort for the selected model"),
    "experiment": Command(words="NAME [TASK [SEED]] [-- instruction]",
                          note="a conversation of an experiment's task on its worker (the eval package's)"),
    "agents": Command(note="switch sub-agents on: for this conversation, or for the next one before it starts"),
    "settings": Command(note="change the settings"),
    "packages": Command(note="the installed packages and the registry's: install, update, turn off, remove"),
    "library": Command(note="what the agent remembers: this conversation's memory and each library's entries"),
    "learn": Command(words="[minutes] [for what]", note="a new conversation that learns this environment instead of "
                                                         "doing a task (default: the settings' minutes); during it, where "
                                                         "it stands"),
    "pause": Command("pause", note="stop at the next step, as Esc does"),
    "cancel": Command("cancel", note="end the turn that runs; the conversation waits for your next message"),
    "steer": Command("steer", takes=("text",), words="TEXT", note="redirect an external turn"),
    "terminal": Command("terminal_input", takes=("text",), words="TEXT", note="send raw PTY input"),
    "answer": Command(words="REQUEST_ID JSON", note="answer the agent's form, or decline with null"),
    "config": Command(words="OPTION VALUE", note="select an advertised external model or mode"),
    "diff": Command(note="inspect this coding session's changes"),
    "merge": Command(note="fast-forward to a closed session's committed work"),
    "handoff": Command(words="AGENT CONTEXT", note="start a new agent with the context you supply"),
    "import": Command(words="PROVIDER FILE", note="open a selected native session transcript read-only"),
    "continue": Command("resume", note="go on after a pause"),
    # remember: for physical input, once (or step: the default, not written), app, session or always.
    "approve": Command("confirm", {"accept": True}, ("remember", "reason", "request_id"), f"[{' | '.join(KEPT[1:])}]",
                       "allow what waits; for physical input, keep it for the app, the session or always"),
    "reject": Command("confirm", {"accept": False}, ("reason", "request_id"), "[why]", "refuse it, saying why"),
    "end": Command("close", note="end the conversation; the evaluator scores an episode"),
    "timeline": Command(note="the timeline (Ctrl+T)"),
    "detach": Command(note="leave; the session goes on (/sessions comes back to it)"),
    "exit": Command(note="leave (Ctrl+C twice)"),
}
# Other words for a remember value.
REMEMBER = {"step": "once"}
# The words /approve takes: what an answer keeps beyond the one step (runtime/safety/input.py REMEMBER).
APPROVE_WORDS = KEPT[1:]

HELP = ("Type a message for the agent, or a command: "
        + ", ".join(f"/{name}" + (f" {command.words}" if command.words else "")
                    + (f" ({command.note})" if command.note else "") for name, command in COMMANDS.items()
                    if command.method or name == "help") + ".")


def command(conversation, name: str, values: dict | None = None) -> None:
    """Do COMMANDS[name] on `conversation` with the user's `values` of its `takes` (empty ones
    left out); KeyError for a name that is none."""
    found = COMMANDS[name]
    given = {key: REMEMBER.get(value, value) if key == "remember" else value for key, value in (values or {}).items()
             if key in found.takes and value not in (None, "")}
    getattr(conversation, found.method)(**found.fixed, **given)
