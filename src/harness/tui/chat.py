"""The terminal chat: the conversation printed into the terminal's scrollback (rich), a live
region under it (prompt_toolkit): an approval's choices when one waits, the input box, one
status line. Keys as in the coding agents' terminals: Enter sends, Shift+Enter or Ctrl+J
is a new line, Up and Down the history, Ctrl+R searches it, Tab completes (/ commands,
@ files), Esc interrupts the agent (Esc Esc clears the input), Ctrl+C interrupts or
clears and twice leaves, Ctrl+D twice leaves, Ctrl+O shows a program's code and output,
Ctrl+T the timeline, ? the keys. !command runs a command here and gives the agent its
output; !!command only runs it.

Nothing starts until the first message: then `start(text, files, log)` gives the host and a
conversation of the app's agent. A message while the agent works reaches it at once."""

import asyncio
import io
import json
import locale
import os
from pathlib import Path
from ..settings import ChoiceRequired
import re
import subprocess
import sys
import threading
import time

from prompt_toolkit.application import Application, in_terminal
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_completions
from prompt_toolkit.history import FileHistory
from prompt_toolkit.input import ansi_escape_sequences, create_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, ScrollOffsets, VSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenuControl
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.widgets import SearchToolbar
from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text

from .. import transcript
from ..core import format as formats
from harness.runtime.safety.approval import say
from ..core.lanes import Lanes
from ..host.client import HostGone
from ..host.sessions import ENDED, LIVE, table_rows, word
from ..paths import data
from harness.runtime.learning.active import progress_line
from ..terminal import APPROVE_WORDS, COMMANDS, command, item_lines
from . import views
from .answer import Answer

# Shift+Enter where the terminal tells it from Enter: as Ctrl+J, a new line.
for _sequence in ("\x1b[13;2u", "\x1b[27;2;13~"):
    ansi_escape_sequences.ANSI_SEQUENCES[_sequence] = Keys.ControlJ

KEYS = [("Enter", "send"), ("Shift+Enter, Ctrl+J", "new line"), ("↑ ↓", "history"), ("Ctrl+R", "search the history"),
        ("Tab", "complete"), ("/", "commands"), ("@", "attach a file"), ("!cmd", "run it, give the agent its output"),
        ("!!cmd", "run it only"), ("Esc", "interrupt the agent"), ("Esc Esc", "clear the input"),
        ("Ctrl+C", "interrupt; clear; twice: leave"), ("Ctrl+D twice", "leave"), ("Ctrl+O", "program details"),
        ("Ctrl+T", "timeline"), ("?", "these keys")]
STYLE = Style.from_dict({"rule": "#585858", "status": "#8a8a8a", "status.state": "bold", "status.busy": "bold #5fafff",
                         "status.wait": "bold #ffaf00", "status.hint": "#6c6c6c", "placeholder": "#6c6c6c",
                         "ask": "bold #ffaf00", "ask.selected": "bold reverse", "help": "#8a8a8a", "help.key": "bold",
                         "completion-menu": "bg:#262626 #bcbcbc", "completion-menu.completion.current": "bg:#444444 #ffffff bold",
                         "completion-menu.meta.completion": "bg:#262626 #808080",
                         "completion-menu.meta.completion.current": "bg:#444444 #bcbcbc"})
# Rich styles of the roles of transcript items (transcript.items).
ROLES = {"task": "bold", "you": "bold", "call": "dim", "thinking": "dim italic", "code": "#5f87ff", "skill": "magenta",
         "result": "green", "verifier": "cyan", "note": "yellow", "turn": "dim", "outcome": "bold green", "end": "bold",
         "error": "red", "entry": "green", "output": "dim"}
# A sub-agent's colour, by its name.
AGENT_COLOURS = ("magenta", "cyan", "green", "yellow", "bright_blue", "bright_magenta")
# Items of a program (its steps, entries, output): shown with Ctrl+O.
DETAILS = {"skill", "skill_step", "entry_start", "entry_claims", "entry_end", "skill_failed", "result", "output",
           "cell_error", "unhandled"}
# Items of the timeline (transcript.items with timeline) the chat leaves out: its calls and
# their usage, how the run ended inside.
TIMELINE = {"call", "usage", "call_set_aside", "compaction", "malformed_dropped", "library_loaded",
            "policy_to_end", "wrap_up", "cleanup_error"}
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# Seconds within which a second Ctrl+C, Ctrl+D or Esc counts.
TWICE = 1.0
# The status of a conversation that can no longer be followed (its session host is gone).
LOST = "LOST"
FILE = re.compile(r'@"([^"]+)"|@(\S+)')


class Chat:
    """One terminal chat; run() returns once the user leaves."""

    # Whether the host parked the conversation shown for its workspace (its next message continues it).
    parked = False

    def __init__(self, conversation=None, records=None, *, host=None, start=None):
        self.conversation, self.records, self.host, self.start = conversation, records, host, start
        self.status = None  # the conversation's last status; "starting" while it is created
        self.before_start = None  # the status before "starting": back to it when the start is cancelled or fails
        self.generation = 0
        self.stop = threading.Event()
        self.pending = []  # messages typed while the conversation was created
        self.waiting = None
        self.details_open = False
        self.details_output = []
        self.printed = []  # every renderable printed into the scrollback, in order (_resized prints them again)
        self.printed_size = None  # the terminal size the scrollback was last printed for
        self.help = False
        self.ask = None  # what waits for the user's approval: {text, options, at, reason}
        self.echoed = None  # the first message of a conversation started here, printed at once
        self.interrupted = False  # asked to pause, not paused yet
        self.starting = None  # what starting the first message's conversation says now
        self.armed = {}  # key: when it was last pressed (twice to leave, Esc Esc)
        self.model, self.workspace = None, None
        self.model_entry = getattr(start, "model_entry", None)
        self.model_effort = getattr(start, "model_effort", None)
        self.environment = None  # (kind, folder) picked with /environment for the next conversation
        self.agents_on = False  # /agents before a conversation starts: on in the next one
        self.learning = None  # where a conversation that learns its environment stands (runtime/learning/active.py progress())
        self.lanes = Lanes()
        self._reset()
        self._refresh_next_model(initial_name=getattr(start, "model_name", None))
        # sys.stdout when it prints: patch_stdout's, above the live region.
        self.console = Console(force_terminal=True, legacy_windows=False, highlight=False, soft_wrap=False,
                               color_system="truecolor" if os.environ.get("WT_SESSION") or os.environ.get("COLORTERM")
                               in ("truecolor", "24bit") else "256")
        self.buffer = Buffer(multiline=True, history=FileHistory(str(_history_file())), completer=Completions(),
                             complete_while_typing=True)
        self.app = self._application()

    # The live region.

    def _application(self) -> Application:
        search = SearchToolbar(text_if_not_searching="", ignore_case=True)
        prompt = lambda line, wrap: [("class:rule", "› " if line == 0 and not wrap else "  ")]  # noqa: E731
        field = Window(BufferControl(self.buffer, search_buffer_control=search.control, preview_search=True,
                                     input_processors=[Placeholder(self)]),
                       height=self._input_height, wrap_lines=True,
                       get_line_prefix=prompt, dont_extend_height=True)
        rule = Window(height=1, char="─", style="class:rule")
        # The completions under the input, as many lines as there are (at most 8).
        menu = ConditionalContainer(Window(CompletionsMenuControl(), height=lambda: min(len(
            self.buffer.complete_state.completions), 8) if self.buffer.complete_state else 1, scroll_offsets=ScrollOffsets(1, 1),
            dont_extend_width=True, style="class:completion-menu"), has_completions)
        status = VSplit([Window(FormattedTextControl(self._status), height=1),
                         Window(FormattedTextControl(self._hint), height=1, width=lambda: min(38, self.app.output.get_size().columns // 2), align=WindowAlign.RIGHT)])
        body = HSplit([ConditionalContainer(Window(FormattedTextControl(self._asking), dont_extend_height=True),
                                            Condition(lambda: self.ask is not None)),
                       rule, field, search, rule, menu, status,
                       ConditionalContainer(Window(FormattedTextControl(self._keys), dont_extend_height=True),
                                            Condition(lambda: self.help))])
        app = Application(Layout(body, focused_element=field), key_bindings=self._keys_bound(), style=STYLE,
                          full_screen=False, refresh_interval=0.25, input=_input(), erase_when_done=True)
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

    def _input_height(self):
        width = max(1, self.app.output.get_size().columns - 2)
        return min(12, sum(max(1, (get_cwidth(line.expandtabs()) + width - 1) // width)
                           for line in self.buffer.text.split("\n")))

    def _status(self):
        status = self.status
        if status == "starting":
            state = ("class:status.busy", f"{SPINNER[int(time.time() * 8) % len(SPINNER)]} {self.starting or 'starting'}")
        elif status == "RUNNING":
            state = ("class:status.busy", f"{SPINNER[int(time.time() * 8) % len(SPINNER)]} working")
        elif status == LOST:
            state = ("class:status.wait", "● not connected")
        elif status == "WAITING_FOR_CONFIRMATION" or self.ask is not None:
            state = ("class:status.wait", "● waits for you")
        elif status is None:
            state = ("class:status.state", "○ new conversation")
        else:
            state = ("class:status.state", "● " + word(status))
        if self.app.output.get_size().columns < 80:
            return [state]
        # Learning the environment first: the line is cut at the terminal's width.
        parts = [progress_line(self.learning, short=True) if self.learning else None, self.model,
                 self.workspace or (self.environment[0] if self.environment and self.conversation is None else None),
                 f"session {self.session}" if self.session else None]
        return [state] + [("class:status", "  ·  " + part) for part in parts if part]

    def _hint(self):
        if getattr(self, "waiting", None) is not None:
            return [("class:status.wait", "waiting · Esc cancel ")]
        if self.armed.get("leave") and time.time() - self.armed["leave"][1] < TWICE:
            return [("class:status.wait", f"{self.armed['leave'][0]} again to leave ")]
        if self.app.output.get_size().columns < 70:
            return [("class:status.hint", "esc pause" if self.status == "RUNNING" else "? keys · / commands")]
        if self.status == "RUNNING":
            return [("class:status.hint", "esc interrupt · type to steer ")]
        return [("class:status.hint", "? keys · / commands ")]

    def _asking(self):
        ask = self.ask
        out = [("class:ask", f"{ask['text']}\n")]
        if ask.get("reason"):
            return out + [("class:status.hint", f"  {say('answer.why')}: type it below, Enter sends, Esc goes back\n")]
        for number, (_, words) in enumerate(ask["options"], 1):
            selected = number - 1 == ask["at"]
            out.append(("class:ask.selected" if selected else "", f"{'❯' if selected else ' '} {number}. {words}"))
            out.append(("", "\n"))
        return out

    def _keys(self):
        out = []
        for index, (key, what) in enumerate(KEYS):
            out += [("class:help.key", f"  {key:<22}"), ("class:help", f"{what:<34}"), ("", "\n" if index % 2 else "")]
        return out

    @property
    def session(self):
        return getattr(self.conversation, "session", None)

    def _keys_bound(self) -> KeyBindings:
        keys = KeyBindings()
        idle = Condition(lambda: self.status != "RUNNING" or self.conversation is None)
        empty = Condition(lambda: not self.buffer.text)
        choosing = Condition(lambda: self.ask is not None and not self.ask.get("reason") and not self.buffer.text)
        buffer = self.buffer

        @keys.add("enter", filter=choosing)
        def _(event):
            self._answer(self.ask["at"])

        for digit in "123456789":
            @keys.add(digit, filter=choosing)
            def _(event, digit=digit):
                if int(digit) <= len(self.ask["options"]):
                    self._answer(int(digit) - 1)

        @keys.add("up", filter=choosing)
        def _(event):
            self.ask["at"] = max(self.ask["at"] - 1, 0)

        @keys.add("down", filter=choosing)
        def _(event):
            self.ask["at"] = min(self.ask["at"] + 1, len(self.ask["options"]) - 1)

        @keys.add("enter", filter=~choosing)
        def _(event):
            state = buffer.complete_state
            slash = buffer.text.startswith("/") and " " not in buffer.text
            if state and state.completions and (state.current_completion or slash):
                # A completion picked (or the first command): taken; Enter sends once nothing changes.
                before = buffer.text
                buffer.apply_completion(state.current_completion or state.completions[0])
                found = COMMANDS.get(buffer.text[1:]) if slash else None
                if found is not None and found.words:
                    buffer.insert_text(" ")
                    return
                if not slash and buffer.text != before:
                    return
            if buffer.document.text_before_cursor.endswith("\\"):
                buffer.delete_before_cursor()
                buffer.newline(copy_margin=False)
                return
            text = buffer.text
            if text.strip():
                buffer.append_to_history()
            buffer.reset()
            self.submit(text)

        @keys.add("c-j")
        @keys.add("escape", "enter")
        def _(event):
            buffer.newline(copy_margin=False)

        @keys.add("escape")
        def _(event):
            if getattr(self, "waiting", None) is not None:
                self.waiting.cancel()
            elif buffer.complete_state:
                buffer.cancel_completion()
            elif self.ask is not None and self.ask.get("reason"):
                self.ask["reason"] = False
            elif self.help:
                self.help = False
            elif not idle():
                self.interrupt()
            elif self._twice("escape") and buffer.text:
                buffer.append_to_history()
                buffer.reset()

        @keys.add("c-c")
        def _(event):
            # The second within TWICE leaves, also while the agent works (its session goes on).
            if self._twice("c-c"):
                event.app.exit()
                return
            if not idle():
                self.interrupt()
            else:
                buffer.reset()
            self.armed["leave"] = ("Ctrl+C", time.time())

        @keys.add("c-d", filter=empty)
        def _(event):
            if self._twice("c-d"):
                event.app.exit()
            else:
                self.armed["leave"] = ("Ctrl+D", time.time())

        @keys.add("c-o")
        def _(event):
            program = self.program or self.last_program
            if program is not None:
                event.app.create_background_task(self._show_details(program))

        @keys.add("c-t")
        def _(event):
            event.app.create_background_task(self._view(views.timeline_view(self.lanes)))

        @keys.add("?", filter=empty)
        def _(event):
            self.help = not self.help

        return keys

    def _twice(self, key) -> bool:
        """Whether `key` was pressed within TWICE seconds before (then it no longer counts)."""
        now, before = time.time(), self.armed.get(key)
        self.armed[key] = None if before and now - before < TWICE else now
        return bool(before and now - before < TWICE)

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
        self._banner()
        self.printed_size = self.app.output.get_size()
        with patch_stdout(raw=True):
            self.app.run(pre_run=lambda: self._follow(self.conversation, self.records)
                         if self.conversation is not None else self._open_environment())
        self.stop.set()
        return self.conversation

    def _banner(self):
        from .. import __version__

        here = os.getcwd().replace(os.path.expanduser("~"), "~", 1)
        self._print(Text.assemble(("The Harness", "bold"), f" {__version__}  ", (here, "dim")),
                    Text("Tell it what to do. / for commands, @ to attach a file, ! to run a command, ? for keys.",
                         style="dim"))
        if warning := getattr(self.start, "warning", None):
            self.note(warning, "yellow")

    # Printing into the scrollback (patch_stdout carries it above the live region).

    def _print(self, *renderables):
        if self.details_open:
            self.details_output.extend(renderables)
            return
        self.printed.extend(renderables)
        try:
            self.console.width = self.app.output.get_size().columns
        except Exception:
            pass
        for renderable in renderables:
            self.console.print(renderable)

    def _resized(self):
        """The terminal changed size: clear it and print the chat again at the new width, then
        draw the live region, as Claude Code does. A terminal reflows the rows it already shows
        in its own way (tmux 3.2 and 3.8 split the same row differently), so erasing the old
        live region in place left some of its rows behind. Clearing also takes the terminal's
        scrollback from before the chat started."""
        app = self.app
        size = app.output.get_size()
        if size == self.printed_size:
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

    def note(self, text, style="dim"):
        self._later(self._print, Text(str(text), style=style))

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
                self.note(f"({error})", "red")

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
        self.conversation, self.ask, self.lanes = conversation, None, Lanes()
        self.learning, self.workspace, self.parked = None, None, False
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
                self._later(self._lost, generation, f"({error}: /resume or harness --continue goes on with "
                                                    "this conversation)")
            except Exception as error:
                self._later(self._lost, generation, f"(the conversation cannot be read any more: {error})")

        threading.Thread(target=read, daemon=True).start()

    def _described(self, generation, agent):
        if generation == self.generation:
            self.model, self.workspace = agent.get("model") or self.model, agent.get("workspace")

    def _lost(self, generation, text):
        """The conversation shown can no longer be followed: say why, and stop showing it as working."""
        if generation != self.generation:
            return
        self.host = None
        self.note(text, "red")
        if self.status not in ENDED:
            self.status, self.interrupted, self.ask = LOST, False, None

    def show(self, record: dict, generation=None):
        if generation is not None and generation != self.generation:
            return
        self.lanes.add(record)
        kind = record.get("event")
        if kind in ("workspace_reclaimed", "resumed"):
            self.parked = kind == "workspace_reclaimed"
        if kind == "state":
            self.status, self.interrupted = record["status"], False
            if self.status in ("IDLE", "PAUSED", *ENDED):
                self.ask = None
        if kind in ("physical_answer", "confirmation"):
            self.ask = None
        # The timeline's items too, for the reasoning and the answer of finish() in a program.
        items = [item for item in transcript.items(record, self.names, timeline=True) if item["kind"] not in TIMELINE]
        if kind == "cell" and self.program is not None:
            out = self._ended(record, items)
        else:
            out = [line for item in items for line in self._item(item, record)]
        if kind == "confirmation_request" and self.program is not None:
            # What it asks to run.
            out += self._program_lines(self.program)[:2]
        if kind in ("physical_request", "confirmation_request"):
            self._ask(record, items)
        if kind in ("library", "cell", "state") and self.host is not None:
            self._background(self._learning_now, self.conversation)
        self._print(*out)
        self.app.invalidate()

    def _ask(self, record, items):
        asked = next(item for item in items if item["kind"] in ("physical_request", "approval_request"))
        keys = asked.get("keys") or {}
        text = asked["text"] if asked["kind"] == "physical_request" else asked["text"].capitalize()
        if keys.get("why") and not keys.get("sensitive"):
            text += f"\n  why: {keys['why']}"
        self.ask = {"text": text, "options": transcript.approval_options(asked),
                    "at": 0, "reason": False, "request_id": record.get("id")}

    def _answer(self, index: int):
        remember = self.ask["options"][index][0]
        if remember is None:
            self.ask["reason"] = True
            return
        request_id = self.ask["request_id"]
        conversation, self.ask = self.conversation, None
        self._background(command, conversation, "approve", {"remember": remember, "request_id": request_id})

    def _item(self, item, record) -> list:
        """Chat scrollback stays compact; program details belong to the reversible view."""
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
            return [] if not answer or answer == self.said else [Answer(answer), Text("")]
        if kind in ("message", "thought", "finish", "verify_ask", "invalid"):
            self.said = text.strip()
            return [Answer(text), Text("")]
        if kind == "reasoning":
            return [Text("\n".join(formats.clip_lines(text, 12)), style="dim italic")]
        if kind == "program":
            self.programs += 1
            self.program = {"number": self.programs, "code": text, "details": [],
                             "lexer": "python" if item["keys"].get("reply") == "python" else "json"}
            return []
        if kind in DETAILS and self.program is not None:
            lines = self._detail_lines(item)
            self.program["details"] += lines
            return []
        if kind == "state":
            return [] if text == "your turn" else [Text(f"— {text}" + (": /continue, or send a message"
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
        """The program's `cell` record: its result and output join its details; one line for it."""
        done, self.program = self.program, None
        self.last_program = done
        result = record.get("result") or {}
        done.update(status=result.get("status"), seconds=result.get("seconds"))
        lines = [line for item in items for line in self._detail_lines(item)]
        done["details"] += lines
        return [self._program_line(done)]

    @staticmethod
    def _detail_lines(item):
        if item["kind"] in ("output", "cell_error", "unhandled"):
            return [Text(item["text"], style=ROLES.get(item["role"], ""))]
        return [Text(line, style=ROLES.get(role, "")) for role, line in item_lines(item)]

    async def _show_details(self, program):
        if self.details_open:
            return
        self.details_open = True
        try:
            await self._view(views.read("Program details · Ctrl+O to return",
                                       lambda: self._details_text(program), close_key="c-o", live=program.get("status") is None))
        finally:
            self.details_open = False
            output, self.details_output = self.details_output, []
            self._print(*output)

    def _details_text(self, program):
        width = self.app.output.get_size().columns
        version = (len(program["details"]), program.get("status"), program.get("seconds"))
        cached = program.get("_rendered")
        if cached and cached[:2] == (version, width):
            return cached[2]
        stream = io.StringIO()
        console = Console(file=stream, force_terminal=False, color_system=None,
                          width=width, highlight=False)
        console.print(*self._program_lines(program), sep="\n")  # each output line on its own
        value = stream.getvalue()
        program["_rendered"] = (version, width, value)
        return value

    def _program_line(self, program) -> Text:
        status = program.get("status") or "?"
        style = "green" if status in ("ok", "finished") else "red" if status in ("error", "failed", "timeout") else "yellow"
        return Text.assemble((f"▸ Program {program['number']}", "#5f87ff"), " · ", (status, style),
                             f" · {formats.duration(program.get('seconds'))}" if program.get("seconds") is not None else "",
                             ("   ctrl+o details", "dim"))

    def _program_lines(self, program) -> list:
        return [Text(f"▾ Program {program['number']}", style="#5f87ff"),
                Syntax(program["code"], program["lexer"], word_wrap=True), *program["details"]]

    # What the user does.

    def submit(self, text: str):
        line = text.strip()
        if self.ask is not None and self.ask.get("reason"):
            # The reason is optional: Enter on an empty one refuses without saying why.
            request_id = self.ask["request_id"]
            conversation, self.ask = self.conversation, None
            self._background(command, conversation, "reject", {"reason": line, "request_id": request_id})
            return
        if not line:
            return
        if line.startswith("!"):
            self._shell(line.lstrip("!").strip(), send=not line.startswith("!!"))
            return
        if line.startswith("/"):
            name, _, rest = line[1:].partition(" ")
            found = COMMANDS.get(name)
            if found is None:
                self.note(f"No command /{name}: /help lists them", "red")
            elif found.method:
                if self.conversation is None:
                    self.note("No conversation yet: send a message first", "red")
                else:
                    values = {found.takes[0]: rest.strip()} if found.takes else {}
                    if self.ask is not None and "request_id" in found.takes:
                        values["request_id"] = self.ask["request_id"]
                    self._background(command, self.conversation, name, values)
            else:
                getattr(self, "do_" + name)(rest.strip())
            return
        files = [str(Path(quoted or bare).expanduser().resolve()) for quoted, bare in FILE.findall(line)
                 if Path(quoted or bare).expanduser().exists()]
        self.send(line, files)

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

    def send(self, text, files=(), learn=None):
        """A message: to the conversation, or the first of a new one (`learn`: one that learns
        its environment for that many minutes, True: the settings')."""
        if self.status == "starting":
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
            self.status, self.echoed = "starting", text
            self._print(Text("› " + text, style="bold"))

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
                                    self._later(self._cancel_start, text, generation)
                                    return
                                continue
                            accepted = asyncio.run_coroutine_threadsafe(
                                self._choose_first_use(error.choice, generation=generation), self.app.loop).result()
                            if not accepted:
                                self._later(self._cancel_start, text, generation)
                                return
                except Exception as error:
                    # As before the message: an ended conversation stays ended, and the next
                    # message starts a new one again.
                    self._later(self._failed_start, generation, str(error))
                    return
                self._later(self._started, conversation, generation, host)

            threading.Thread(target=begin, daemon=True).start()

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

    def do_environment(self, _):
        """/environment: where this conversation works, and the choice for the next one."""
        async def pick():
            offered = await asyncio.to_thread(lambda: self._host().get("/api/app/environments"))
            now = f"This conversation works in: {self.workspace}. " if self.conversation is not None and self.workspace                 else ""
            place = await self._choose_environment({
                "title": now + "Where should the next conversation work?", "selected": offered.get("selected"),
                "folder": offered.get("folder"),
                "options": [{**row, "name": row["label"]} for row in offered["options"]]})
            if place is not None:
                self.environment = place
                self.note(f"The next conversation works in {place[0]}" + (f" ({place[1]})" if place[1] else "")
                          + ("; /new starts it" if self.conversation is not None else ""))

        self.app.create_background_task(self._guarded(pick))

    def do_agents(self, _):
        """/agents: sub-agents on, for this conversation or (before one starts) the next."""
        if self.conversation is not None and self.status not in ENDED:
            def switch():
                self.conversation.enable_agents()
                self._later(self.note, "Sub-agents are on for this conversation")

            self._background(switch)
        else:
            self.agents_on = True
            self.note("Sub-agents are on for the next conversation (session.agents in /settings keeps them on)")

    def _failed_start(self, generation, error):
        if generation != self.generation:
            return
        self.status, self.starting, self.pending = self.before_start, None, []
        self.note(f"(could not start: {error}; queued follow-ups discarded)", "red")

    def _cancel_start(self, text, generation=None):
        if generation is not None and generation != self.generation:
            return
        self.status, self.starting = self.before_start, None
        self.pending = []
        self.buffer.text = text
        self.buffer.cursor_position = len(text)  # typing goes on from its end, as before it was sent
        self.note("Task not started. Your message is kept in the input box.")

    def _starting(self, message, generation=None):
        """What starting the conversation says (the session host starting): the status line's."""
        if generation is not None and generation != self.generation:
            return
        self.starting = str(message).removeprefix("harness: ").split(" (log:")[0]
        self._later(self.app.invalidate)

    def _started(self, conversation, generation=None, host=None):
        if generation is not None and generation != self.generation:
            return
        pending, self.pending = self.pending, []
        if host is not None:
            self.host = host
        self.starting = None
        self._follow(conversation)
        self.status = "RUNNING"
        for text, files in pending:
            self._background(_message, conversation, text, files)
        self.pending = []

    def interrupt(self):
        """Esc or Ctrl+C while the agent works: it pauses at its next step, keeping what it did."""
        if self.conversation is not None and self.status == "RUNNING" and not self.interrupted:
            self.interrupted = True
            self._background(self.conversation.pause)
            self.note("interrupting: it stops at its next step (/continue goes on, a message tells it what to do)")

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

    # The terminal's own commands (terminal.COMMANDS without a method).

    def do_help(self, _):
        width = max(len(name) + len(found.words) for name, found in COMMANDS.items()) + 4
        self._print(*[Text.assemble((f"  /{name} {found.words}".ljust(width), "bold"), (found.note, "dim"))
                      for name, found in COMMANDS.items()],
                    *[Text.assemble((f"  {key}".ljust(width), "bold"), (what, "dim")) for key, what in KEYS])

    def do_answer(self, words):
        if self.conversation is None:
            self.note("Open a conversation first", "red")
            return
        identifier, _, value = words.partition(" ")
        try:
            content = json.loads(value)
        except ValueError:
            self.note("Use /answer REQUEST_ID JSON (or null to decline)", "red")
            return
        self._background(self.conversation.answer, identifier, content)

    def do_config(self, words):
        if self.conversation is None:
            self.note("Open a conversation first", "red")
            return
        identifier, _, value = words.partition(" ")
        self._background(self.conversation.set_config, identifier, value)

    def do_diff(self, _):
        if self.conversation is None:
            self.note("Open a conversation first", "red")
            return

        def show():
            result = self.conversation.diff()
            text = "\n".join([result["patch"], *(f"Untracked: {path}" for path in result["untracked"])])
            self._print(Text(text or "No changes"))

        self._background(show)

    def do_merge(self, _):
        if self.conversation is None:
            self.note("Open a conversation first", "red")
            return
        self._background(self.conversation.merge)

    def do_handoff(self, words):
        if self.conversation is None:
            self.note("Open a conversation first", "red")
            return
        agent, _, context = words.partition(" ")

        origin, generation = self.conversation, self.generation

        def handoff():
            self._later(self._started, origin.handoff(agent, context), generation)

        self._background(handoff)

    def do_import(self, words):
        provider, _, file = words.partition(" ")
        generation = self.generation

        def load():
            conversation = self._host().import_session(Path(file.strip('"')).expanduser().resolve(), provider)
            self._later(self._started, conversation, generation)

        self._background(load)

    def do_new(self, _):
        self._leave()
        self._print(Text("── new conversation " + "─" * 40, style="dim"))
        self._open_environment()

    do_clear = do_new

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
        self.conversation, self.status, self.ask, self.lanes = None, None, None, Lanes()
        self.learning = None
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
                from ..providers import load

                label = load(data())["model"]
            except Exception:
                label = self.model
        self.next_model_label, self.next_model_problem = label, problem
        if self.conversation is None:
            self.model = label
        return problem is None

    def do_exit(self, _):
        self.app.exit()

    do_detach = do_exit

    def do_learn(self, rest):
        """/learn [minutes] [for what]: a new conversation that learns this environment; while
        one runs, where it stands."""
        if self.learning and self.status not in ENDED:
            self.note(progress_line(self.learning) + ("\n  open: " + " | ".join(self.learning["open"][:8])
                                                      if self.learning["open"] else ""))
            return
        first, _, words = rest.partition(" ")
        try:
            minutes = float(first)
        except ValueError:
            minutes, words = True, rest
        if self.start is None:
            self.note("This chat follows one conversation: /learn starts one in harness (the terminal chat)", "red")
            return
        if self.status == "starting":
            self.note("A conversation is starting: /learn once it has", "red")
            return
        if self.conversation is not None:
            self.do_new("")
        self.send(words.strip() or "Get to know this environment for the tasks I give you.", learn=minutes)

    def do_timeline(self, _):
        self.app.create_background_task(self._view(views.timeline_view(self.lanes)))

    def _host(self, start=True):
        if self.host is None:
            from ..host import Host

            self.host = Host.connect(start=start)
        return self.host

    def do_host(self, words):
        """/host: how the session host runs; /host stop: end it, with what runs in it."""
        async def show():
            if str(words or "").strip() == "stop":
                await asyncio.to_thread(self._host_info, words)
            else:
                await self._request(self._host_info, words)

        self.app.create_background_task(self._guarded(show))

    def _host_info(self, words):
        host = self._host(start=False)
        if host is None:
            self.note("No session host runs (the next conversation starts it)")
            return
        if str(words or "").strip() == "stop":
            self._later(self._leave)
            host.stop(force=True)
            self.host = None
            self.note(f"Stopped the session host at {host.url}")
            return
        info = host.info()
        self.note(f"Session host {host.url}, process {info.get('pid')}, version {info.get('version')}, "
                  f"{info.get('open', 0)} open, idle {formats.duration(info.get('idle_seconds') or 0)}")

    def do_effort(self, words):
        """Choose an effort for the saved model or apply an explicit effort to an open conversation."""
        from ..model_list import select
        from harness.runtime.decision.model import valid_effort

        async def pick():
            conversation = self.conversation
            active = conversation is not None and self.status not in ENDED
            level = str(words or "").strip()
            if active and not level:
                self.note("Use /effort LEVEL or /effort default for the open conversation.")
                return
            row = None if active else select(data(), self.model_entry)
            if not level:
                levels = [value for value in (row or {}).get("efforts", []) if value != "default"]
                option = await self._view(views.choose("Reasoning effort", ["Provider default", *levels]))
                if option is None:
                    return
                level = (["default", *levels])[option]
            effort = "" if level == "default" else level
            if not valid_effort(effort):
                raise ValueError("invalid reasoning effort ID")
            if active:
                self._background(lambda: conversation.set_model(reasoning_effort=effort))
            elif row:
                if effort and effort not in row["efforts"]:
                    raise ValueError("this model does not offer that reasoning effort")
                self.model_entry, self.model_effort = row["id"], effort
            else:
                raise ValueError("add an enabled model first")
            self.note(f"Effort: {level}")

        self.app.create_background_task(self._guarded(pick))

    def do_experiment(self, words):
        """/experiment NAME [TASK [SEED]] [-- instruction]: a session of an experiment's task on
        its worker, in the session host (as the app's /dev page starts one)."""
        from shlex import split

        try:
            parts = split(str(words or ""))
            instruction = ""
            if "--" in parts:
                marker = parts.index("--")
                instruction, parts = " ".join(parts[marker + 1:]), parts[:marker]
            if not 1 <= len(parts) <= 3:
                raise ValueError("experiment arguments")
            seed = int(parts[2]) if len(parts) > 2 else 0
        except ValueError:
            self.note("/experiment NAME [TASK [SEED]] [-- instruction]", "red")
            return

        generation = self.generation

        def start():
            request = {"experiment": parts[0], "task": parts[1] if len(parts) > 1 else None,
                       "seed": seed, "frontend": "terminal",
                       **({"instruction": instruction.strip()} if instruction.strip() else {})}
            conversation = self._host().start(**request)
            self._later(self._print, Text(f"── experiment {parts[0]} " + "─" * 40, style="dim"))
            self._later(self._started, conversation, generation)

        self._background(start)

    def do_sessions(self, _):
        async def pick():
            host = await self._request(self._host, False)
            if host is None:
                self.note("No session host runs: nothing is open")
                return
            sessions = await self._request(host.sessions)
            lines = table_rows([session.row for session in sessions])
            if not lines:
                self.note("No sessions run")
                return
            rows = [f"{line['session'] or ' '}  {line['agent']:<12} {line['status']:<26} {line['spent']:<16} {line['title']}"
                    for line in lines]
            current = next((index for index, line in enumerate(lines) if line["run"] == getattr(self.conversation, "run", None)), 0)
            picked = await self._view(views.choose("Sessions that run", rows, current=current))
            if picked is not None and lines[picked]["run"] != getattr(self.conversation, "run", None):
                self._print(Text(f"── session {lines[picked]['run']} " + "─" * 40, style="dim"))
                self._follow(await self._request(host.conversation, lines[picked]["run"]))

        self.app.create_background_task(self._guarded(pick))

    def do_resume(self, _):
        async def pick():
            host = await self._request(self._host)
            sessions = [session.row for session in await self._request(host.sessions, all=True, limit=100)]
            if not sessions:
                self.note("No conversations yet")
                return
            rows = [f"{formats.timestamp(row.get('created'))}  {word(row.get('status')):<26} {row.get('title') or ''}"
                    for row in sessions]
            picked = await self._view(views.choose("Resume a conversation", rows))
            if picked is None:
                return
            row = sessions[picked]
            self._print(Text(f"── {row.get('title') or row['id']} " + "─" * 40, style="dim"))
            if row.get("status") in LIVE:
                self._follow(await self._request(host.conversation, row["run"]))
                return
            if row.get("kind", "harness") == "harness":
                # It goes on in its own session: its messages and facts, a new kernel.
                self._background(self._continue, row["id"])
                return
            from ..core.episodes import Follow

            self._leave()
            for record in Follow(Path(row["directory"])).next() if row.get("directory") else []:
                self.show(record)
            self.status = None
            self.note("This conversation has ended; a message starts a new one")

        self.app.create_background_task(self._guarded(pick))

    def do_model(self, _):
        async def pick():
            from ..model_list import models, select
            from ..providers import PROVIDERS

            options = [row for row in models(data()) if row["enabled"]]
            try:
                current = select(data(), self.model_entry) if any(
                    row["id"] == self.model_entry for row in options) else select(data())
            except ValueError:
                current = None  # an invalid default must not prevent choosing a valid route
            rows = [f"{row['name']}  ·  {PROVIDERS[row['provider']].name if row['provider'] in PROVIDERS else row['provider']}"
                    + (f"  ·  {row['base_url']}" if row["base_url"] else "") for row in options]
            picked = await self._view(views.choose("Model for new conversations", rows,
                current=options.index(current) if current else 0,
                hint="Enter select · Esc close · /models edits the local list"))
            if picked is not None:
                row = options[picked]
                self.model_entry, self.model_effort = row["id"], None
                self._refresh_next_model(rows=options)
                self.note(f"Model for new conversations: {rows[picked]}")

        self.app.create_background_task(self._guarded(pick))

    def do_models(self, _):
        async def edit():
            from shlex import split

            from ..model_list import models

            path = data() / "models.json"
            try:
                models(data())  # writes the list when there is none yet
            except ValueError:
                pass  # one saved with a mistake opens as it is, to be put right
            self.note(f"Editing {path}. Save and close your editor to return. vi: Esc, :wq, Enter saves; :q! discards. Set EDITOR to choose another editor.")
            editor = os.environ.get("EDITOR") or ("notepad.exe" if os.name == "nt" else "vi")
            command = [editor] if os.path.isfile(editor) else split(editor, posix=os.name != "nt")
            async with in_terminal():
                result = await asyncio.to_thread(subprocess.run, [*command, str(path)], check=False)
            if result.returncode:
                raise ValueError(f"the editor exited with code {result.returncode}")
            try:
                rows = models(data())
            except ValueError as error:
                raise ValueError(f"{error}; /models opens it again to correct it") from None
            if not self._refresh_next_model(rows=rows):
                self.note(self.next_model_problem, "yellow")
            count = sum(row["enabled"] for row in rows)
            self.note(f"{count} enabled models · /model to select · {path}")

        self.app.create_background_task(self._guarded(edit))

    def do_settings(self, _):
        async def edit():
            for line in await self._view(views.settings_view(data())):
                self.note(f"set {line}")

        self.app.create_background_task(self._guarded(edit))

    def do_packages(self, _):
        async def edit():
            for line in await self._view(views.packages_view(await self._request(self._host))):
                self.note(line)

        self.app.create_background_task(self._guarded(edit))

    def do_library(self, _):
        from harness.core.memory import rows

        conversation = self.conversation
        # A session's conversation says (RemoteConversation.memory); one in this process, its trace.
        memory = getattr(conversation, "memory", None) or (
            (lambda: rows(run=conversation.directory)) if conversation is not None else None)
        self.app.create_background_task(self._guarded(lambda: self._view(views.library_view(memory))))

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
            self.note(f"({error})", "red")


class Completions(Completer):
    """/ the commands (and /approve's words), @ the paths under this directory."""

    def __init__(self):
        self.paths = PathCompleter(expanduser=True)

    def get_completions(self, document, event):
        text = document.text_before_cursor
        if text.startswith("/") and " " not in text:
            for name, found in COMMANDS.items():
                if name.startswith(text[1:]):
                    yield Completion(f"/{name}", -len(text), display=f"/{name} {found.words}".strip(),
                                     display_meta=found.note)
            return
        if text.startswith("/approve ") and text.count(" ") == 1:
            for remember in APPROVE_WORDS:
                if remember.startswith(text.split(" ")[1]):
                    yield Completion(remember, -len(text.split(" ")[1]))
            return
        found = re.search(r'@("?)([^\s"]*)$', text)
        if found:
            for completion in self.paths.get_completions(Document(found.group(2)), event):
                path = found.group(2)[:len(found.group(2)) + completion.start_position] + completion.text
                quoted = f'"{path}"' if " " in path else path
                yield Completion(quoted, -len(found.group(1) + found.group(2)), display=completion.display,
                                 display_meta="folder" if Path(path).is_dir() else "")


class Placeholder(Processor):
    """What the empty input box is for, dim."""

    def __init__(self, chat):
        self.chat = chat

    def apply_transformation(self, given):
        if given.document.text or given.lineno:
            return Transformation(given.fragments)
        ask = self.chat.ask
        words = (f"{say('answer.why')}, Enter" if ask and ask.get("reason") else
                 f"1-{len(ask['options'])} or ↑↓ Enter to answer, or type a message" if ask else
                 "a message: it reaches the agent at once" if self.chat.status in ("RUNNING", "starting") else
                 "what should it do?")
        return Transformation(given.fragments + [("class:placeholder", words)])


# Seconds a choice opened by sending a message does not take Enter (views.choose settle).
SETTLE = 0.6


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


def _history_file() -> Path:
    path = data() / "tui-history"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _input():
    """The terminal's keys; on Windows read as the console's key records, so that Shift+Enter
    comes apart from Enter (as Ctrl+J, a new line)."""
    if sys.platform != "win32":
        return create_input()
    from prompt_toolkit.input.win32 import ConsoleInputReader, Win32Input
    from prompt_toolkit.key_binding.key_processor import KeyPress

    class Reader(ConsoleInputReader):
        def _event_to_key_presses(self, ev):
            # Shift+Enter, Ctrl+Enter and Ctrl+J: a new line (the console gives the last two as Esc, Ctrl+J).
            control = ev.ControlKeyState & (self.LEFT_CTRL_PRESSED | self.RIGHT_CTRL_PRESSED)
            if ev.VirtualKeyCode == 13 and ev.ControlKeyState & (self.SHIFT_PRESSED | control) or \
                    ev.VirtualKeyCode == 0x4A and control:
                return [KeyPress(Keys.ControlJ, "\n")]
            return super()._event_to_key_presses(ev)

    found = Win32Input()
    found._use_virtual_terminal_input = False
    found.console_input_reader = Reader()
    return found
