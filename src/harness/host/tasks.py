"""Host bounded natural-language tasks for CLI, Python and package frontends.

The host owns execution configuration, workers, run records and resource cleanup.
Each task has its own budget and working state. Persistent identities, conversation
history and personal memory are supplied by the optional agent package through the
public task API; this module neither loads nor imports that package.

POST /api/tasks starts a task with an optional explicit library and budget. Existing
run/session routes expose its evidence, steering and approvals. Workspace providers
own target selection and environment-specific behavior. The generic package/model
settings routes retain their /api/app prefix for existing frontend clients.
"""

from http import HTTPStatus
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import tomllib

from .. import providers
from ..core import episodes as runs
from ..core.remote import RemoteEnvironment
from ..packages import MissingPackage, Packages, RegistryError, activate, addons, describe
from ..paths import ROOT, data
from harness.runtime.task.delegation import Agents, Place
from harness.runtime.task.environments import Place as Attaching
from ..settings import ChoiceRequired, Credentials, Settings
from .http import Handler, Server
from .sessions import title as session_title

CONVERSATION = ROOT / "configs" / "assistant.toml"
# What one conversation may set for itself (agent.runtime keys): harness run "task" --physical,
# --window-details, --think; and `learn`, a conversation that learns its environment for live
# minutes (true: learning.active_minutes) instead of doing a task (runtime/learning/active.py).
# `agents`: sub-agents on in this conversation whatever session.agents says.
RUN_KEYS = ("physical", "privacy", "think_while_acting", "think_interval", "learn", "managed_workspace", "agents")
# The keys of a conversation profile's file (profiles()).
PROFILE_KEYS = {
    "description": "one line: what conversations of this profile are for",
    "skills": "optional skills these conversations have on top of the assistant's; conversations of other "
              "profiles (or none) do not have them",
    "prompt": "a file (relative to the profile's) whose text is added to the system prompt",
}
# What the agent is told when the user gives the computer back (the page shows it as a note).
HANDBACK = "I took over the computer for a moment and have handed it back. Look at the screen again before you go on."


class TaskHost:
    """The app's state: its data directory, the model key, this computer's worker and
    the conversations it started."""

    def __init__(self, directory: Path | None = None, *, chat=None, verifier=None):
        self.directory = Path(directory or data()).expanduser().resolve()
        # Models in place of the configured ones (tests).
        self._models = {"chat": chat, "verifier": verifier}
        self.conversations_dir = self.directory / "conversations"
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        self.credentials = Credentials(self.directory)
        self.credentials.load()
        self.settings = Settings(self.directory)
        # The skills of the user's packages load beside the built-in ones, here and in kernels;
        # first, as the settings a package adds are checked by its own code.
        self.packages = activate(Packages(self.directory))
        self.prune()
        # Where conversations run: a package's (the computer's), made when first asked for.
        self._workspaces = None
        self.starting = {}
        # Brings the chat's browser window to the front (the app package's focus, set by run()).
        self.focus_chat = None
        self._threads = {}
        # The workspace kind of each conversation started here.
        self._kinds = {}
        # One reclaim at a time: conversations waiting for a workspace pick together.
        self._reclaiming = threading.Lock()
        self._external_start_lock = threading.Lock()
        from ..services.mcp import Resources
        self._mcp_resources = Resources()

    def llm(self) -> dict:
        """The model the user chose, and whether its provider's key is there."""
        settings = providers.load(self.directory)
        provider = providers.PROVIDERS[settings["provider"]]
        key = self.credentials.status(provider.key_env) if provider.key_env else {"set": True, "source": None}
        return {**settings, "key_env": provider.key_env, "key": key, "ready": key["set"]}

    def status(self) -> dict:
        workspaces = self.available_workspaces()
        return {"llm": self.llm(), "providers": providers.described(),
                "workspaces": workspaces.status(), **workspaces.presentation()}

    def conversations(self, server) -> list[dict]:
        from .listing import conversations

        return conversations(server)

    def available_workspaces(self):
        """The workspaces a package of this process gives (harness/extensions.py), or None."""
        if self._workspaces is None:
            from .workspaces import Workspaces
            self._workspaces = Workspaces(self.directory, self.settings)
        return self._workspaces

    @property
    def workspaces(self):
        """Workspace providers from installed packages."""
        return self.available_workspaces()

    def kind(self, workspace: str | None = None, text: str | None = None) -> str:
        """The workspace kind a new conversation takes: `workspace` ("auto": the one its task
        in words asks for), else the computer's mode."""
        return self.workspaces.kind(workspace, text)

    def environments(self, model_entry: str | None = None) -> dict:
        """What a new conversation may work in, for a frontend's choice: {"options": each
        kind the core and the installed packages give ({"value", "label", "about"} and its
        "folder", "views" and "physical" flags), "selected": what the choice highlights (the
        last conversation's, else a saved computer.mode, else None: nothing is preselected),
        "folder": the last project folder, "setting": session.environment}. An environment
        with a screen carries a `note` when the model (`model_entry`, default the chosen
        one) reads no images: the user is told before they choose."""
        options = self.workspaces.environments()
        have = {row["value"] for row in options}
        options += [row for row in self.installable_environments() if row["value"] not in have]
        note = self.reads_no_images(model_entry)
        if note:
            options = [{**row, "note": note} if row.get("views") else row for row in options]
        kinds = [row["value"] for row in options]
        last = self.settings.remembered("session", "last_environment")
        if last not in kinds:
            last = self.settings.remembered("computer", "mode")
        return {"options": options, "selected": last if last in kinds else None,
                "folder": self.settings.remembered("session", "last_folder") or None,
                "setting": self.settings.get()["session"]["environment"]}

    def installable_environments(self) -> list[dict]:
        """What a new installation can choose before any environment package is installed:
        the environments of the registry's packages, as rows of the choice ({"value",
        "label", "about", "package"}); choosing one installs its package as
        packages.auto_install says. None when that is off, when the registry cannot be read
        (asked again after ten minutes), or once a package gives an environment: from then
        on the choice lists what is installed, and naming another one still installs it."""
        if self.packages.auto_install() == "off" or self.workspaces.providers():
            return []
        if time.monotonic() < getattr(self, "_registry_unread_until", 0):
            return []
        try:
            rows = self.packages.registry.search()
        except (RegistryError, OSError, ValueError):
            self._registry_unread_until = time.monotonic() + 600
            return []
        installed = {row["name"] for row in self.packages.installed()}
        found = {}
        for row in rows:
            if row["name"] in installed:
                continue
            for kind in row.get("provides", {}).get("workspaces", []):
                found.setdefault(kind, {"value": kind, "label": kind.replace("-", " ").capitalize(),
                                        "about": f"{row['summary']} (installs the package {row['name']})",
                                        "package": row["name"]})
        from .workspaces import ORDER
        return [found[kind] for kind in (*[k for k in ORDER if k in found], *sorted(set(found) - set(ORDER)))]

    def install_environment(self, workspace: str) -> bool:
        """Install the registry's package of an environment no installed package gives
        (packages.auto_install); False when there is none or it is not to be installed."""
        try:
            self.packages.ensure("workspaces", workspace, log=lambda message: None)
        except (MissingPackage, RegistryError, OSError):
            return False
        return workspace in self.workspaces.kinds()

    def reads_no_images(self, model_entry: str | None = None) -> str:
        """What to say beside an environment with a screen when the model reads no images
        (its entry of the model list); empty when it reads them."""
        from .. import model_list

        try:
            row = next((item for item in self.models() if item["id"] == model_entry), None) if model_entry else None
            choice = row or providers.load(self.directory)
            if (row.get("images") is not False) if row else model_list.reads_images(self.directory, choice):
                return ""
        except (ValueError, OSError):
            return ""
        vision = self.settings.get()["model"].get("vision")
        name = choice.get("model") or "the model"
        return (f"{name} reads no images: {vision} describes what it looks at" if vision else
                f"needs a model that reads images: {name} reads none, so no picture is sent and it works "
                "from text only")

    def environment(self, workspace=None, folder=None, *, last=False, model_entry=None) -> tuple:
        """Where a new conversation works, as (kind, folder): the `workspace` it names; a
        `folder` alone names a project; with neither, session.environment decides: a fixed
        kind, `last` (the last conversation's choice; `last=True` asks for that whatever the
        setting says: a frontend with no way to ask or to name one), or `ask`, which raises
        ChoiceRequired with the choice for the frontend to put to the user. Nothing is ever
        chosen for the user."""
        offered = self.environments(model_entry)
        by = {row["value"]: row for row in offered["options"]}
        if workspace in (None, "auto") and folder is not None:
            if any(provider.accepts({"folder": folder}) for provider in self.workspaces.providers()):
                workspace = self.workspaces.kind(None, None, binding={"folder": folder})
            else:
                # No installed package takes a folder: a folder alone names a project.
                workspace = "project"
        if workspace in (None, "auto"):
            setting = "last" if last else offered["setting"]
            if setting == "last" and offered["selected"]:
                workspace = offered["selected"]
            elif setting not in ("ask", "last"):
                if setting not in by:
                    raise ValueError(f"session.environment is {setting!r}, which no installed package provides; "
                                     f"it is ask, last or one of {', '.join(by)}")
                workspace = setting
            else:
                names = ", ".join(by)
                raise ChoiceRequired({
                    "section": "session", "key": "environment", "per_conversation": True,
                    "title": "Where should Harness work?", "selected": offered["selected"],
                    "folder": offered["folder"],
                    "options": [{**row, "label": (f"{row['label']} — {row['about']}" if row.get("about") else
                                                  row["label"]) + (f" ({row['note']})" if row.get("note") else ""),
                                 "name": row["label"]} for row in offered["options"]],
                    "message": "Choose where this conversation works: --workspace KIND (workspace=KIND in Python), "
                               f"one of {names}; or set session.environment to last or to one of them"})
            if by.get(workspace, {}).get("folder") and folder is None:
                folder = offered["folder"]
        # An environment of a package that is not installed yet: installed the first time.
        if (workspace not in by or by[workspace].get("package")) and self.install_environment(workspace):
            offered = self.environments(model_entry)
            by = {row["value"]: row for row in offered["options"]}
        if workspace not in by or by[workspace].get("package"):
            raise ValueError(f"no installed package provides workspace {workspace!r}; there are "
                             f"{', '.join(kind for kind, row in by.items() if not row.get('package'))}"
                             + "".join(f"; {problem}" for problem in self.workspaces.problems.values()))
        kind = self.workspaces.kind(workspace)
        if by[workspace].get("folder") and not folder:
            raise ValueError(f"a {kind} conversation works in one folder: name it with --folder PATH (folder=PATH)")
        return kind, folder

    def models(self, change=None):
        from .. import model_list

        return model_list.models(self.directory, change)

    def set_model(self, body: dict) -> dict:
        """Choose a provider and model (and give its key): checked with the provider before
        anything is kept."""
        settings = providers.check(body)
        provider = providers.PROVIDERS[settings["provider"]]
        key = str(body.get("key") or "").strip() or (os.environ.get(provider.key_env) if provider.key_env else None)
        if provider.key_env and not key:
            return {"ok": False, "detail": "no key"}
        result = providers.reach(settings, key)
        if result["ok"]:
            if provider.key_env and body.get("key"):
                self.credentials.save(key, provider.key_env)
            providers.save(self.directory, settings)
            from .. import model_list

            row = model_list.entry(settings)
            if not any(item["id"] == row["id"] for item in self.models()):
                self.models({"action": "save", **settings})
        return result

    def config(self, model=None, kind=None, profile=None, *, choice=None, effort=None, agents=None):
        """The configuration (TaskConfig) of an assistant conversation with the user's model (or
        `model`, another id of the same provider) and settings, in a workspace of `kind`
        (default: the computer's mode), of a package's `profile` (profiles()); its endpoint is
        set when the workspace runs."""
        from ..bench import bench_specs, declares_channels
        from ..extensions import hosts
        from ..config.agent import overridden_agent, task_config
        from ..services.placement import load_deploy

        values = self.settings.get()
        kind = self.kind(kind)
        from .. import model_list

        current = providers.load(self.directory)
        advanced = values["model"]
        if choice is not None:
            advanced = {**advanced, "reasoning_effort": effort}
            if any(choice.get(key) != current.get(key) for key in ("provider", "base_url")):
                advanced.pop("checker", None)
                advanced.pop("vision", None)
        choice = choice or current
        if model:
            choice = {**choice, "model": str(model)}
        # A model the list says reads no images is sent none (its role's `images`).
        try:
            if not model_list.reads_images(self.directory, choice):
                advanced = {**advanced, "images": False}
        except (ValueError, OSError):
            pass
        path = providers.model_file(choice, self.directory, advanced)
        tree = self.conversation_tree(values, kind)
        skills = self.skills_on(values, kind, profile, agents=agents)
        embodiment = bench_specs()[tree["bench"]].kind
        embodiment_config = tree.setdefault("overrides", {}).setdefault("agent", {}).setdefault(embodiment, {})
        embodiment_config["skills"] = {**embodiment_config.get("skills", {}), "enable": skills["enable"]}
        # What waits for the user in this conversation (its lock records it; the conversation's
        # confirmation follows it, confirmation_policy).
        embodiment_config["runtime"] = {**embodiment_config.get("runtime", {}), "approvals": {"ask": values["approvals"]["ask"]}}
        # The skills the user installed: the prompt's installed section (runtime/decision/prompts.py).
        if skills["installed"]:
            embodiment_config["runtime"] = {**embodiment_config.get("runtime", {}), "installed_skills": skills["installed"]}
        if skills["agent"]:
            embodiment_config["runtime"] = {**embodiment_config.get("runtime", {}),
                                  "agent_skills": addons.agent_skill_options(self.packages, skills["agent"])}
        # No implicit cross-task knowledge. A caller can explicitly bind a learning library.
        embodiment_config["runtime"] = {**embodiment_config.get("runtime", {}), "library": None}
        servers = self.mcp_servers()
        if servers:
            # The MCP servers a package connects (the app's connectors, through its gateway).
            embodiment_config["skills"]["enable"] = [*embodiment_config["skills"]["enable"], "mcp"]
            embodiment_config["runtime"] = {**embodiment_config.get("runtime", {}), "mcp": servers}
        spec = bench_specs()[tree["bench"]]
        agent = overridden_agent(tree.get("overrides", {}), model=str(path), deploy=load_deploy(None),
                                 embodiment=spec.kind, channels=declares_channels(spec),
                                 package_paths=[spec.path, *profile_paths().get(profile, ()),
                                                *(package.path for package, module in hosts()
                                                  if servers and hasattr(module, "mcp_servers"))])
        config = task_config(agent, "free", [0], budget=tree.get("budget"), endpoint="http://127.0.0.1:1",
                             path=CONVERSATION)
        viewer = providers.viewer_role(choice, advanced)
        if viewer:
            config.runtime = {**config.runtime, "viewer": viewer}
        additions = ""
        if servers:
            additions += "\nConnectors the user added:\n" + "".join(
                f"  {name}: {server['description']}\n" for name, server in servers.items())
        if profile and profiles()[profile]["prompt"]:
            additions += "\n" + profiles()[profile]["prompt"] + "\n"
        config.system_prompt += additions
        config.base_prompt += additions
        return config

    def learning(self, config, minutes):
        """`config` as a conversation that learns its environment for `minutes` of live time
        (true: the settings' learning.active_minutes), its entries' tests run again at its start
        (runtime/learning/active.py active_config). ValueError when learning is frozen."""
        from harness.runtime.learning import active

        library = config.runtime.get("library") or {}
        if library.get("learn") != "on":
            raise ValueError("learning is frozen in the settings (learning.mode): nothing would be kept")
        minutes = self.settings.get()["learning"]["active_minutes"] if minutes is True else minutes
        config.runtime = {**config.runtime, "library": {**library, "replay": True, "active_minutes": minutes}}
        return active.active_config(config)

    def progress(self, server, run: str) -> dict:
        """Where a conversation that learns its environment stands (runtime/learning/active.py
        progress()); {"active": False} for any other."""
        from harness.runtime.learning import active

        conversation = server.conversations.get(run)
        if conversation is None or not active.is_active(conversation.config.runtime):
            return {"active": False}
        return {"active": True, "status": conversation.status, "library": conversation._learner().directory.name,
                **conversation._learning_progress()}

    def skills_on(self, values: dict | None = None, kind: str | None = None, profile: str | None = None, *,
                  agents: bool | None = None) -> dict:
        """The skills a new conversation enables: checklist unless the user turned it off, chat
        (stay_on_screen), screens (several monitors), the installed ones that are on;
        instructions when an Agent Skill is on; browser in a browser workspace, physical
        (asking for the real mouse and keyboard up front) on the desktop; environments
        (taking another environment, asking for sub-agents); agents (sub-agents) only when
        they are on (`agents`, default the setting session.agents) and the nesting depth
        allows one; entries (parts of the work that run beside the programs). An installed
        skill a profile names is on only in the conversations of that profile."""
        from harness.runtime.execution.skills import load_skills

        values = values or self.settings.get()
        off = set((values.get("skills") or {}).get("off", []))
        loaded = load_skills()
        given = profiles()
        if profile is not None and profile not in given:
            raise ValueError(f"no profile {profile}" + (f"; profiles: {', '.join(sorted(given))}" if given else ""))
        mine = set(given[profile]["skills"]) if profile else set()
        off |= {name for found in given.values() for name in found["skills"]} - mine
        rows = [row for row in addons.skills(self.packages) if "problem" not in row and row["name"] not in off]
        # The app's agent works on this computer: the packages' skills for it.
        from ..bench import bench_spec
        embodiment = bench_spec(self.workspaces.bench(kind)).kind
        installed = [row["name"] for row in rows if row["format"] == "harness" and row["name"] in loaded
                     and embodiment in row.get("embodiments", ())]
        agent = [row["name"] for row in rows if row["format"] == "agent"]
        enable = [*(["checklist"] if not {"checklist", "plan"} & off else []), "entries", *installed,
                  *sorted(mine - set(installed)), *(["instructions"] if agent else [])]
        enable += list(self.workspaces.provider(kind).extra_skills(kind))
        enable.append("environments")
        if agents is None:
            agents = values["session"]["agents"] == "on"
        if agents and values["limits"]["agent_depth"] > 0:
            enable.append("agents")
        return {"enable": enable, "installed": installed, "agent": agent}

    def skills(self) -> dict:
        """The skills as Settings lists them: the built-in ones of this computer and the
        installed ones, each on or off; why an installed one cannot load."""
        from harness.runtime.execution.skills import USER_PROBLEMS, load_skills

        off = set((self.settings.get().get("skills") or {}).get("off", []))
        loaded = load_skills()
        from ..bench import bench_spec
        embodiment = bench_spec(self.workspaces.bench(self.kind())).kind
        rows = [{"name": embodiment, "format": "built-in", "summary": loaded[embodiment].summary, "locked": True,
                 "on": True},
                {"name": "checklist", "format": "built-in", "summary": loaded["checklist"].summary,
                 "on": not {"checklist", "plan"} & off}]
        for name in self.workspaces.provider().builtin_skills(self.kind()):
            if name != embodiment:
                rows.append({"name": name, "format": "built-in", "summary": loaded[name].summary,
                             "locked": True, "on": True})
        for row in addons.skills(self.packages):
            if row["format"] == "harness" and "embodiments" in row and embodiment not in row["embodiments"]:
                continue
            problem = row.get("problem") or USER_PROBLEMS.get(row["path"]) if row["format"] == "harness" else \
                row.get("problem")
            if row["format"] == "harness" and not problem and row["name"] not in loaded:
                problem = "did not load"
            rows.append({**row, "on": row["name"] not in off and not problem, **({"problem": problem} if problem else {})})
        return {"skills": rows}

    def switch_skill(self, name: str, on: bool) -> dict:
        known = {row["name"]: row for row in self.skills()["skills"]}
        if name not in known or known[name].get("locked"):
            raise ValueError(f"no skill {name} to switch")
        section = dict(self.settings.get().get("skills") or {})
        names = {"checklist", "plan"} if name == "checklist" else {name}
        off = [item for item in section.get("off", []) if item not in names] + ([] if on else [name])
        self.settings.put("skills", {**section, "off": off})
        return self.skills()

    def packages_state(self) -> dict:
        """The Packages page: the installed packages (`shown`: describe()), the skills, the settings."""
        return {"packages": [{**row, "shown": describe(row)} for row in self.packages.installed()], **self.skills(),
                "auto_install": self.packages.auto_install(), "registry": self.packages.registry.base}

    def install_packages(self, body: dict) -> dict:
        """Install from a source (a registry name, a git or archive URL, a folder) or an
        uploaded archive. One from outside the registry runs code nobody reviewed: it is
        installed only with `trust`, after the page showed what it brings. A folder of
        skills becomes a package per skill, taken only when it runs on this computer."""
        import base64
        from ..bench import bench_spec

        zip_bytes = base64.b64decode(body["zip"]) if body.get("zip") else None
        if not zip_bytes and not body.get("source"):
            raise ValueError("give a package name, a folder, an archive or a git URL")

        def kernel_python():
            # A skill's requirements are for the kernel: the environment of the computer's mode.
            return self.workspaces.provider().python(self.kind(), log=lambda message: None)

        result = self.packages.install([body["source"]] if body.get("source") else [], zip_bytes=zip_bytes,
                                       consent=lambda found: bool(body.get("trust")), python=kernel_python,
                                       embodiment=bench_spec(self.workspaces.bench(self.kind())).kind,
                                       log=lambda message: None)
        if result.get("found"):
            result = {**result, "found": [{**found, "shown": describe(found)} for found in result["found"]]}
        return {**result, **self.packages_state()}

    def conversation_tree(self, values: dict, kind: str | None = None) -> dict:
        """The assistant's configuration (configs/assistant.toml) with the user's limits, in a
        workspace of `kind` (default: the computer's mode)."""
        from ..config import load_layered

        tree = load_layered(CONVERSATION)
        limits = values["limits"]
        # No cost limit: only OpenRouter reports a cost, so one would stop conversations
        # on that provider alone. Calls and minutes bound every conversation.
        budget = {key: value for key, value in tree.get("budget", {}).items() if key != "max_cost_usd"}
        tree["budget"] = {**budget, "max_model_calls": int(limits["max_steps"]),
                          "max_wall_seconds": int(limits["max_minutes"]) * 60}
        # The workspace's own (a background browser's prompt).
        tree = self.workspaces.tree(tree, kind)
        # When the model thinks while the agent acts (Settings, Model).
        model = values.get("model") or {}
        thinks = {**({"think_while_acting": model["think_while_acting"]}
                     if model.get("think_while_acting", "default") != "default" else {}),
                  **({"think_interval": int(model["think_interval"])} if model.get("think_interval") else {})}
        if thinks:
            from ..bench import bench_spec
            embodiment = bench_spec(tree["bench"]).kind
            embodiment_config = tree.setdefault("overrides", {}).setdefault("agent", {}).setdefault(embodiment, {})
            embodiment_config["runtime"] = {**embodiment_config.get("runtime", {}), **thinks}
        return tree

    def prune(self) -> list[str]:
        """Delete the conversations older than the user keeps them (data.keep_days)."""
        import shutil

        days = self.settings.get()["data"]["keep_days"]
        if not days:
            return []
        limit = time.time() - days * 86400
        gone = []
        for directory in sorted(self.conversations_dir.iterdir()):
            trace = directory / "events.jsonl"
            if directory.is_dir() and trace.is_file() and trace.stat().st_mtime < limit:
                shutil.rmtree(directory, ignore_errors=True)
                gone.append(directory.name)
        return gone

    def _meta(self, server, run) -> tuple[Path, dict]:
        directory = (server.root / str(run)).resolve()
        if self.conversations_dir.resolve() not in directory.parents or not directory.is_dir():
            raise ValueError(f"no conversation {run}")
        try:
            meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        return directory, meta

    def model_changed(self, server, run, changed: dict) -> None:
        """Keep a conversation's model and reasoning effort as they are now in its meta.json
        (the app's conversations only)."""
        try:
            directory, meta = self._meta(server, run)
        except ValueError:
            return
        meta.update(model=changed.get("model"), reasoning_effort=changed.get("reasoning_effort"))
        (directory / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


    def start(self, server, text: str, model: str | None = None, confirmation: str | None = None,
              workspace: str | None = None, runtime: dict | None = None, files=(),
              reasoning_effort: str | None = None, profile: str | None = None, *,
              agent: str | None = None, folder: str | None = None, isolation: str | None = None,
              frontend: str | None = None, mcp_tools=(), execution: str | None = None,
              budget: dict | None = None, library: dict | None = None, title: str | None = None, model_entry: str | None = None) -> str:
        """Start a conversation with the user's first message: its directory and record
        now, its workspace (of kind `workspace`: "none" takes none; without one and without a
        `folder`, session.environment decides, environment(); installed on first use) and the
        episode on a thread of their own. `runtime`: this conversation's
        own physical-input policy, what the model learns of other windows and when it
        thinks while acting (RUN_KEYS, as harness run "task" --physical ... gives them).
        `files`: paths the first message attaches. `reasoning_effort`: the main model's provider option ID.
        `profile`: a package's (profiles()), its skills and prompt. Returns its run (a path under
        the conversations directory)."""
        from .. import model_list
        from harness.runtime.decision.model import valid_effort

        choice = None
        if reasoning_effort == "default":
            reasoning_effort = ""
        if reasoning_effort is not None and not valid_effort(reasoning_effort):
            raise ValueError("invalid reasoning effort ID")
        if not model_entry and not model and not agent and frontend == "taptab":
            default = model_list.select(self.directory, native=True)
            if default is None:
                raise ValueError("add an enabled Harness model in Settings")
            model_entry = default["id"]
        if model_entry:
            choice = next((row for row in self.models()
                           if row["id"] == model_entry and row["enabled"]), None)
            if choice is None:
                raise ValueError("the selected model is no longer enabled")
            model = choice["model"] or None
            if choice["provider"] not in providers.PROVIDERS:
                if agent and agent != choice["provider"]:
                    raise ValueError("the selected model uses a different agent")
                agent = choice["provider"]
            elif agent and agent != "harness":
                raise ValueError("the selected model uses a different provider")
            if reasoning_effort and reasoning_effort not in choice["efforts"]:
                raise ValueError("this model does not offer that reasoning effort")
        if agent and agent != "harness":
            if execution is not None or budget is not None:
                raise ValueError("this adapter does not accept execution bounds")
            if runtime or profile or confirmation or workspace not in (None, "auto"):
                raise ValueError("native workspace, isolation and approval settings apply only to the Harness agent")
            return self.start_external(server, agent, str(text or ""), files, folder, isolation,
                                       frontend, model, reasoning_effort or None, mcp_tools=mcp_tools)
        if isolation or mcp_tools:
            raise ValueError("isolation and mcp_tools are options for external agents")
        from harness.runtime.learning import active
        from harness.runtime.task.run import TaskRun
        from harness.runtime.safety.approval import confirmation_policy

        text = str(text or "").strip()
        if not text:
            raise ValueError("say what to do")
        if choice:
            provider = providers.PROVIDERS[choice["provider"]]
            if provider.key_env:
                self.credentials.load()
                if not os.environ.get(provider.key_env):
                    raise ValueError(f"configure credentials for {provider.name} in Settings")
        elif not self.llm()["ready"]:
            raise ValueError("no model key yet")
        kind, folder = self.environment(workspace, folder, last=frontend == "taptab", model_entry=model_entry)
        request = {"folder": folder} if folder is not None else {}
        self.workspaces.require_choices(kind, runtime)
        # The package of the workspace's bench (computer, browser), installed the first
        # time as packages.auto_install says.
        if self.workspaces.environment(kind) is None:
            self.packages.ensure("benches", self.workspaces.bench(kind), log=lambda message: None)
        switched = (runtime or {}).get("agents")
        if switched is not None and type(switched) is not bool:
            raise ValueError("agents must be a boolean")
        config = self.config(model, kind, profile, choice=choice, effort=reasoning_effort, agents=switched)
        if budget is not None:
            import math

            for key, limit in budget.items():
                if key not in ("max_wall_seconds", "max_model_calls", "max_cost_usd"):
                    raise ValueError(f"unknown execution budget {key!r}")
                if type(limit) not in (int, float) or not math.isfinite(limit) or limit <= 0:
                    raise ValueError(f"{key} must be a finite positive number")
                if key == "max_model_calls" and type(limit) is not int:
                    raise ValueError("max_model_calls must be an integer")
                current = getattr(config, key)
                setattr(config, key, min(limit, current) if current is not None else limit)
        unknown = set(runtime or {}) - set(RUN_KEYS)
        if unknown:
            raise ValueError(f"a conversation's own runtime keys are {', '.join(RUN_KEYS)}, not {sorted(unknown)}")
        runtime = dict(runtime or {})
        learn = runtime.pop("learn", None)
        runtime.pop("agents", None)
        managed = runtime.pop("managed_workspace", False)
        if type(managed) is not bool:
            raise ValueError("managed_workspace must be a boolean")
        if managed:
            self.workspaces.provider(kind).validate_managed(kind)
            profile_skills = profiles()[profile].get("skills") if profile and execution is not None else None
            if (runtime or learn
                    or profile is not None and (execution is None or profile_skills)):
                raise ValueError("A managed workspace requires a prompt-only profile without runtime overrides")
        config.runtime = {**config.runtime, **runtime}
        if library is not None:
            from harness.runtime.learning.learner import settings as library_settings
            if not isinstance(library, dict) or not library.get("path"):
                raise ValueError("library requires an explicit path and learning settings")
            library_settings(library)
            config.runtime = {**config.runtime, "library": dict(library)}
        name = runs.new_name()
        directory = self.conversations_dir / name
        if learn is not None and learn is not False:
            if library is None:
                config.runtime = {**config.runtime, "library": {"path": str(directory / "library"),
                                  "learn": "on", "reflect": True}}
            config = self.learning(config, learn)
        if managed:
            config.runtime = {**config.runtime, "library": None, "agent_skills": [], "think_while_acting": False}
        if reasoning_effort:
            config.main = {**config.main, "reasoning_effort": reasoning_effort}
        elif reasoning_effort == "":
            config.main.pop("reasoning_effort", None)
        options, metadata = self.workspaces.bind(kind, directory, request)
        conversation = TaskRun(config, 0, directory, interactive=True,
                                    confirmation=confirmation_policy(confirmation), instruction=text,
                                    agents=None if managed else self.sub_agents(server, kind, assistant=True), **self._models)
        from ..extensions import hosts

        conversation.workspace_kind = kind
        conversation.workspace_options = options
        if not managed:
            from harness.runtime.task.environments import Environments

            place = AttachPlace(self, server, run_name=name)
            place.kind = kind
            conversation.environments = Environments(conversation, place)
        conversation.session_metadata = {"workspace": metadata} if metadata else {}
        if execution is not None:
            conversation.session_metadata = {**getattr(conversation, "session_metadata", {}), "execution": execution}
        conversation.mcp_resources = self._mcp_resources
        conversation.mcp_authorize = self.authorize_mcp
        conversation.mcp_prepare = next((lambda *args, module=module: module.prepare_mcp(self, *args)
                                         for _, module in hosts() if hasattr(module, "prepare_mcp")), None)
        conversation.send_message("", files=files)
        meta = {"title": session_title(title or text, 60), "text": text, "created": time.time(), "model": config.main.get("model"),
                "reasoning_effort": config.main.get("reasoning_effort"), "workspace": kind,
                **metadata,
                **({"model_entry": model_entry} if model_entry else {}),
                **({"learning": config.max_wall_seconds / 60} if active.is_active(config.runtime) else {}),
                **({"profile": profile} if profile else {})}
        (directory / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        run = directory.relative_to(server.root).as_posix()
        self._kinds[run] = kind
        # What the next conversation's choice highlights (and session.environment = last takes).
        self.settings.remember("session", "last_environment", kind)
        if metadata.get("folder"):
            self.settings.remember("session", "last_folder", metadata["folder"])
        if frontend is None:
            server.conversations[run] = conversation
        else:
            server.conversations.add(run, conversation, title=meta["title"], frontend=frontend)
        self.starting[run] = "preparing the workspace"
        # Its trace begins now, so the page lists and follows it while the computer is
        # prepared (the first time installs its environment).
        conversation.trace.emit("state", status=conversation.status, reason="preparing the workspace")
        if execution is None:
            conversation.trace.subscribe(self._watcher())

        def begin():
            recording = None
            workspaces = self.workspaces
            try:
                if conversation._closing:
                    raise workspaces.Cancelled()
                local = workspaces.environment(kind)
                if local is not None:
                    # No worker: the kind's environment lives in this process (none).
                    conversation.env = local
                elif managed:
                    lease = workspaces.provider(kind).acquire_managed(
                        run, kind, log=lambda message: self._note(run, message),
                        evict=lambda runs: self._evict(server, runs, run), cancelled=lambda: conversation._closing)
                    conversation.env = conversation._managed_workspace = lease
                else:
                    worker = workspaces.acquire(run, kind, log=lambda message: self._note(run, message),
                                                evict=lambda runs: self._evict(server, runs, run),
                                                cancelled=lambda: conversation._closing,
                                                options=conversation.workspace_options)
                    conversation.config.environment = {**conversation.config.environment, "endpoint": worker.endpoint}
                    if key := getattr(worker, "approval_key", None):
                        conversation.env = RemoteEnvironment(worker.endpoint, timeout=600, approval_key=key)
                    recording = workspaces.record(directory, kind, conversation.trace)
                    if worker.python and worker.python != sys.executable:
                        conversation.config.runtime = {**conversation.config.runtime, "python": worker.python}
                thread = self._threads[run] = conversation.start()
            except workspaces.Cancelled:
                workspaces.release(run)
                conversation._set_status("FINISHED", reason="ended before it began")
                return
            except Exception as error:
                if recording is not None:
                    recording.stop()
                workspaces.release(run)
                self.starting[run] = f"error: {error}"
                conversation.trace.emit("error", message=f"The workspace could not be prepared: {error}")
                conversation._set_status("ERROR", reason="error")
                return
            finally:
                if not str(self.starting.get(run, "")).startswith("error"):
                    self.starting.pop(run, None)
            # The workspace is given back when the episode ends.
            thread.join()
            workspaces.release(run)
            if recording is not None:
                # screen.json has the times; the trace has ended.
                recording.stop()

        threading.Thread(target=begin, name=f"start-{name}", daemon=True).start()
        return run

    def start_external(self, server, agent, text, files, folder, isolation, frontend, model, effort, *,
                       handoff=None, reconnect=None, observe=None, mcp_tools=()):
        from ..core import atomic_write
        from ..extensions import modules

        cwd = Path(folder).expanduser().resolve() if folder else None
        if cwd is not None and not cwd.is_dir():
            raise ValueError("the project directory does not exist")
        directory = Path(reconnect["directory"]) if reconnect else self.conversations_dir / runs.new_name()
        if mcp_tools and (not isinstance(mcp_tools, (list, tuple))
                          or not isinstance(agent, str) or not agent.startswith("acp:")
                          or any(name not in ("project_info", "project_diff") for name in mcp_tools)):
            raise ValueError("MCP grants for external sessions are explicit ACP project tool names")
        for module in modules():
            factory = getattr(module, "session_adapter", None)
            adapter = factory(agent, directory, cwd=cwd, isolation=isolation, model=model, effort=effort,
                              **({"restore": reconnect["metadata"]} if reconnect else {}),
                              **({"observe": observe} if observe else {})) if factory else None
            if adapter is not None:
                break
        else:
            raise ValueError(f"no enabled session adapter for {agent!r}")

        if observe:
            from .sessions import history

            index = server.conversations.index
            known = server.conversations.sessions()
            known += history(index, skip={row["id"] for row in known}) if index else []
            keys = ("adapter_id", "account_scope", "external_id")
            for row in known:
                if all(row["metadata"].get(key) == adapter.session_metadata.get(key) for key in keys):
                    (directory / "events.jsonl").unlink()
                    directory.rmdir()
                    return row["run"]
        run = directory.relative_to(server.root).as_posix()
        adapter.instruction = text
        if mcp_tools:
            adapter.mcp_tools = tuple(mcp_tools)
        if handoff:
            adapter.session_metadata["handoff_from"] = handoff
        if reconnect:
            server.conversations.reconnect(reconnect, adapter)
        else:
            atomic_write(directory / "meta.json", json.dumps({"title": session_title(text or agent, 60),
                                                              "created": time.time()}))
            server.conversations.add(run, adapter, title=session_title(text or agent, 60), frontend=frontend)
        adapter.trace.subscribe(self._watcher())
        adapter.identity_changed = lambda: server.conversations.save_metadata(run)
        adapter.start(text, files)
        return run

    # Records after which the user is needed in the chat: the agent waits for an approval,
    # or it stopped on an error. And the end of the agent's turn (an answer, a question, its
    # task done, the budget used up), unless the agent kept the screen (stay_on_screen).
    NEEDS_THE_USER = ("confirmation_request", "error", "kernel_died", "external_notice", "external_question")
    TURN_ENDS = ("message", "finish", "budget")

    def _watcher(self):
        """A conversation's watcher (a subscriber of its trace): brings the app's window to
        the front when the conversation needs the user (only where run() set focus_chat:
        the app the user opened)."""
        turn = {"stay": False}

        def watch(record: dict) -> None:
            event = record.get("event")
            if record.get("replay"):
                return
            if event == "stay_on_screen":
                turn["stay"] = True
            elif event == "user_message":
                turn["stay"] = False
            needed = event in self.NEEDS_THE_USER or (
                event == "state" and record.get("status") == "IDLE" and record.get("reason") in self.TURN_ENDS
                and not turn["stay"])
            if needed and self.focus_chat is not None:
                threading.Thread(target=self.focus_chat, name="show-chat", daemon=True).start()

        return watch

    def sub_agents(self, server, kind: str | None, assistant: bool = False) -> Agents:
        """The sub-agents of a session `server` runs, in workspaces of this pool: of any kind
        this machine serves for the assistant's conversations (each kind has its
        configuration), else (an experiment's session) of the session's own kind only."""
        workspaces = self.available_workspaces()
        # (A sub-agent works somewhere: never in the kind without an environment.)
        served = tuple(name for name in workspaces.kinds() if workspaces.environment(name) is None)             if workspaces is not None else ()
        kinds = tuple(served) if assistant else ((kind,) if kind in served else ())
        return Agents(PoolPlace(self, server, kinds, assistant), sessions=server.conversations,
                      windows=workspaces.windows() if workspaces is not None else None,
                      max_depth=self.settings.get()["limits"]["agent_depth"])

    def _evict(self, server, runs, run) -> bool:
        """Make room for `run`: end the conversation among `runs` that has waited longest
        for the user (IDLE after its turn); its workspace comes back when its episode ends.
        Whether one was ended (none is while all of them work)."""
        with self._reclaiming:
            idle = []
            for other in runs:
                conversation = server.conversations.get(other)
                if other == run or conversation is None or conversation.status != "IDLE" or conversation._closing:
                    continue
                # IDLE before its first turn too, while its workspace starts: only a turn
                # that ended waits for the user.
                since = getattr(conversation, "waiting_since", None)
                if since is None:
                    continue
                idle.append((since, other, conversation))
            if not idle:
                return False
            _, other, conversation = min(idle, key=lambda item: item[0])
            self._note(run, "ending the conversation that waited longest, for its workspace")
            conversation.trace.emit("workspace_reclaimed", by=run)
            conversation.close()
            return True

    def _note(self, run, message):
        self.starting[run] = str(message)

    def authorize_mcp(self, config, tool=None):
        from ..services.connectors import authorize_connector

        authorize_connector(self.settings.get(), self.credentials, config, tool)

    def mcp_servers(self) -> dict:
        """{name: client config} of the MCP servers the packages' host modules connect for the
        conversations (`mcp_servers(app)`: the app's connectors)."""
        from ..extensions import hosts
        from ..packages import activate

        from ..services.connectors import configured_servers
        servers = configured_servers(self.settings.get(), self.credentials)
        catalog_connectors = [row for row in self.settings.get().get("connectors", [])
                              if row.get("enabled", True) and row.get("catalog")]
        if catalog_connectors and not any(hasattr(module, "mcp_servers") for _, module in hosts()):
            self.packages.ensure("commands", "app")
            activate(self.packages)
        for _, module in hosts():
            connect = getattr(module, "mcp_servers", None)
            if connect is not None:
                servers.update(connect(self))
        return servers

    def close(self):
        if self._workspaces is not None:
            self._workspaces.close()
        from ..extensions import modules

        for module in modules():
            closing = getattr(module, "close_app", None)
            if closing is not None:
                closing(self)


class AttachPlace(Attaching):
    """What the session host gives a conversation that asks for another environment
    (runtime/task/environments.py): a workspace of the app's pools, under the user's
    settings environments.attach and its rules."""

    def __init__(self, app: TaskHost, server, run_name: str):
        self.app, self.server, self.run_name = app, server, run_name

    def kinds(self):
        workspaces = self.app.workspaces
        return {row["value"]: row for row in workspaces.environments()
                if workspaces.environment(row["value"]) is None}

    def level(self, kind, runtime):
        settings = self.app.settings
        values = settings.get()["environments"]
        rule = next((row for row in values["rules"] if row.get("kind") == kind), None)
        # Skipping confirmations is the user's own switch for their real mouse and keyboard:
        # this run's level, else the one they saved (never the schema's default).
        physical = (runtime.get("physical") or {}).get("level") or settings.remembered("physical", "level")
        return (rule["level"] if rule else values["attach"]), physical == "allow"

    def begin(self, conversation, kind, folder, cancelled):
        from harness.runtime.decision.prompts import assemble_prompt, features_for
        from harness.runtime.task.environments import Refused
        from ..bench import bench_spec, declares_channels

        app, workspaces = self.app, self.app.workspaces
        try:
            workspaces.require_choices(kind, conversation.config.runtime)
        except ChoiceRequired as error:
            raise Refused(f"{kind} needs the user's own choice first ({error.choice['section']}."
                          f"{error.choice['key']}: {error.choice['title']}). Tell them to set it in the settings; "
                          "go on without it meanwhile.") from None
        key = f"{self.run_name}+{kind}"
        directory = Path(conversation.directory) / "environments" / kind
        options, metadata = workspaces.bind(kind, directory, {"folder": folder} if folder else {})
        values = app.settings.get()
        tree = app.conversation_tree(values, kind)
        spec = bench_spec(tree["bench"])
        provider = workspaces.provider(kind)
        skills = list(dict.fromkeys([*provider.builtin_skills(kind), *provider.extra_skills(kind)]))
        runtime = (tree["overrides"]["agent"].get(spec.kind) or {}).get("runtime") or {}
        prompt = assemble_prompt(tree["overrides"]["agent"]["prompt"][spec.kind], skills,
                                 features=features_for(runtime, declares_channels(spec), embodiment=spec.kind),
                                 embodiment=spec.kind, own=True)
        app.packages.ensure("benches", workspaces.bench(kind), log=lambda message: None)
        worker = workspaces.acquire(key, kind, log=lambda message: app._note(key, message),
                                    evict=lambda runs: app._evict(self.server, runs, key), cancelled=cancelled,
                                    **({"options": options} if options else {}))
        app.starting.pop(key, None)
        env = RemoteEnvironment(worker.endpoint, timeout=600, approval_key=getattr(worker, "approval_key", None))
        return {"env": env, "embodiment": spec.kind, "task": "free", "skills": skills, "prompt": prompt,
                "metadata": metadata, "release": lambda: workspaces.release(key)}

    def agents(self):
        from harness.runtime.decision.prompts import assemble_prompt, features_for
        from ..bench import bench_spec, declares_channels

        values = self.app.settings.get()
        return {"mode": values["session"]["agents"], "depth": values["limits"]["agent_depth"],
                "prompt": self._agents_prompt(values)}

    def _agents_prompt(self, values):
        from harness.runtime.decision.prompts import assemble_prompt, features_for
        from ..bench import bench_spec, declares_channels

        kind = getattr(self, "kind", None)
        try:
            tree = self.app.conversation_tree(values, kind) if kind else None
            if tree is None:
                return ""
            spec = bench_spec(tree["bench"])
            runtime = (tree["overrides"]["agent"].get(spec.kind) or {}).get("runtime") or {}
            return assemble_prompt(tree["overrides"]["agent"]["prompt"][spec.kind], ["agents", "environments"],
                                   features=features_for(runtime, declares_channels(spec), embodiment=spec.kind),
                                   embodiment=spec.kind, only=["agents"])
        except (ValueError, KeyError, OSError):
            return ""


class PoolPlace(Place):
    """Where the sub-agents of the app's sessions run (runtime/task/delegation.py): each takes a
    workspace of the app's pool, like a conversation, until it ends."""

    why_not = "this session has no package-provided workspace lease"

    def __init__(self, app: TaskHost, server, kinds, assistant: bool):
        self.app, self.server, self.kinds, self.assistant = app, server, tuple(kinds), assistant

    def config(self, parent, kind, model):
        # The assistant's configuration of another kind (or model) is the app's to build.
        if self.assistant and (kind != parent.workspace_kind or model):
            config = self.app.config(model, kind)
            # A sub-agent can propose while working. Its parent reflects on the result.
            library = config.runtime.get("library")
            if library:
                config.runtime = {**config.runtime, "library": {**library, "reflect": False}}
            return config
        return None

    def begin(self, child, kind, cancelled):
        app = self.app
        app.workspaces.require_choices(kind, child.config.runtime)
        identity = child.identity or {}
        run = f"{identity.get('session')}/{identity.get('agent')}"
        options, metadata = app.workspaces.bind(kind, child.directory, {}, child.parent)
        child.workspace_kind, child.workspace_options = kind, options
        child.session_metadata = {"workspace": metadata} if metadata else {}
        worker = app.workspaces.acquire(run, kind, log=lambda message: app._note(run, message),
                                        evict=lambda runs: app._evict(self.server, runs, run), cancelled=cancelled,
                                        **({"options": options} if options else {}))
        app.starting.pop(run, None)
        app._kinds[run] = kind
        child.config.environment = {**child.config.environment, "endpoint": worker.endpoint}
        if key := getattr(worker, "approval_key", None):
            child.env = RemoteEnvironment(worker.endpoint, timeout=600, approval_key=key)
        if worker.python and worker.python != sys.executable:
            child.config.runtime = {**child.config.runtime, "python": worker.python}
        return lambda: app.workspaces.release(run)


def profile_paths() -> dict:
    from ..extensions import modules

    found = {}
    for module in modules():
        for name, path in (getattr(module, "profiles", None) or {}).items():
            found.setdefault(name, (path,))
    return found


def profiles() -> dict:
    """The conversation profiles the packages give ({name: path} as `profiles` of their host
    modules, harness/extensions.py), read: {name: {"description", "skills", "prompt"}}
    (PROFILE_KEYS; the prompt as its text). The first package to give a name has it."""
    return {name: load_profile(paths[0]) for name, paths in profile_paths().items()}


def load_profile(path) -> dict:
    """A conversation profile's file (PROFILE_KEYS), its prompt read; ValueError says what is wrong."""
    path = Path(path)
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"profile {path}: {error}") from None
    unknown = set(data) - set(PROFILE_KEYS)
    if unknown:
        raise ValueError(f"profile {path}: unknown keys {sorted(unknown)} (it has {', '.join(PROFILE_KEYS)})")
    skills = data.get("skills", [])
    if not isinstance(skills, list) or not all(isinstance(name, str) for name in skills):
        raise ValueError(f"profile {path}: skills is a list of skill names")
    prompt = (path.parent / data["prompt"]).read_text(encoding="utf-8").strip() if data.get("prompt") else ""
    return {"description": str(data.get("description", "")), "skills": list(skills), "prompt": prompt}


class TaskHandler(Handler):
    # A skill's .zip comes in the body.
    body_limits = {"/api/app/packages/install": 40 * 1024 * 1024}

    def get_app(self, query):
        self._json(self.server.app.status())

    def get_app_agents(self, query):
        from ..extensions import modules

        self._json({"agents": [agent for module in modules()
                               for agent in getattr(module, "agents", lambda: [])()]})

    def get_app_agent_models(self, query):
        """Discover the installed adapter's model options without opening a user conversation."""
        from tempfile import TemporaryDirectory

        from ..extensions import modules

        identifier = (query.get("agent") or [""])[0]
        for module in modules():
            factory = getattr(module, "session_adapter", None)
            if factory and any(agent["id"] == identifier and agent["kind"] == "acp" and agent["installed"]
                               for agent in getattr(module, "agents", lambda: [])()):
                break
        else:
            raise ValueError("choose an installed ACP adapter")

        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            adapter = factory(identifier, folder / "probe", cwd=folder, isolation=None, model=None, effort=None)
            try:
                adapter.open("", ())
                selected = (query.get("model") or [""])[0]
                if selected:
                    adapter.set_model(model=selected)
                config = adapter.capabilities.get("config_options") or []
                option = next((item for item in config if item.get("category") == "model"), {})
                choices = [choice for item in option.get("options", [])
                           for choice in item.get("options", [item])]
                models = [{"id": choice["value"], "name": choice.get("name") or choice["value"]}
                          for choice in choices if isinstance(choice.get("value"), str) and choice["value"]]
                effort = next((item for item in config if item.get("category") == "thought_level"), {})
                efforts = [choice["value"] for item in effort.get("options", [])
                           for choice in item.get("options", [item])
                           if isinstance(choice.get("value"), str) and choice["value"]]
            except (RuntimeError, OSError) as error:
                raise ValueError(str(error)) from error
            finally:
                adapter.close()
        self._json({"models": models, "efforts": efforts})

    def get_app_models(self, query):
        app = self.server.app
        self._json({"models": app.models(), "path": str(app.directory / "models.json")})

    def post_app_models(self, body):
        self._json({"models": self.server.app.models(body)})

    def get_app_models_settings(self, query):
        self._file(Path(__file__).parents[1] / "builtin" / "model-settings.js", "text/javascript; charset=utf-8")

    def get_app_models_catalog(self, query):
        identifier = (query.get("provider") or [""])[0]
        if identifier.startswith("acp:"):
            return self.get_app_agent_models({**query, "agent": [identifier]})
        app = self.server.app
        app.credentials.load()
        self._json({"models": providers.catalog(app.directory, identifier)})

    def post_app_model(self, body):
        self._json(self.server.app.set_model(body))

    def post_tasks(self, body):
        confirmation = {"always": "always", "never": "never"}.get(body.get("confirmation"))
        self._json({"run": self.server.app.start(self.server, body.get("text"), body.get("model"), confirmation,
                                                 body.get("workspace") or None, body.get("runtime") or None,
                                                 body.get("files") or (), body.get("reasoning_effort"),
                                                 body.get("profile") or None,
                                                 agent=body.get("agent"), folder=body.get("folder"),
                                                 isolation=body.get("isolation"), frontend=body.get("frontend"),
                                                 mcp_tools=body.get("mcp_tools") or (),
                                                 model_entry=body.get("model_entry"), library=body.get("library"), budget=body.get("budget"))})

    def post_conversations_handoff(self, body):
        source = self.server.conversations.resolve(body.get("run"))
        if source is None:
            self.server.directory(body.get("run"))
            source = body["run"]
        current = self.server.conversations.get(source)
        metadata = getattr(current, "session_metadata", {})
        agent, context = body.get("agent"), str(body.get("context") or "").strip()
        if not context or not isinstance(agent, str) or not agent:
            raise ValueError("handoff requires an agent and the context approved by the user")
        if getattr(current, "status", None) in ("RUNNING", "WAITING_FOR_CONFIRMATION", "WAITING_FOR_INPUT"):
            raise ValueError("stop the active turn before handing off")
        if agent == "harness":
            folder = metadata.get("project") or (metadata.get("workspace") or {}).get("folder")
            run = self.server.app.start(self.server, context, workspace=getattr(current, "workspace_kind", None),
                                        folder=folder if getattr(current, "workspace_kind", None) == "project" else None)
            conversation = self.server.conversations[run]
            conversation.session_metadata = {"handoff_from": source, "project": metadata.get("project")}
            self.server.conversations.save_metadata(run)
        else:
            run = self.server.app.start_external(
                self.server, agent, context, (), body.get("folder") or metadata.get("project"),
                body.get("isolation"), body.get("frontend"), None, None, handoff=source)
        self._json({"run": run})

    def post_sessions_import(self, body):
        from ..core import atomic_write
        from ..extensions import first
        from .sessions import history

        importer = first("import_session")
        if importer is None or not isinstance(body.get("file"), str) or not body["file"]:
            raise ValueError("enable the external-agents package and choose one native transcript")
        app = self.server.app
        with app._external_start_lock:
            directory = app.conversations_dir / runs.new_name()
            adapter = importer(directory, body.get("provider"), body["file"], body.get("follow") is True)
            rows = self.server.conversations.sessions()
            index = self.server.conversations.index
            rows += history(index, skip={row["id"] for row in rows}) if index else []
            fields = ("kind", "adapter_id", "external_id", "cwd")
            duplicate = next((row for row in rows if all(
                row["metadata"].get(key) == adapter.session_metadata.get(key) for key in fields)), None)
            if duplicate is not None:
                # The new trace is still empty and belongs to this request.
                (directory / "events.jsonl").unlink()
                directory.rmdir()
                return self._json({"run": duplicate["run"], "id": duplicate["id"]})
            name = session_title(f"{body['provider']} {adapter.session_metadata['external_id']}", 60)
            atomic_write(directory / "meta.json", json.dumps({"title": name, "created": time.time()}))
            run = directory.relative_to(self.server.root).as_posix()
            identifier = self.server.conversations.add(run, adapter, title=name, frontend="import")
            adapter.trace.subscribe(app._watcher())
            adapter.start("", ())
        self._json({"run": run, "id": identifier})

    def post_sessions_discover(self, body):
        from ..extensions import first

        discover = first("discover_sessions")
        agent = str(body.get("agent") or "")
        if discover is None or not agent or not (body.get("folder") or agent.startswith("cloud:")):
            raise ValueError("choose a configured agent and project directory")
        self._json(discover(agent, body.get("folder"), body.get("cursor")))

    def post_sessions_observe(self, body):
        agent, identifier = body.get("agent"), body.get("external_id")
        if (not isinstance(agent, str) or not agent.startswith(("cloud:", "acp:")) or not isinstance(identifier, str)
                or not identifier or len(identifier) > 256):
            raise ValueError("choose an ACP or cloud adapter and an external session ID")
        with self.server.app._external_start_lock:
            run = self.server.app.start_external(self.server, agent, "", (), body.get("folder"), None,
                                                 body.get("frontend"), None, None, observe=identifier)
        self._json({"run": run})

    def post_conversations_reconnect(self, body):
        from .sessions import history

        if body.get("released") is not True:
            raise ValueError("confirm the previous controller has stopped before reconnecting")
        app = self.server.app
        with app._external_start_lock:
            active = self.server.conversations.sessions()
            index = self.server.conversations.index
            rows = active + (history(index, skip={row["id"] for row in active}) if index else [])
            row = next((row for row in rows if body.get("run") in (row["run"], row["id"])), None)
            if row is None or row["live"]:
                raise ValueError("the original session must be known and disconnected")
            metadata = row["metadata"]
            name = body.get("agent") or metadata.get("adapter_id")
            if not isinstance(name, str) or not name.startswith("acp:") or not metadata.get("external_id"):
                raise ValueError("original session recovery needs an ACP adapter and native session ID")
            if metadata.get("kind") == "acp" and name != metadata.get("adapter_id"):
                raise ValueError("use the original adapter to reconnect an ACP session")
            if metadata.get("kind") not in ("acp", "observed"):
                raise ValueError("this source does not support ACP recovery")
            run = app.start_external(self.server, name, "", (), metadata.get("cwd"), None,
                                     row["frontend"], None, None, reconnect=row)
        self._json({"run": run, "id": row["id"]})

    def get_app_screen(self, query):
        run = (query.get("run") or [""])[0] or None
        try:
            image = self.server.app.workspaces.screen(run)
        except (OSError, ValueError, KeyError) as error:
            return self._error(HTTPStatus.SERVICE_UNAVAILABLE, f"no screen: {error}")
        if image is None:
            return self._error(HTTPStatus.SERVICE_UNAVAILABLE, "no workspace of this conversation is running")
        self._send(HTTPStatus.OK, image, "image/jpeg")

    def get_app_environments(self, query):
        self._json(self.server.app.environments((query.get("model_entry") or [""])[0] or None))

    def get_app_settings(self, query):
        from ..settings import described

        self._json({"values": self.server.app.settings.get(), "schema": described()})

    def post_app_settings(self, body):
        self._json({"values": self.server.app.settings.update(body)})

    def get_app_learning(self, query):
        self._json(self.server.app.progress(self.server, (query.get("run") or [""])[0]))

    def get_app_skills(self, query):
        self._json(self.server.app.skills())

    def post_app_skills_switch(self, body):
        self._json(self.server.app.switch_skill(str(body.get("name")), bool(body.get("on"))))

    def get_app_packages(self, query):
        self._json(self.server.app.packages_state())

    def get_app_packages_search(self, query):
        try:
            found = self.server.app.packages.search((query.get("q") or [""])[0])
            self._json({"results": [{**row, "shown": describe(row)} for row in found]})
        except RegistryError as error:
            self._json({"results": [], "error": str(error)})

    def get_app_packages_info(self, query):
        found = self.server.app.packages.info((query.get("name") or [""])[0])
        self._json({**found, "shown": describe(found)})

    def post_app_packages_install(self, body):
        self._json(self.server.app.install_packages(body))

    def post_app_packages_remove(self, body):
        self.server.app.packages.remove([str(body.get("name"))], log=lambda message: None)
        self._json(self.server.app.packages_state())

    def post_app_packages_update(self, body):
        self.server.app.packages.update(body.get("names") or [], log=lambda message: None)
        self._json(self.server.app.packages_state())

    def post_app_packages_enable(self, body):
        self.server.app.packages.enable(str(body.get("name")), bool(body.get("on")))
        self._json(self.server.app.packages_state())

    def post_conversations_agents(self, body):
        """Switch sub-agents on for a running conversation (the user's own switch)."""
        self._conversation(body).enable_agents()
        self._json({"ok": True})

    def post_app_takeover(self, body):
        self._conversation(body).pause()
        self._json({"ok": True})

    def post_app_handback(self, body):
        self._conversation(body).send_message(HANDBACK)
        self._json({"ok": True})


class TaskServer(Server):
    """The GUI's server with the app's routes, over the app's conversations."""

    page = "app.html"
    handler_class = TaskHandler

    def __init__(self, address, app: TaskHost, token: str | None = None):
        self.app = app
        super().__init__(address, app.directory, token=token)

    def sub_agents(self, kind):
        return self.app.sub_agents(self, kind)

    def model_changed(self, run, changed):
        self.app.model_changed(self, run, changed)

    def info(self) -> dict:
        return {**super().info(), "app": True, "handback": HANDBACK}

    def workspace(self, request: dict, experiment):
        """A workspace of the kind the conversation asked for (POST /api/conversations {workspace}),
        from the app's pool, for an experiment of the bench that serves it."""
        kind = request.get("workspace")
        if not kind:
            return None
        workspaces = self.app.workspaces
        kind = workspaces.kind(kind)
        workspaces.require_choices(kind)
        if workspaces.bench(kind) != experiment.bench:
            raise ValueError(f"a {kind} workspace runs the {workspaces.bench(kind)} bench; this experiment runs "
                             f"{experiment.bench}")
        key = f"session-{secrets.token_hex(4)}"
        worker = workspaces.acquire(key, kind, log=lambda message: None)
        return {"kind": kind, "endpoint": worker.endpoint,
                "environment": (RemoteEnvironment(worker.endpoint, timeout=600, approval_key=worker.approval_key)
                                if getattr(worker, "approval_key", None) else None),
                "python": worker.python if worker.python != sys.executable else None,
                "release": lambda: workspaces.release(key)}
