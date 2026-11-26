"""The first run in a terminal (harness, harness setup, harness model): what on this
computer can be the agent's model, one real call with the one chosen, and it is kept
(onboarding.py: the same steps the app's page goes through). Everything else keeps its
default and is changed later.

It asks only what must be asked: which source (one that was found is one Enter away), a
key when a provider is added by hand, and, where no login item exists yet, whether the
agent keeps running in the background. The lines it leaves in the terminal say what was
chosen; the lists and the waiting line are erased once answered.
"""

import threading
import time

from prompt_toolkit import print_formatted_text, prompt
from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from .. import onboarding, providers
from ..problems import lines as problem_lines

STYLE = Style.from_dict({"title": "bold", "pick": "bold reverse", "dim": "#8a8a8a", "ok": "#5faf5f", "bad": "#d75f5f",
                         "key": "bold"})
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ADD_KEY, BRING = "add a key", "bring over"


def say(*parts) -> None:
    """Print styled parts: (style, text) pairs, or plain strings."""
    print_formatted_text(FormattedText([part if isinstance(part, tuple) else ("", part) for part in parts]),
                         style=STYLE)


def select(title: str, rows: list, *, notes=(), default: int = 0, leave: str = "Esc to leave") -> int | None:
    """One of `rows` ("name\\twhat it is") picked with the arrows or its number and Enter:
    its index, or None when left with Esc or Ctrl+C. The list is erased once answered."""
    state = {"at": max(0, min(default, len(rows) - 1))}

    def text():
        out = [("class:title", title), ("", "\n")]
        for index, row in enumerate(rows):
            name, _, about = row.partition("\t")
            here = index == state["at"]
            out += [("class:pick" if here else "", f"{'❯' if here else ' '} {index + 1}. {name} "),
                    ("class:dim", f"  {about}" if about else ""), ("", "\n")]
        for note in notes:
            out += [("class:dim", f"  {note}"), ("", "\n")]
        out += [("class:dim", f"  ↑ ↓ to move · Enter to choose · {leave}")]
        return out

    keys = KeyBindings()

    @keys.add("up")
    @keys.add("c-p")
    def _(event):
        state["at"] = (state["at"] - 1) % len(rows)

    @keys.add("down")
    @keys.add("c-n")
    @keys.add("tab")
    def _(event):
        state["at"] = (state["at"] + 1) % len(rows)

    for digit in "123456789"[:len(rows)]:
        @keys.add(digit)
        def _(event, digit=digit):
            state["at"] = int(digit) - 1

    @keys.add("enter")
    def _(event):
        event.app.exit(result=state["at"])

    @keys.add("escape", eager=True)
    @keys.add("c-c")
    @keys.add("c-d")
    def _(event):
        event.app.exit(result=None)

    app = Application(layout=Layout(Window(FormattedTextControl(text), wrap_lines=True)), key_bindings=keys,
                      full_screen=False, erase_when_done=True, style=STYLE)
    # Esc alone is told from the start of an arrow key's sequence at once, as in the chat.
    app.timeoutlen, app.ttimeoutlen = 0.3, 0.05
    return app.run()


def wait(text: str, function):
    """What `function(log)` returns, run on a thread while a line shows that it runs, for
    how long, and the last thing it logged. Its exception is raised here; Ctrl+C stops
    waiting (KeyboardInterrupt)."""
    said, box, began = [text], {}, time.monotonic()

    def line():
        seconds = time.monotonic() - began
        return [("class:dim", f"{SPINNER[int(seconds * 10) % len(SPINNER)]} {said[-1]}  {seconds:.0f} s · Ctrl+C to stop")]

    keys = KeyBindings()

    @keys.add("c-c")
    def _(event):
        event.app.exit(result=False)

    app = Application(layout=Layout(Window(FormattedTextControl(line), height=1)), key_bindings=keys,
                      full_screen=False, erase_when_done=True, style=STYLE, refresh_interval=0.1)

    def work():
        try:
            box["result"] = function(lambda message: said.append(str(message).removeprefix("harness: ")))
        except BaseException as error:  # noqa: BLE001 - raised again by the caller's thread
            box["error"] = error
        loop = getattr(app, "loop", None)
        if loop is not None and app.is_running:
            loop.call_soon_threadsafe(lambda: app.is_running and app.exit(result=True))

    def begin():
        threading.Thread(target=work, daemon=True).start()

    if app.run(pre_run=begin) is False:
        raise KeyboardInterrupt
    if "error" in box:
        raise box["error"]
    return box.get("result")


def failed(error) -> None:
    first, *rest = problem_lines(error)
    say(("class:bad", f"✗ {first}"))
    for line in rest:
        say(("class:dim", f"  {line}"))


def source_rows(found: dict) -> tuple[list, list]:
    """The list of the first question: (rows, choices), a choice being a source of
    onboarding.found or ADD_KEY."""
    rows, choices = [], []
    for agent in found["agents"]:
        state = {True: "signed in", False: f"not signed in: {agent['sign_in']}", None: "installed"}[agent["signed_in"]]
        rows.append(f"{agent['name']}\t{state}" + (f" · uses {agent['plan']}, no key needed" if agent["plan"] else ""))
        choices.append(agent)
    for key in found["keys"]:
        rows.append(f"{key['name']}\tkey found in {key['from']} ({key['key_env']})")
        choices.append(key)
    for local in found["local"][:3]:
        rows.append(f"{local['name']} · {local['model']}\ta model on this computer, no key needed")
        choices.append(local)
    rows.append("Enter a key for a provider…\tOpenRouter, OpenAI, Anthropic, Gemini and others, or an endpoint of your own")
    choices.append(ADD_KEY)
    return rows, choices


def ask_key() -> tuple[dict, str] | None:
    """A provider added by hand: (choice, key), or None when left."""
    listed = [provider for provider in providers.PROVIDERS.values()]
    picked = select("Which provider?", [f"{provider.name}\t{provider.note}" for provider in listed], leave="Esc to go back")
    if picked is None:
        return None
    provider = listed[picked]
    suggested = providers.DEFAULT["model"] if provider.id == providers.DEFAULT["provider"] else ""
    try:
        model = prompt(f"  Model{f' [{suggested}]' if suggested else ''}: ").strip() or suggested
        base_url = prompt("  Base URL of the endpoint: ").strip() if provider.base_url is None and \
            provider.backend != "openrouter" else None
        key = prompt(f"  {provider.key_env}{'' if providers.requires_key(provider.id) else ' (optional)'}: ",
                     is_password=True).strip() if provider.key_env else ""
    except (KeyboardInterrupt, EOFError):
        return None
    return {"kind": "key", "provider": provider.id, "name": provider.name, "model": model, "base_url": base_url}, key


def model_step(directory) -> dict | None:
    """Choose the model's source, try it, keep it: the entry kept, or None when left."""
    while True:
        try:
            found = wait("looking at what is on this computer", lambda log: onboarding.found(directory))
        except KeyboardInterrupt:
            return None
        rows, choices = source_rows(found)
        notes = [] if found["agents"] else ["Claude Code or Codex signed in on this computer would be listed here: "
                                           "they run under your own plan, without a key."]
        picked = select("Which model should it use?", rows, notes=notes)
        if picked is None:
            return None
        choice, key = choices[picked], None
        if choice == ADD_KEY:
            given = ask_key()
            if given is None:
                continue
            choice, key = given
        name = choice["name"]
        try:
            tried = wait(f"trying {name}", lambda log: onboarding.tryout(directory, choice, key, log))
        except KeyboardInterrupt:
            continue
        except Exception as error:  # noqa: BLE001 - said, then the list again
            failed(error)
            continue
        entry = onboarding.choose(directory, choice, key)
        about = "" if entry["model"] == "default" else f" · {entry['model']}"
        say(("class:ok", "✓ "), f"{name}{about} answered in {tried['seconds']} s")
        return entry


def background_step() -> None:
    """Where no login item exists yet: whether the agent keeps running in the background and
    starts at sign-in. The system's login item is the one truth of it, so one that exists
    (the desktop app's installer made it) is not asked about again."""
    from ..host import login

    try:
        if login.status().get("on"):
            return
    except (OSError, RuntimeError, ValueError):
        return
    picked = select("Keep it running in the background, and start it when you sign in?",
                    ["Yes\tit goes on with its work while no window is open", "No\tit runs while harness is open"],
                    leave="Esc for No")
    if picked == 0:
        try:
            login.install()
            say(("class:ok", "✓ "), "It starts when you sign in", ("class:dim", "  (harness host uninstall turns that off)"))
        except (OSError, RuntimeError, ValueError) as error:
            failed(error)
    else:
        say(("class:dim", "  It runs while harness is open (harness host install changes that)"))


def bring_step() -> None:
    """An agent of another product found on this computer: bring it over, when the user says so."""
    from ..extensions import first

    find, bring = first("elsewhere"), first("bring_over")
    if find is None or bring is None:
        return
    try:
        here = find()
    except (OSError, ValueError):
        return
    for row in here:
        name = {"openclaw": "OpenClaw", "hermes": "Hermes"}.get(row["kind"], row["kind"])
        picked = select(f"An agent of {name} is on this computer. Bring it over?",
                        ["Yes\tits persona, memory and skills; never its channel tokens or keys", "Not now"],
                        leave="Esc for not now")
        if picked != 0:
            continue
        try:
            made = wait(f"bringing over the {name} agent", lambda log, kind=row["kind"]: bring(kind))
            say(("class:ok", "✓ "), f"It is the identity {made.get('id') or name.lower()}",
                ("class:dim", "  (harness agent list shows them; stop the one in " + name + " so that both do not answer)"))
        except KeyboardInterrupt:
            return
        except Exception as error:  # noqa: BLE001 - said; the first run goes on without it
            failed(error)


def run(directory, *, version: str = "", only_model: bool = False) -> bool:
    """Go through the first run in this terminal. Whether a model is in use at its end
    (False: the user left; nothing was changed)."""
    if not only_model:
        say(("class:title", f"Welcome to The Harness {version}".rstrip()))
        say(("class:dim", "An agent that lives on this computer. First, the model it thinks with."))
        say("")
    entry = model_step(directory)
    if entry is None:
        say(("class:dim", "Nothing was changed. harness setup starts this again."))
        return False
    if only_model:
        return True
    bring_step()
    background_step()
    onboarding.done(directory)
    say("")
    for line in onboarding.next_steps():
        say(("class:dim", line))
    say("")
    return True
