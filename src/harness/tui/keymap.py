"""The chat's keys as named actions, and the user's own keys over them.

The file is keybindings.json in the data folder (/keybindings opens it), in the format of
Claude Code's keybindings file (keybindings page): an object with a `bindings` array of
blocks, each a `context` and a map of keystrokes to actions, `null` to unbind:

    {"bindings": [{"context": "Chat", "bindings": {"ctrl+e": "chat:externalEditor", "ctrl+s": null}}]}

Contexts and actions carry Claude Code's names where the chat has the same thing (CONTEXTS,
ACTIONS); `command:<name>` runs the command /<name>. Ctrl+C and Ctrl+D cannot be rebound, nor
can the keys a terminal sends as Enter, Tab, Escape and Backspace (keys.RESERVED). A file with
a mistake is not fatal: load() keeps every binding that reads and says what is wrong with the
others (Keymap.problems), as Claude Code's validation does. The text editing keys (Ctrl+A,
Ctrl+K, Alt+B, ...) are not actions and cannot be remapped, as there."""

import json
from pathlib import Path
import sys

from . import keys

FILE = "keybindings.json"
DOCS = "https://harness.lmms-lab.com/docs/use/terminal/#customize-the-keys"
# The contexts the chat has, in the order their bindings are added: a later one wins a key
# that an earlier one binds too while both apply.
CONTEXTS = {
    "Global": "everywhere in the chat",
    "Chat": "the input box",
    "Help": "the ? panel is open",
    "Autocomplete": "the list of commands or files is open",
    "Confirmation": "an approval waits for an answer",
    "HistorySearch": "searching the history (Ctrl+R)",
    "Transcript": "the transcript viewer (Ctrl+O)",
    "Select": "a full-screen list",
}
# Contexts of Claude Code that are no part of this chat: a block naming one is not a mistake.
ELSEWHERE = ("Settings", "Tabs", "Task", "ThemePicker", "Attachments", "Footer", "MessageSelector", "DiffDialog",
             "DiffPanel", "ModelPicker", "EffortSlider", "Plugin", "AbovePrompt", "AbovePromptInput",
             "AbovePromptSelect", "Pane", "PaneField", "Agents", "Scroll")
# action: (its context, what it does).
ACTIONS = {
    "app:interrupt": ("Global", "stop what runs; clear the input; twice: leave"),
    "app:exit": ("Global", "leave (twice); with text, delete the character after the cursor"),
    "app:redraw": ("Global", "draw the terminal again"),
    "app:toggleTranscript": ("Global", "the transcript viewer"),
    "app:toggleTimeline": ("Global", "the timeline"),
    "chat:cancel": ("Chat", "stop the turn; twice: clear the input"),
    "chat:clearInput": ("Chat", "draw the terminal again, keeping the input and the conversation"),
    "chat:cycleMode": ("Chat", "the next approval level"),
    "chat:modelPicker": ("Chat", "switch the model"),
    "chat:submit": ("Chat", "send the message"),
    "chat:sendNow": ("Chat", "stop the turn and send what is queued, and the draft, now"),
    "chat:newline": ("Chat", "a new line"),
    "chat:undo": ("Chat", "undo the last edit"),
    "chat:externalEditor": ("Chat", "edit the input in your editor"),
    "chat:stash": ("Chat", "put the input aside; on an empty input, bring it back"),
    "chat:imagePaste": ("Chat", "attach the image on the clipboard"),
    "history:search": ("Chat", "search the history"),
    "history:previous": ("Chat", "the line above, then the message before"),
    "history:next": ("Chat", "the line below, then the message after"),
    "help:dismiss": ("Help", "close the panel"),
    "autocomplete:accept": ("Autocomplete", "take the suggestion"),
    "autocomplete:dismiss": ("Autocomplete", "close the list"),
    "autocomplete:previous": ("Autocomplete", "the suggestion above"),
    "autocomplete:next": ("Autocomplete", "the suggestion below"),
    "confirm:yes": ("Confirmation", "answer with the option chosen"),
    "confirm:no": ("Confirmation", "decline"),
    "confirm:previous": ("Confirmation", "the option above"),
    "confirm:next": ("Confirmation", "the option below"),
    "confirm:addNote": ("Confirmation", "open or close a line for a note to go with the answer"),
    "historySearch:next": ("HistorySearch", "the match before"),
    "historySearch:accept": ("HistorySearch", "take the match and go on editing"),
    "historySearch:cancel": ("HistorySearch", "back to what was typed"),
    "historySearch:execute": ("HistorySearch", "take the match and send it"),
    "transcript:exit": ("Transcript", "close the viewer"),
    "transcript:toggleShowAll": ("Transcript", "everything, or the last turns"),
    "select:next": ("Select", "the row below"),
    "select:previous": ("Select", "the row above"),
    "select:pageUp": ("Select", "a page up"),
    "select:pageDown": ("Select", "a page down"),
    "select:first": ("Select", "the first row"),
    "select:last": ("Select", "the last row"),
    "select:accept": ("Select", "take the row"),
    "select:cancel": ("Select", "close"),
}
# Claude Code's defaults for what the chat has; Ctrl+T is the timeline here (our own view).
DEFAULTS = {
    "Global": {"ctrl+c": "app:interrupt", "ctrl+d": "app:exit", "ctrl+o": "app:toggleTranscript",
               "ctrl+t": "app:toggleTimeline"},
    "Chat": {"escape": "chat:cancel", "ctrl+l": "chat:clearInput", "shift+tab": "chat:cycleMode",
             "meta+p": "chat:modelPicker", "enter": "chat:submit", "ctrl+j": "chat:newline",
             "shift+enter": "chat:newline", "meta+enter": "chat:newline", "ctrl+_": "chat:undo",
             "ctrl+shift+-": "chat:undo", "ctrl+g": "chat:externalEditor", "ctrl+x ctrl+e": "chat:externalEditor",
             "ctrl+s": "chat:stash", ("alt+v" if sys.platform == "win32" else "ctrl+v"): "chat:imagePaste",
             "ctrl+enter": "chat:sendNow", "ctrl+x ctrl+s": "chat:sendNow", "ctrl+r": "history:search",
             "up": "history:previous", "down": "history:next", "ctrl+p": "history:previous",
             "ctrl+n": "history:next"},
    "Help": {"escape": "help:dismiss"},
    "Autocomplete": {"tab": "autocomplete:accept", "escape": "autocomplete:dismiss", "up": "autocomplete:previous",
                     "down": "autocomplete:next"},
    "Confirmation": {"enter": "confirm:yes", "escape": "confirm:no", "up": "confirm:previous",
                     "down": "confirm:next", "tab": "confirm:addNote"},
    "HistorySearch": {"ctrl+r": "historySearch:next", "escape": "historySearch:accept", "tab": "historySearch:accept",
                      "ctrl+c": "historySearch:cancel", "enter": "historySearch:execute"},
    "Transcript": {"q": "transcript:exit", "ctrl+c": "transcript:exit", "escape": "transcript:exit",
                   "ctrl+e": "transcript:toggleShowAll"},
    "Select": {"down": "select:next", "ctrl+n": "select:next", "up": "select:previous", "ctrl+p": "select:previous",
               "pageup": "select:pageUp", "pagedown": "select:pageDown", "home": "select:first",
               "end": "select:last", "enter": "select:accept", "escape": "select:cancel"},
}


class Keymap:
    """What each key does in each context: {context: {chord: action}}, a chord being a tuple
    of keystrokes in their one spelling."""

    def __init__(self, bindings: dict, problems=()):
        self.bindings, self.problems = bindings, list(problems)

    def of(self, action: str) -> list[str]:
        """The keys of `action` as hints write them, in the order they were bound."""
        context = ACTIONS[action][0] if action in ACTIONS else "Chat"
        return [" ".join(keys.shown(stroke) for stroke in chord) for chord, bound in self.bindings[context].items()
                if bound == action]

    def key(self, action: str) -> str:
        """The first key of `action` ("" when nothing is bound to it)."""
        found = self.of(action)
        return found[0] if found else ""

    def bind(self, bindings, context: str, handlers: dict, *, filter=None, command=None, eager=(),
             filters=None) -> None:
        """Add this keymap's keys of `context` to prompt_toolkit `bindings`: handlers[action]
        for each, `command(name)` for a command:<name> action, while `filter` holds (or the
        action's own of `filters`)."""
        from prompt_toolkit.filters import Always

        done = set()
        for chord, action in self.bindings.get(context, {}).items():
            handler = handlers.get(action)
            if handler is None and action.startswith("command:") and command is not None:
                handler = (lambda event, name=action.split(":", 1)[1]: command(name))
            if handler is None:
                continue
            pressed = tuple(key for stroke in chord for key in keys.keys(stroke))
            if pressed in done:
                continue  # two spellings of one key (ctrl+_ and ctrl+shift+-)
            done.add(pressed)
            when = (filters or {}).get(action, filter)
            bindings.add(*pressed, filter=when if when is not None else Always(), eager=pressed in eager)(handler)

    def carried(self) -> set:
        """The keystrokes of this keymap that reach the chat as carriers."""
        pressed = [key for context in self.bindings.values() for chord in context
                   for stroke in chord for key in keys.keys(stroke)]
        names = {char: name for name, char in keys.carriers().items()}  # after keys() made them
        return {names[key] for key in pressed if key in names}


def defaults() -> dict:
    return {context: {keys.chord(stroke): action for stroke, action in DEFAULTS[context].items()}
            for context in CONTEXTS}


def template() -> str:
    """The file /keybindings creates: the defaults, to change in place."""
    blocks = [{"context": context, "bindings": {stroke: action for stroke, action in DEFAULTS[context].items()
                                                if not _reserved(keys.chord(stroke))}}
              for context in CONTEXTS]
    return json.dumps({"$docs": DOCS, "bindings": blocks}, indent=2) + "\n"


def _reserved(chord) -> str | None:
    return next((stroke for stroke in chord if stroke in keys.RESERVED), None)


def _pairs(pairs):
    """A JSON object as its pairs when a key comes twice in it (else a dict)."""
    found = dict(pairs)
    return found if len(found) == len(pairs) else _Repeated(pairs)


class _Repeated(dict):
    def __init__(self, pairs):
        super().__init__(pairs)
        names = [name for name, _ in pairs]
        self.repeated = sorted({name for name in names if names.count(name) > 1})


def read(text: str) -> Keymap:
    """The keymap of a keybindings file's text over the defaults."""
    bindings, problems = defaults(), []
    try:
        data = json.loads(text, object_pairs_hook=_pairs)
    except ValueError as error:
        return Keymap(bindings, [f"it is not valid JSON ({error}); the default keys are in use"])
    blocks = data.get("bindings") if isinstance(data, dict) else None
    if not isinstance(blocks, list):
        return Keymap(bindings, ['it needs a "bindings" array of blocks; the default keys are in use'])
    for number, block in enumerate(blocks, 1):
        context = block.get("context") if isinstance(block, dict) else None
        given = block.get("bindings") if isinstance(block, dict) else None
        if context in ELSEWHERE:
            continue
        if context not in CONTEXTS:
            problems.append(f"block {number}: {context!r} is not a context ({', '.join(CONTEXTS)})")
            continue
        if not isinstance(given, dict):
            problems.append(f"{context}: \"bindings\" is a map of keystrokes to actions")
            continue
        for name in getattr(given, "repeated", ()):
            problems.append(f"{context}: {name} is bound twice; the last one applies")
        for stroke, action in given.items():
            try:
                chord = keys.chord(stroke)
                [keys.keys(part) for part in chord]
            except keys.KeystrokeError as error:
                problems.append(f"{context}: {error}; the binding is ignored")
                continue
            reserved = _reserved(chord)
            if reserved:
                if bindings[context].get(chord) != action:
                    problems.append(f"{context}: {keys.shown(reserved)} cannot be rebound "
                                    f"({keys.RESERVED[reserved]})")
                continue
            if action is None:
                bindings[context].pop(chord, None)
                continue
            known = action in ACTIONS or isinstance(action, str) and action.startswith("command:") and action[8:]
            if not known:
                problems.append(f"{context}: {action!r} is not an action; {stroke} keeps what it did")
                continue
            home = ACTIONS[action][0] if action in ACTIONS else "Chat"
            if home != context:
                problems.append(f"{context}: {action} is an action of the {home} context; {stroke} keeps what it did")
                continue
            bindings[context][chord] = action
    return Keymap(bindings, problems)


def path(directory) -> Path:
    return Path(directory) / FILE


def stamp(directory):
    """What changes when the file does: (modified, size), None without a file."""
    try:
        found = path(directory).stat()
    except OSError:
        return None
    return found.st_mtime_ns, found.st_size


def load(directory) -> Keymap:
    """The keymap in use: the defaults, with the data folder's keybindings.json over them."""
    try:
        text = path(directory).read_text(encoding="utf-8")
    except FileNotFoundError:
        return Keymap(defaults())
    except (OSError, UnicodeError) as error:
        return Keymap(defaults(), [f"it cannot be read ({error}); the default keys are in use"])
    return read(text)
