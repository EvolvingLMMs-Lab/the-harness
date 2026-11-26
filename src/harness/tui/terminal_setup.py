"""/terminal-setup: Shift+Enter as a new line in the terminals that do not report it, done
as Claude Code's /terminal-setup does it (terminal-config page, "Enter multiline prompts"):
the terminal's own configuration gets a Shift+Enter binding that sends Escape then Enter,
which every terminal chat reads as Alt+Enter, a new line.

    VS Code, Cursor, Windsurf   keybindings.json of the editor's user folder
    Alacritty                   alacritty.toml
    Zed                         keymap.json

An existing binding is left as it is, the file is copied to `<name>.<8 hex>.bak` before it
changes, and a file that cannot be read, parsed or backed up is left unchanged with the
block to add by hand. Terminals that report Shift+Enter themselves need nothing, and where
it cannot work (the terminal has no such setting) Ctrl+J and \\ then Enter are the keys."""

import json
import os
from pathlib import Path
import re
import secrets
import sys

SEQUENCE = "\x1b\r"
VSCODE_BINDING = {"key": "shift+enter", "command": "workbench.action.terminal.sendSequence",
                  "args": {"text": SEQUENCE}, "when": "terminalFocus"}
ZED_BINDING = {"context": "Terminal", "bindings": {"shift-enter": ["terminal::SendText", SEQUENCE]}}
ALACRITTY_BINDING = '[[keyboard.bindings]]\nkey = "Return"\nmods = "Shift"\nchars = "\\u001B\\r"\n'
EDITORS = {"vscode": ("VSCode", "Code"), "vscode-insiders": ("VSCode", "Code - Insiders"), "cursor": ("Cursor", "Cursor"),
           "windsurf": ("Windsurf", "Windsurf")}
# Terminals that report Shift+Enter without any setup (the chat asks them to when it starts).
NATIVE = {"windows-terminal": "Windows Terminal", "iterm": "iTerm2", "wezterm": "WezTerm", "ghostty": "Ghostty",
          "kitty": "Kitty", "warp": "Warp", "conhost": "the Windows console"}


def terminal(environ=None, platform=None) -> str:
    """Which terminal this is, from what it puts into the environment."""
    environ, platform = os.environ if environ is None else environ, platform or sys.platform
    if environ.get("TMUX"):
        return "tmux"
    if environ.get("STY"):
        return "screen"
    program = (environ.get("TERM_PROGRAM") or "").lower()
    if program == "vscode":
        clues = " ".join(environ.get(name, "") for name in ("VSCODE_GIT_ASKPASS_NODE", "VSCODE_GIT_ASKPASS_MAIN",
                                                             "__CFBundleIdentifier", "VSCODE_NLS_CONFIG")).lower()
        if environ.get("CURSOR_TRACE_ID") or "cursor" in clues:
            return "cursor"
        if "windsurf" in clues:
            return "windsurf"
        return "vscode-insiders" if "insiders" in clues else "vscode"
    if environ.get("ZED_TERM") or program == "zed":
        return "zed"
    if program == "alacritty" or environ.get("ALACRITTY_WINDOW_ID") or environ.get("ALACRITTY_SOCKET") or \
            environ.get("TERM") == "alacritty":
        return "alacritty"
    if environ.get("WT_SESSION"):
        return "windows-terminal"
    if environ.get("KITTY_WINDOW_ID") or environ.get("TERM") == "xterm-kitty":
        return "kitty"
    known = {"iterm.app": "iterm", "wezterm": "wezterm", "ghostty": "ghostty", "warpterminal": "warp",
             "apple_terminal": "apple-terminal"}
    if program in known:
        return known[program]
    if environ.get("VTE_VERSION"):
        return "vte"
    if program == "mintty":
        return "mintty"
    if platform == "win32":
        return "conhost"
    return program or environ.get("TERM") or "this terminal"


def _config(home: Path, environ, platform: str) -> Path:
    """Where applications keep the user's configuration on this system."""
    if platform == "win32":
        return Path(environ.get("APPDATA") or home / "AppData" / "Roaming")
    if platform == "darwin":
        return home / "Library" / "Application Support"
    return Path(environ.get("XDG_CONFIG_HOME") or home / ".config")


def strip_comments(text: str) -> str:
    """JSON with comments and trailing commas (the editors' own files) as plain JSON."""
    out, index, quoted = [], 0, False
    while index < len(text):
        character = text[index]
        if quoted:
            out.append(character)
            if character == "\\" and index + 1 < len(text):
                out.append(text[index + 1])
                index += 1
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
            out.append(character)
        elif text.startswith("//", index):
            index = text.find("\n", index)
            if index < 0:
                break
            continue
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end < 0 else end + 2
            continue
        else:
            out.append(character)
        index += 1
    return re.sub(r",(\s*[\]}])", r"\1", "".join(out))


def _backup(path: Path) -> Path | None:
    """A copy of `path` beside it; None when it could not be made."""
    copy = path.with_name(f"{path.name}.{secrets.token_hex(4)}.bak")
    try:
        copy.write_bytes(path.read_bytes())
    except OSError:
        return None
    return copy


def _add_to_array(text: str, block: dict) -> str:
    """`text` (a JSON array, with whatever comments it has) with `block` as its last item."""
    added = "\n".join("  " + line for line in json.dumps(block, indent=2).splitlines())
    close = text.rstrip().rfind("]")
    before = text[:close].rstrip()
    comma = "" if before.endswith(("[", ",")) else ","
    return f"{before}{comma}\n{added}\n]\n"


def _json_array(path: Path, block: dict, exists, name: str) -> list:
    """Add `block` to the JSON array in `path` unless `exists(items)` says how it is there
    already ("same" or "different"). The lines to say."""
    by_hand = [(f"To add the binding yourself, put this in {path}:", "dim"),
               (json.dumps([block], indent=2), "")]
    if path.is_symlink():
        return [(f"Your {name} is a symbolic link, so it was left unchanged.", "yellow"), *by_hand]
    text = ""
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
            items = json.loads(strip_comments(text)) if text.strip() else []
        except (OSError, UnicodeError, ValueError):
            return [(f"Couldn't read your {name}, so it was left unchanged.", "yellow"), *by_hand]
        if not isinstance(items, list):
            return [(f"Your {name} isn't a readable list of keybindings, so it was left unchanged.", "yellow"),
                    *by_hand]
        found = exists(items)
        if found == "same":
            return [(f"{name}: Shift+Enter key binding already configured", "green"), (f"See {path}", "dim")]
        if found == "different":
            return [(f"{name} already has a Shift+Enter terminal binding with different args; leaving it as-is.",
                     "yellow"), (f"See {path}", "dim")]
        if text.strip():
            copy = _backup(path)
            if copy is None:
                return [(f"Couldn't back up your {name}, so it wasn't changed.", "yellow"), (f"See {path}", "dim")]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = _add_to_array(text, block) if text.strip() else json.dumps([block], indent=2) + "\n"
        json.loads(strip_comments(new))  # what is written must still read
        path.write_text(new, encoding="utf-8", newline="\n")
    except (OSError, ValueError) as error:
        return [(f"Couldn't update your {name}, so it was left unchanged ({error}).", "yellow"), *by_hand]
    return [(f"Installed {name.split(' ')[0]} terminal Shift+Enter key binding", "green"), (f"See {path}", "dim")]


def _editor(which: str, home: Path, environ, platform: str) -> list:
    label, folder = EDITORS[which]
    # The editor's window is on another computer than this shell: its keybindings are there.
    if environ.get("SSH_CONNECTION") or environ.get("REMOTE_CONTAINERS") or environ.get("WSL_DISTRO_NAME"):
        return [(f"Can't install keybindings from a remote {label} session.", "yellow"),
                (f"{label} keybindings must be installed on your local machine, not the remote server.", ""),
                ("To install the Shift+Enter keybinding:", ""),
                (f"1. Open {label} on your local machine (not connected to remote)", ""),
                ('2. Open the Command Palette (Cmd/Ctrl+Shift+P) → "Preferences: Open Keyboard Shortcuts (JSON)"', ""),
                ("3. Add this keybinding (the file must be a JSON array):", ""),
                (json.dumps([VSCODE_BINDING], indent=2), "")]

    def exists(items):
        for item in items:
            if isinstance(item, dict) and str(item.get("key", "")).lower() == "shift+enter" and \
                    item.get("command") == VSCODE_BINDING["command"] and "terminalFocus" in str(item.get("when", "")):
                return "same" if (item.get("args") or {}).get("text") == SEQUENCE else "different"
        return None

    path = _config(home, environ, platform) / folder / "User" / "keybindings.json"
    return _json_array(path, VSCODE_BINDING, exists, f"{label} terminal keybindings")


def _zed(home: Path, environ, platform: str) -> list:
    def exists(items):
        for item in items:
            if isinstance(item, dict) and item.get("context") == "Terminal" and \
                    "shift-enter" in (item.get("bindings") or {}):
                return "same" if item["bindings"]["shift-enter"] == ZED_BINDING["bindings"]["shift-enter"] \
                    else "different"
        return None

    folder = Path(environ.get("APPDATA") or home / "AppData" / "Roaming") / "Zed" if platform == "win32" \
        else Path(environ.get("XDG_CONFIG_HOME") or home / ".config") / "zed"
    return _json_array(folder / "keymap.json", ZED_BINDING, exists, "Zed keymap")


def _alacritty(home: Path, environ, platform: str) -> list:
    places = [Path(environ["XDG_CONFIG_HOME"]) / "alacritty" / "alacritty.toml"] if environ.get("XDG_CONFIG_HOME") \
        else [home / ".config" / "alacritty" / "alacritty.toml"]
    if platform == "win32" and environ.get("APPDATA"):
        places.append(Path(environ["APPDATA"]) / "alacritty" / "alacritty.toml")
    path = next((place for place in places if place.is_file()), places[-1] if platform == "win32" else places[0])
    text = ""
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return [("Couldn't read your Alacritty config, so nothing was changed.", "yellow"), (f"See {path}", "dim")]
        if 'mods = "Shift"' in text and 'key = "Return"' in text:
            return [("Alacritty Shift+Enter key binding already configured", "green"), (f"See {path}", "dim")]
        if _backup(path) is None:
            return [("Couldn't back up your Alacritty config, so nothing was changed.", "yellow"),
                    (f"See {path}", "dim")]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + ("" if not text or text.endswith("\n") else "\n") + "\n" + ALACRITTY_BINDING,
                        encoding="utf-8", newline="\n")
    except OSError as error:
        return [(f"Couldn't install the Alacritty Shift+Enter key binding ({error}).", "yellow"),
                ("To add the binding yourself, put this in " + str(path) + ":", "dim"), (ALACRITTY_BINDING, "")]
    return [("Installed Alacritty Shift+Enter key binding", "green"),
            ("Restart Alacritty if Shift+Enter doesn't work yet", "green"), (f"See {path}", "dim")]


def shift_enter(environ=None, platform=None) -> str:
    """Whether Shift+Enter reaches the chat in this terminal: "native" (nothing to do),
    "setup" (/terminal-setup writes the terminal's binding) or "no" (use Ctrl+J)."""
    which = terminal(environ, platform)
    return "native" if which in NATIVE else "setup" if which in EDITORS or which in ("zed", "alacritty") else "no"


def run(environ=None, home=None, platform=None) -> list:
    """Do what this terminal needs for Shift+Enter; the lines to say, as (text, style)."""
    environ, platform = os.environ if environ is None else environ, platform or sys.platform
    home = Path(home or Path.home())
    which = terminal(environ, platform)
    if which in EDITORS:
        return _editor(which, home, environ, platform)
    if which == "zed":
        return _zed(home, environ, platform)
    if which == "alacritty":
        return _alacritty(home, environ, platform)
    if which in NATIVE:
        return [(f"{NATIVE[which]} reports Shift+Enter itself: nothing to set up.", "green"),
                ("Shift+Enter, Ctrl+J and \\ then Enter all start a new line.", "dim")]
    name = {"tmux": "tmux", "screen": "screen", "apple-terminal": "Apple Terminal",
            "vte": "this terminal (GNOME Terminal and others built on VTE)"}.get(which, which)
    lines = [(f"Terminal setup cannot be run from {name}.", "yellow"), ("", ""),
             ("This command configures a convenient Shift+Enter shortcut for multi-line prompts.", ""),
             ("Note: You can already use Ctrl+J, or backslash (\\) + return, to add newlines.", "dim"), ("", "")]
    if which in ("tmux", "screen"):
        lines += [("To set up the shortcut (optional):", ""), (f"1. Exit {name} temporarily", ""),
                  ("2. Run /terminal-setup directly in one of these terminals:", ""),
                  ("   • IDE: VSCode, Cursor, Windsurf, Zed", ""), ("   • Other: Alacritty", ""),
                  (f"3. Return to {name} - settings will persist", "")]
        if which == "tmux":
            lines += [("", ""), ("Inside tmux, Shift+Enter also needs these lines in ~/.tmux.conf:", ""),
                      ("   set -s extended-keys on", ""), ("   set -as terminal-features 'xterm*:extkeys'", "")]
    else:
        lines += [("/terminal-setup writes the binding for VSCode, Cursor, Windsurf, Zed and Alacritty.", ""),
                  ("iTerm2, WezTerm, Ghostty, Kitty, Warp and Windows Terminal support Shift+Enter natively.", "")]
        if which == "apple-terminal":
            lines += [("In Apple Terminal, Option+Enter starts a new line once Settings → Profiles → Keyboard → "
                       "\"Use Option as Meta Key\" is on.", "")]
    return lines
