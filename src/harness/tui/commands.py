"""The terminal chat's own commands (terminal.COMMANDS without a method): do_<name> of the
chat, called with the words after the command. What each does follows the command of that
name in Claude Code (its commands page), or in Hermes for what Claude Code does not have
(its slash-commands page): /help, /clear, /resume, /model, /config, /status, /usage,
/context, /permissions, /memory, /skills, /copy, /export, /rename, /keybindings,
/terminal-setup, /login, /logout, /doctor, /exit as there; /queue, /bg, /stop, /update,
/version as in Hermes; /library, /calendar, /channels, /timeline are The Harness's own."""

import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from textwrap import wrap
import time

from prompt_toolkit.application import in_terminal
from rich.text import Text

from ..core import format as formats
from ..host.client import HostGone
from ..host.sessions import ENDED, LIVE, table_rows, word
from ..paths import data
from ..problems import Problem
from .. import spending
from harness.runtime.learning.active import progress_line
from ..terminal import COMMANDS
from . import agent as life
from . import calendar, connectors, control, keymap as keymaps, library, settings as tui_settings, terminal_setup, usage, views

DOCS = "https://harness.lmms-lab.com/docs/use/terminal/"
ABOUT = ("The Harness is an agent that lives on this computer: it works in your folders and apps with your "
         "approval, remembers what it learns, and goes on while this terminal is closed.")
FENCE = re.compile(r"^```([\w+-]*)[^\n]*\n(.*?)^```\s*$", re.S | re.M)


class Commands:
    def do_help(self, _):
        """/help: what it is and the shortcuts, the commands, the skills, as Claude Code's
        help has its tabs."""
        from .. import __version__

        columns = self.shortcuts()
        widths = [max(len(text) for text in column) + 3 for column in columns]
        keys_ = ["".join((column[index] if index < len(column) else "").ljust(width)
                         for column, width in zip(columns, widths)).rstrip()
                 for index in range(max(len(column) for column in columns))]
        room = max(self._columns() - 2, 40)

        def entry(usage, about):
            """A command and what it does: beside it when the command is short, else under it."""
            if len(usage) > 22:
                return [usage, *wrap(about, room, initial_indent=" " * 24, subsequent_indent=" " * 24)]
            return wrap(f"{usage:<24}{about}", room, subsequent_indent=" " * 24)

        listed = []
        for name, found in sorted((name, found) for name, found in COMMANDS.items() if not found.hidden
                                  and self.available(name) is None):
            other = f" (also {', '.join('/' + alias for alias in found.aliases)})" if found.aliases else ""
            listed += entry(f"/{name} {found.words}".strip(), found.note + other)
        skills = [line for name, about in self.skills for line in entry(f"/{name}", about)] or \
            wrap("No skills yet. What it learns to do becomes a skill, and each skill is a command: /name", room)
        tabs = [("general", [*wrap(ABOUT, room), "", "Shortcuts", *keys_, "", f"For more help: {DOCS}"]),
                ("commands", ["Browse the commands:", "", *listed]),
                ("skills", ["Skills are called by their name:", "", *skills])]
        self.app.create_background_task(self._guarded(lambda: self._view(views.tabs(f"The Harness v{__version__}", tabs))))

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
        """/config (/settings): the settings; /config section.key=value sets one, and for a
        conversation of an external agent, option=value one of the options it advertises."""
        words = words.strip()
        if not words:
            self._settings()
            return
        from ..settings import SCHEMA, Settings

        pairs = [pair.partition("=") for pair in words.split()] if "=" in words else [words.partition(" ")]
        for name, _, value in pairs:
            section, _, key = name.partition(".")
            if section in SCHEMA and key in SCHEMA[section]:
                kind = SCHEMA[section][key].kind
                try:
                    given = {"bool": lambda: value.lower() in ("true", "on", "yes", "1"), "int": lambda: int(value),
                             "float": lambda: float(value)}.get(kind, lambda: value)()
                    Settings(data()).update({section: {key: given}})
                except (OSError, ValueError) as error:
                    self.problem(error)
                    continue
                self.note(f"set {name} = {value}")
            elif self.conversation is not None and hasattr(self.conversation, "set_config"):
                self._background(self.conversation.set_config, name, value)
            else:
                self.note(f"No setting {name}: /config lists them", "red")
        self._read_settings()

    def _settings(self, pages=None, title="Settings"):
        """The settings by their names and pages (tui/settings.py), for this computer and for
        the identity the chat runs as."""
        async def edit():
            client = life.Client(self.host, self.identity["id"]) if self._agent_mode() and self.host is not None else None
            for line in await self._view(tui_settings.config_view(data(), client, pages=pages, title=title)):
                self.note(f"set {line}")
            self._read_settings()

        self.app.create_background_task(self._guarded(edit))

    def do_permissions(self, _):
        """/permissions: what waits for your approval and what is allowed (the settings of the
        page "Permissions and limits": approvals.*, each package's rules, the limits)."""
        self._settings(pages=("Permissions and limits",), title="Permissions")

    def do_agent(self, _):
        """/agent (/profile): the identities: use, new, rename, delete; the one made current
        opens here."""
        async def manage():
            host = await self._request(self._host)
            picked = await self._view(tui_settings.identities_view(host, (self.identity or {}).get("id")))
            if picked is not None and picked["id"] != (self.identity or {}).get("id"):
                self.identity = picked
                self._print(Text(f"── {picked['name']} " + "─" * 40, style="dim"))
                self._follow(life.AgentChat(host, picked))
                self._background(self._load_skills)

        self.app.create_background_task(self._guarded(manage))

    def _connectors(self, group):
        async def show():
            host = await self._request(self._host)
            client = life.Client(host, self.identity["id"]) if getattr(self, "identity", None) else None
            await self._view(connectors.connectors_view(host, client, self.note, group))
            self._background(self._load_skills)

        self.app.create_background_task(self._guarded(show))

    def do_channels(self, _):
        """/channels (/platforms): the identity's accounts in the channels its packages declare."""
        self._connectors("channels")

    def do_mcp(self, _):
        """/mcp: the MCP servers: list, add, test, turn off, remove."""
        self._connectors("mcp")

    def do_acp(self, _):
        """/acp: the external agents (ACP): found here, from the registry, or a command of yours."""
        self._connectors("acp")

    def do_diff(self, _):
        if self.conversation is None or not hasattr(self.conversation, "diff"):
            self.note("/diff shows the changes of a coding session: none is open here", "red")
            return

        def show():
            result = self.conversation.diff()
            text = "\n".join([result["patch"], *(f"Untracked: {path}" for path in result["untracked"])])
            self._later(self._print, Text(text or "No changes"))

        self._background(show)

    def do_merge(self, _):
        if self.conversation is None or not hasattr(self.conversation, "merge"):
            self.note("/merge takes a closed coding session's work: none is open here", "red")
            return
        self._background(self.conversation.merge)

    def do_handoff(self, words):
        if self.conversation is None or not hasattr(self.conversation, "handoff"):
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

    def do_clear(self, words):
        """/clear [name] (/reset, /new): a new conversation with nothing of this one, which
        goes on and is called `name` from then on (Claude Code's /clear)."""
        name = words.strip()
        if isinstance(self.conversation, life.AgentChat):
            # "New chat": a chat of the identity for one piece of work, kept in its list.
            conversation = self.conversation

            def new():
                if name:
                    self._controlled(lambda: control.chat_change(conversation.client, "rename", conversation.chat, name))
                chat = conversation.client.post("new_chat", {"title": "New chat"})["chat"]
                self._later(self._switch, conversation.host, chat, "New chat")

            self._background(new)
            return
        if name:
            self.note("A name is kept for an identity's chats; this conversation is found by its first message")
        self._leave()
        self._print(Text("── new conversation " + "─" * 40, style="dim"))
        self._open_environment()

    def do_project(self, words):
        """/project [FOLDER] (/where): where this chat works, as a session of Claude Code is
        opened on the folder it was started in. With a folder (. is this terminal's): the
        chat works in that project (connected when it was not). Without one, pick: wherever
        it decides, a project, a git project's isolated copy (a worktree on the chat's own
        branch), this terminal's folder, or another folder. A chat you started keeps its
        place; from the main conversation a new chat is opened on the project."""
        conversation = self.conversation
        if not isinstance(conversation, life.AgentChat):
            self.note("A place is kept for an identity's chats: harness --identity ID", "yellow")
            return
        given = str(words or "").strip().strip('"')

        async def choose():
            client = conversation.client
            folder, place, isolation = (os.path.abspath(os.path.expanduser(given)) if given else None), None, None
            if folder is None:
                found = (await self._request(client.get, "places"))["places"]
                projects = [row for row in found if row["kind"] == "folder"]
                here = os.getcwd()
                rows, picks = ["It decides"], [(None, None, None)]
                for row in projects:
                    rows.append(f"{row.get('title') or row['id']}  ·  {row.get('folder')}")
                    picks.append((None, row["id"], None))
                    if row.get("git"):
                        rows.append(f"{row.get('title') or row['id']} · isolated copy")
                        picks.append((None, row["id"], "worktree"))
                for row in found:
                    if row["kind"] in ("browser", "desktop"):
                        rows.append(f"{row.get('title') or row['id']}  ·  {row['kind']}")
                        picks.append((None, row["id"], None))
                if not any(os.path.normcase(str(row.get("folder"))) == os.path.normcase(here) for row in projects):
                    rows.append(f"This terminal's folder  ·  {here}")
                    picks.append((here, None, None))
                rows.append("Another folder…")
                picks.append(("", None, None))
                # the list opens on where the chat works now
                now = next((row for row in (await self._request(client.get, "chats"))["chats"]
                            if row["chat"] == conversation.chat), {})
                at = next((index for index, pick in enumerate(picks)
                           if pick[1] and pick[1] == now.get("place") and pick[2] == now.get("isolation")), 0)
                picked = await self._view(views.choose("Where this chat works", rows, current=at,
                                                       hint="↑↓ move · Enter choose · type filter · Esc back"))
                if picked is None:
                    return
                folder, place, isolation = picks[picked]
                if folder == "":
                    typed = await self._view(views.ask("The project's folder", default=here, hint="Enter open it · Esc cancel"))
                    if not typed or not typed.strip():
                        return
                    folder = os.path.abspath(os.path.expanduser(typed.strip().strip('"')))
            if folder:
                place = (await self._request(client.post, "places", {"action": "project", "folder": folder}))["place"]
            rows = (await self._request(client.get, "chats"))["chats"]
            mine = next((row for row in rows if row["chat"] == conversation.chat), {})
            where = f"{place}" + (" (an isolated copy)" if isolation else "") if place else "nowhere in particular: it decides per task"
            if mine.get("kind") == "new":
                await self._request(client.post, "chats", {"action": "place", "chat": conversation.chat, "place": place,
                                                           "isolation": isolation})
                self.note(f"This chat works in {where}")
            elif place:
                # the main conversation is tied to no place: a chat of its own is opened on the project
                chat = (await self._request(client.post, "new_chat", {"title": "New chat", "place": place,
                                                                      **({"isolation": isolation} if isolation else {})}))["chat"]
                self._switch(conversation.host, chat, f"New chat · {where}")
            else:
                self.note("The main conversation is tied to no place already: it decides per task")

        self.app.create_background_task(self._guarded(choose))

    def do_rename(self, words):
        """/rename [NAME]: what this conversation is called (an identity's chat); without a
        name, one made from what it began with (Claude Code's /rename)."""
        name = " ".join(words.split())[:200]
        conversation = self.conversation
        if not isinstance(conversation, life.AgentChat):
            self.note("A name is kept for an identity's chats: harness --identity ID", "yellow")
            return
        if not name:
            first = next((str(record.get("text") or "") for record in self.seen if record.get("event") == "user"), "")
            name = formats.clip(" ".join(first.split()), 48)
            if not name:
                self.note("Nothing was said here yet to name it by: /rename <name>", "yellow")
                return

        def rename():
            control.chat_change(conversation.client, "rename", conversation.chat, name)
            conversation.title = name
            self.note(f"This conversation is now called {name}")

        self._background(self._controlled, rename)

    def do_agents(self, words):
        """/agents: the sub-agents of this conversation: open one, stop one; /agents on lets it
        start them, for this conversation or (before one starts) the next."""
        if words.strip() == "on":
            if self.conversation is not None and self.status not in ENDED and hasattr(self.conversation, "enable_agents"):
                def switch():
                    self.conversation.enable_agents()
                    self.note("Sub-agents are on for this conversation")

                self._background(switch)
            else:
                self.agents_on = True
                self.note("Sub-agents are on for the next conversation (session.agents in /config keeps them on)")
            return
        run = getattr(self.conversation, "run", None)
        if run is None:
            self.note("Sub-agents belong to a conversation of the app's agent; none is open here. /agents on lets the "
                      "next one start them.")
            return

        async def manage():
            host = await self._request(self._host)
            while True:
                sessions = [session.row for session in await self._request(host.sessions)]
                mine = [session for session in sessions if any(agent["run"] == run for agent in session.get("agents") or ())]
                agents = [line for line in table_rows(mine) if line["agent"].strip() != line["agent"]]
                rows = [f"{line['agent'].strip():<14} {line['status']:<24} {line['spent']:<12} {line['title']}" for line in agents]
                picked = await self._view(views.browse(
                    "Sub-agents of this conversation", rows, keys=["x"],
                    hint="↑ ↓ move · Enter open its conversation · x stop it · esc back",
                    empty="No sub-agent runs. Ask it to hand a part of the work to one (/agents on allows it)."))
                if picked is None:
                    return
                key, index = picked
                if index is None:
                    continue
                line = agents[index]
                if key == "enter":
                    self._print(Text(f"── sub-agent {line['agent_id']} " + "─" * 40, style="dim"))
                    self._follow(await self._request(host.conversation, line["run"]))
                    return
                if await self._view(views.confirm(f"Stop the sub-agent {line['agent_id']}?", yes="Yes, stop it")):
                    await self._request(host.stop_session, line["session_id"], line["agent_id"])

        self.app.create_background_task(self._guarded(manage))

    def do_exit(self, _):
        self.app.exit()

    def do_stop(self, _):
        """/stop: what Esc does."""
        if self.status == "RUNNING" and self.conversation is not None:
            self.interrupt()
        else:
            self.note("Nothing runs: a message starts its next turn")

    def do_queue(self, words):
        """/queue TEXT: a message for its next turn (Hermes's /queue); /queue lists what waits,
        /queue edit N TEXT, /queue rm N and /queue clear change it."""
        conversation = self.conversation
        first, _, rest = words.strip().partition(" ")
        if not isinstance(conversation, life.AgentChat):
            if words.strip() and first not in ("list", "edit", "rm", "clear"):
                self.send(words.strip())
            else:
                self.note("Messages are queued in an identity's chat: harness --identity ID", "yellow")
            return
        client, chat = conversation.client, conversation.chat

        def listed(queue):
            rows = queue["queued"]
            if not rows:
                self.note("Nothing is queued")
            for number, row in enumerate(rows, 1):
                self.note(f"  {number}. {formats.clip(row['text'].splitlines()[0] if row['text'] else '', 100)}")

        def row_of(number):
            rows = control.queue(client, chat)["queued"]
            if not number.isdigit() or not 1 <= int(number) <= len(rows):
                raise Problem(f"no queued message {number}", "/queue lists them with their numbers")
            return rows[int(number) - 1]

        if first in ("", "list"):
            call = lambda: listed(control.queue(client, chat))  # noqa: E731
        elif first == "clear":
            call = lambda: listed(control.change(client, chat, "clear"))  # noqa: E731
        elif first == "rm":
            call = lambda: listed(control.change(client, chat, "remove", id=row_of(rest.strip())["id"]))  # noqa: E731
        elif first == "edit":
            number, _, text = rest.strip().partition(" ")
            call = lambda: listed(control.change(client, chat, "edit", id=row_of(number)["id"], text=text))  # noqa: E731
        else:
            call = lambda: conversation.say(words.strip())  # noqa: E731

        def run():
            call()
            conversation.nudge()

        self._background(self._controlled, run)

    def do_bg(self, words):
        """/bg PROMPT: a chat of its own for the prompt (Hermes's /bg); this chat stays free,
        and what comes of it is told here in a line."""
        prompt = words.strip()
        conversation = self.conversation
        if not prompt:
            self.note("Usage: /bg <prompt>", "red")
        elif not isinstance(conversation, life.AgentChat):
            self.note("/bg starts a chat of an identity: harness --identity ID", "yellow")
        else:
            def start():
                title = formats.clip(prompt.splitlines()[0], 40)
                chat = conversation.client.post("new_chat", {"title": title})["chat"]
                conversation.client.post("say", {"chat": chat, "text": prompt})
                self.note(f"— {title}: started in the background · /sessions opens it")

            self._background(start)

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
            self.do_clear("")
        self.send(words.strip() or "Get to know this environment for the tasks I give you.", learn=minutes)

    def do_timeline(self, _):
        self.app.create_background_task(self._view(views.timeline_view(self.lanes)))

    def do_transcript(self, _):
        """/transcript, Ctrl+O: every step of the conversation in detail."""
        if self.__dict__.get("transcript_open"):
            return
        self.transcript_open = True
        state = {"all": False}

        async def show():
            try:
                await self._view(views.read("Transcript", lambda: self.transcript_text(state["all"]),
                                            keymap=self.keymap, live=True, end=True,
                                            toggle=lambda: state.update(all=not state["all"]),
                                            close=("app:toggleTranscript",)))
            finally:
                self.transcript_open = False

        self.app.create_background_task(self._guarded(show))

    def do_status(self, words):
        """/status (/host): the version, the model, the identity, the session host and whether
        it and the model's provider answer; /status stop ends the session host."""
        async def show():
            if str(words or "").strip() == "stop":
                await asyncio.to_thread(self._host_stop)
                return
            for line in await self._request(self._status_lines):
                self.note(line, "" if line[:1] != " " else "dim")

        self.app.create_background_task(self._guarded(show))

    def _status_lines(self) -> list:
        """What /status says: a name and its value on each line, the host's own lines under it."""
        from .. import __version__
        from ..cli import host_lines
        from ..providers import PROVIDERS, load, reach
        from ..settings import Credentials
        from .chat import LEVELS

        identity = getattr(self, "identity", None)
        who = "none (the agent package adds identities)" if not identity else \
            identity["name"] if identity["name"] == identity["id"] else f"{identity['name']} ({identity['id']})"
        lines = [f"The Harness {__version__}", f"  Identity      {who}", f"  Model         {self.model or 'none: /login'}",
                 f"  Directory     {os.getcwd()}",
                 f"  Approvals     {dict(LEVELS).get(self.level, self.level)} (/permissions)"]
        try:
            chosen = load(data())
            provider = PROVIDERS.get(chosen["provider"])
            if provider is None:
                lines.append(f"  Provider      {chosen['provider']}: an agent signed in on this computer answers as the model")
            else:
                Credentials(data()).load()
                found = reach(chosen, os.environ.get(provider.key_env) if provider.key_env else None, timeout=10)
                lines.append(f"  Provider      {provider.name} " + (
                    "answers" + (f" · {found['detail']}" if found.get("detail") else "") if found["ok"]
                    else f"does not answer: {found.get('detail')} (/login chooses another)"))
        except Exception as error:  # noqa: BLE001 - said in its line; the rest of the status still shows
            lines.append(f"  Provider      {error}")
        began = time.monotonic()
        try:
            host = self._host(start=False)
            rows = host_lines(host) if host is not None else None
        except (HostGone, OSError) as error:
            self.host = None
            lines.append(f"  Session host  does not answer: {error}")
            return lines
        if rows is None:
            lines.append("  Session host  not running (the next message starts it)")
        else:
            lines.append(f"  Session host  answers in {round((time.monotonic() - began) * 1000)} ms · /status stop ends it")
            lines += ["    " + row.strip() for row in rows]
            lines += [f"    left out: {text}" for text in ((getattr(host, "state", None) or {}).get("problems") or {}).values()]
        return lines

    def _host_stop(self):
        host = self._host(start=False)
        if host is None:
            self.note("No session host runs (the next conversation starts it)")
            return
        self._later(self._leave)
        host.stop(force=True)
        self.host = None
        self.note(f"Stopped the session host at {host.url}")

    def do_doctor(self, _):
        """/doctor: harness doctor, here."""
        async def check():
            done = await self._request(lambda: subprocess.run(
                [sys.executable, "-m", "harness", "doctor"], capture_output=True, encoding="utf-8", errors="replace",
                stdin=subprocess.DEVNULL, timeout=300))
            text = (done.stdout + done.stderr).strip() or "harness doctor said nothing"
            self._print(Text(text), Text("" if done.returncode == 0 else f"(harness doctor ended with {done.returncode})",
                                         style="dim"))

        self.app.create_background_task(self._guarded(check))

    def do_update(self, _):
        """/update: whether a newer version is out and how to get it (a running chat does not
        replace the code it runs on)."""
        from .. import update

        def check():
            found = update.latest(refresh=True)
            now, latest = update.current(), found.get("version")
            if found.get("error") and not latest:
                self.problem(Problem(f"could not ask for the newest version ({found['error']})",
                                     "check the network, then /update again"))
            elif latest and update.newer(latest, now):
                how = "the desktop app updates itself: Settings > About > Check for updates" if update.bundled() \
                    else "leave the chat (/exit) and run: harness update"
                self.note(f"The Harness {latest} is available (this is {now}); {how}")
            else:
                self.note(f"The Harness {now} is the newest version")

        self._background(check)

    def do_version(self, _):
        import platform

        from .. import __version__

        self.note(f"The Harness {__version__} · Python {platform.python_version()} · {platform.system()} "
                  f"{platform.release()} · {Path(__file__).resolve().parents[1]}")

    def do_login(self, _):
        """/login: add a source of models, as the first run's first step does (an agent signed
        in here, a provider's key, a local model): tried once, then kept and in use."""
        async def add():
            from .first import model_step

            self._report_keys(False)
            try:
                async with in_terminal():
                    entry = await asyncio.to_thread(model_step, data())
            finally:
                self._report_keys(True)
            if entry is not None:
                self.model_entry = self.model_effort = None
                self._refresh_next_model()
                self.note(f"The model in use is now {self.model}")

        self.app.create_background_task(self._guarded(add))

    def do_logout(self, _):
        """/logout: remove a source of models: its models leave the list and its key leaves
        the credentials file."""
        async def remove():
            from ..model_list import models
            from ..providers import PROVIDERS
            from ..settings import Credentials

            rows = models(data())
            names = list(dict.fromkeys(row["provider"] for row in rows))
            if not names:
                self.note("No source of models to remove: /login adds one")
                return
            credentials = Credentials(data())
            credentials.load()

            def label(name):
                count = sum(row["provider"] == name for row in rows)
                provider = PROVIDERS.get(name)
                source = credentials.sources.get(provider.key_env) if provider is not None and provider.key_env else None
                key = "" if source is None else " · key from the environment" if source == "environment" else " · key kept here"
                return f"{provider.name if provider else name}  ·  {count} model{'' if count == 1 else 's'}{key}"

            picked = await self._view(views.choose("Remove which source of models?", [label(name) for name in names],
                                                   hint="Enter remove · Esc keep them all"))
            if picked is None:
                return
            name = names[picked]
            provider = PROVIDERS.get(name)
            for row in [row for row in rows if row["provider"] == name]:
                models(data(), {"action": "remove", "id": row["id"]})
            if provider is not None and provider.key_env:
                if credentials.sources.get(provider.key_env) == "environment":
                    self.note(f"Its key comes from the environment variable {provider.key_env}: unset it in your "
                              "shell to stop using it", "yellow")
                else:
                    credentials.keep(provider.key_env, None)
                    os.environ.pop(provider.key_env, None)
            self.model_entry = self.model_effort = None
            self._refresh_next_model()
            self.note(f"Removed {provider.name if provider else name}" + (
                "" if models(data()) else ". No model is left: /login adds one"))

        self.app.create_background_task(self._guarded(remove))

    def do_keybindings(self, _):
        """/keybindings: your keyboard shortcuts file in your editor (made with the defaults
        when there is none); what it says applies once it is saved."""
        async def edit():
            path = keymaps.path(data())
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(keymaps.template(), encoding="utf-8", newline="\n")
            await self._edit(path)
            self.stamps = (keymaps.stamp(data()), self.stamps[1])
            self.reload_keys()
            if not self.keymap.problems:
                self.note(f"Keyboard shortcuts read from {path}")

        self.app.create_background_task(self._guarded(edit))

    def do_terminal_setup(self, _):
        self._print(*[Text(text, style=style) for text, style in terminal_setup.run()])

    def do_effort(self, words):
        """Choose an effort for the saved model or apply an explicit effort to an open conversation."""
        from ..model_list import select
        from harness.runtime.decision.model import valid_effort

        async def pick():
            conversation = self.conversation
            active = conversation is not None and self.status not in ENDED and hasattr(conversation, "set_model")
            level = str(words or "").strip()
            if active and not level:
                self.note("Use /effort LEVEL or /effort default for the open conversation.")
                return
            row = None if active else select(data(), self.model_entry)
            if not level:
                levels = [value for value in (row or {}).get("efforts", []) if value != "default"]
                if not levels:
                    self.note(f"{(row or {}).get('name') or 'This model'} has no effort levels to choose from")
                    return
                option = await self._view(views.choose(f"Reasoning effort of {row['name']}", ["The model's default", *levels]))
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
        if isinstance(self.conversation, life.AgentChat):
            conversation = self.conversation

            async def chats():
                listed = (await self._request(conversation.client.get, "chats"))["chats"]
                rows = [f"{row['title'][:30]:<30} {time.strftime('%H:%M', time.localtime(row.get('updated') or 0)):<6} "
                        + ("working" if row.get("busy") else f"waiting for {row['waiting']}" if row.get("waiting")
                           else f"{row['unread']} new" if row.get("unread") else "idle") for row in listed]
                current = next((index for index, row in enumerate(listed) if row["chat"] == conversation.chat), 0)
                picked = await self._view(views.choose(f"Chats of {self.identity['name']}", rows, current=current,
                                                       hint="↑↓ move · Enter switch · type filter · Esc back"))
                if picked is not None and listed[picked]["chat"] != conversation.chat:
                    self._switch(conversation.host, listed[picked]["chat"], listed[picked]["title"])

            self.app.create_background_task(self._guarded(chats))
            return

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

    def do_resume(self, words):
        """/resume [conversation] (/continue): go on with an earlier conversation: the one whose
        id or title is given, or one picked from the list (Claude Code's /resume)."""
        wanted = words.strip().lower()

        async def pick():
            if isinstance(self.conversation, life.AgentChat):
                conversation = self.conversation
                listed = (await self._request(conversation.client.get, "chats"))["chats"]
                found = [row for row in listed if wanted and (row["chat"].lower() == wanted
                                                                or wanted in str(row.get("title") or "").lower())]
                if wanted and len(found) == 1:
                    self._switch(conversation.host, found[0]["chat"], found[0]["title"])
                elif wanted and not found:
                    self.note(f"No conversation called {words.strip()!r}: /resume lists them", "red")
                else:
                    self.do_sessions("")
                return
            host = await self._request(self._host)
            sessions = [session.row for session in await self._request(host.sessions, all=True, limit=100)]
            if not sessions:
                self.note("No conversations yet")
                return
            found = [row for row in sessions if wanted and (str(row.get("id") or "").lower() == wanted
                                                             or wanted in str(row.get("title") or "").lower())]
            if wanted and not found:
                self.note(f"No conversation called {words.strip()!r}: /resume lists them", "red")
                return
            if wanted and len(found) == 1:
                row = found[0]
            else:
                shown = found if wanted else sessions
                rows = [f"{formats.timestamp(row.get('created'))}  {word(row.get('status')):<26} {row.get('title') or ''}"
                        for row in shown]
                picked = await self._view(views.choose("Resume a conversation", rows))
                if picked is None:
                    return
                row = shown[picked]
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

    def do_model(self, words):
        """/model [NAME]: the model named, at once; without a name, pick one (Claude Code's
        /model and Alt+P). Each row is a model with the source it comes from; under them, one
        row for each source opens every other model that source offers, then a row adds a
        source and the last one opens the model list to edit it."""
        name = str(words or "").strip()

        async def pick():
            from ..model_list import models, select
            from ..onboarding import model_name, source_name

            options = [row for row in models(data()) if row["enabled"]]
            if name:
                try:
                    self._use_model(select(data(), name), options)
                except ValueError:
                    # by the name it is listed under, as /model opus is said (the one model whose name is, or holds, it)
                    said = name.casefold()
                    named = [row for row in options if model_name(row).casefold() == said] or                         [row for row in options if said in model_name(row).casefold()]
                    if len(named) == 1:
                        self._use_model(named[0], options)
                    else:
                        self.problem(Problem(f"{'several enabled models are' if named else 'no enabled model is'} called {name}",
                                             "/model lists the models; /login adds a source of models"))
                return
            try:
                current = select(data(), self.model_entry) if any(
                    row["id"] == self.model_entry for row in options) else select(data())
            except ValueError:
                current = None  # an invalid default must not prevent choosing a valid route
            rows = [f"{model_name(row)}  ·  {source_name(row['provider'])}"
                    + (f"  ·  {', '.join(row['efforts'])}" if row.get("efforts") else "")
                    + (f"  ·  {row['base_url']}" if row["base_url"] else "") for row in options]
            sources = list(dict.fromkeys(row["provider"] for row in options))
            more = [f"More models of {source_name(provider)}…" for provider in sources]
            picked = await self._view(views.choose(
                "Select model", [*rows, *more, "Add a source of models: test it, then use it…",
                                 "Edit the model list…"],
                current=options.index(current) if current in options else 0,
                text="" if options else "No model yet: the row below adds a source.",
                hint="↑↓ move · Enter select · type filter · Esc close · /effort sets how hard it thinks"))
            if picked is None:
                return
            if picked < len(options):
                self._use_model(options[picked], options)
            elif picked < len(options) + len(sources):
                await self._more_models(sources[picked - len(options)])
            elif picked == len(options) + len(sources):
                await self._add_model()
            else:
                await self._edit_models()

        self.app.create_background_task(self._guarded(pick))

    async def _more_models(self, provider, keep=None):
        """Every model the source `provider` offers (an agent's are asked of it through ACP,
        a provider's are its catalog): the one picked is kept in the model list as its source
        describes it, with its effort levels, and used. `keep`: the entry to stay with when
        the list is left (after a source was just added)."""
        from ..model_list import models
        from ..onboarding import source_name
        from urllib.parse import quote

        host = await self._request(self._host)
        name = source_name(provider)

        async def flow():
            found = await views._load(f"Asking {name} for its models",
                                      lambda: host.get(f"/api/app/models/catalog?provider={quote(provider)}", timeout=120))
            listed = found.get("models") or []
            if not listed:
                await views.failed(f"{name} lists no models", Problem(str(found.get("error") or "it named none"),
                                                                      str(found.get("fix") or "")))
                return None
            at = next((index for index, row in enumerate(listed) if row["id"] in ((keep or {}).get("model"), found.get("current"))), 0)
            picked = await views.choose(f"Models of {name}", [f"{row.get('name') or row['id']}  ·  {row.get('description') or row['id']}"
                                                             for row in listed], current=at,
                                        hint="↑↓ move · Enter use it · type filter · Esc back")
            if picked is None:
                return None
            kept = await views._load(f"Keeping {listed[picked].get('name') or listed[picked]['id']}", lambda: host.post(
                "/api/app/models", {"action": "use", "provider": provider, "model": listed[picked]["id"]}, timeout=120))
            return kept.get("entry")

        entry = await self._view(flow())
        if entry:
            self._use_model(entry, [row for row in models(data()) if row["enabled"]])

    async def _add_model(self):
        """A model from what is on this computer (an agent signed in here, a key, a local
        model): tried with one call that keeps nothing (the host's model/test), and kept only
        when you say so after it answered (onboard)."""
        from ..providers import is_agent
        from .first import ADD_KEY, MORE, source_rows

        host = await self._request(self._host)

        async def flow():
            found = await views._load("Looking at what is on this computer", lambda: host.get("/api/app/found"))
            rows, choices, opens = source_rows(found)
            picked = await views.choose("Add a model from this computer", [row.replace("\t", "  ·  ") for row in rows],
                                        current=opens, hint="↑↓ move · Enter try it · Esc back")
            if picked is None:
                return
            choice = choices[picked]
            if choice == ADD_KEY:
                return ADD_KEY  # a key typed by hand: the first run's own questions
            if choice == MORE:
                # the rest of the ACP Registry: the one chosen has its adapter installed, then is tried
                listed = [row for row in (await views._load("Reading the ACP Registry", lambda: host.get(
                    "/api/app/acp?registry=1")))["agents"] if row["state"] == "available" and row.get("runs_here", True)
                          and row["id"] not in {agent["provider"] for agent in found["agents"]}]
                picked = await views.choose("Add an agent of the ACP Registry", [row["name"] for row in listed],
                                            hint="↑↓ move · Enter try it · type filter · Esc back")
                if picked is None:
                    return
                choice = {"provider": listed[picked]["id"], "name": listed[picked]["name"], "model": "default"}
            name = str(choice.get("name") or choice.get("provider"))
            body = {key: choice[key] for key in ("provider", "model", "base_url") if choice.get(key)}
            if is_agent(body.get("provider")):
                body["name"] = name
            if not body.get("model") and not is_agent(body.get("provider")):
                model = await views.ask(f"Which model of {name}", hint="Enter try it · Esc cancel")
                if not model or not model.strip():
                    return
                body["model"] = model.strip()
            tried = await views._load(f"Trying {name}", lambda: host.post("/api/app/model/test", body, timeout=300))
            while not tried.get("ok") and tried.get("sign_in"):
                # it is not signed in, and offers to be signed in to through it: one of its ways, then tried again
                ways = tried["sign_in"]
                picked = await views.choose(f"{name} is not signed in. Sign in to it here?",
                                            [f"{way['name']}  ·  {way.get('description') or way['id']}" for way in ways],
                                            text=str(tried.get("detail") or ""), hint="↑↓ move · Enter sign in · Esc back")
                if picked is None:
                    return
                done = await views._load(f"Signing in to {name}: finish in the page it opens", lambda: host.post(
                    "/api/app/acp", {"action": "sign_in", "id": body["provider"], "method": ways[picked]["id"]}, timeout=960))
                if done.get("error"):
                    await views.failed(f"{name} was not signed in to", Problem.of(done, str(done.get("error"))))
                    return
                tried = await views._load(f"Trying {name}", lambda: host.post("/api/app/model/test", body, timeout=300))
            if not tried.get("ok"):
                await views.failed(f"{name} did not answer; nothing was kept",
                                   Problem.of(tried, str(tried.get("detail") or "it did not answer")))
                return
            if not await views.confirm(f"{name} answered in {tried.get('seconds')} s. Use it as the model?",
                                       yes="Yes, use it", no="No, keep things as they are"):
                return
            kept = await views._load(f"Keeping {name}", lambda: host.post("/api/app/onboard", body, timeout=300))
            if not kept.get("ok"):
                await views.failed(f"{name} was not kept", Problem.of(kept, str(kept.get("detail") or "it did not answer")))
                return
            return kept

        done = await self._view(flow())
        if done == ADD_KEY:
            self.do_login("")
        if not isinstance(done, dict):
            return
        self.model_entry = self.model_effort = None
        self._refresh_next_model()
        self.note(f"The model in use is now {self.model}")
        if is_agent(done.get("provider")):
            # a source that offers several models: which one, the one it is set to marked
            await self._more_models(done["provider"], keep=done)

    def _use_model(self, row, rows=None):
        """Make `row` (of the model list) the model: the identity's from its next turn, an open
        conversation's from its next call where it can change, and every new conversation's."""
        from ..onboarding import model_name, source_name
        from ..providers import save

        # the model by its own name, and where it comes from: "Opus 5.5 (Claude Code)"
        name = model_name(row)
        named = f"{name} ({source_name(row['provider'])})"
        conversation = self.conversation
        self.model_entry, self.model_effort = row["id"], None
        self._refresh_next_model(rows=rows)
        if isinstance(conversation, life.AgentChat) or conversation is None and self._agent_mode():
            # The identity thinks with the model in use: this makes it that one.
            save(data(), {"provider": row["provider"], "model": row["model"], "base_url": row.get("base_url")})
            self.model = name
            self.note(f"Model: {named}")
        elif conversation is not None and self.status not in ENDED and hasattr(conversation, "set_model"):
            def switch():
                try:
                    conversation.set_model(model=row["model"])
                except Exception as error:  # noqa: BLE001 - said; the choice still holds for the next one
                    self.note(f"This conversation keeps its model ({error}); new conversations use {named}", "yellow")
                else:
                    self._later(setattr, self, "model", name)
                    self.note(f"Model: {named} from its next call")

            self._background(switch)
        else:
            self.note(f"Model for new conversations: {named}")

    def do_memory(self, words):
        """/memory [N] (/instructions): the instruction files, each opened in your editor, and
        what it remembers (the library's memory)."""
        files = list(getattr(self, "instruction_files", None) or [])
        for label, path in (("yours", data() / "AGENTS.md"), ("this folder", Path.cwd() / "AGENTS.md")):
            if str(path) not in [found for _, found in files]:
                files.append((label + ("" if Path(path).exists() else " (not written yet)"), str(path)))
        if words.strip().isdigit() and 1 <= int(words) <= len(files):
            path = files[int(words) - 1][1]
            self.app.create_background_task(self._guarded(lambda: self._edit(path)))
            return

        async def pick():
            rows = [f"{label:<28} {path}" for label, path in files] + ["What it remembers (the library's memory)"]
            picked = await self._view(views.choose(
                "Memory", rows, text="The instruction files a new conversation reads, and what it has learned to remember.",
                hint="↑↓ move · Enter open in your editor · Esc close"))
            if picked is None:
                return
            if picked == len(files):
                self._library("memory")
            else:
                await self._edit(files[picked][1])
                self.note("A new conversation reads the instruction files again.")

        self.app.create_background_task(self._guarded(pick))

    def do_skills(self, words):
        """/skills: the skills it has (the library's skills); each is a command, /name.
        /skills sources: where skills come from besides what it learned."""
        if words.strip() == "sources":
            self._connectors("skills")
            return
        if self._agent_mode():
            self._library("skills")
            return

        async def show():
            await self._request(self._load_skills)
            rows = [f"/{name:<24} {about}" for name, about in self.skills]
            await self._view(views.choose("Skills", rows, empty="No skills yet.",
                                          hint="type to filter · Esc close · each skill is a command: /name"))

        self.app.create_background_task(self._guarded(show))

    def _load_skills(self):
        """The skills callable as /name: the identity's, or the ones this host loads."""
        try:
            if self._agent_mode():
                client = life.Client(self._host(), self.identity["id"])
                found = [(row["name"], formats.clip(str(row.get("description") or "a skill it learned"), 80))
                         for row in client.get("learned").get("skills") or () if row.get("evidence") != "undone"]
            else:
                host = self._host(start=False)
                rows = host.get("/api/app/skills").get("skills") or () if host is not None else ()
                found = [(row["name"], formats.clip(str(row.get("summary") or ""), 80)) for row in rows if row.get("on")]
        except Exception:  # noqa: BLE001 - the list of commands goes on without them
            return
        self.skills = [(name, about) for name, about in found if re.fullmatch(r"[\w][\w:-]*", name)]

    def do_packages(self, _):
        async def edit():
            for line in await self._view(views.packages_view(await self._request(self._host))):
                self.note(line)

        self.app.create_background_task(self._guarded(edit))

    def do_usage(self, words):
        """/usage [week | month] (/cost, /stats): what the identity spent (tui/usage.py);
        /usage raise DOLLARS raises today's limit."""
        identity = getattr(self, "identity", None)
        first, _, rest = words.strip().partition(" ")
        if first not in ("", "today", "week", "month", "raise"):
            self.note("Use /usage, /usage week, /usage month or /usage raise DOLLARS", "red")
            return
        if isinstance(self.conversation, life.AgentChat) and first != "raise":
            async def show():
                client = await self._request(self._client)
                await self._view(usage.usage_view(client, self.note, first or "today"))

            self.app.create_background_task(self._guarded(show))
            return
        if not identity or not identity.get("account"):
            self.note("Spending is kept per agent identity: harness --identity ID (the agent package)", "yellow")
            return
        account = spending.Account(identity["account"])
        if first == "raise":
            try:
                account.raise_today(float(rest))
            except ValueError as error:
                self.note(f"/usage raise DOLLARS: {error}", "red")
                return
            self._spent_kept = None
        self._print(*[Text(line, style="bold" if index == 0 else "") for index, line in
                      enumerate(spending.report(account, week=first == "week"))])

    def do_compact(self, words):
        """/compact [instructions]: make the earlier part of the conversation a summary now, to
        free context; the instructions say what the summary must keep (Claude Code's /compact)."""
        conversation = self.conversation
        if not isinstance(conversation, life.AgentChat):
            self.note("/compact is for an identity's chat: a conversation of the app's agent summarizes itself "
                      "when it grows long", "yellow")
            return

        def compact():
            done = control.compact(conversation.client, conversation.chat, words.strip())
            conversation.nudge()
            if not done["compacted"]:
                self.note("Nothing to compact yet: the conversation is short")

        self.note("Compacting the conversation…")
        self._background(self._controlled, compact)

    def do_context(self, _):
        """/context: how much of the model's context the conversation used at its last call,
        and whether its earlier part is a summary."""
        context = self.context
        if not context:
            self.note("Context use is known once the model has answered in an identity's chat")
            return
        compacted = sum(1 for record in self.seen if record.get("event") == "compacted")
        tokens, window = context["tokens"], context.get("window")
        lines = [Text(f"Context · {self.model or 'model'}", style="bold")]
        if window:
            share = min(1.0, tokens / window)
            filled = round(30 * share)
            lines.append(Text(f"  {'█' * filled}{'░' * (30 - filled)}  {tokens:,} of {window:,} tokens ({share:.0%})"))
        else:
            lines.append(Text(f"  {tokens:,} tokens at the model's last call (its window is not reported)"))
        if context.get("messages") is not None:
            lines.append(Text(f"  {context['messages']} messages carried" + (", the earlier part as a summary"
                                                                              if context.get("summarized") else "")
                              + " · /compact makes room", style="dim"))
        elif compacted:
            lines.append(Text(f"  the earlier part of the conversation was summarized {compacted} "
                              f"time{'' if compacted == 1 else 's'} to make room", style="dim"))
        self._print(*lines)

    def do_copy(self, words):
        """/copy [N]: the last response (the Nth latest) to the clipboard; when it has code
        blocks, pick the whole response or one block (Claude Code's /copy)."""
        number = int(words) if words.strip().isdigit() and int(words) > 0 else 1
        if number > len(self.answers):
            self.note("Nothing to copy yet" if not self.answers else f"There are only {len(self.answers)} responses",
                      "yellow")
            return
        text = self.answers[-number]

        async def copy():
            from . import clipboard

            chosen = text
            blocks = FENCE.findall(text)
            if blocks:
                rows = ["The whole response"] + [
                    f"Code block {index} · {language or 'text'} · {code.count(chr(10)) or 1} lines"
                    for index, (language, code) in enumerate(blocks, 1)]
                picked = await self._view(views.choose("Copy", rows, hint="↑↓ move · Enter copy · Esc cancel"))
                if picked is None:
                    return
                chosen = text if picked == 0 else blocks[picked - 1][1]
            output = self.app.output
            how = await asyncio.to_thread(clipboard.copy, chosen, lambda sequence: (output.write_raw(sequence),
                                                                                    output.flush()))
            self.note(f"Copied {len(chosen):,} characters to the clipboard"
                      + (" (through the terminal)" if how == "terminal" else ""))

        self.app.create_background_task(self._guarded(copy))

    def _plain(self) -> str:
        """The conversation as plain text (/export)."""
        conversation = self.conversation
        if isinstance(conversation, life.AgentChat):
            records = conversation.client.get("chat", chat=conversation.chat, after=0)["records"]
            out = []
            for record in records:
                for line in life.lines(record):
                    out.append(line[1] if line[0] == "answer" else line[0])
                    if line[0] == "answer":
                        out.append("")
            return "\n".join(out).rstrip() + "\n"
        import io

        from rich.console import Console

        stream = io.StringIO()
        console = Console(file=stream, force_terminal=False, color_system=None, width=100, highlight=False)
        for renderable in self.printed:
            console.print(renderable)
        return stream.getvalue()

    def do_export(self, words):
        """/export [FILE]: the conversation as plain text, written to FILE (never over a file
        that exists), or copied or saved from a choice (Claude Code's /export)."""
        name = words.strip().strip('"')

        async def export():
            from . import clipboard

            text = await self._request(self._plain)
            target = name
            if not target:
                picked = await self._view(views.choose("Export the conversation", ["Copy to the clipboard", "Save to a file"],
                                                       hint="↑↓ move · Enter choose · Esc cancel"))
                if picked is None:
                    return
                if picked == 0:
                    output = self.app.output
                    await asyncio.to_thread(clipboard.copy, text, lambda sequence: (output.write_raw(sequence),
                                                                                    output.flush()))
                    self.note("Conversation copied to the clipboard")
                    return
                target = await self._view(views.ask("Save the conversation as", time.strftime("conversation-%Y%m%d-%H%M%S.txt"),
                                                    hint="Enter save · Esc cancel"))
                if not target:
                    return
            path = Path(target).expanduser()
            path = path if path.suffix else path.with_suffix(".txt")
            if path.exists():
                raise Problem(f"{path} exists already", "give /export another file name")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            self.note(f"Conversation exported to {path.resolve()}")

        self.app.create_background_task(self._guarded(export))

    def do_init(self, _):
        """Have the agent write the project's AGENTS.md (Claude Code's and Codex's /init)."""
        self.send("Write an AGENTS.md at the root of this project for the agents that work in it: how to set it "
                  "up, build, test and lint it, how the code is laid out, its conventions, and what to check "
                  "before a change is done. Read the project first, and keep it short and specific to it. If an "
                  "AGENTS.md or a CLAUDE.md is there already, do not replace it: tell me what you would change "
                  "and why, and change it only when I agree.")

    async def _edit_models(self):
        """The model list in the user's editor; one saved with a mistake opens again as it is."""
        from ..model_list import models

        path = data() / "models.json"
        try:
            models(data())  # writes the list when there is none yet
        except ValueError:
            pass  # one saved with a mistake opens as it is, to be put right
        await self._edit(path)
        try:
            rows = models(data())
        except ValueError as error:
            raise ValueError(f"{error}; /model opens the list again to correct it") from None
        if not self._refresh_next_model(rows=rows):
            self.note(self.next_model_problem, "yellow")
        count = sum(row["enabled"] for row in rows)
        self.note(f"{count} enabled models · /model to select · {path}")

    def do_calendar(self, _):
        """/calendar: the identity's calendar by day, week and month (tui/calendar.py)."""
        async def show():
            client = await self._request(self._client)
            if client is not None:
                await self._view(calendar.calendar_view(client, self.note))

        self.app.create_background_task(self._guarded(show))

    def do_library(self, _):
        self._library()

    def _library(self, group=None):
        """/library, and /skills and /memory on their group of it."""
        from harness.core.memory import rows

        conversation = self.conversation
        # A session's conversation says (RemoteConversation.memory); one in this process, its trace.
        memory = getattr(conversation, "memory", None) or (
            (lambda: rows(run=conversation.directory)) if getattr(conversation, "directory", None) else None)
        if self._agent_mode():
            # The identity's three groups (skills, the tree of reactions, memory), then the libraries.
            async def show():
                client = await self._request(self._client)
                await self._view(library.library_view(client, self.note, libraries=lambda: views.library_view(memory),
                                                      group=group))
                self._background(self._load_skills)

            self.app.create_background_task(self._guarded(show))
            return
        self.app.create_background_task(self._guarded(lambda: self._view(views.library_view(memory))))

    def do_environment(self, _):
        """/environment: where this conversation works, and the choice for the next one."""
        async def pick():
            offered = await asyncio.to_thread(lambda: self._host().get("/api/app/environments"))
            now = f"This conversation works in: {self.workspace}. " if self.conversation is not None and self.workspace \
                else ""
            place = await self._choose_environment({
                "title": now + "Where should the next conversation work?", "selected": offered.get("selected"),
                "folder": offered.get("folder"),
                "options": [{**row, "name": row["label"]} for row in offered["options"]]})
            if place is not None:
                self.environment = place
                self.note(f"The next conversation works in {place[0]}" + (f" ({place[1]})" if place[1] else "")
                          + ("; /clear starts it" if self.conversation is not None else ""))

        self.app.create_background_task(self._guarded(pick))
