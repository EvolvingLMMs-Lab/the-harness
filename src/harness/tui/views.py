"""The full-screen views of the terminal chat, each opened over it and closed back to it:
a picker (sessions, conversations, models), the settings (settings.SCHEMA, whatever the
packages add), the packages (packages/describe.py, as harness install / remove / list),
the libraries of what the agent learned (runtime/learning/learner.py) and the timeline
(core/lanes.py: the GUI's lanes, as bars under an axis)."""

import asyncio
import threading
import time

from prompt_toolkit.application import Application, in_terminal
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.text import Text

from ..core import format as formats
from ..core import lanes as timeline_lanes
from . import timeline_rows

STYLE = Style.from_dict({"title": "bold", "selected": "reverse", "dim": "#888888", "error": "#ff5f5f",
                         "lane.model": "#d787ff", "lane.verifier": "#5fd7d7", "lane.program": "#5f87ff",
                         "lane.agent": "#5fd7d7", "lane.env": "#d7d75f", "lane.other": "#5fd787"})
# Characters of a lane's name on the timeline.
LABEL = 24


async def choose(title: str, rows: list[str], *, hint: str = "", current: int = 0, typed: bool = False,
                 text: str = "", settle: float = 0.0):
    """A full-screen list to pick from, under `text` (lines about it), filtered as the user
    types: the index picked (in `rows`), None when closed; with `typed`, Enter on a text that
    matches nothing returns it. `settle`: seconds after it opens in which Enter is not
    taken: a view that opens because the user pressed Enter (a message was sent) must not
    be answered by that same key press."""
    query = Buffer(multiline=False)
    state = {"at": max(0, min(current, len(rows) - 1))}
    opened = time.monotonic()

    def shown():
        words = query.text.lower().split()
        return [index for index, row in enumerate(rows) if all(word in row.lower() for word in words)]

    def listing():
        found = shown()
        state["at"] = min(state["at"], max(len(found) - 1, 0))
        out = []
        for place, index in enumerate(found):
            out += [("class:selected" if place == state["at"] else "", f"{'❯' if place == state['at'] else ' '} {rows[index]}"),
                    ("", "\n")]
        return out or [("class:dim", "  nothing matches" + (": Enter takes what you typed" if typed else ""))]

    keys = KeyBindings()

    @keys.add("up")
    def _(event):
        state["at"] = max(state["at"] - 1, 0)

    @keys.add("down")
    def _(event):
        state["at"] = min(state["at"] + 1, max(len(shown()) - 1, 0))

    @keys.add("pageup")
    def _(event):
        state["at"] = max(state["at"] - 10, 0)

    @keys.add("pagedown")
    def _(event):
        state["at"] = min(state["at"] + 10, max(len(shown()) - 1, 0))

    @keys.add("enter")
    def _(event):
        if time.monotonic() - opened < settle:
            return
        found = shown()
        event.app.exit(result=found[state["at"]] if found else (query.text.strip() or None) if typed else None)

    @keys.add("escape", eager=True)
    @keys.add("c-c")
    def _(event):
        event.app.exit(result=None)

    @keys.add("f2")
    async def _(event):
        found = shown()
        if found:
            state["at"] = min(state["at"], len(found) - 1)
            async with in_terminal(render_cli_done=False):
                await read("Selected option · Esc returns to the list", rows[found[state["at"]]])

    lines = [Window(FormattedTextControl([("class:title", title)]), height=1),
             Window(BufferControl(query), height=1, get_line_prefix=lambda *_: [("class:dim", "filter: ")]),
             Window(height=1, char="─", style="class:dim"),
             Window(FormattedTextControl(listing, focusable=False, get_cursor_position=lambda: Point(0, state["at"])),
                    wrap_lines=False),
             Window(FormattedTextControl([("class:dim", "F2 full row · " + (hint or "↑↓ move · Enter pick · type filter · Esc close"))]),
                    height=1)]
    def selected():
        found = shown()
        state["at"] = min(state["at"], max(0, len(found) - 1))
        return rows[found[state["at"]]] if found else ""

    lines.insert(-1, Window(FormattedTextControl(selected),
                            height=3, wrap_lines=True))
    if text:
        lines.insert(1, Window(FormattedTextControl(text), wrap_lines=True, dont_extend_height=True))
    app = Application(Layout(HSplit(lines), focused_element=lines[1]), key_bindings=keys, style=STYLE,
                      full_screen=True)
    return await app.run_async()


async def ask(title: str, default: str = "", hint: str = "Enter keep · Esc cancel") -> str | None:
    """One line typed full screen (a setting's value): the text, None when cancelled."""
    field = Buffer(multiline=False)
    field.text = default
    field.cursor_position = len(default)  # typing goes on from the end of what is there
    keys = KeyBindings()

    @keys.add("enter")
    def _(event):
        event.app.exit(result=field.text)

    @keys.add("escape", eager=True)
    @keys.add("c-c")
    def _(event):
        event.app.exit(result=None)

    body = Window(BufferControl(field), height=1, get_line_prefix=lambda *_: "› ")
    app = Application(Layout(HSplit([Window(FormattedTextControl([("class:title", title)]), height=1), body,
                                     Window(FormattedTextControl([("class:dim", hint)]), height=1)]),
                             focused_element=body), key_bindings=keys, style=STYLE, full_screen=True)
    return await app.run_async()


async def read(title: str, text, *, close_key=None, live=None) -> None:
    """Read text (or a live text callback) on an alternate screen, then restore chat."""
    cache = {"key": None, "lines": [""], "text": ""}
    state = {"at": 0}
    keys = KeyBindings()

    def lines():
        value = str(text() if callable(text) else text)
        width = max(1, app.output.get_size().columns)
        if cache["key"] != (value, width):
            console = Console(width=width, color_system=None)
            cache["lines"] = [line.plain for line in Text(value).wrap(console, width, overflow="fold")] or [""]
            cache["text"] = "\n".join(cache["lines"])
            cache["key"] = (value, width)
        state["at"] = min(state["at"], len(cache["lines"]) - 1)
        return cache["lines"]

    def move(step):
        state["at"] = max(0, min(state["at"] + step, len(lines()) - 1))

    keys.add("up")(lambda event: move(-1))
    keys.add("down")(lambda event: move(1))
    keys.add("pageup")(lambda event: move(-max(1, event.app.output.get_size().rows - 3)))
    keys.add("pagedown")(lambda event: move(max(1, event.app.output.get_size().rows - 3)))
    keys.add("home")(lambda event: state.update(at=0))
    keys.add("end")(lambda event: state.update(at=len(lines()) - 1))

    @keys.add("escape", eager=True)
    @keys.add("q")
    @keys.add("c-c")
    def _(event):
        event.app.exit()

    if close_key:
        keys.add(close_key)(lambda event: event.app.exit())

    buffer = Buffer(read_only=True)

    def update(app):
        lines()
        if buffer.text != cache["text"]:
            buffer.set_document(Document(cache["text"]), bypass_readonly=True)
        buffer.cursor_position = buffer.document.translate_row_col_to_index(state["at"], 0)

    body = Window(BufferControl(buffer), wrap_lines=False)
    app = Application(Layout(HSplit([Window(FormattedTextControl([("class:title", title)]), height=1), body,
                                     Window(FormattedTextControl([("class:dim", "↑↓ PgUp PgDn Home End scroll · Esc close")]),
                                            height=1)])), key_bindings=keys, style=STYLE, full_screen=True,
                      refresh_interval=0.25 if (callable(text) if live is None else live) else None,
                      before_render=update)
    await app.run_async()


# A dismissed mutation still runs in its host/thread; it has no UI owner afterward.
_DISMISSED = object()


async def working(title: str, function, *, cancellable=False, dismissible=False):
    """Run off the UI loop. Read waits can be cancelled; mutation waits can be left.

    Returns (result, error), or (_DISMISSED, None) when the operation keeps running.
    """
    said, done = [], {}
    closed, lock = threading.Event(), threading.Lock()

    def log(message):
        with lock:
            if not closed.is_set():
                said.append(str(message))

    def finish():
        if not closed.is_set() and app.is_running:
            app.exit()

    def run():
        try:
            result, error = function(log), None
        except Exception as problem:
            result, error = None, problem
        with lock:
            if closed.is_set():
                return
            done.update(result=result, error=error)
        if app.is_running:
            app.loop.call_soon_threadsafe(finish)

    keys = KeyBindings()

    if cancellable or dismissible:
        @keys.add("escape", eager=True)
        @keys.add("c-c")
        def _(event):
            with lock:
                closed.set()
                if dismissible:
                    done["dismissed"] = True
                else:
                    done["error"] = InterruptedError("Stopped waiting; the host request may still finish.")
            event.app.exit()

    hint = " · Esc return; operation keeps running" if dismissible else " · Esc cancel" if cancellable else ""
    app = Application(Layout(HSplit([Window(FormattedTextControl([("class:title", f"{title} ...{hint}")]), height=1),
                                     Window(FormattedTextControl(lambda: "\n".join(said[-40:])), wrap_lines=True)])),
                      style=STYLE, key_bindings=keys, full_screen=True, refresh_interval=0.3)
    app.pre_run_callables.append(lambda: threading.Thread(target=run, daemon=True).start())
    try:
        await app.run_async()
    finally:
        closed.set()
    if done.get("dismissed"):
        return _DISMISSED, None
    return done.get("result"), done.get("error")


async def _load(title, function):
    value, error = await working(title, lambda log: function(), cancellable=True)
    if error:
        raise error
    return value


async def packages_view(host) -> list[str]:
    """The installed packages and the registry's, each with what it provides; Enter on one
    shows all of it and what can be done: install, update, turn on or off, remove (asked
    first). Returns what changed."""
    from urllib.parse import quote

    from ..packages import activate
    from ..packages.describe import COLUMNS, describe, rows

    # A previous dismissed host mutation may have completed since this view closed.
    await asyncio.to_thread(activate)
    changed, registry = [], False
    while True:
        # The registry may be read over the network: on a thread, as installing is.
        payload = await _load("Reading the packages", lambda: host.get("/api/app/packages/search?q=") if registry
                              else host.get("/api/app/packages"))
        problem = payload.get("error")
        found, which = payload.get("results" if registry else "packages", []), "available" if registry else "installed"
        table, columns = rows(found, which, 40), COLUMNS[which]
        widths = {column: min(max([len(column)] + [len(str(row[column])) for row in table]), 40) for column in columns}
        lines = ["↔ " + ("the installed packages" if registry else "the registry's packages")] + [
            "  ".join(formats.clip(row[column], widths[column]).ljust(widths[column]) for column in columns)
            for row in table]
        heading = "  " + "  ".join(column.ljust(widths[column]) for column in columns)
        picked = await choose(f"Packages: {'the registry' if registry else 'installed'}", lines, text=(
            f"{problem}" if problem else heading if found else "Nothing installed yet." if not registry else ""))
        if picked is None:
            return changed
        if picked == 0:
            registry = not registry
            continue
        row = found[picked - 1]
        try:
            info = await _load("Reading package details", lambda: host.get("/api/app/packages/info?name=" + quote(row["name"])))
            about = "\n".join((info.get("shown") or describe(info))["lines"])
        except Exception as error:
            about = f"{row['name']}: {error}"
        if registry:
            actions = ["update", "remove"] if row.get("installed") else ["install"]
        else:
            actions = ["update", "turn " + ("off" if row.get("enabled") else "on"), "remove"]
        action = await choose(row["name"], actions + ["back"], text=about)
        if action is None or action == len(actions):
            continue
        action = actions[action]
        name = row["name"]
        if action in ("install", "remove") and await choose(
                f"{action.capitalize()} {name}?" + (" Its skills, embodiments and services go with it."
                                                    if action == "remove" else ""), ["no", "yes"]) != 1:
            continue
        if action.startswith("turn"):
            calls = lambda log: host.post("/api/app/packages/enable", {"name": name, "on": action.endswith("on")}, timeout=3600)  # noqa: E731
        else:
            body = {"source": name} if action == "install" else {"names": [name]} if action == "update" else {"name": name}
            calls = lambda log: host.post("/api/app/packages/" + action, body, timeout=3600)  # noqa: E731
        result, error = await working(f"{action.capitalize()} {name}", calls, dismissible=True)
        if result is _DISMISSED:
            return [*changed, "Stopped waiting; check /packages for outcome"]
        if not error and result and result.get("needs_trust"):
            # Non-registry sources require a separate explicit trust decision.
            if await choose("Trust and install this package?", ["no", "yes"],
                            text="\n".join(str(row) for row in result["found"])) == 1:
                result, error = await working(f"Install {name}", lambda log: host.post(
                    "/api/app/packages/install", {"source": name, "trust": True}, timeout=3600), dismissible=True)
                if result is _DISMISSED:
                    return [*changed, "Stopped waiting; check /packages for outcome"]
            else:
                continue
        if not error:
            await asyncio.to_thread(activate)
        changed.append(f"{action} {name}: " + (f"failed: {error}" if error else "done"))
        if error:
            await read(f"{action} {name} failed", str(error))


async def library_view(memory=None) -> None:
    """What the agent remembers: this conversation's memory (`memory`: a call that gives its
    rows, runtime/task/context.py) and the libraries; Enter on one lists its entries as every
    frontend shows them, Enter on an entry shows it."""
    from pathlib import Path

    from harness.runtime.learning import learner
    from harness.core.memory import COLUMNS, rows as memory_rows

    while True:
        found = await _load("Reading libraries", learner.libraries)
        lines = [f"{row['name']:<28} {row['entries']:>4} entries   version {row['version'][:12]}" for row in found]
        picked = await choose("Memory: this conversation's and the libraries'",
                              (["this conversation: what it saw and where, and its library"] if memory else []) + lines,
                              text="" if found or memory else "No library yet: a run with [runtime.library] learn = "
                                                              "\"on\" keeps what it learns there.")
        if picked is None:
            return
        if memory and picked == 0:
            title, load = "this conversation", memory
        else:
            row = found[picked - (1 if memory else 0)]
            title, load = f"{row['name']}: version {row['version'][:12]}", \
                (lambda directory=Path(row["directory"]): memory_rows(library=directory))
        while True:
            entries = await _load("Reading memory", load)
            at = await choose(title, ["  ".join(f"{cell:<12}" for cell in row["cells"][:7]) for row in entries],
                              hint="Enter read · type to filter · Esc back")
            if at is None:
                break
            row = entries[at]
            from json import dumps

            details = [f"{column}: {cell}" for column, cell in zip(COLUMNS, row["cells"][:-1])]
            if row.get("summary"):
                details.append(f"summary: {row['summary']}")
            if row.get("history"):
                details.append("history: " + dumps(row["history"], ensure_ascii=False, indent=2))
            await read(f"{row['scope']} {row['kind']} {row['name'] or row['id']}",
                       "\n".join([row["text"] or "", "", *details]))


async def settings_view(directory) -> list[str]:
    """Every setting (settings.rows) to change one at a time until closed, under the packages'
    note on this computer; returns what changed."""
    from ..extensions import first
    from ..settings import SCHEMA, Settings, rows

    store, changed, at, note = Settings(directory), [], 0, first("note")
    while True:
        values = store.get()
        found = [row for row in rows(values) if row["section"] != "general" and row["setting"] not in
                 ("model.reasoning_effort", "model.think_while_acting", "model.think_interval")]
        lines = [f"{row['setting']:<36} {_shown(row)}" for row in found]
        at = await choose("Settings" + (f"   {note(values)}" if note else ""), lines, current=at,
                          hint="Enter change · type to filter · Esc close · /models edits the model list")
        if at is None:
            return changed
        row, spec = found[at], SCHEMA[found[at]["section"]][found[at]["key"]]
        if row["kind"] == "bool":
            value = not row["value"]
        elif row["kind"] == "choice":
            picked = await choose(f"{row['setting']}: {row['about']}", list(spec.bounds),
                                  current=list(spec.bounds).index(row["value"]) if row["value"] in spec.bounds else 0)
            value = spec.bounds[picked] if picked is not None else None
        elif row["kind"] == "rules":
            try:
                value = await _rules(row, spec)
            except ValueError as error:
                await choose(f"Not changed: {error}", ["back"])
                continue
        else:
            value = await ask(f"{row['setting']} ({row['about']})", str(row["value"]))
        if value is None or value == row["value"]:
            continue
        try:
            store.update({row["section"]: {row["key"]: value}})
            changed.append(f"{row['setting']} = {_shown({**row, 'value': store.get()[row['section']][row['key']]})}"
                           + ("" if spec.applies == "now" else f" ({spec.applies.replace('_', ' ')})"))
        except ValueError as error:
            await choose(f"Not changed: {error}", ["back"])


def _shown(row) -> str:
    value = row["value"]
    if row["kind"] == "rules":
        return f"{len(value)} rule{'s' if len(value) != 1 else ''}"
    return formats.clip(str(value).replace("\n", " "), 60) if value != "" else "(empty)"


async def _rules(row, spec) -> list | None:
    """Remove a rule or add one with all of the scopes that must match."""
    from ..settings import SCHEMA

    rules = list(row["value"])
    levels = list(getattr(SCHEMA[row["section"]].get("level"), "bounds", None) or ())
    picked = await choose(f"{row['setting']}: {row['about']}", [_rule(rule) for rule in rules] + ["+ add a rule"],
                          hint="Enter on a rule removes it · Esc back")
    if picked is None:
        return None
    if picked < len(rules):
        return rules[:picked] + rules[picked + 1:]
    level = await choose("Its level", levels) if levels else None
    if level is None:
        return None
    rule = {"level": levels[level]}
    fields = {**(spec.fields or {}), **(spec.fields_when or {}).get(rule["level"], {})}
    while True:
        names = list(fields)
        labels = [f"{name}: {rule[name]}" if name in rule else name for name in names]
        field = await choose("What it is for", [*labels, "Save rule"], current=len(names) if len(rule) > 1 else 0)
        if field is None:
            return None
        if field == len(names):
            return rules + [rule]
        name = names[field]
        kind = fields[name]
        if isinstance(kind, (list, tuple)):
            chosen = await choose(name, list(kind))
            if chosen is not None:
                rule[name] = kind[chosen]
        else:
            value = await ask(name, str(rule.get(name, "")))
            if value:
                rule[name] = float(value) if kind == "float" else value
            elif value == "":
                rule.pop(name, None)


def _rule(rule: dict) -> str:
    return f"{rule.get('level', '?'):<18} " + ", ".join(f"{key} {value}" for key, value in rule.items() if key != "level")


def timeline_lines(lanes, width: int, seconds: float | None = None) -> list:
    """The timeline as formatted lines: an axis with the times at its ends, then each lane's
    name and its bars (core/lanes.rows), no other text."""
    if lanes.t0 is None:
        return [("class:dim", "no records yet")]
    now = lanes.now(time.time())
    start = lanes.t0 if seconds is None else max(lanes.t0, now - seconds)
    start = min(start, now - 1.0)
    cells = max(width - LABEL - 1, 10)
    left, right = formats.clock(start - lanes.t0), formats.clock(now - lanes.t0)
    axis = "├" + "─" * (cells - 2) + "┤"
    out = [("", " " * (LABEL + 1)), ("class:dim", left + right.rjust(cells - len(left))), ("", "\n"),
           ("", " " * (LABEL + 1)), ("class:dim", axis), ("", "\n")]
    for row in timeline_rows.rows(lanes, start, now, cells, now):
        lane = row["lane"]
        style = "class:error" if lane.get("status") == "failed" else "class:dim" if lane.get("end") is not None else ""
        out += [(style, f"{formats.clip(row['label'], LABEL):<{LABEL}} "),
                (f"class:lane.{lane['kind'] if lane['kind'] in LANE_KINDS else 'other'}", row["cells"]), ("", "\n")]
    return out


LANE_KINDS = ("model", "verifier", "program", "agent", "env")


async def timeline_view(lanes, feed=None) -> None:
    """`lanes` full screen, drawn again twice a second (`feed()` first adds what came);
    + and - zoom, 0 shows the whole run, Esc, q or Ctrl+T close."""
    window = {"seconds": None, "at": 0, "count": 1}
    keys = KeyBindings()

    @keys.add("escape", eager=True)
    @keys.add("q")
    @keys.add("c-t")
    @keys.add("c-c")
    def _(event):
        event.app.exit()

    @keys.add("+")
    @keys.add("=")
    def _(event):
        whole = lanes.now(time.time()) - (lanes.t0 or 0)
        window["seconds"] = max(5.0, (window["seconds"] or whole) / 2)

    @keys.add("-")
    def _(event):
        window["seconds"] = window["seconds"] and window["seconds"] * 2

    @keys.add("0")
    def _(event):
        window["seconds"] = None

    def move(step):
        window["at"] = max(0, min(window["at"] + step, window["count"] - 1))

    keys.add("up")(lambda event: move(-1))
    keys.add("down")(lambda event: move(1))
    keys.add("pageup")(lambda event: move(-max(1, event.app.output.get_size().rows - 3)))
    keys.add("pagedown")(lambda event: move(max(1, event.app.output.get_size().rows - 3)))
    keys.add("home")(lambda event: window.update(at=0))
    keys.add("end")(lambda event: window.update(at=window["count"] - 1))

    def draw():
        if feed is not None:
            feed()
        lines = timeline_lines(lanes, app.output.get_size().columns, window["seconds"])
        window["count"] = 1 + sum(text.count("\n") for _, text in lines)
        return lines

    app = Application(Layout(HSplit([
        Window(FormattedTextControl([("class:title", "Timeline")]), height=1),
        Window(FormattedTextControl(draw, get_cursor_position=lambda: Point(0, window["at"])), wrap_lines=False),
        Window(FormattedTextControl([("class:dim", "↑↓ PgUp PgDn scroll · + - zoom · 0 whole run · Esc close")]), height=1)])),
        key_bindings=keys, style=STYLE, full_screen=True, refresh_interval=0.5)
    await app.run_async()


def follow_timeline(directory) -> int:
    """harness timeline RUN in a terminal: the episode in `directory` followed while it is written."""
    import asyncio

    from ..core.episodes import Follow

    lanes, follow = timeline_lanes.Lanes(), Follow(directory)

    def feed():
        for record in follow.next():
            lanes.add(record)

    asyncio.run(timeline_view(lanes, feed))
    return 0
