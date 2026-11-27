"""The first run in a terminal (harness, harness setup, harness model): what on this
computer can be the agent's model, one real call with the one chosen, and it is kept
(onboarding.py: the same steps the app's page goes through). Everything else keeps its
default and is changed later.

It asks only what must be asked: which source (one that was found is one Enter away), a
key when a provider is added by hand, and, where no login item exists yet, whether the
agent keeps running in the background. The lines it leaves in the terminal say what was
chosen; the lists and the waiting line are erased once answered.
"""

import shutil
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
ADD_KEY, MORE = "add a key", "more agents"


def say(*parts) -> None:
    """Print styled parts: (style, text) pairs, or plain strings."""
    print_formatted_text(FormattedText([part if isinstance(part, tuple) else ("", part) for part in parts]),
                         style=STYLE)


def select(title: str, rows: list, *, notes=(), default: int = 0, leave: str = "Esc to leave",
           search: bool = False) -> int | None:
    """One of `rows` ("name\\twhat it is") picked with the arrows and Enter: its index, or
    None when left with Esc or Ctrl+C. A short list also takes a row's number; with `search`
    (a long list) typing narrows it instead. As many rows as the terminal has room for are
    shown, around the one chosen. The list is erased once answered."""
    state = {"at": max(0, min(default, len(rows) - 1)), "query": ""}

    def shown():
        words = state["query"].lower().split()
        return [index for index, row in enumerate(rows) if all(word in row.lower() for word in words)]

    def text():
        found = shown()
        state["at"] = min(state["at"], max(len(found) - 1, 0))
        room = max(3, min(12, shutil.get_terminal_size().lines - len(notes) - 5))
        first = max(0, min(state["at"] - room // 2, len(found) - room))
        out = [("class:title", title), ("", "\n")]
        if search:
            out += [("class:dim", "  Search: "), ("", state["query"]), ("class:dim", "▏"), ("", "\n")]
        if first:
            out += [("class:dim", f"  ↑ {first} more"), ("", "\n")]
        for place in range(first, min(first + room, len(found))):
            name, _, about = rows[found[place]].partition("\t")
            here = place == state["at"]
            mark = name if search else f"{found[place] + 1}. {name}"
            out += [("class:pick" if here else "", f"{'❯' if here else ' '} {mark} "),
                    ("class:dim", f"  {about}" if about else ""), ("", "\n")]
        if not found:
            out += [("class:dim", "  Nothing matches"), ("", "\n")]
        if len(found) > first + room:
            out += [("class:dim", f"  ↓ {len(found) - first - room} more"), ("", "\n")]
        for note in notes:
            out += [("class:dim", f"  {note}"), ("", "\n")]
        out += [("class:dim", f"  ↑ ↓ to move · Enter to choose · {'type to search · ' if search else ''}{leave}")]
        return out

    keys = KeyBindings()

    def move(by):
        state["at"] = (state["at"] + by) % max(len(shown()), 1)

    @keys.add("up")
    @keys.add("c-p")
    def _(event):
        move(-1)

    @keys.add("down")
    @keys.add("c-n")
    @keys.add("tab")
    def _(event):
        move(1)

    if search:
        @keys.add("<any>")
        def _(event):
            if event.data.isprintable():
                state["query"] += event.data
                state["at"] = 0

        @keys.add("backspace")
        def _(event):
            state["query"] = state["query"][:-1]
            state["at"] = 0
    else:
        for digit in "123456789"[:len(rows)]:
            @keys.add(digit)
            def _(event, digit=digit):
                state["at"] = int(digit) - 1

    @keys.add("enter")
    def _(event):
        found = shown()
        if found:
            event.app.exit(result=found[state["at"]])

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


def agent_row(agent: dict) -> str:
    """An agent as a row: its name and its state, nothing else (what to do about a state is
    said when the agent is chosen and does not answer)."""
    if not agent.get("installed", True):
        # one that installs when it is chosen, or one whose own command line has to be here first
        return f"{agent['name']}\t" + ("can be installed" if agent.get("standalone") else "not installed")
    return f"{agent['name']}\t" + {True: "signed in", False: "not signed in", None: "installed"}[agent.get("signed_in")]


def source_rows(found: dict) -> tuple[list, list, int]:
    """The list of the first question: (rows, choices, where it opens), a choice being a
    source of onboarding.found, MORE or ADD_KEY. What can be used as it is comes first (the
    list opens on it); the agents that are not here or not signed in follow, each with how
    to get it; then the rest of the ACP Registry, and a key typed by hand (where the list
    opens when nothing here can be used yet)."""
    rows, choices = [], []
    ready = [agent for agent in found["agents"] if onboarding.usable(agent)]
    for agent in ready:
        rows.append(agent_row(agent))
        choices.append(agent)
    for key in found["keys"]:
        rows.append(f"{key['name']}\tkey · {key['key_env']}")
        choices.append(key)
    for local in found["local"][:3]:
        rows.append(f"{local['name']} · {local['model']}\tlocal")
        choices.append(local)
    for agent in found["agents"]:
        if agent not in ready:
            rows.append(agent_row(agent))
            choices.append(agent)
    rows.append("More agents…")
    choices.append(MORE)
    rows.append("Enter a key…")
    choices.append(ADD_KEY)
    usable = len(ready) + len(found["keys"]) + len(found["local"][:3])
    return rows, choices, 0 if usable else len(rows) - 1


def ask_agent() -> dict | None:
    """An agent of the ACP Registry: the choice, or None when left."""
    try:
        listed = wait("reading the ACP Registry", lambda log: onboarding.more_agents())
    except KeyboardInterrupt:
        return None
    except Exception as error:  # noqa: BLE001 - said, then the list again
        failed(error)
        return None
    picked = select("Which agent?", [f"{agent['name']}\t{agent['provider'].removeprefix('acp:')}" for agent in listed],
                    leave="Esc to go back", search=True)
    return None if picked is None else listed[picked]


def ask_key() -> tuple[dict, str] | None:
    """A provider added by hand: (choice, key), or None when left."""
    listed = [provider for provider in providers.PROVIDERS.values()]
    picked = select("Which provider?", [provider.name for provider in listed], leave="Esc to go back")
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
        rows, choices, opens = source_rows(found)
        picked = select("Model source", rows, default=opens)
        if picked is None:
            return None
        choice, key = choices[picked], None
        if choice == MORE:
            choice = ask_agent()
            if choice is None:
                continue
        elif choice == ADD_KEY:
            given = ask_key()
            if given is None:
                continue
            choice, key = given
        name = choice["name"]
        tried = None
        while tried is None:
            try:
                tried = wait(f"trying {name}", lambda log: onboarding.tryout(directory, choice, key, log))
            except KeyboardInterrupt:
                break
            except Exception as error:  # noqa: BLE001 - said; signed in to here when that is what is missing, else the list again
                failed(error)
                if not (getattr(error, "code", "") == "not_signed_in" and sign_in_here(choice["provider"], name)):
                    break
        if tried is None:
            continue
        try:
            entry = wait(f"reading the models of {name}", lambda log: onboarding.choose(directory, choice, key, log))
        except KeyboardInterrupt:
            continue
        say(("class:ok", "✓ "), f"{name} answered in {tried['seconds']} s")
        entry = model_question(directory, entry, name)
        say(("class:ok", "✓ "), f"Model: {onboarding.model_name(entry)}", ("class:dim", f"  from {name} · /model changes it"))
        return entry


def sign_in_here(provider: str, name: str) -> bool:
    """An agent that said it is not signed in: the ways it offers to sign in through it, one
    of them gone through now (the agent opens a page in the browser). Whether it was."""
    try:
        ways = wait(f"asking {name} how to sign in", lambda log: onboarding.sign_in(provider, None, log))
    except (KeyboardInterrupt, Exception):  # noqa: BLE001 - it is signed in to with its own command then
        return False
    if not ways:
        return False
    picked = select(f"Sign in to {name}?", [f"{way['name']}\t{way.get('description') or way['id']}" for way in ways]
                    + ["Not now"], leave="Esc for not now")
    if picked is None or picked >= len(ways):
        return False
    try:
        wait(f"signing in to {name}: finish in the page it opens", lambda log: onboarding.sign_in(provider, ways[picked]["id"], log))
    except KeyboardInterrupt:
        return False
    except Exception as error:  # noqa: BLE001 - said, then the list again
        failed(error)
        return False
    say(("class:ok", "✓ "), f"Signed in to {name}")
    return True


def model_question(directory, entry: dict, name: str) -> dict:
    """Which of the source's models: asked of an agent, which offers a handful (a provider's
    model was named when its key was given). Enter keeps the one the agent is set to; another
    one is kept in its place. The entry in use after it."""
    if not providers.is_agent(entry["provider"]):
        return entry
    try:
        found = onboarding.offered(directory, entry["provider"])
    except Exception:  # noqa: BLE001 - the model it is set to stays
        return entry
    listed = found["models"]
    if len(listed) < 2:
        return entry
    at = next((index for index, row in enumerate(listed) if row["id"] == entry["model"]), 0)
    picked = select(f"Which model of {name}?", [f"{row['name']}\t{row.get('description') or row['id']}" for row in listed],
                    default=at, leave="Esc keeps the first choice", search=len(listed) > 9,
                    )
    if picked is None or picked == at:
        return entry
    choice = {"provider": entry["provider"], "model": listed[picked]["id"]}
    try:
        return wait(f"keeping {listed[picked]['name']}", lambda log: onboarding.choose(directory, choice, None, log))
    except (KeyboardInterrupt, Exception) as error:  # noqa: BLE001 - said; the first one stays
        if not isinstance(error, KeyboardInterrupt):
            failed(error)
        return entry


def preferences_step(directory) -> None:
    """First-run user preferences: daily limits, autonomous mode, and raw record retention.
    Pressing Enter keeps each unset / off so nothing is decided without asking."""
    from .. import settings

    if "agent" not in settings.SCHEMA:
        return
    changes = {}
    try:
        raw_budget = prompt("  Daily spending limit in US$ [Enter = no limit]: ").strip()
        if raw_budget:
            budget = float(raw_budget)
            if budget >= 0:
                changes["daily_budget"] = budget
                if budget > 0:
                    raw_reserve = prompt("  Reserved for you in US$ [Enter = none]: ").strip()
                    if raw_reserve:
                        reserve = float(raw_reserve)
                        if reserve >= 0:
                            changes["reserve"] = reserve
        raw_calls = prompt("  Daily unpriced calls limit [Enter = no limit]: ").strip()
        if raw_calls:
            calls = int(raw_calls)
            if calls >= 0:
                changes["daily_calls"] = calls
    except (ValueError, KeyboardInterrupt, EOFError):
        return
    picked = select("Acting on its own?",
                    ["Off\tonly when called", "Only to learn\tbackground learning only", "On\tscheduled & proactive tasks"],
                    default=0, leave="Esc for Off")
    if picked is not None and picked != 0:
        changes["proactive"] = ("off", "learn_only", "on")[picked]
    try:
        raw_keep = prompt("  Keep raw conversation records (days) [Enter = forever]: ").strip()
        if raw_keep:
            keep = int(raw_keep)
            if keep >= 0:
                changes["keep_days"] = keep
    except (ValueError, KeyboardInterrupt, EOFError):
        pass
    if changes:
        try:
            settings.Settings(directory).update({"agent": changes})
            summary = ", ".join(f"{k}={v}" for k, v in changes.items())
            say(("class:ok", "✓ "), f"Preferences saved ({summary})")
        except (OSError, ValueError) as error:
            failed(error)


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
                    ["Yes\tstarts when you sign in", "No\truns only while the-harness is open"],
                    default=1, leave="Esc for No")
    if picked == 0:
        try:
            login.install()
            say(("class:ok", "✓ "), "It starts when you sign in", ("class:dim", "  (the-harness host uninstall turns that off)"))
        except (OSError, RuntimeError, ValueError) as error:
            failed(error)
    else:
        say(("class:dim", "  Runs while the-harness is open"))


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
                        ["Yes", "Not now"],
                        leave="Esc for not now")
        if picked != 0:
            continue
        try:
            made = wait(f"bringing over the {name} agent", lambda log, kind=row["kind"]: bring(kind))
            say(("class:ok", "✓ "), f"It is the identity {made.get('id') or name.lower()}",
                ("class:dim", "  (the-harness agent list shows them; stop the one in " + name + " so that both do not answer)"))
        except KeyboardInterrupt:
            return
        except Exception as error:  # noqa: BLE001 - said; the first run goes on without it
            failed(error)


def run(directory, *, version: str = "", only_model: bool = False) -> bool:
    """Go through the first run in this terminal. Whether a model is in use at its end
    (False: the user left; nothing was changed)."""
    if not only_model:
        say(("class:title", f"The Harness {version}".rstrip()))
        say("")
    entry = model_step(directory)
    if entry is None:
        say(("class:dim", "Nothing was changed"))
        return False
    if only_model:
        return True
    bring_step()
    preferences_step(directory)
    background_step()
    onboarding.done(directory)
    say("")
    for line in onboarding.next_steps():
        say(("class:dim", line))
    say("")
    return True
