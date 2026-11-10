"""The user's configuration: one file, config.toml in the data directory
(~/.harness/config.toml), with

    [model]        the model chosen (providers.py) and its advanced settings (SCHEMA)
    [keys]         the keys given to the harness (Credentials), readable by the user only
    [packages]     packages.auto_install and packages.registry, the installed packages
                   ([packages.installed.<name>], packages/state.py) and the trusted projects
    [general] ...  the settings the user changes in Settings (SCHEMA), and the sections
                   other modules keep (connectors, skills)

A project adds a harness.toml of its own (its [packages] and harness.lock). The files of
earlier versions (settings.json, model.json, credentials.env, packages.toml) are merged
into config.toml the first time it is read, and no longer read after that.

Each value has a default, a kind and its bounds (SCHEMA); update() takes a section's
changes, checks them and keeps the file. The settings reach a conversation when it
starts (App.config): its budget, its skills (sub-agents while limits.agent_depth allows
them), the model's advanced settings, the user's instructions; the computer's settings reach a workspace's worker when it starts, and
its limits (workspaces, chromes, displays) the workspace pool at once; the physical-input
policy and what the model learns of the user's windows are read by the workers each time
they change (the computer package's sections: its settings.toml).
Settings are changed from the app's page and the terminal chat's /settings.
"""

from collections import namedtuple
from collections.abc import Mapping
import json
import os
from pathlib import Path
import threading
import tomllib

from .config import dumps
from .core import atomic_write


# One setting: `applies` is now, next_conversation or app_start; a list of rules has the fields a
# rule names besides its level ({name: "text", "id", "float" or its choices}), the rule a page
# adds, and any additional fields keyed by level.
Setting = namedtuple("Setting", "default kind bounds about applies fields example fields_when",
                     defaults=("next_conversation", None, None, None))
# (default, kind, choices or (min, max), what it is[, applies]). Kinds: choice, bool, int,
# float, text, rules (a list of the section's rules, at most max of them, checked by the row's check).
_CORE_SCHEMA = {section: {key: Setting(*row) for key, row in rows.items()} for section, rows in {
    "general": {
        "language": ("system", "choice", ("system", "zh", "en"), "the page's language (system: the browser's)", "now"),
        "theme": ("system", "choice", ("system", "light", "dark"), "light or dark (system: the computer's)", "now"),
        "open_browser": (True, "bool", None, "open the page in the browser when the app starts", "app_start"),
        "notifications": (True, "bool", None, "a notification when the agent asks or finishes, while the page "
                                              "is in the background", "now"),
    },
    "model": {
        "reasoning_effort": ("default", "choice", ("default", "low", "medium", "high"),
                             "how much the model reasons before it answers (default: the provider's)"),
        "max_output_tokens": (0, "int", (0, 200000), "tokens per reply (0: the harness's default)"),
        "checker": ("", "text", (0, 200), "a model of the same provider that checks the result (empty: the "
                                          "model itself)"),
        "vision": ("", "text", (0, 200), "a model of the same provider that reads images, asked to describe a "
                                         "view when the main model reads none (empty: such a model is told the "
                                         "view was not sent and works from text)"),
        "think_while_acting": ("default", "choice", ("default", "off", "on", "on_events", "periodic"),
                               "one speculative thought during a long program. Legacy on_events and periodic mean on"),
        "think_interval": (0, "int", (0, 600), "accepted for older configurations"),
    },
    "session": {
        "environment": ("ask", "text", (0, 40),
                        "where a new conversation works when none is named: ask (ask every new conversation, the last "
                        "choice highlighted), last (the last choice again, without asking), or one kind (none, project, "
                        "browser, apps, desktop, display: those the installed packages give)", "next_conversation"),
        "agents": ("off", "choice", ("off", "on"),
                   "sub-agents in new conversations: off (their calls and prompt are not loaded; you can switch "
                   "them on in a conversation, and the agent may ask you to), on (loaded from the start, as deep "
                   "as limits.agent_depth allows)"),
    },
    "environments": {
        "attach": ("ask_once_session", "choice", ("never", "ask_each", "ask_once_session", "allow"),
                   "when an agent may take another environment into its conversation (a project task that needs "
                   "to see a page takes the browser or your desktop), where no rule says otherwise: never, ask "
                   "each time, ask once per conversation and kind, allow. Each attachment and its reason is shown "
                   "and recorded whether or not it asked. When you skip confirmations (physical.level allow) it "
                   "does not ask; never still refuses", "now"),
        "rules": ([], "rules", (0, 50),
                  "a level for one environment kind (desktop, apps, display, browser, project); it wins over "
                  "environments.attach", "now", {"kind": "text"}, {"level": "never", "kind": "desktop"}),
    },
    "approvals": {
        "ask": ("sensitive", "choice", ("sensitive", "programs"),
                "what waits for your approval: sensitive (steps that touch credentials, a payment, sending, deleting "
                "or cannot be undone; they always wait) or programs (every program as well)"),
    },
    "limits": {
        "max_steps": (60, "int", (1, 1000), "model calls a task may take"),
        "max_minutes": (360, "int", (1, 1440), "minutes a conversation may run"),
        "max_cost_usd": (5.0, "float", (0.01, 1000.0), "dollars a conversation may spend on the model"),
        "agent_depth": (1, "int", (0, 4), "how deep agents start sub-agents (their budgets come out of the "
                                          "conversation's): 0 none, 1 the conversation's agent does and they do "
                                          "not, 2 theirs do too"),
    },
    "learning": {
        "mode": ("on", "choice", ("on", "replay_always", "frozen"),
                 "default mode for explicitly selected learning libraries (legacy paths under "
                 "$HARNESS_HOME/libraries): on (keep observations and proposals; use executable entries once "
                 "a trusted verifier has checked them and they are activated); replay_always (also independently "
                 "recheck eligible entries at the start of ordinary conversations); frozen (read one snapshot)"),
        "active_minutes": (30, "int", (1, 240), "minutes of live time a \"learn this environment\" conversation "
                                                "takes (the app's Learn, /learn, harness run --learn)"),
    },
    "packages": {
        "auto_install": ("official", "choice", ("official", "ask", "off"),
                         "when a task needs an embodiment, bench, skill or service no installed package provides: "
                         "official (install the registry's package that provides it), ask (ask first), off (stop "
                         "and say which package to install)", "now"),
        "registry": ("", "text", (0, 300), "where packages come from: an https address or a folder of a registry "
                                           "(empty: harness.lmms-lab.com; $HARNESS_REGISTRY wins over it)", "now"),
    },
    "data": {
        "keep_days": (0, "int", (0, 3650), "conversations older than this are deleted when the app starts (0: "
                                           "kept)", "app_start"),
    },
}.items()}


class _Schema(Mapping):
    """The core's sections and those packages add in their settings.toml, one table per
    setting with its default, kind, bounds (choices for a choice) and what it is:

        [kit.speed]
        default = 1.0
        kind = "float"
        bounds = [0.1, 10.0]
        about = "how fast the kit moves"

    with applies, fields, example and fields_when as in Setting (a section's applies: its rows' default).
    A row may name what checks its value (check = "module:function", returning the value as
    kept or raising ValueError): a list of rules, a text of a form of its own. A package's
    section of a name the core has is left out."""

    def __init__(self, core):
        self._core = core
        self._cache = (None, core)
        self._checks = {}

    @staticmethod
    def _row(row: dict, applies: str) -> Setting:
        bounds = row.get("choices", row.get("bounds"))
        return Setting(row.get("default"), row.get("kind", "text"), tuple(bounds) if bounds is not None else None,
                       row.get("about", ""), row.get("applies", applies), row.get("fields"), row.get("example"),
                       row.get("fields_when"))

    def _sections(self) -> dict:
        from .paths import find

        files = tuple(find("settings.toml"))
        if files != self._cache[0]:
            sections = dict(self._core)
            checks = {}
            for path in files:
                with path.open("rb") as handle:
                    for section, keys in tomllib.load(handle).items():
                        if section in self._core or not isinstance(keys, dict):
                            continue
                        sections[section] = {key: self._row(row, keys.get("applies", "next_conversation"))
                                             for key, row in keys.items() if isinstance(row, dict)}
                        checks.update({(section, key): row["check"] for key, row in keys.items()
                                       if isinstance(row, dict) and row.get("check")})
            self._cache, self._checks = (files, sections), checks
        return self._cache[1]

    def __getitem__(self, section):
        return self._sections()[section]

    def checker(self, section: str, key: str):
        """The function that checks section.key's value, when its row names one."""
        import importlib

        self._sections()
        reference = self._checks.get((section, key))
        if reference is None:
            return None
        module, _, attribute = reference.partition(":")
        return getattr(importlib.import_module(module), attribute)

    def __iter__(self):
        return iter(self._sections())

    def __len__(self):
        return len(self._sections())


SCHEMA = _Schema(_CORE_SCHEMA)


# The configuration file, and the files of earlier versions merged into it once.
FILE = "config.toml"
OLD_FILES = ("settings.json", "model.json", "credentials.env", "packages.toml")
# The app's provider key.
KEY = "OPENROUTER_API_KEY"
COMMENT = "The Harness: your configuration (/settings in harness, the app's Settings)."
# Not settings: never in get(), never written by put() ([model] is a SCHEMA section too).
PRIVATE = ("model", "keys")


def defaults() -> dict:
    return {section: {key: (list(spec[0]) if isinstance(spec[0], list) else spec[0]) for key, spec in keys.items()}
            for section, keys in SCHEMA.items()}


def check(section: str, key: str, value):
    """`value` for section.key as its kind takes it, or ValueError."""
    if section not in SCHEMA or key not in SCHEMA[section]:
        raise ValueError(f"no setting {section}.{key}")
    kind, bounds = SCHEMA[section][key].kind, SCHEMA[section][key].bounds
    checker = SCHEMA.checker(section, key) or _CORE_CHECKS.get((section, key))
    if checker is not None and kind != "rules":
        try:
            return checker(value)
        except ValueError as error:
            raise ValueError(f"{section}.{key}: {error}") from None
    if kind == "choice":
        if value not in bounds:
            raise ValueError(f"{section}.{key} is one of {', '.join(bounds)}")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{section}.{key} is true or false")
        return value
    if kind == "rules":
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{section}.{key} is a list of rules")
        if len(value) > bounds[1]:
            raise ValueError(f"{section}.{key} has at most {bounds[1]} rules")
        if checker is None:
            raise ValueError(f"{section}.{key}: nothing checks its rules here")
        try:
            return checker(value)
        except ValueError as error:
            raise ValueError(f"{section}.{key}: {error}") from None
    if kind in ("int", "float"):
        if isinstance(value, bool):
            raise ValueError(f"{section}.{key} is a number")
        try:
            number = int(value) if kind == "int" else float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{section}.{key} is a number") from None
        if kind == "int" and float(value) != number:
            raise ValueError(f"{section}.{key} is a whole number")
        low, high = bounds
        if not low <= number <= high:
            raise ValueError(f"{section}.{key} is between {low} and {high}")
        return number
    text = str(value if value is not None else "").strip()
    if len(text) > bounds[1]:
        raise ValueError(f"{section}.{key} has at most {bounds[1]} characters")
    return text


def _environment(value):
    """session.environment: ask, last, or the name of a workspace kind (checked against the
    installed packages when a conversation starts)."""
    import re

    text = str(value if value is not None else "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", text):
        raise ValueError("ask, last, or a workspace kind (none, project, browser, apps, desktop, display)")
    return text


def _attach_rules(value):
    """environments.rules: each {"level": one of environments.attach's, "kind": a workspace kind},
    one rule per kind."""
    levels = _CORE_SCHEMA["environments"]["attach"].bounds
    rules, seen = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"level", "kind"}:
            raise ValueError("a rule is {level, kind}")
        kind = _environment(row["kind"])
        if row["level"] not in levels:
            raise ValueError(f"a rule's level is one of {', '.join(levels)}")
        if kind in ("ask", "last", "none") or kind in seen:
            raise ValueError(f"one rule for each workspace kind; {kind!r} cannot have one here")
        seen.add(kind)
        rules.append({"level": row["level"], "kind": kind})
    return rules


# What checks a core setting whose kind's own check is not enough.
_CORE_CHECKS = {("session", "environment"): _environment, ("environments", "rules"): _attach_rules}


# One change at a time in this process (the page's requests come on threads of their own).
_WRITING = threading.RLock()


def path(directory) -> Path:
    return Path(directory) / FILE


def read(directory) -> dict:
    """The whole configuration file ({} when there is none), the files of earlier
    versions merged into it first."""
    file = path(directory)
    if not file.is_file() and any((Path(directory) / name).is_file() for name in OLD_FILES):
        with _WRITING:
            if not file.is_file():
                write(directory, _merged_old(Path(directory)))
    try:
        with file.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data


def write(directory, data: dict) -> None:
    """Keep the whole configuration file (readable by the user only: it holds keys)."""
    atomic_write(path(directory), dumps(data, COMMENT), private=True)


def change(directory, function) -> dict:
    """Read the file, let `function` change the data in place, keep it; returns the data."""
    with _WRITING:
        data = read(directory)
        function(data)
        write(directory, data)
        return data


def env_file(path) -> dict:
    """NAME=value (or `export NAME=value`) lines of an env file ({} when there is none)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    values = {}
    for line in text.splitlines():
        name, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and name.strip().isidentifier():
            values[name.strip()] = value.strip().strip("\"'")
    return values


class Credentials:
    """The providers' keys (providers.KEY_NAMES), loaded here only: from the environment or
    [keys] of the user's config.toml (put into this process's environment on load); a key
    given in a frontend goes to [keys] (the file is readable by the user only)."""

    def __init__(self, directory: Path, names=None):
        from .providers import KEY_NAMES

        self.directory = Path(directory)
        self.file = path(directory)
        self.names = list(names or KEY_NAMES)
        self.sources = {}

    @property
    def source(self):
        return self.sources.get(KEY)

    def _kept(self) -> dict:
        return {str(name): str(value) for name, value in (read(self.directory).get("keys") or {}).items()}

    def load(self) -> None:
        kept = self._kept()
        for name in self.names:
            if os.environ.get(name):
                self.sources[name] = "environment"
                continue
            if kept.get(name):
                os.environ[name] = kept[name]
                self.sources[name] = str(self.file)

    def status(self, name: str = KEY) -> dict:
        return {"set": bool(os.environ.get(name)), "source": self.sources.get(name), "name": name}

    def save(self, value: str, name: str = KEY) -> None:
        value = value.strip()
        self.keep(name, value)
        os.environ[name] = value
        self.sources[name] = str(self.file)

    def secret(self, name: str) -> str | None:
        """A secret kept for a connector (only in [keys]: never put into the
        environment, so no process the app starts inherits it)."""
        return self._kept().get(name) or None

    def keep(self, name: str, value: str | None) -> None:
        """Persist a key in [keys] of config.toml (None removes it), leaving the process
        environment and provider source tracking unchanged."""
        def apply(data):
            keys = data.setdefault("keys", {})
            if value is None:
                keys.pop(name, None)
            else:
                keys[name] = str(value).strip()

        change(self.directory, apply)


def _merged_old(directory: Path) -> dict:
    """settings.json, model.json, credentials.env and packages.toml as one configuration."""
    data = {}
    try:
        old = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
        data.update({key: value for key, value in old.items() if key != "keys"})
    except (OSError, ValueError, AttributeError):
        pass
    try:
        model = json.loads((directory / "model.json").read_text(encoding="utf-8"))
        if isinstance(model, dict):
            data.setdefault("model", {}).update({key: value for key, value in model.items() if value is not None})
    except (OSError, ValueError):
        pass
    keys = env_file(directory / "credentials.env")
    if keys:
        data["keys"] = keys
    try:
        with (directory / "packages.toml").open("rb") as handle:
            packages = tomllib.load(handle)
        section = data.setdefault("packages", {})
        section["installed"] = packages.get("packages", {})
        section["trusted_projects"] = packages.get("trusted_projects", [])
        section["addons_migrated"] = bool(packages.get("migrated", False))
    except (OSError, tomllib.TOMLDecodeError):
        pass
    return data


class ChoiceRequired(ValueError):
    """A user preference is unset; no task has started and no value was selected."""

    def __init__(self, choice):
        self.choice = choice
        super().__init__(choice.get("message")
                         or f"Choose {choice['section']}.{choice['key']} before using this capability")


class Settings:
    """The settings in config.toml (FILE) of a data directory, over the defaults.
    Sections other modules keep (connectors, skills) are stored as they give them."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.file = path(directory)

    def _read(self) -> dict:
        return read(self.directory)

    def require_choice(self, section, key, *, title, options, override=None):
        """Use an explicit valid value, never a schema default, for a user decision."""
        value = override if override is not None else self._read().get(section, {}).get(key)
        if value is not None:
            try:
                value = check(section, key, value)
                if any(option['value'] == value for option in options):
                    return value
            except ValueError:
                pass
        raise ChoiceRequired({"section": section, "key": key, "title": title, "options": options})

    def remembered(self, section, key):
        """What the harness itself kept under section.key (remember), or None: state beside
        the settings (the last environment a conversation chose), never a setting."""
        return (self._read().get(section) or {}).get(key)

    def remember(self, section, key, value) -> None:
        """Keep `value` under section.key for remembered() (None forgets it)."""
        if key in SCHEMA.get(section, {}):
            raise ValueError(f"{section}.{key} is a setting; use update()")

        def apply(saved):
            if value is None:
                saved.get(section, {}).pop(key, None)
            else:
                saved.setdefault(section, {})[key] = value

        change(self.directory, apply)

    def get(self) -> dict:
        """Every setting: the saved ones, the defaults for the rest (a saved value that no
        longer checks falls back to its default)."""
        saved = self._read()
        # limits.ask_before_acting (before 1.0) is approvals.ask = "programs".
        if (saved.get("limits") or {}).get("ask_before_acting") is True and "ask" not in (saved.get("approvals") or {}):
            saved.setdefault("approvals", {})["ask"] = "programs"
        values = defaults()
        for section, keys in SCHEMA.items():
            for key in keys:
                if key in (saved.get(section) or {}):
                    try:
                        values[section][key] = check(section, key, saved[section][key])
                    except ValueError:
                        pass
        for section, value in saved.items():
            if section not in SCHEMA and section not in PRIVATE:
                values[section] = value
        return values

    def update(self, changes: dict) -> dict:
        """Apply {section: {key: value}} (every value checked first) and keep the file."""
        if not isinstance(changes, dict):
            raise ValueError("send {section: {key: value}}")
        checked = {}
        for section, values in changes.items():
            if not isinstance(values, dict):
                raise ValueError(f"{section}: send {{key: value}}")
            checked[section] = {key: check(section, key, value) for key, value in values.items()}
        def apply(saved):
            for section, values in checked.items():
                saved.setdefault(section, {}).update(values)

        change(self.directory, apply)
        return self.get()

    def put(self, section: str, value) -> None:
        """Keep a section another module owns (connectors, skills) as it is."""
        if section in SCHEMA or section in PRIVATE:
            raise ValueError(f"{section} is not kept by put()")
        change(self.directory, lambda saved: saved.__setitem__(section, value))


def described() -> dict:
    """The schema as the pages read it: {section: {key: Setting as a dict}}."""
    return {section: {key: spec._asdict() for key, spec in keys.items()} for section, keys in SCHEMA.items()}


def rows(values: dict) -> list[dict]:
    """Every setting as a row of a list (the terminal chat's /settings, the app's Settings)."""
    return [{"setting": f"{section}.{key}", "section": section, "key": key, "kind": spec.kind,
             "value": values.get(section, {}).get(key, spec.default), "applies": spec.applies, "about": spec.about}
            for section, keys in SCHEMA.items() for key, spec in keys.items()]


def rule_fields(section: str) -> dict:
    """The fields a rule of `section` names besides its level; {} when it has no rules."""
    return next((dict(spec.fields or {}) for spec in SCHEMA.get(section, {}).values() if spec.kind == "rules"), {})

