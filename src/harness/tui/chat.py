"""The terminal chat: the conversation printed into the terminal's scrollback (rich), and a
live region under it (prompt_toolkit) laid out as Claude Code's: what waits its turn, the
reply while it is written, a line that says it works and for how long, an approval's
choices when one waits, the input box, and under it a hint, the status (identity, model,
today's spending, context in use) and the approval level.

Using it is using Claude Code (interactive-mode page): Enter sends; Shift+Enter, Ctrl+J,
Alt+Enter and \\ then Enter start a new line; a paste never sends; the readline keys edit;
Up and Down move in a draft of several rows, then walk this directory's history; Ctrl+R
searches it; / lists the commands, @ completes files, ! runs a command here, ? on an empty
input shows the keys. While it works a message typed is queued (Up takes the queue back),
Esc stops the turn and keeps what it did, Ctrl+C interrupts, then clears, then leaves,
Ctrl+O is the transcript, Ctrl+T the timeline, Shift+Tab the next approval level and Alt+P
another model. The keys are actions of a keymap the user can change (keymap.py), read by
keys.py; the editing itself is editing.py, the history history.py, the commands commands.py.

Nothing starts until the first message: then `start(text, files, log)` gives the host and a
conversation of the app's agent.

With an agent identity (the agent package; harness --identity) the chat is the identity's: its
main conversation on the session host (tui/agent.py), the same life the app, the command line
and Python show; /sessions switches among its chats, and what happens in its other chats is
told in lines starting with "—", which are not written into the main conversation's record.
Its queue, stopping a turn and the reply being written are the host's (tui/control.py)."""

import asyncio
import difflib
import io
import locale
import os
from pathlib import Path
from ..settings import ChoiceRequired
import re
import subprocess
import sys
import threading
import time

from prompt_toolkit.application import Application, get_app_session, in_terminal
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.filters import Condition, has_completions, vi_insert_mode
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import DynamicKeyBindings, KeyBindings
from prompt_toolkit.key_binding.vi_state import InputMode
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, ScrollOffsets, VSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenuControl
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth
from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text

from .. import transcript
from ..core import format as formats
from harness.runtime.safety.approval import say
from ..core.lanes import Lanes
from ..host.client import HostGone, RemoteError
from ..host.sessions import ENDED, word
from ..paths import data
from ..problems import Problem, lines as problem_lines
from .. import spending
from harness.runtime.learning.active import progress_line
from ..terminal import APPROVE_WORDS, COMMANDS, command, find, item_lines
from . import agent as life
from . import control, editing, keymap as keymaps, keys, terminal_setup, views
from .answer import Answer
from .commands import Commands
from .history import History

STYLE = Style.from_dict({"rule": "#585858", "status": "#8a8a8a", "status.state": "bold", "status.busy": "#d7875f",
                         "status.wait": "bold #ffaf00", "status.hint": "#6c6c6c", "placeholder": "#6c6c6c",
                         "mode": "#af87ff", "queued": "#6c6c6c", "shell": "#d75f87",
                         "ask": "bold", "ask.title": "bold #ffaf00", "ask.selected": "bold #5f87ff", "ask.why": "#8a8a8a",
                         "help": "#8a8a8a", "search": "#8a8a8a",
                         "completion-menu": "bg:default #8a8a8a",
                         "completion-menu.completion": "bg:default #8a8a8a",
                         "completion-menu.completion.current": "bg:default #5f87ff bold",
                         "completion-menu.meta.completion": "bg:default #6c6c6c",
                         "completion-menu.meta.completion.current": "bg:default #5f87ff"})
# Rich styles of the roles of transcript items (transcript.items).
ROLES = {"task": "bold", "you": "bold", "call": "dim", "thinking": "dim italic", "code": "#5f87ff", "skill": "magenta",
         "result": "green", "verifier": "cyan", "note": "yellow", "turn": "dim", "outcome": "bold green", "end": "bold",
         "error": "red", "entry": "green", "output": "dim"}
# A sub-agent's colour, by its name.
AGENT_COLOURS = ("magenta", "cyan", "green", "yellow", "bright_blue", "bright_magenta")
# Items of a program (its steps, entries, output): in the transcript (Ctrl+O), not in the chat.
DETAILS = {"skill", "skill_step", "entry_start", "entry_claims", "entry_end", "skill_failed", "result", "output",
           "cell_error", "unhandled"}
# Items of the timeline (transcript.items with timeline) the chat leaves out: its calls and
# their usage, how the run ended inside.
TIMELINE = {"call", "usage", "call_set_aside", "compaction", "malformed_dropped", "library_loaded",
            "policy_to_end", "wrap_up", "cleanup_error"}
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# Seconds within which a second Ctrl+C or Ctrl+D leaves, and a second Esc clears the input
# (Claude Code: "a second press within 800ms exits").
TWICE = 0.8
# The status of a conversation that can no longer be followed (its session host is gone).
LOST = "LOST"
FILE = re.compile(r'@"([^"]+)"|@(\S+)')
# approvals.programs, in the order Shift+Tab goes through it, as the mode line says each.
LEVELS = (("ask_each", "ask each time"), ("ask_once_session", "ask once per conversation"), ("allow", "allow"),
          ("never", "never"))
# Records of a conversation kept for the transcript (Ctrl+O).
KEPT = 5000
# Rows of the queue that the live region shows.
QUEUE_ROWS = 5
# The turns the transcript opens on (Ctrl+E there shows them all).
LAST_TURNS = 3
# Commands of a session with another agent (a coding agent, a terminal agent).
SESSION = ("steer", "terminal", "answer", "merge", "handoff")


class Chat(Commands):
    """One terminal chat; run() returns once the user leaves."""

    # Whether the host parked the conversation shown for its workspace (its next message continues it).
    parked = False
    # What a chat built without __init__ (tests) still has.
    ask = search = stash = live = waiting = context = since = None
    help = interrupted = vim = answered = False
    seen = answers = skills = ()
    queue = {"held": False, "running": None, "queued": []}
    level = "ask_once_session"
    last_sent = None

    def __init__(self, conversation=None, records=None, *, host=None, start=None, input=None, output=None):
        self.conversation, self.records, self.host, self.start = conversation, records, host, start
        self.status = None  # the conversation's last status; "starting" while it is created
        self.before_start = None  # the status before "starting": back to it when the start is cancelled or fails
        self.generation = 0
        self.stop = threading.Event()
        self.pending = []  # messages typed while the conversation was created
        self.waiting = None
        self.printed = []  # every renderable printed into the scrollback, in order (_resized prints them again)
        self.printed_size = None  # the terminal size the scrollback was last printed for
        self.help = False
        # What waits for the user's approval: {what, why, options, at, note, request_id, draft}.
        self.ask = None
        self.echoed = None  # a message of this chat printed when it was sent: its record is not printed again
        self.interrupted = False  # asked to stop, not stopped yet
        self.starting = None  # what starting the first message's conversation says now
        self.armed = {}  # key: when it was last pressed (twice to leave, Esc Esc)
        self.model, self.workspace = None, None
        # The agent identity its conversations run as ({id, name, runtime}), or None.
        self.identity = getattr(start, "identity", None)
        self.model_entry = getattr(start, "model_entry", None)
        self.model_effort = getattr(start, "model_effort", None)
        self.environment = None  # (kind, folder) picked with /environment for the next conversation
        self.agents_on = False  # /agents on before a conversation starts: on in the next one
        self.learning = None  # where a conversation that learns its environment stands (runtime/learning/active.py progress())
        self.lanes = Lanes()
        self.seen = []  # the conversation's records, for the transcript
        self.answers = []  # what it answered, newest last (/copy)
        self.skills = []  # the skills callable as /name: (name, what it is)
        self.since = None  # when the turn that runs began
        self._reset()
        self._refresh_next_model(initial_name=getattr(start, "model_name", None))
        self.history = History(data(), Path.cwd())
        self.attachments = editing.Attachments()
        self.keymap = keymaps.load(data())
        self.stamps = (keymaps.stamp(data()), _stamp(data() / "config.toml"))
        self._read_settings()
        # sys.stdout when it prints: patch_stdout's, above the live region.
        self.console = Console(force_terminal=True, legacy_windows=False, highlight=False, soft_wrap=False,
                               color_system="truecolor" if os.environ.get("WT_SESSION") or os.environ.get("COLORTERM")
                               in ("truecolor", "24bit") else "256")
        self.buffer = Buffer(multiline=True, completer=Completions(self), complete_while_typing=True)
        self.app = self._application(input, output)
        self.bound = self._bindings()

    # The live region.

    def _application(self, input=None, output=None) -> Application:
        prompt = lambda line, wrap: [("class:shell" if self.buffer.text.startswith("!") else "class:rule",  # noqa: E731
                                      "› " if line == 0 and not wrap else "  ")]
        field = Window(BufferControl(self.buffer, input_processors=[Placeholder(self)]), height=self._input_height,
                       wrap_lines=True, get_line_prefix=prompt, dont_extend_height=True)
        rule = Window(height=1, char="─", style=lambda: "class:shell" if self.buffer.text.startswith("!") else "class:rule")
        # The completions under the input, as many lines as there are (at most 8).
        menu = ConditionalContainer(Window(CompletionsMenuControl(), height=lambda: min(len(
            self.buffer.complete_state.completions), 8) if self.buffer.complete_state else 1, scroll_offsets=ScrollOffsets(1, 1),
            dont_extend_width=True, style="class:completion-menu"), has_completions)
        def line(left, right):
            return VSplit([Window(FormattedTextControl(left), height=1),
                           Window(FormattedTextControl(right), height=1, dont_extend_width=True, align=WindowAlign.RIGHT)])

        footer = line(self._hint, self._status)
        context = lambda: [("class:status", (self._context_part() or "") + " ")]  # noqa: E731

        def part(text, when, **options):
            return ConditionalContainer(Window(FormattedTextControl(text), **options), Condition(when))

        body = HSplit([part(self._queued, lambda: bool(self.queue["queued"]), dont_extend_height=True),
                       part(self._writing, lambda: bool(self.live and self.live["text"]), dont_extend_height=True),
                       part(self._working, self._busy, height=1),
                       part(self._asking, lambda: self.ask is not None, dont_extend_height=True),
                       rule, field, rule,
                       part(self._searching, lambda: self.search is not None, height=1),
                       menu, footer, line(self._mode, context),
                       part(self._keys, lambda: self.help, dont_extend_height=True)])
        app = Application(Layout(body, focused_element=field), key_bindings=DynamicKeyBindings(lambda: self.bound),
                          style=STYLE, full_screen=False, refresh_interval=0.25, erase_when_done=True,
                          input=input if input is not None else keys.console_input(), output=output,
                          editing_mode=EditingMode.VI if self.vim else EditingMode.EMACS)
        if sys.platform == "win32" and hasattr(app.output, "get_win32_screen_buffer_info"):
            from .renderer import WindowsInlineRenderer

            app.renderer = WindowsInlineRenderer(app.renderer.style, app.output,
                                                 cpr_not_supported_callback=app.cpr_not_supported_callback)
        else:
            # A resize prints the chat again (_resized). tmux does not always deliver SIGWINCH for
            # each change, so the size is also polled; _resized acts once per size.
            app._on_resize = self._resized
            app.terminal_size_polling_interval = 0.2
        app.timeoutlen, app.ttimeoutlen = 0.3, 0.05
        return app

    def _columns(self) -> int:
        return self.app.output.get_size().columns

    def _input_height(self):
        return min(12, len(editing.rows(self.buffer.text, max(1, self._columns() - 2))))

    def _busy(self) -> bool:
        return self.status in ("RUNNING", "starting") and self.ask is None

    def _working(self):
        """The line over the input while it works: what it does, for how long, how to stop it."""
        now = time.time()
        frame = SPINNER[int(now * 8) % len(SPINNER)]
        if self.status == "starting":
            words, stop = (self.starting or "Starting") + "…", ""
        else:
            thinking = self.live and not self.live["text"]
            words = "Compacting…" if (self.queue["running"] or {}).get("kind") == "compact" else \
                "Thinking…" if thinking else "Working…"
            key = self.keymap.key("chat:cancel")
            stop = f" · {key} to interrupt" if key else ""
        since = (self.live or {}).get("since") or (self.queue["running"] or {}).get("since") or self.since
        if since is None:
            since = self.since = now
        return [("class:status.busy", f"{frame} {words} "), ("class:status.hint", f"({_elapsed(now - float(since))}{stop})")]

    def _queued(self):
        """The messages that wait their turn, dim, each on a line."""
        rows = self.queue["queued"]
        out = []
        for row in rows[:QUEUE_ROWS]:
            first, _, more = row["text"].partition("\n")
            out += [("class:queued", "› " + formats.clip(first, max(self._columns() - 6, 10)) + (" …" if more else "")),
                    ("", "\n")]
        if len(rows) > QUEUE_ROWS:
            out += [("class:queued", f"  and {len(rows) - QUEUE_ROWS} more"), ("", "\n")]
        return out[:-1]

    def _writing(self):
        """The reply while it is written: its last rows, as the Markdown read so far."""
        size = self.app.output.get_size()
        text = self.live["text"]
        kept = self.__dict__.get("_written")
        if not kept or kept[0] != (text, size.columns):
            stream = io.StringIO()
            Console(file=stream, force_terminal=True, legacy_windows=False, highlight=False, soft_wrap=False,
                    color_system=self.console.color_system, width=size.columns).print(Answer(text))
            kept = self._written = ((text, size.columns), stream.getvalue().rstrip("\n").split("\n"))
        return ANSI("\n".join(kept[1][-max(3, size.rows - 14):]))

    def _status(self):
        """The right of the line under the input: the conversation's state when it is not
        simply ready, then the identity with today's spending and the model (the context in
        use is at the right of the line under it, beside the approval level)."""
        status = self.status
        state = None
        if status == LOST:
            state = ("class:status.wait", "● not connected")
        elif status == "WAITING_FOR_CONFIRMATION" or self.ask is not None:
            state = ("class:status.wait", "● waits for you")
        elif status not in (None, "IDLE", "RUNNING", "starting"):
            state = ("class:status.state", "● " + word(status))
        if isinstance(self.conversation, life.AgentChat):
            title = self.conversation.title if self.conversation.chat != "main" else None
            parts = [self._identity_part(), self.model, title]
        else:
            # Learning the environment first: the line is cut at the terminal's width.
            parts = [progress_line(self.learning, short=True) if self.learning else None, self._identity_part(),
                     self.model, self.workspace or (self.environment[0] if self.environment and
                                                    self.conversation is None else None),
                     f"session {self.session}" if self.session else None]
        out = [state] if state else []
        # What the hint leaves of the line; a part that does not fit is left out, the model
        # first tried by its short name (without its provider).
        room = self._columns() - get_cwidth("".join(text for _, text in self._hint())) - 3 - (get_cwidth(state[1]) if state else 0)
        for part in parts:
            between = 3 if out else 0
            if part and part == self.model and get_cwidth(part) + between > room:
                part = part.rsplit("/", 1)[-1]
            if part and get_cwidth(part) + between <= room:
                out.append(("class:status", (" · " if out else "") + part))
                room -= get_cwidth(part) + between
        return out + [("", " ")]

    def _identity_part(self):
        """The identity the chat runs as, in the status line, with what it spent today."""
        identity = getattr(self, "identity", None)
        if not identity:
            return None
        name = identity["name"] if identity["name"] == identity["id"] else f"{identity['name']} ({identity['id']})"
        if isinstance(getattr(self, "conversation", None), life.AgentChat):
            spent = life.spend(self.conversation.life)
            return f"{name} · {spent}" if spent else name
        spent = self._spent()
        return f"{name} · {spending.line(spent)}" if spent else name

    def _context_part(self):
        """The context in use, from the model's last call: a share of its window, or tokens."""
        context = self.context
        if not context or not context.get("tokens"):
            return None
        if context.get("window"):
            return f"{min(100, round(100 * context['tokens'] / context['window']))}% context"
        return f"{_count(context['tokens'])} tokens of context"

    def _spent(self):
        """Today's spending of the identity's account, read at most every two seconds."""
        identity = getattr(self, "identity", None)
        if not identity or not identity.get("account"):
            return None
        kept = getattr(self, "_spent_kept", None)
        if kept is None or time.monotonic() - kept[0] > 2:
            try:
                kept = (time.monotonic(), spending.Account(identity["account"]).day())
            except OSError:
                kept = (time.monotonic(), None)
            self._spent_kept = kept
        return kept[1]

    def _hint(self):
        """The left of the line under the input, as Claude Code's footer says it."""
        if self.waiting is not None:
            return [("class:status.wait", "  waiting · esc to cancel")]
        leave = self.armed.get("leave")
        if leave and time.time() - leave[1] < TWICE:
            return [("class:status.wait", f"  Press {leave[0]} again to exit")]
        if self.search is not None:
            return []
        if self.buffer.text.startswith("!"):
            return [("class:shell", "  ! for shell mode")]
        if self.vim:
            mode = "INSERT" if self.app.vi_state.input_mode in (InputMode.INSERT, InputMode.INSERT_MULTIPLE) else \
                "REPLACE" if self.app.vi_state.input_mode in (InputMode.REPLACE, InputMode.REPLACE_SINGLE) else "NORMAL"
            return [("class:status.hint", f"  -- {mode} --")]
        if self.queue["queued"]:
            return [("class:status.hint", "  Press up to edit queued messages")]
        if self.stash is not None:
            return [("class:status.hint", "  Stashed (comes back after you send)")]
        return [("class:status.hint", "" if self.buffer.text else "  ? for shortcuts")]

    def _mode(self):
        """The approval level, and the key that changes it (Claude Code's mode indicator)."""
        label = dict(LEVELS).get(self.level, self.level)
        key = self.keymap.key("chat:cycleMode")
        return [("class:mode", f"  ⏵⏵ approvals: {label}"), ("class:status.hint", f" ({key} to cycle)" if key else "")]

    def _searching(self):
        search = self.search
        return [("class:search", ("no matching prompt: " if search["failed"] else "search prompts: ") + search["query"])]

    def _asking(self):
        """An approval as Claude Code asks a permission: what it is about to do, why it waits
        for you, the answers by number, and a line for a note when Tab opened one."""
        ask = self.ask
        out = [("class:ask.title", "● Approval needed\n"), ("class:ask", f"  {ask['what']}\n")]
        if ask.get("why"):
            out.append(("class:ask.why", f"  {ask['why']}\n"))
        out.append(("", "\n  Do you want to proceed?\n"))
        for number, (_, words) in enumerate(ask["options"], 1):
            selected = number - 1 == ask["at"]
            out += [("class:ask.selected" if selected else "", f"  {'❯' if selected else ' '} {number}. {words}"),
                    ("", "\n")]
        tab, no = self.keymap.key("confirm:addNote"), self.keymap.key("confirm:no")
        if ask["note"]:
            out.append(("class:status.hint", f"  Type the note below · Enter to answer with it · {tab} to close it"))
        else:
            out.append(("class:status.hint", "  " + " · ".join(part for part in (
                "Enter to answer", f"{no} to decline" if no else "", f"{tab} to add a note" if tab else "") if part)))
        return out

    def shortcuts(self) -> list:
        """The three columns of the ? panel and of /help, as Claude Code's shortcuts list is
        laid out: what starts an input, then `key to action` for every key that works here."""
        def row(action, words):
            key = self.keymap.key(action)
            return f"{key} to {words}" if key else None

        newline = [key for key in self.keymap.of("chat:newline")]
        reported = terminal_setup.shift_enter()
        if reported != "native":
            newline = [key for key in newline if key != "shift+enter"]
        first = ["! for shell mode", "!! to run without sending", "/ for commands", "@ for file paths",
                 "\\⏎ for newline"]
        second = ["esc esc to clear input" if self.keymap.key("chat:cancel") == "esc" else None,
                  row("chat:cycleMode", "cycle approval levels"), row("app:toggleTranscript", "see the transcript"),
                  row("app:toggleTimeline", "see the timeline"),
                  (" or ".join(newline[:2]) + " for newline") if newline else None,
                  "shift+enter: /terminal-setup" if reported == "setup" else None,
                  row("history:search", "search history")]
        third = [row("chat:undo", "undo"), "ctrl+z to suspend" if sys.platform != "win32" else None,
                 row("chat:imagePaste", "paste images"), row("chat:modelPicker", "switch model"),
                 row("chat:stash", "stash prompt"), row("chat:externalEditor", "edit in $EDITOR"),
                 row("chat:sendNow", "send queued now"), "/keybindings to customize"]
        return [[text for text in column if text] for column in (first, second, third)]

    def _keys(self):
        columns = self.shortcuts()
        widths = [max(len(text) for text in column) + 3 for column in columns]
        out = []
        for index in range(max(len(column) for column in columns)):
            for column, width in zip(columns, widths):
                out.append(("class:help", "  " + (column[index] if index < len(column) else "").ljust(width)))
            out.append(("", "\n"))
        return out[:-1]

    @property
    def session(self):
        return getattr(self.conversation, "session", None)

    # The keys.

    def _bindings(self) -> KeyBindings:
        """The keymap as prompt_toolkit bindings. A context added later wins a key an earlier
        one binds too; a key no keymap names (the text editing keys) is bound here once."""
        bound, keymap, buffer = KeyBindings(), self.keymap, self.buffer
        fixed = {"ctrl+backspace"}
        keys.bound.clear()
        keys.bound.update(keymap.carried() | fixed)
        views.use(keymap)  # the lists and readers opened over the chat take the same keys
        for carrier in {*keys.carriers().values(), keys.carrier("ctrl+backspace")}:
            bound.add(carrier)(lambda event: None)  # a carrier nothing takes types nothing

        searching = Condition(lambda: self.search is not None)
        asking = Condition(lambda: self.ask is not None)
        choosing = Condition(lambda: self.ask is not None and not self.ask["note"])
        typing = ~searching & ~choosing
        empty = Condition(lambda: not buffer.text)
        clipboard = lambda event: event.app.clipboard  # noqa: E731

        # Editing that is no action of the keymap (Claude Code's "Text editing").
        @bound.add("escape", "b", filter=typing)
        @bound.add("c-left", filter=typing)
        def _(event):
            buffer.cursor_position = editing.word_start(buffer.text, buffer.cursor_position)

        @bound.add("escape", "f", filter=typing)
        @bound.add("c-right", filter=typing)
        def _(event):
            buffer.cursor_position = editing.word_end(buffer.text, buffer.cursor_position)

        @bound.add("escape", "d", filter=typing)
        def _(event):
            editing.kill(buffer, clipboard(event), buffer.cursor_position,
                         editing.word_end(buffer.text, buffer.cursor_position))

        @bound.add("escape", "backspace", filter=typing)
        @bound.add(keys.carrier("ctrl+backspace"), filter=typing)
        def _(event):
            editing.kill(buffer, clipboard(event), editing.word_start(buffer.text, buffer.cursor_position),
                         buffer.cursor_position)

        @bound.add("c-w", filter=typing)
        def _(event):
            before = buffer.document.text_before_cursor
            editing.kill(buffer, clipboard(event), len(before.rstrip()) - len(before.rstrip().split()[-1])
                         if before.strip() else 0, buffer.cursor_position)

        @bound.add("c-k", filter=typing)
        def _(event):
            end = buffer.document.get_end_of_line_position()
            editing.kill(buffer, clipboard(event), buffer.cursor_position,
                         buffer.cursor_position + (end or (1 if buffer.cursor_position < len(buffer.text) else 0)))

        @bound.add("c-u", filter=typing)
        def _(event):
            start = -buffer.document.get_start_of_line_position()
            editing.kill(buffer, clipboard(event), buffer.cursor_position - (start or (1 if buffer.cursor_position else 0)),
                         buffer.cursor_position)

        @bound.add("backspace", filter=typing)
        def _(event):
            editing.backspace(buffer)

        @bound.add("c-z")
        def _(event):
            if sys.platform != "win32":
                event.app.create_background_task(self._suspend())

        @bound.add(Keys.BracketedPaste, filter=typing)
        def _(event):
            buffer.insert_text(self.attachments.paste(event.data))

        @bound.add("?", filter=empty & typing & ~asking)
        def _(event):
            self.help = not self.help

        @bound.add(Keys.Any, filter=choosing)
        def _(event):
            pass  # the approval has the keys until it is answered

        for digit in "123456789":
            @bound.add(digit, filter=choosing)
            def _(event, digit=digit):
                if int(digit) <= len(self.ask["options"]):
                    self._answer(int(digit) - 1)

        # Searching the history: what is typed is the query.
        @bound.add(Keys.Any, filter=searching)
        @bound.add(Keys.BracketedPaste, filter=searching)
        def _(event):
            self._search_for(self.search["query"] + event.data.replace("\r", " ").replace("\n", " "))

        @bound.add("backspace", filter=searching)
        def _(event):
            if self.search["query"]:
                self._search_for(self.search["query"][:-1])
            else:
                self._search_end(restore=True)

        for moving in ("left", "right", "up", "down", "home", "end", "c-a", "c-e", "c-k", "c-u", "c-w", "delete"):
            @bound.add(moving, filter=searching)
            def _(event):
                self._search_end()
                event.key_processor.feed(event.key_sequence[-1], first=True)

        run = lambda name: self.submit("/" + name)  # noqa: E731
        keymap.bind(bound, "Global", {
            "app:interrupt": lambda event: self._interrupt_key(event),
            "app:exit": lambda event: self._exit_key(event),
            "app:redraw": lambda event: self._redraw(),
            "app:toggleTranscript": lambda event: self.do_transcript(""),
            "app:toggleTimeline": lambda event: self.do_timeline("")})
        keymap.bind(bound, "Chat", {
            "chat:cancel": lambda event: self._cancel(event),
            "chat:clearInput": lambda event: self._redraw(),
            "chat:cycleMode": lambda event: self._cycle_level(),
            "chat:modelPicker": lambda event: self.do_model(""),
            "chat:submit": lambda event: self._enter(event),
            "chat:sendNow": lambda event: self._send_now(),
            "chat:newline": lambda event: buffer.newline(copy_margin=False),
            "chat:undo": lambda event: self._undo(),
            "chat:externalEditor": lambda event: event.app.create_background_task(self._guarded(self._edit_draft)),
            "chat:stash": lambda event: self._stash(),
            "chat:imagePaste": lambda event: self._paste_image(),
            "history:search": lambda event: self._search_start(),
            "history:previous": lambda event: self._up(),
            "history:next": lambda event: self._down()},
            filter=typing, command=run, filters={"chat:cancel": typing & ~vi_insert_mode})
        keymap.bind(bound, "Help", {"help:dismiss": lambda event: setattr(self, "help", False)},
                    filter=typing & Condition(lambda: self.help) & ~vi_insert_mode)
        keymap.bind(bound, "Autocomplete", {
            "autocomplete:accept": lambda event: self._complete(),
            "autocomplete:dismiss": lambda event: buffer.cancel_completion(),
            "autocomplete:previous": lambda event: buffer.complete_previous(),
            "autocomplete:next": lambda event: buffer.complete_next()}, filter=typing & has_completions)
        keymap.bind(bound, "Confirmation", {
            "confirm:yes": lambda event: self._answer(self.ask["at"]),
            "confirm:no": lambda event: self._decline(),
            "confirm:previous": lambda event: self._choose(-1),
            "confirm:next": lambda event: self._choose(1),
            "confirm:addNote": lambda event: self._note_field()}, filter=asking)
        keymap.bind(bound, "HistorySearch", {
            "historySearch:next": lambda event: self._search_for(self.search["query"], self.search["skip"] + 1),
            "historySearch:accept": lambda event: self._search_end(),
            "historySearch:cancel": lambda event: self._search_end(restore=True),
            "historySearch:execute": lambda event: self._search_end(send=True)}, filter=searching)
        return bound

    def _twice(self, key) -> bool:
        """Whether `key` was pressed within TWICE seconds before (then it no longer counts)."""
        now, before = time.time(), self.armed.get(key)
        self.armed[key] = None if before and now - before < TWICE else now
        return bool(before and now - before < TWICE)

    def _interrupt_key(self, event):
        """Ctrl+C: stop what runs; then clear the input (the draft comes back with Up); the
        second press within TWICE leaves, also while the agent works (it goes on)."""
        if self._twice("c-c"):
            event.app.exit()
            return
        if self._busy() and self.conversation is not None and not self.interrupted:
            self.interrupt()
        elif self.buffer.text:
            self._clear_draft()
        self.armed["leave"] = ("Ctrl-C", time.time())

    def _exit_key(self, event):
        """Ctrl+D: with text, delete the character after the cursor; on an empty input the
        second press within TWICE leaves."""
        if self.buffer.text:
            self.buffer.delete(1)
        elif self._twice("c-d"):
            event.app.exit()
        else:
            self.armed["leave"] = ("Ctrl-D", time.time())

    def _cancel(self, event):
        """Esc: stop waiting for the host, else stop the turn; twice with text: clear the input."""
        if self.waiting is not None:
            self.waiting.cancel()
        elif self._busy() and self.conversation is not None:
            self.interrupt()
        elif self.buffer.text and self._twice("escape"):
            self._clear_draft()

    def _clear_draft(self):
        """Empty the input, keeping what was in it for Up."""
        self.history.draft(self.buffer.text, self.attachments.kept(self.buffer.text))
        self.buffer.set_document(Document(""))

    def _put(self, text: str, kept=None):
        """`text` into the input with the cursor at its end (a recalled message, a draft given back)."""
        if kept:
            self.attachments.restore(kept)
        self.buffer.set_document(Document(text, len(text)))

    def _up(self):
        """Up: a row up in the draft; from its first row, take back what is queued, else the
        message before in the history."""
        if editing.vertical(self.buffer, self._columns() - 2, -1):
            return
        if self.queue["queued"] and isinstance(self.conversation, life.AgentChat):
            self._take_back()
            return
        entry = self.history.previous(self.buffer.text)
        if entry is not None:
            self._put(entry["text"], entry)

    def _down(self):
        if editing.vertical(self.buffer, self._columns() - 2, 1):
            return
        entry = self.history.next()
        if entry is not None:
            self._put(entry["text"], entry)

    def _enter(self, event):
        buffer = self.buffer
        state = buffer.complete_state
        slash = buffer.text.startswith("/") and " " not in buffer.text
        if state and state.completions and (state.current_completion or slash):
            # A completion picked (or the command the letters name): taken; Enter sends once nothing changes.
            picked = state.current_completion or state.completions[0]
            if _nothing(picked):
                buffer.cancel_completion()  # nothing matches: sent as typed, answered "Unknown command"
            else:
                before = buffer.text
                buffer.apply_completion(picked)
                found = find(buffer.text[1:]) if slash else None
                if found is not None and found[1].words and not found[1].words.startswith("["):
                    buffer.insert_text(" ")
                    return
                if not slash and buffer.text != before:
                    return
        if buffer.document.text_before_cursor.endswith("\\"):
            buffer.delete_before_cursor()
            buffer.newline(copy_margin=False)
            return
        self._send_draft()

    def _send_draft(self):
        text = self.buffer.text
        self.history.add(text, self.attachments.kept(text))
        self.buffer.set_document(Document(""))
        self.help = False
        self.submit(text)
        if self.stash is not None and not self.buffer.text:
            self._stash()  # what was put aside comes back once something was sent

    def _complete(self):
        """Tab on the list: the highlighted suggestion, or the first."""
        state = self.buffer.complete_state
        if state and state.completions:
            picked = state.current_completion or state.completions[0]
            if not _nothing(picked):
                self.buffer.apply_completion(picked)

    def _undo(self):
        """Ctrl+_: the last edit undone. What was typed goes a word at a time (prompt_toolkit
        keeps a step for every character typed)."""
        buffer, steps = self.buffer, 0
        while True:
            before = buffer.text
            buffer.undo()
            after = buffer.text
            if after == before or len(before) - len(after) != 1:
                return
            at = next((index for index in range(len(after)) if before[index] != after[index]), len(after))
            if before[at].isspace():
                if steps:
                    buffer.redo()  # the space before the word stays
                return
            steps += 1

    def _stash(self):
        """Ctrl+S: put the draft aside; on an empty input, bring it back."""
        buffer = self.buffer
        if buffer.text:
            self.stash = (buffer.text, buffer.cursor_position, self.attachments.kept(buffer.text))
            buffer.set_document(Document(""))
        elif self.stash is not None:
            (text, cursor, kept), self.stash = self.stash, None
            self.attachments.restore(kept)
            buffer.set_document(Document(text, cursor))

    async def _edit_draft(self):
        """Ctrl+G: the draft in the user's editor; what is saved there is the draft."""
        folder = data() / "drafts"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"draft-{os.getpid()}.md"
        path.write_text(self.buffer.text, encoding="utf-8", newline="\n")
        try:
            await self._edit(path, say=False)
            self._put(path.read_text(encoding="utf-8").rstrip("\n"))
        finally:
            path.unlink(missing_ok=True)

    def _paste_image(self):
        """The image on the clipboard as a chip in the draft; its file goes with the message."""
        from . import clipboard

        def read():
            found = clipboard.image(data() / "pasted", time.strftime("image-%Y%m%d-%H%M%S"))
            if found is None:
                self.note("No image on the clipboard.", "yellow")
            else:
                self._later(lambda: self.buffer.insert_text(self.attachments.image(found)))

        self._background(read)

    async def _suspend(self):
        """Ctrl+Z: back to the shell until `fg` (not on Windows)."""
        import signal

        self._report_keys(False)
        async with in_terminal():
            os.kill(0, signal.SIGTSTP)
        self._report_keys(True)

    # The history search (Ctrl+R).

    def _search_start(self):
        self.search = {"query": "", "skip": 0, "failed": False,
                       "original": (self.buffer.text, self.buffer.cursor_position)}
        self.buffer.cancel_completion()

    def _search_for(self, query: str, skip: int = 0):
        search = self.search
        entry = self.history.search(query, skip)
        if entry is None and skip:
            return  # no earlier match: the one shown stays
        search.update(query=query, skip=skip, failed=bool(query) and entry is None, entry=entry)
        if entry is not None:
            self._put(entry["text"], entry)
        elif not query:
            self.buffer.set_document(Document(*search["original"]))
        self.buffer.cancel_completion()

    def _search_end(self, restore=False, send=False):
        search, self.search = self.search, None
        if restore:
            self.buffer.set_document(Document(*search["original"]))
        elif send and self.buffer.text.strip():
            self._send_draft()

    # The approval level and the settings the chat reads.

    def _read_settings(self):
        """What config.toml says of the chat: the approval level and the editing mode."""
        from ..settings import Settings

        try:
            values = Settings(data()).get()
        except (OSError, ValueError):
            return
        self.level = (values.get("approvals") or {}).get("programs", self.level)
        self.vim = (values.get("terminal") or {}).get("editor_mode") == "vim"
        app = self.__dict__.get("app")
        if app is not None:
            app.editing_mode = EditingMode.VI if self.vim else EditingMode.EMACS

    def _cycle_level(self):
        """Shift+Tab: the next approval level (approvals.programs), kept in the settings."""
        from ..settings import Settings

        names = [name for name, _ in LEVELS]
        level = names[(names.index(self.level) + 1) % len(names)] if self.level in names else names[0]
        try:
            Settings(data()).update({"approvals": {"programs": level}})
        except (OSError, ValueError) as error:
            self.problem(error)
            return
        self.level = level
        self.stamps = (self.stamps[0], _stamp(data() / "config.toml"))
        self.app.invalidate()

    async def _watch(self):
        """Take the keybindings file and the settings again when they change on disk."""
        while True:
            await asyncio.sleep(1.0)
            stamps = (keymaps.stamp(data()), _stamp(data() / "config.toml"))
            if stamps[0] != self.stamps[0]:
                self.reload_keys()
            if stamps[1] != self.stamps[1]:
                self._read_settings()
            self.stamps = stamps

    def reload_keys(self):
        """Read keybindings.json again and bind what it says; say what is wrong with it."""
        self.keymap = keymaps.load(data())
        self.bound = self._bindings()
        for problem in self.keymap.problems:
            self.note(f"{keymaps.FILE}: {problem}", "yellow")
        self.app.invalidate()

    def _report_keys(self, on: bool):
        """Ask the terminal to report modified keys (keys.ENABLE), or put it back as it was."""
        translator = getattr(getattr(self.app, "input", None), "translator", None)
        if translator is None:
            return  # the console's key records carry every modifier: nothing to ask for
        output = self.app.output
        if on:
            translator.on_kitty = lambda: (output.write_raw(keys.KITTY_ON), output.flush())
            output.write_raw(keys.ENABLE + (keys.KITTY_ON if translator.kitty else ""))
        else:
            translator.on_kitty = None
            output.write_raw((keys.KITTY_OFF if translator.kitty else "") + keys.MODIFY_OFF)
        output.flush()

    async def _view(self, coroutine):
        """A full-screen view over the chat; what it returns."""
        size = self.app.output.get_size()
        try:
            async with in_terminal(render_cli_done=False):
                return await coroutine
        finally:
            if sys.platform != "win32" and self.app.output.get_size() != size:
                self._resized()

    def run(self):
        """Until the user leaves; returns the conversation shown then (None: none)."""
        # The views opened over the chat read the same keys as the chat: the session's input is
        # the chat's while it runs (prompt_toolkit 3.0.52 keeps it in AppSession._input; a
        # session of its own would hide the running chat from patch_stdout's thread).
        session = get_app_session()
        before, session._input = session._input, self.app.input
        self._banner()
        self.printed_size = self.app.output.get_size()
        try:
            with patch_stdout(raw=True):
                self.app.run(pre_run=self._begin)
        finally:
            session._input = before
            self._report_keys(False)
        self.stop.set()
        self._farewell()
        return self.conversation

    def _begin(self):
        self._report_keys(True)
        self.app.create_background_task(self._watch())
        for problem in self.keymap.problems:
            self.note(f"{keymaps.FILE}: {problem}", "yellow")
        if self.conversation is not None:
            self._follow(self.conversation, self.records)
        else:
            self._open()

    def _farewell(self):
        """What leaving says: the agent goes on, how to come back, how to stop it."""
        conversation = self.conversation
        if isinstance(conversation, life.AgentChat) and self.host is not None:
            name = (self.identity or {}).get("name") or "The agent"
            lines = [f"{name} goes on in the background.", "  harness             come back to it",
                     "  harness host stop   stop it (and what runs in it)"]
        elif conversation is not None and self.status not in (*ENDED, LOST, None) and self.host is not None:
            lines = ["The conversation goes on in the background.", "  harness -c          come back to it",
                     "  harness host stop   stop the session host (and what runs in it)"]
        else:
            return
        for line in lines:
            self.console.print(Text(line, style="dim"))

    def _agent_mode(self) -> bool:
        """Whether the chat is an identity's (an identity, and nothing on the command line that
        names a conversation of the app's agent: --workspace, --folder, --agent)."""
        return (bool(getattr(self, "identity", None)) and not getattr(getattr(self, "start", None), "named", False)
                and not getattr(self, "identity_chat_error", None))

    def _open(self):
        if not self._agent_mode():
            self._open_environment()
            self._first_message()
            return
        generation = self.generation
        self.before_start, self.status, self.starting = None, "starting", "Connecting to the session host"

        def connect():
            try:
                from ..host import Host

                host = self.host or Host.connect(log=lambda message: self._later(self._starting, message, generation))
                self._later(self._left_out, host)
                # The chat harness was started on (harness -r CHAT), else the main conversation.
                chat = life.AgentChat(host, self.identity, getattr(self.start, "chat", None) or "main")
                chat.describe()
            except Exception as error:
                # No resident life in the host (an agent package without it): as before.
                self._later(self._agent_unavailable, generation, error)
                return
            self._later(self._agent_opened, generation, host, chat)

        threading.Thread(target=connect, daemon=True).start()

    def _left_out(self, host) -> None:
        """Say once which packages this host left out and why (its `problems`): what they
        would add is missing from this chat, and the reason is not in a log only."""
        shown = self.__dict__.setdefault("_problems_shown", set())
        for text in ((getattr(host, "state", None) or {}).get("problems") or {}).values():
            if text not in shown:
                shown.add(text)
                self.note(text, "yellow")

    def _agent_opened(self, generation, host, chat):
        if generation != self.generation:
            return
        self.host, self.starting = host, None
        self._follow(chat)
        self._background(self._load_skills)
        self._first_message()

    def _first_message(self):
        """The message harness was started with (harness "do this") is sent once the chat is open."""
        prompt = getattr(self.start, "prompt", None)
        if prompt:
            self.start.prompt = None
            self.send(prompt)

    def _agent_unavailable(self, generation, error):
        if generation != self.generation:
            return
        self.status, self.starting = None, None
        self.identity_chat_error = str(error)
        # A host that did not start, or one that left the agent package out, is said; a host
        # whose agent package has no resident life (an older one) is not a failure.
        if not control.missing(error):
            self.problem(error, "the identity's conversation is not available: ")
        if isinstance(error, RemoteError):
            self._open_environment()  # the host answers: ask it where the conversation works

    def _agent_show(self, record):
        """A record of the identity's chat (or a notice about another chat of it)."""
        kind = record.get("event")
        conversation = self.conversation
        live = not record.get("history")
        if kind == "live_now":
            self.live = record.get("live")
            self.app.invalidate()
            return
        if kind == "queue_now":
            self.queue = record["queue"]
            self.app.invalidate()
            return
        if kind == "context_now":
            self.context = record["context"]
            self.app.invalidate()
            return
        if kind not in ("agent_state", "notice"):
            self._keep(record)
            self.lanes.add(record)
        if kind == "agent_state":
            # A turn that already answered is over for the user while the host finishes it.
            if self.status != "starting" and not (record["status"] == "RUNNING" and self.answered):
                self._state(record["status"])
            if record["status"] != "RUNNING":
                self.answered = False
        elif kind == "turn_started" and live:
            self._state("RUNNING")
            self.answered = False
        elif kind in ("reply", "done", "error", "asleep", "spending_limit", "deferred", "interrupted") and live:
            self._state("IDLE")
            self.interrupted, self.answered = False, True
        if kind == "model_reply" and record.get("role") in (None, "dialogue") and getattr(conversation, "context", None) is None:
            # A host that does not say the context in use: the last call's tokens are it.
            usage = record.get("usage") or {}
            tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
            if tokens:
                self.context = {"tokens": tokens, "window": usage.get("context_window")}
        if kind == "user" and live and self.echoed is not None and record.get("text") == self.echoed:
            self.echoed = None
            return
        if kind == "approval":
            code = record.get("code")
            if record.get("state") == "waiting" and code in getattr(conversation, "pending", {}):
                self._asked(life.approval_ask(record))
            elif self.ask is not None and self.ask.get("request_id") == code:
                self._asked(None)
        if kind == "reply":
            self.answers.append(str(record.get("text") or ""))
        if kind == "error" and live:
            self._give_back()
        out = []
        for line in life.lines(record):
            if line[0] == "answer":
                out += [Answer(line[1]), Text("")]
            else:
                out.append(Text(line[0], style=line[1]))
        self._print(*out)
        self.app.invalidate()

    def _state(self, status):
        """The conversation's status; a turn that begins is timed from now."""
        if status == "RUNNING" and self.status != "RUNNING":
            self.since = time.time()
        self.status = status

    def _keep(self, record):
        self.seen.append(record)
        if len(self.seen) > KEPT:
            del self.seen[:len(self.seen) - KEPT]

    def _give_back(self):
        """After a failed turn: the message it was about back in the input box, to change and send again."""
        text, self.last_sent = self.last_sent, None
        if text and not self.buffer.text and not self.queue["queued"]:
            self._put(text)
            self.note("  Your message is back in the input box.")

    def _client(self):
        """The identity's /api/agent routes on the host; None (and a note) without an identity."""
        if not getattr(self, "identity", None):
            self.note("This is an agent identity's: harness --identity ID (the agent package)", "yellow")
            return None
        return life.Client(self._host(), self.identity["id"])

    def _banner(self):
        """Above the input when the chat opens, as Claude Code starts: the product and its
        version, the model and who it runs as, the directory."""
        from .. import __version__

        here = os.getcwd().replace(os.path.expanduser("~"), "~", 1)
        identity = getattr(self, "identity", None)
        who = [part for part in (self.model, f"as {identity['name']}" if identity else None) if part]
        self._print(Text.assemble(("▌ ", "#af87ff"), ("The Harness", "bold"), (f" v{__version__}", "dim")),
                    Text.assemble(("▌ ", "#af87ff"), (" · ".join(who) or "no model yet: /login", "dim")),
                    Text.assemble(("▌ ", "#af87ff"), (here, "dim")), Text(""))
        if warning := getattr(self.start, "warning", None):
            self.note(warning, "yellow")
        from ..update import check_in_background

        # A newer release on PyPI, in one line (asked at most once a day, in the background).
        check_in_background(self.note)

    # Printing into the scrollback (patch_stdout carries it above the live region).

    def _print(self, *renderables):
        self.printed.extend(renderables)
        try:
            self.console.width = self.app.output.get_size().columns
        except Exception:
            pass
        for renderable in renderables:
            self.console.print(renderable)

    def _resized(self, force=False):
        """The terminal changed size: clear it and print the chat again at the new width, then
        draw the live region, as Claude Code does. A terminal reflows the rows it already shows
        in its own way (tmux 3.2 and 3.8 split the same row differently), so erasing the old
        live region in place left some of its rows behind. Clearing also takes the terminal's
        scrollback from before the chat started."""
        app = self.app
        size = app.output.get_size()
        if size == self.printed_size and not force:
            return
        self.printed_size = size
        stream = io.StringIO()
        console = Console(file=stream, force_terminal=True, legacy_windows=False, highlight=False, soft_wrap=False,
                          color_system=self.console.color_system, width=size.columns)
        for renderable in self.printed:
            console.print(renderable)
        # Home, clear the screen, then the scrollback (clearing the screen copies it there in tmux).
        app.output.write_raw("\x1b[H\x1b[2J\x1b[3J" + stream.getvalue().replace("\n", "\r\n"))
        app.output.flush()
        app.renderer.reset(leave_alternate_screen=False)
        app.renderer.request_absolute_cursor_position()
        app.invalidate()

    def _redraw(self):
        """Ctrl+L: draw the whole terminal again, keeping the input and the conversation."""
        self._resized(force=True)

    def note(self, text, style="dim"):
        self._later(self._print, Text(str(text), style=style))

    def problem(self, error, lead: str = "") -> None:
        """A failure as every frontend says it (problems.py): what went wrong, in red, then
        what to do and where the log is. `error` is an exception or its words."""
        first, *rest = problem_lines(error if isinstance(error, BaseException) else Problem(str(error)))
        if str(getattr(error, "code", "")).startswith(("host_", "data_")):
            lead = ""  # the reason names the session host already
        self.note(f"{lead}{first}", "red")
        for line in rest:
            self.note(f"  {line}")

    def _later(self, function, *args):
        """`function` on the chat's own thread (the event loop), from any thread."""
        loop = getattr(self.app, "loop", None)
        if loop is not None and self.app.is_running:
            loop.call_soon_threadsafe(function, *args)
        else:
            function(*args)

    def _background(self, function, *args):
        """`function` on a thread of its own (the host's calls block); an error is noted."""
        def run():
            try:
                function(*args)
            except Exception as error:
                self.problem(error)

        threading.Thread(target=run, daemon=True).start()

    # The conversation's records.

    def _reset(self):
        self.names, self.program, self.last_program, self.programs, self.said = {}, None, None, 0, None

    def _follow(self, conversation, records=None):
        """Show `conversation` from its first record (or `records`, a local one's), in place of
        any other (that goes on)."""
        self.stop.set()
        self.stop, self.generation = threading.Event(), self.generation + 1
        self.pending = []
        self.starting = None
        self.conversation, self.lanes = conversation, Lanes()
        self._asked(None)
        self.learning, self.workspace, self.parked = None, None, False
        self.live, self.queue, self.context, self.since = None, {"held": False, "running": None, "queued": []}, None, None
        self.seen, self.answers, self.interrupted, self.last_sent = [], [], False, None
        self.instruction_files = []  # (label, path) of each instruction file the conversation read
        self.status = getattr(conversation, "status", None)
        self._reset()
        generation, stop = self.generation, self.stop

        def read():
            try:
                if hasattr(conversation, "describe"):
                    conversation.describe()
                    agent = conversation.agent or {}
                    self._later(self._described, generation, agent)
            except Exception:
                pass
            try:
                for record in records if records is not None else conversation.records(stop=stop):
                    if generation != self.generation:
                        return
                    self._later(self.show, record, generation)
            except HostGone as error:
                self._later(self._lost, generation, error)
            except Exception as error:
                self._later(self._lost, generation, error, "the conversation cannot be read any more: ")

        threading.Thread(target=read, daemon=True).start()

    def _described(self, generation, agent):
        if generation == self.generation:
            self.model, self.workspace = agent.get("model") or self.model, agent.get("workspace")

    def _lost(self, generation, error, lead=""):
        """The conversation shown can no longer be followed: say why, and stop showing it as working."""
        if generation != self.generation:
            return
        self.host = None
        self.problem(error, lead)
        if self.status not in ENDED:
            self.status, self.interrupted, self.live = LOST, False, None
            self._asked(None)

    def show(self, record: dict, generation=None):
        if generation is not None and generation != self.generation:
            return
        if record.get("agent_chat") is not None:
            self._agent_show(record)
            return
        self._keep(record)
        self.lanes.add(record)
        kind = record.get("event")
        if kind in ("workspace_reclaimed", "resumed"):
            self.parked = kind == "workspace_reclaimed"
        if kind == "state":
            self._state(record["status"])
            self.interrupted = False
            if self.status in ("IDLE", "PAUSED", *ENDED):
                self._asked(None)
        if kind in ("physical_answer", "confirmation"):
            self._asked(None)
        if kind == "instructions":
            known = getattr(self, "instruction_files", None)
            if known is None:
                known = self.instruction_files = []
            known += [(item["label"], item["path"]) for item in record.get("files") or ()
                      if (item["label"], item["path"]) not in known]
        # The timeline's items too, for the reasoning and the answer of finish() in a program.
        items = [item for item in transcript.items(record, self.names, timeline=True) if item["kind"] not in TIMELINE]
        if kind == "cell" and self.program is not None:
            out = self._ended(record, items)
        else:
            out = [line for item in items for line in self._item(item, record)]
        if kind == "confirmation_request" and self.program is not None:
            # What it asks to run.
            out += self._program_lines(self.program)
        if kind in ("physical_request", "confirmation_request"):
            self._ask(record, items)
        if kind in ("library", "cell", "state") and self.host is not None:
            self._background(self._learning_now, self.conversation)
        self._print(*out)
        self.app.invalidate()

    # An approval.

    def _ask(self, record, items):
        asked = next(item for item in items if item["kind"] in ("physical_request", "approval_request"))
        keys_ = asked.get("keys") or {}
        what = asked["text"] if asked["kind"] == "physical_request" else asked["text"].capitalize()
        why = keys_.get("why") if not keys_.get("sensitive") else None
        self._asked({"what": what, "why": f"Why it asks: {why}" if why else "It waits for you before it does this.",
                     "options": transcript.approval_options(asked), "request_id": record.get("id")})

    def _asked(self, ask):
        """An approval begins to wait (the draft is put aside until it is answered), or stops waiting."""
        buffer = self.__dict__.get("buffer")
        before = self.ask
        if before is not None and buffer is not None and (ask is None or before.get("draft") is not None):
            draft = before.get("draft")
            if ask is None and draft is not None:
                buffer.set_document(Document(*draft))
            elif ask is None and before.get("note"):
                buffer.set_document(Document(""))
        if ask is None:
            self.ask = None
            return
        draft = (before or {}).get("draft")
        if before is None and buffer is not None and buffer.text:
            draft = (buffer.text, buffer.cursor_position)
            buffer.set_document(Document(""))
        self.ask = {"why": "", **ask, "at": 0, "note": False, "draft": draft}

    def _choose(self, step: int):
        self.ask["at"] = max(0, min(self.ask["at"] + step, len(self.ask["options"]) - 1))

    def _note_field(self):
        """Tab: a line for a note that goes with the answer; again: close it."""
        self.ask["note"] = not self.ask["note"]
        self.buffer.set_document(Document(""))

    def _answer(self, index: int, note=None):
        """Answer the approval with its option `index`; a note typed goes with it."""
        ask = self.ask
        remember = ask["options"][index][0]
        if note is None:
            note = self.buffer.text.strip() if ask["note"] else ""
        conversation = self.conversation
        self._asked(None)
        if remember is None:
            self._background(command, conversation, "deny", {"reason": note, "request_id": ask["request_id"]})
        else:
            self._background(command, conversation, "approve",
                             {"remember": remember, "reason": note, "request_id": ask["request_id"]})

    def _decline(self):
        """Esc on an approval: declined, as "no" without a note."""
        ask = self.ask
        self._answer(next(index for index, (value, _) in enumerate(ask["options"]) if value is None), note="")

    def _item(self, item, record) -> list:
        """Chat scrollback stays compact; program details belong to the transcript."""
        kind, text = item["kind"], item["text"]
        if not text.strip():
            return []
        if kind == "task" and text == self.echoed:
            self.echoed = None
            return []
        if kind in ("task", "user"):
            return [Text("› " + text, style="bold")]
        if kind == "finished":  # finish(answer) in a program, or the reply that said it
            answer = str(record.get("text") or "").strip()
            if answer and answer != self.said:
                self.answers.append(answer)
            return [] if not answer or answer == self.said else [Answer(answer), Text("")]
        if kind in ("message", "thought", "finish", "verify_ask", "invalid"):
            self.said = text.strip()
            self.answers.append(text.strip())
            return [Answer(text), Text("")]
        if kind == "reasoning":
            return [Text("\n".join(formats.clip_lines(text, 12)), style="dim italic")]
        if kind == "program":
            self.programs += 1
            self.program = {"number": self.programs, "code": text,
                            "lexer": "python" if item["keys"].get("reply") == "python" else "json"}
            return []
        if kind in DETAILS and self.program is not None:
            return []  # in the transcript
        if kind == "state":
            return [] if text == "your turn" else [Text(f"— {text}" + (": a message goes on with it"
                                                                       if text == "paused" else ""), style="dim")]
        if kind == "approval_request" or kind == "outcome" and (record.get("outcome") or {}).get("success") is None:
            return []  # the approval box asks; an outcome nothing scored says nothing
        if kind == "physical_request":  # asked in the approval box; its answer is a line of its own
            return []
        agent = record.get("agent") if kind.startswith("agent") else None
        if agent:
            colour = AGENT_COLOURS[sum(map(ord, str(agent))) % len(AGENT_COLOURS)]
            return [Text.assemble((f"◆ {agent} ", f"bold {colour}"), (line, ROLES.get(role, "")))
                    for role, line in item_lines(item)]
        return [Text(line, style=ROLES.get(role, "")) for role, line in item_lines(item)]

    def _ended(self, record, items) -> list:
        """The program's `cell` record: one line for it; its result and output are the transcript's."""
        done, self.program = self.program, None
        self.last_program = done
        result = record.get("result") or {}
        done.update(status=result.get("status"), seconds=result.get("seconds"))
        return [self._program_line(done)]

    def _program_line(self, program) -> Text:
        status = program.get("status") or "?"
        style = "green" if status in ("ok", "finished") else "red" if status in ("error", "failed", "timeout") else "yellow"
        key = self.keymap.key("app:toggleTranscript")
        return Text.assemble((f"▸ Program {program['number']}", "#5f87ff"), " · ", (status, style),
                             f" · {formats.duration(program.get('seconds'))}" if program.get("seconds") is not None else "",
                             (f"   ({key} to expand)" if key else "", "dim"))

    def _program_lines(self, program) -> list:
        """A program it asks to run: its number and its code."""
        return [Text(f"▾ Program {program['number']}", style="#5f87ff"),
                Syntax(program["code"], program["lexer"], word_wrap=True)]

    def transcript_text(self, everything=False) -> str:
        """The transcript viewer's text: every record of the conversation in detail (a
        program's code and whole output, a call's model, tokens and time), the last turns
        unless `everything`."""
        if isinstance(self.conversation, life.AgentChat):
            rows = life.details(self.seen)
        else:
            rows, names, programs = [], {}, 0
            for record in self.seen:
                when = time.strftime("%H:%M:%S", time.localtime(record["time"])) if record.get("time") else "--:--:--"
                lines, turn = [], False
                for item in transcript.items(record, names, timeline=True):
                    turn = turn or item["kind"] in ("task", "user")
                    if item["kind"] == "program":
                        programs += 1
                        lines.append(f"{when}  ▾ Program {programs}")
                        lines += ["    " + line for line in item["text"].splitlines()]
                    elif item["kind"] in ("output", "cell_error", "unhandled"):
                        lines += ["    " + line for line in item["text"].splitlines()]
                    else:
                        lines += [f"{when}  {line}" for _, line in item_lines(item) if line.strip()]
                if lines:
                    rows.append((turn, lines))
        if not rows:
            return "Nothing happened in this conversation yet."
        turns = [index for index, (turn, _) in enumerate(rows) if turn]
        if not everything and len(turns) > LAST_TURNS:
            rows = rows[turns[-LAST_TURNS]:]
        return "\n".join(line for _, lines in rows for line in lines)

    # What the user does.

    def submit(self, text: str):
        line = text.strip()
        if self.ask is not None and self.ask.get("note"):
            self._answer(self.ask["at"], note=line)
            return
        if not line:
            return
        if line.startswith("!"):
            self._shell(line.lstrip("!").strip(), send=not line.startswith("!!"))
            return
        if line.startswith("/"):
            name, _, rest = line[1:].partition(" ")
            if self.run_command(name, rest.strip()):
                return
            self.note(self._unknown(name), "red")
            return
        full, images = self.attachments.expand(line)
        files = [str(Path(quoted or bare).expanduser().resolve()) for quoted, bare in FILE.findall(line)
                 if Path(quoted or bare).expanduser().exists()]
        self.send(full, [*files, *[path for path in images if path not in files]], shown=line)

    def run_command(self, name: str, rest: str = "") -> bool:
        """Do the command /name (by its name, an alias, or a skill's name); False when there is none."""
        found = find(name)
        if found is None:
            skill = next((row for row in self.skills if row[0] == name), None)
            if skill is None:
                return False
            self.send(f"Use your skill {skill[0]}." + (f" {rest}" if rest else ""))
            return True
        name, found = found
        why = self.available(name)
        if why is not None:
            self.note(f"/{name} is not for this conversation: {why}", "yellow")
        elif found.method:
            if self.conversation is None:
                self.note("No conversation yet: send a message first", "red")
            else:
                values = {found.takes[0]: rest} if found.takes else {}
                if self.ask is not None and "request_id" in found.takes:
                    values["request_id"] = self.ask["request_id"]
                    self._asked(None)
                self._background(command, self.conversation, name, values)
        else:
            getattr(self, "do_" + name.replace("-", "_"))(rest)
        return True

    def available(self, name: str):
        """Why the command /name is not offered in this conversation (None: it is). The
        commands of a session with another agent are for such a session, an identity's chat
        does not end, and /experiment comes with the eval package."""
        conversation = self.conversation
        identity = isinstance(conversation, life.AgentChat) or conversation is None and self._agent_mode()
        if name in SESSION and (conversation is None or identity):
            return "it is a command of a session with another agent, and none is open here"
        if name == "end" and identity:
            return "an identity's chat does not end (/clear starts another one, /exit leaves)"
        if name == "experiment":
            if "_eval" not in self.__dict__:
                from ..extensions import first

                self._eval = first("doctor_experiment") is not None
            return None if self._eval else "it comes with the eval package (harness install eval)"
        return None

    def _unknown(self, name: str) -> str:
        """Claude Code's answer to a command that is none, with the nearest one when there is one."""
        names = [*[known for known, row in COMMANDS.items() if not row.hidden],
                 *[alias for row in COMMANDS.values() for alias in row.aliases], *[row[0] for row in self.skills]]
        near = difflib.get_close_matches(name, names, n=1, cutoff=0.6)
        return f"Unknown command: /{name}" + (f". Did you mean /{near[0]}?" if near else "")

    def _learning_now(self, conversation):
        """Where the conversation stands, if it learns its environment (the status line's)."""
        run = getattr(conversation, "run", None)
        if run is None or conversation is not self.conversation:
            return
        now = self._host().learning(run)
        self._later(self._learned, conversation, now)

    def _learned(self, conversation, now):
        if conversation is self.conversation:
            self.learning = now if now.get("active") else None
            self.app.invalidate()

    def send(self, text, files=(), learn=None, shown=None):
        """A message: to the conversation, or the first of a new one (`learn`: one that learns
        its environment for that many minutes, True: the settings'). `shown`: the message as
        the input box had it (its long pastes as chips). While an identity works, the host
        queues it and it is listed over the input until its turn."""
        shown = shown or text
        if isinstance(self.conversation, life.AgentChat):
            conversation = self.conversation
            sent = life.message(text, files)
            if self.status != "RUNNING" and not self.queue["queued"]:
                self._print(Text("› " + shown, style="bold"))
                self.echoed = sent
            self.last_sent = shown

            def tell():
                conversation.say(sent)

            self._background(tell)
        elif self.status == "starting":
            self.pending.append((text, files))
        elif self.conversation is not None and self.status not in ENDED:
            self._background(_message, self.conversation, text, files)
        elif self.conversation is not None and self.parked:
            # The host parked it for its workspace: the message continues it.
            self._background(self._continue, self.conversation.run, text, files)
        elif self.start is None:
            self.note("The conversation has ended", "red")
        else:
            if self.model_entry is not None and not self._refresh_next_model():
                self.note(self.next_model_problem, "red")
                return
            generation = self.generation
            self.pending = []
            self.before_start = self.status
            self.status, self.echoed, self.since = "starting", text, time.time()
            self._print(Text("› " + shown, style="bold"))

            place, self.environment = self.environment, None
            agents, self.agents_on = self.agents_on, False
            model_entry, model_effort = self.model_entry, self.model_effort

            def begin():
                # Where it works: what /environment picked, else the opening choice below.
                nonlocal place
                try:
                    while True:
                        if generation != self.generation:
                            return
                        try:
                            host, conversation = self.start(text, files, log=lambda message: self._later(self._starting, message, generation),
                                                                 **({"learn": learn} if learn is not None else {}),
                                                                 **({"model_entry": model_entry, "reasoning_effort": model_effort}
                                                                    if model_entry else {}),
                                                                 **({"workspace": place[0], "folder": place[1]} if place else {}),
                                                                 **({"agents": True} if agents else {}))
                            break
                        except ChoiceRequired as error:
                            if generation != self.generation:
                                return
                            if error.choice.get("per_conversation"):
                                # (Opened by the Enter that sent the message: that key press
                                # must not answer it.)
                                place = asyncio.run_coroutine_threadsafe(
                                    self._choose_environment(error.choice, settle=SETTLE, generation=generation), self.app.loop).result()
                                if place is None:
                                    self._later(self._cancel_start, shown, generation)
                                    return
                                continue
                            accepted = asyncio.run_coroutine_threadsafe(
                                self._choose_first_use(error.choice, generation=generation), self.app.loop).result()
                            if not accepted:
                                self._later(self._cancel_start, shown, generation)
                                return
                except Exception as error:
                    # As before the message: an ended conversation stays ended, and the next
                    # message starts a new one again.
                    self._later(self._failed_start, generation, error, shown)
                    return
                self._later(self._started, conversation, generation, host)

            threading.Thread(target=begin, daemon=True).start()

    def _take_back(self):
        """Up with messages queued: out of the host's queue and into the input box, one per
        line, ahead of what was typed (Claude Code's "Take back what you queued")."""
        conversation, rows = self.conversation, list(self.queue["queued"])

        def take():
            taken = []
            for row in rows:
                try:
                    control.change(conversation.client, conversation.chat, "remove", id=row["id"])
                    taken.append(row["text"])
                except Problem as error:
                    if control.missing(error):
                        raise
                    # Its turn began meanwhile: it is no longer the owner's to take back.
            conversation.nudge()
            self._later(self._taken, conversation, taken)

        self._background(take)

    def _taken(self, conversation, texts):
        if conversation is self.conversation and texts:
            self.queue = {**self.queue, "queued": [row for row in self.queue["queued"] if row["text"] not in texts]}
            self._put("\n".join([*texts, *([self.buffer.text] if self.buffer.text else [])]))

    def _send_now(self):
        """Ctrl+Enter: the turn that runs stops and what is queued goes now, the draft after it."""
        conversation = self.conversation
        text = self.buffer.text
        if not isinstance(conversation, life.AgentChat) or self.status != "RUNNING":
            if text.strip():
                self._send_draft()
            return
        waiting = [row["id"] for row in self.queue["queued"]]
        if text.strip():
            self._send_draft()
        if not waiting and not text.strip():
            return

        def now():
            found = waiting or [row["id"] for row in control.queue(conversation.client, conversation.chat)["queued"]]
            if found:
                control.change(conversation.client, conversation.chat, "send_now", id=found[0])
            conversation.nudge()

        self._background(self._controlled, now)

    def _controlled(self, call):
        """`call()`, a call of the host's conversation control; a host without it is said."""
        try:
            call()
        except Problem as error:
            if not control.missing(error):
                raise
            self.note("This session host is from an earlier version and cannot do that: harness update", "yellow")

    def interrupt(self):
        """Esc or Ctrl+C while it works: the turn stops, what it did is kept, and what is
        queued goes next (Claude Code's Esc)."""
        conversation = self.conversation
        if conversation is None or self.interrupted:
            return
        if isinstance(conversation, life.AgentChat):
            self.interrupted = True

            def stop():
                try:
                    self._controlled(lambda: control.stop(conversation.client, conversation.chat))
                finally:
                    self._later(setattr, self, "interrupted", False)
                    conversation.nudge()

            self._background(stop)
        elif self.status == "RUNNING":
            self.interrupted = True
            self._background(conversation.pause)
            self.note("⎿  Interrupted: it stops at its next step. What should it do instead?")

    def _shell(self, line: str, send: bool):
        """!command: run it here (in this directory), show its output, and give it to the agent
        with the command (send)."""
        if not line:
            return

        origin, generation = self.conversation, self.generation

        def deliver(output):
            message = f"I ran `{line}` here:\n```\n{formats.clip(output, 20000)}\n```"
            if origin is not None and origin is self.conversation:
                self.send(message)
            elif origin is not None:
                self._background(_message, origin, message, ())
            elif generation == self.generation:
                self.send(message)
            else:
                self.note("Shell output was not sent: its original conversation was left.")

        def run():
            try:
                done = subprocess.run(line, shell=True, capture_output=True, text=True, encoding=locale.getpreferredencoding(False),
                                      errors="replace", timeout=600)
                output = (done.stdout + done.stderr).rstrip() + ("" if done.returncode == 0 else f"\n(exit {done.returncode})")
            except subprocess.TimeoutExpired:
                output = "(stopped after 600 s)"
            self._later(self._print, Text(f"! {line}", style="bold"), Text("\n".join(formats.clip_lines(output, 40)),
                                                                              style="dim"))
            if send:
                self._later(deliver, output)

        threading.Thread(target=run, daemon=True).start()

    # Starting a conversation of the app's agent.

    async def _choose_first_use(self, choice, generation=None):
        """No initial answer: Enter on the placeholder does not save a preference."""
        if generation is not None and generation != self.generation:
            return False
        options = choice["options"]
        while True:
            if generation is not None and generation != self.generation:
                return False
            picked = await self._view(views.choose(choice["title"],
                ["Choose an option below (nothing selected)", *[row["label"] for row in options]],
                hint="↑↓ choose · Enter confirm · Esc cancel task · Saved for future tasks; change in /settings"))
            if generation is not None and generation != self.generation:
                return False
            if picked is None:
                return False
            if picked == 0:
                continue
            changes = {choice["section"]: {choice["key"]: options[picked - 1]["value"]}}
            def save():
                if generation is not None and generation != self.generation:
                    return False
                host = self._host()
                if generation is not None and generation != self.generation:
                    return False
                host.post("/api/app/settings", changes)
                return True

            return await asyncio.to_thread(save)

    def _open_environment(self):
        """A conversation opens: ask where it works before the first message is typed, when
        the setting asks (session.environment) and the command line named none. The last
        choice is highlighted and Enter takes it; Esc leaves it for the first message."""
        if self.start is None or getattr(self.start, "named", False) or self.environment is not None:
            return

        async def ask():
            offered = await asyncio.to_thread(lambda: self._host().get("/api/app/environments"))
            if offered.get("setting") != "ask" or self.conversation is not None or self.status is not None:
                return
            place = await self._choose_environment({
                "title": "Where should Harness work?", "selected": offered.get("selected"),
                "folder": offered.get("folder"),
                "options": [{**row, "name": row["label"]} for row in offered["options"]]})
            if place is not None and self.conversation is None:
                self.environment = place
                self.note(f"This conversation works in {place[0]}" + (f" ({place[1]})" if place[1] else "")
                          + " · /environment changes it")
                self.app.invalidate()

        self.app.create_background_task(self._guarded(ask))

    async def _choose_environment(self, choice, settle=0.0, generation=None):
        """The opening choice of a new conversation: where it works. The last choice is
        highlighted and Enter takes it; with none yet, nothing is preselected. A kind bound
        to a folder then asks for the folder (this directory inside a repository, else the
        last one). (kind, folder), or None when cancelled. Nothing is saved as a setting."""
        if generation is not None and generation != self.generation:
            return None
        options = choice["options"]
        values = [row["value"] for row in options]
        chosen = choice.get("selected") in values
        rows = [environment_row(row) for row in options]
        while True:
            if generation is not None and generation != self.generation:
                return None
            picked = await self._view(views.choose(
                choice["title"], rows if chosen else ["Choose an option below (nothing selected)", *rows],
                current=values.index(choice["selected"]) if chosen else 0, settle=settle,
                hint="↑↓ choose · Enter confirm · Esc cancel task · Asked for each new conversation "
                     "(session.environment in /settings)"))
            if generation is not None and generation != self.generation:
                return None
            if picked is None:
                return None
            if not chosen:
                if picked == 0:
                    continue
                picked -= 1
            row = options[picked]
            if not row.get("folder"):
                return row["value"], None
            folder = await self._view(views.ask(f"{row.get('name') or row['value']}: the folder to work in",
                                                default_folder(choice.get("folder")),
                                                hint="Enter confirm · Esc back"))
            if generation is not None and generation != self.generation:
                return None
            if folder and folder.strip():
                return row["value"], str(Path(folder.strip()).expanduser())

    def _failed_start(self, generation, error, text=""):
        """The conversation did not start: say why and what to do, and give the message back
        to the input box so that it is sent again once the cause is gone."""
        if generation != self.generation:
            return
        discarded, self.pending = len(self.pending), []
        self.status, self.starting = self.before_start, None
        self.problem(error, "could not start: ")
        if text and not self.buffer.text:
            self._put(text)
            self.note("  Your message is kept in the input box." +
                      (f" {discarded} typed after it {'was' if discarded == 1 else 'were'} not sent." if discarded else ""))
        elif discarded:
            self.note(f"  {discarded} message{'' if discarded == 1 else 's'} typed meanwhile "
                      f"{'was' if discarded == 1 else 'were'} not sent.")

    def _cancel_start(self, text, generation=None):
        if generation is not None and generation != self.generation:
            return
        self.status, self.starting = self.before_start, None
        self.pending = []
        self._put(text)  # typing goes on from its end, as before it was sent
        self.note("Task not started. Your message is kept in the input box.")

    def _starting(self, message, generation=None):
        """What starting the conversation says (the session host starting): the working line's."""
        if generation is not None and generation != self.generation:
            return
        text = str(message).removeprefix("harness: ").split(" (log:")[0]
        self.starting = text[:1].upper() + text[1:]
        self._later(self.app.invalidate)

    def _started(self, conversation, generation=None, host=None):
        if generation is not None and generation != self.generation:
            return
        pending, self.pending = self.pending, []
        if host is not None:
            self.host = host
        self.starting = None
        since = self.since
        self._follow(conversation)
        self.status, self.since = "RUNNING", since
        for text, files in pending:
            self._background(_message, conversation, text, files)
        self.pending = []

    def _continue(self, session, text=None, files=()):
        """Go on with the ended session `session` in its own id (the host starts it again
        from what it kept), then send it `text`."""
        generation = self.generation
        conversation = self._host().resume_session(session)
        if text is not None:
            _message(conversation, text, files)
        self._later(self._resumed, conversation, generation)

    def _resumed(self, conversation, generation):
        if generation == self.generation:
            self._follow(conversation)

    def _leave(self):
        """No conversation shown (the one that was goes on)."""
        self.stop.set()
        self.generation += 1
        self.pending, self.starting = [], None
        self.conversation, self.status, self.lanes = None, None, Lanes()
        self._asked(None)
        self.learning, self.live, self.context = None, None, None
        self.queue = {"held": False, "running": None, "queued": []}
        self.seen, self.answers = [], []
        self._reset()
        self._refresh_next_model()

    def _refresh_next_model(self, *, rows=None, initial_name=None):
        """Keep the explicit next route, including an invalid one, until /model replaces it."""
        problem, label = None, initial_name
        if self.model_entry is not None:
            if initial_name is None:
                try:
                    if rows is None:
                        from ..model_list import select

                        row = select(data(), self.model_entry)
                    else:
                        row = next((row for row in rows if row["enabled"] and row["id"] == self.model_entry), None)
                    if row is None:
                        raise ValueError("selected model is unavailable")
                    label = row["name"]
                except (OSError, ValueError):
                    self.model_effort = None
                    label = "model unavailable · choose with /model"
                    problem = "The selected model is unavailable. Choose with /model before starting a new conversation."
        else:
            try:
                from ..model_list import select

                # The name of the model in use as its list has it (an agent that answers as
                # the model is known by its own name, not by "default").
                label = (select(data(), native=True) or {}).get("name")
                if not label:
                    from ..providers import load

                    label = load(data())["model"]
            except Exception:
                label = self.model
        self.next_model_label, self.next_model_problem = label, problem
        if self.conversation is None or isinstance(self.conversation, life.AgentChat):
            self.model = label
        return problem is None

    def _host(self, start=True):
        if self.host is None:
            from ..host import Host

            self.host = Host.connect(start=start)
        return self.host

    def _switch(self, host, chat, title):
        self._print(Text(f"── {title} " + "─" * 40, style="dim"))
        self._follow(life.AgentChat(host, self.identity, chat, title))

    async def _edit(self, path, say=True):
        """`path` in the user's editor ($VISUAL, $EDITOR; notepad on Windows, vi elsewhere), until it closes."""
        from shlex import split

        if say:
            self.note(f"Editing {path}. Save and close your editor to return. vi: Esc, :wq, Enter saves; :q! "
                      "discards. Set EDITOR to choose another editor.")
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("notepad.exe" if os.name == "nt" else "vi")
        words = [editor] if os.path.isfile(editor) else split(editor, posix=os.name != "nt")
        self._report_keys(False)
        try:
            async with in_terminal():
                result = await asyncio.to_thread(subprocess.run, [*words, str(path)], check=False)
        finally:
            self._report_keys(True)
        if result.returncode:
            raise ValueError(f"the editor exited with code {result.returncode}")

    async def _request(self, function, *args, **kwargs):
        """A host read may finish after cancellation, but never applies its abandoned result."""
        task, generation = asyncio.current_task(), self.generation
        self.waiting = task
        self.app.invalidate()
        try:
            result = await asyncio.to_thread(function, *args, **kwargs)
            if generation != self.generation:
                raise asyncio.CancelledError
            return result
        finally:
            if self.waiting is task:
                self.waiting = None
                self.app.invalidate()

    async def _guarded(self, function):
        try:
            await function()
        except asyncio.CancelledError:
            self.note("Stopped waiting for the host.")
        except Exception as error:
            if isinstance(error, (HostGone, OSError)):
                self.host = None
            self.problem(error)


class Completions(Completer):
    """/ the commands, their aliases and the skills, as Claude Code's menu matches them (a
    name or alias from its start or from a word in it, the separators ignored); a command's
    words (/approve, /model, /effort); @ the paths under this directory."""

    def __init__(self, chat=None):
        self.chat = chat
        self.paths = PathCompleter(expanduser=True)

    def commands(self, typed: str):
        """(name, words, note) of each command or skill that `typed` names, best first."""
        wanted = re.sub(r"[-_:]", "", typed.lower())
        first, later = [], []
        offered = getattr(self.chat, "available", lambda name: None)
        rows = [(name, found.words, found.note, (name, *found.aliases)) for name, found in COMMANDS.items()
                if not found.hidden and offered(name) is None]
        rows += [(name, "", about, (name,)) for name, about in getattr(self.chat, "skills", ())
                 if name not in COMMANDS]
        for name, words, note, names in rows:
            plain = [re.sub(r"[-_:]", "", known) for known in names]
            if any(known.startswith(wanted) for known in plain):
                first.append((name, words, note))
            elif any(part.startswith(wanted) for known in names for part in re.split(r"[-_:]", known)[1:]):
                later.append((name, words, note))
        # The command the letters spell exactly comes first (/agent before /agents).
        exact = [row for row in first if typed.lower() in dict((name, names) for name, _, _, names in rows)[row[0]]]
        return exact + [row for row in first if row not in exact] + later

    def get_completions(self, document, event):
        text = document.text_before_cursor
        if text.startswith("/") and " " not in text:
            found = self.commands(text[1:])
            for name, words, note in found:
                yield Completion(f"/{name}", -len(text), display=f"/{name} {words}".strip(), display_meta=note)
            if not found:
                yield Completion(text, -len(text), display=f'{NOTHING} "{text}"')
            return
        if text.startswith("/") and text.count(" ") == 1:
            name, _, started = text[1:].partition(" ")
            known = find(name)
            for value in self.words(known[0] if known else name):
                if value.startswith(started) and value != started:
                    yield Completion(value, -len(started))
            if known:
                return
        middle = re.search(r"(?<=\s)/([a-z][\w-]*)$", text)
        if middle:
            for name, words, note in self.commands(middle.group(1)):
                if name.startswith(middle.group(1)):
                    yield Completion(f"/{name}", -len(middle.group()), display=f"/{name}", display_meta=note)
            return
        found = re.search(r'@("?)([^\s"]*)$', text)
        if found:
            for completion in self.paths.get_completions(Document(found.group(2)), event):
                path = found.group(2)[:len(found.group(2)) + completion.start_position] + completion.text
                quoted = f'"{path}"' if " " in path else path
                yield Completion(quoted, -len(found.group(1) + found.group(2)), display=completion.display,
                                 display_meta="folder" if Path(path).is_dir() else "")

    def words(self, name: str) -> list:
        """The words the command /name takes that can be listed."""
        if name == "approve":
            return list(APPROVE_WORDS)
        if name == "effort":
            return ["default", "low", "medium", "high"]
        if name == "model":
            try:
                from ..model_list import models

                return [row["model"] for row in models(data()) if row["enabled"]]
            except (OSError, ValueError):
                return []
        if name == "queue":
            return ["list", "edit", "rm", "clear"]
        return []


class Placeholder(Processor):
    """What the empty input box is for, dim."""

    def __init__(self, chat):
        self.chat = chat

    def apply_transformation(self, given):
        if given.document.text or given.lineno:
            return Transformation(given.fragments)
        chat = self.chat
        ask = chat.ask
        words = (f"{say('answer.why')}" if ask and ask.get("note") else "" if ask or chat.search is not None else
                 'Try "what can you do on this computer?"' if chat.conversation is None or not chat.seen else "")
        return Transformation(given.fragments + [("class:placeholder", words)])


# Seconds a choice opened by sending a message does not take Enter (views.choose settle).
SETTLE = 0.6
# What the command list says when the letters typed name no command (Claude Code's words).
NOTHING = "No commands match"


def _nothing(completion) -> bool:
    """Whether the completion is the list's "No commands match" line, which is no suggestion."""
    return completion.display_text.startswith(NOTHING)


def environment_row(row) -> str:
    """One environment of the opening choice as its line: the label, what it is, a note."""
    text = row.get("name") or row.get("label") or row["value"]
    about = row.get("about")
    return text + (f" — {about}" if about else "") + (f"  ({row['note']})" if row.get("note") else "")


def default_folder(last=None) -> str:
    """The folder a project choice starts from: this directory when it is inside a
    repository, else the last folder chosen, else this directory."""
    here = Path.cwd()
    if any((parent / ".git").exists() for parent in (here, *here.parents)):
        return str(here)
    return str(last or here)


def _message(conversation, text, files):
    if files:
        conversation.send_message(text, files=files)
    else:
        conversation.send_message(text)


def _stamp(path):
    try:
        found = Path(path).stat()
    except OSError:
        return None
    return found.st_mtime_ns, found.st_size


def _elapsed(seconds: float) -> str:
    """12s, 2m 05s, 1h 03m: how long a turn has run."""
    seconds = max(int(seconds), 0)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"


def _count(number: int) -> str:
    return f"{number / 1000:.1f}k" if number >= 1000 else str(number)
