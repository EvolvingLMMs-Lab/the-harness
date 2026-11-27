"""A conversation's records as lines for a terminal (harness run, harness replay, a session's
last lines), each after the path of its lane on the timeline (core/lanes.py: model, e0,
e0/e2, env); and the commands the user gives a conversation, one table for the terminal
chat (tui/) and harness run rpc.

The commands carry the names people know from Claude Code (its commands page), with its
aliases, and Hermes's names for what Claude Code does not have (its slash-commands page):
find(word) gives the command a name or an alias stands for."""

from typing import NamedTuple

from harness.runtime.safety.input import REMEMBER as KEPT
from .transcript import TextTranscript as Printer, item_lines as item_lines, record_lines as record_lines


class Command(NamedTuple):
    """A word the user gives a conversation: its `method`, called with `fixed` and the values
    for `takes` (a terminal gives the words after it to the first); `words`, `note`: its help;
    `aliases`: other words for it. One without a method is the terminal chat's own
    (tui/commands.py do_<name>). A `hidden` one is a word of harness run rpc only: the chat
    neither lists it nor takes it (an alias of the same name wins there)."""

    method: str = ""
    fixed: dict = {}
    takes: tuple = ()
    words: str = ""
    note: str = ""
    aliases: tuple = ()
    hidden: bool = False


# The commands, the same in the terminal chat (/stop, ...) and harness run rpc
# ({"type": "pause"}, those with a method).
COMMANDS = {
    "help": Command(note="Show help and available commands"),
    "clear": Command(words="[name]", aliases=("reset", "new"),
                     note="Start a new conversation with nothing of this one (this one goes on, and /resume comes "
                          "back to it); name: what this one is called from now on"),
    "resume": Command(words="[conversation]", aliases=("continue",),
                      note="Go on with an earlier conversation: the one named, or pick one"),
    "sessions": Command(note="The sessions that run, or an identity's chats: switch to one"),
    "rename": Command(words="[name]", note="Rename this conversation (without a name: by what it began with)"),
    "project": Command(words="[folder]", aliases=("where",),
                       note="Where this chat works: a project folder (. is this terminal's), its isolated copy, or wherever it decides"),
    "model": Command(words="[model]", aliases=("models",),
                     note="Switch the model: the one named, or pick one (the picker also edits the list)"),
    "effort": Command(words="[level]", note="Set the reasoning effort of the model"),
    "login": Command(note="Add a source of models: an agent signed in here, a provider's key, a local model"),
    "logout": Command(note="Remove a source of models and the key kept for it"),
    "status": Command(words="[stop]", aliases=("host",),
                      note="Version, model, identity, the session host and whether it answers; stop: end the "
                           "session host (and what runs in it)"),
    "usage": Command(words="[week | month | raise DOLLARS]", aliases=("cost", "stats"),
                     note="What the identity spent: today, 7 days, 30 days, by chat, task and model; raise: "
                          "today's limit only"),
    "context": Command(note="How much of the model's context this conversation uses"),
    "compact": Command(words="[instructions]", note="Free context: make the earlier part of the conversation a "
                                                   "summary; the instructions say what it must keep"),
    "config": Command(words="[key=value ...]", aliases=("settings",),
                      note="Open the settings, or set one directly (an external agent's option too)"),
    "permissions": Command(aliases=("allowed-tools",), note="The approval rules: what waits for you, per kind of step"),
    "mode": Command(words="[plan | ask | auto | full]",
                    note="Show or set execution mode for this chat (plan, ask, auto, full)"),
    "plan": Command(note="Switch this chat to Plan mode (read-only analysis and planning)"),
    "ask": Command(note="Switch this chat to Ask mode (confirm before edits and commands)"),
    "auto": Command(note="Switch this chat to Auto mode (auto inside workspace, ask on high-risk)"),
    "full": Command(note="Switch this chat to Full Access mode (run all actions without prompts)"),
    "artifacts": Command(words="[name]", aliases=("artifact",),
                         note="Browse and read this chat's Markdown artifacts (plans, specs)"),
    "rewind": Command(words="[N]", aliases=("undo",),
                      note="Undo back to an earlier message (optionally restoring project files)"),
    "keybindings": Command(note="Open your keyboard shortcuts file"),
    "terminal-setup": Command(note="Install a Shift+Enter key binding for newlines in VS Code, Cursor, Windsurf, "
                                   "Alacritty or Zed"),
    "memory": Command(words="[N]", aliases=("instructions",),
                      note="The instruction files (AGENTS.md) and what it remembers; N: open that file"),
    "skills": Command(words="[sources]", note="The skills it has: each is also a command, /name; sources: where "
                                             "skills come from"),
    "library": Command(note="What it learned: an identity's skills, its tree of reactions and its memory; this "
                            "conversation's memory and each library's entries"),
    "agents": Command(words="[on]", note="The sub-agents of this conversation: open one, stop one; on: let it "
                                         "start them"),
    "init": Command(note="Have the agent write the project's AGENTS.md, or suggest improvements to the one there"),
    "diff": Command(note="Review uncommitted changes of this project or coding session"),
    "copy": Command(words="[N]", note="Copy the last response to the clipboard (N: the Nth latest)"),
    "export": Command(words="[filename]", note="Export this conversation as plain text: to the file, or pick"),
    "doctor": Command(note="Check this installation: what is missing and how to fix it"),
    "update": Command(note="Whether a newer version is out, and how to get it"),
    "version": Command(note="The version of The Harness and where it runs"),
    "calendar": Command(note="The identity's calendar by day, week and month: what it did, who (tree, on its own, "
                             "you), outcomes, refusals, when it slept; add, edit, remove, undo; pause its own work"),
    "channels": Command(aliases=("platforms",),
                        note="The identity's accounts in the channels its packages declare: add, log in, groups, "
                             "pairing requests, test, remove"),
    "mcp": Command(note="The MCP servers: list, add, test, turn off, remove"),
    "acp": Command(aliases=("external-agents",),
                   note="The external agents (ACP): found here, from the registry or a command of yours; add, "
                        "test, remove"),
    "agent": Command(aliases=("profile",), note="The identities: use, new, rename, delete"),
    "timeline": Command(note="The timeline of this conversation: who did what when"),
    "transcript": Command(note="The transcript: every step in detail, with times and the model used"),
    "environment": Command(note="Where this conversation works; choose where the next one does"),
    "packages": Command(aliases=("plugin",),
                        note="The installed packages and the registry's: install, update, turn off, remove"),
    "experiment": Command(words="<name> [task [seed]] [-- instruction]",
                          note="A conversation of an experiment's task on its worker (the eval package's)"),
    "learn": Command(words="[minutes] [for what]", note="A new conversation that learns this environment instead of "
                                                         "doing a task (default: the settings' minutes); during it, where "
                                                         "it stands. (Not Hermes's /learn, which writes a skill from "
                                                         "what you point it at: here, ask it to.)"),
    "stop": Command(aliases=("pause", "cancel"), note="Stop the turn that runs and keep what it did, as Esc does"),
    "queue": Command(words="[text | list | edit N text | rm N | clear]", aliases=("q",),
                     note="Queue a message for its next turn; list, change or drop what is queued"),
    "bg": Command(words="<prompt>", aliases=("background",),
                  note="Have it do something in a chat of its own while this one stays free"),
    "steer": Command("steer", takes=("text",), words="<text>", note="Redirect an external agent's turn"),
    "terminal": Command("terminal_input", takes=("text",), words="<text>", note="Send raw input to an external "
                                                                                "agent's terminal"),
    "answer": Command(words="<request-id> <json>", note="Answer the agent's form, or decline with null"),
    "merge": Command(note="Fast-forward to a closed coding session's committed work"),
    "handoff": Command(words="<agent> <context>", note="Start a new agent with the context you supply. (Not "
                                                        "Hermes's /handoff, which moves a session to a channel.)"),
    "import": Command(words="<provider> <file>", note="Open a native session transcript of another agent read-only"),
    # remember: for physical input, once (or step: the default, not written), app, session or always.
    "approve": Command("confirm", {"accept": True}, ("remember", "reason", "request_id"), f"[{' | '.join(KEPT[1:])}]",
                       "Allow what waits; for physical input, keep it for the app, the session or always"),
    "deny": Command("confirm", {"accept": False}, ("reason", "request_id"), "[why]", "Refuse what waits, saying why",
                    aliases=("reject",)),
    "end": Command("close", note="End the conversation; the evaluator scores an episode"),
    "exit": Command(aliases=("quit", "detach"), note="Leave the chat; what runs goes on in the background"),
    # Words of harness run rpc that the chat says otherwise (/stop; a message goes on after a stop).
    "pause": Command("pause", note="stop at the next step", hidden=True),
    "cancel": Command("cancel", note="end the turn that runs; the conversation waits for the next message",
                      hidden=True),
    "continue": Command("resume", note="go on after a pause", hidden=True),
    "reject": Command("confirm", {"accept": False}, ("reason", "request_id"), "[why]", "refuse it, saying why",
                      hidden=True),
}
# The command each other word stands for in the chat.
ALIASES = {alias: name for name, found in COMMANDS.items() if not found.hidden for alias in found.aliases}
# Other words for a remember value.
REMEMBER = {"step": "once"}
# The words /approve takes: what an answer keeps beyond the one step (runtime/safety/input.py REMEMBER).
APPROVE_WORDS = KEPT[1:]

HELP = ("Type a message for the agent, or a command: "
        + ", ".join(f"/{name}" + (f" {command.words}" if command.words else "")
                    + (f" ({command.note})" if command.note else "") for name, command in COMMANDS.items()
                    if command.method and not command.hidden or name == "help") + ".")


def find(word: str):
    """(name, Command) of the chat's command `word` (its name or an alias), or None."""
    name = ALIASES.get(word, word)
    found = COMMANDS.get(name)
    return None if found is None or found.hidden else (name, found)


def command(conversation, name: str, values: dict | None = None) -> None:
    """Do COMMANDS[name] on `conversation` with the user's `values` of its `takes` (empty ones
    left out); KeyError for a name that is none."""
    found = COMMANDS[name]
    given = {key: REMEMBER.get(value, value) if key == "remember" else value for key, value in (values or {}).items()
             if key in found.takes and value not in (None, "")}
    getattr(conversation, found.method)(**found.fixed, **given)
