"""What an agent's model learns about the user's windows: the window-details policy.

An agent owns the windows it launched, the ones window ownership gives it
(coordination.py WindowOwners: a window it chose to work in, use_window or a step into
it, as far as the physical-input policy let it; one its parent handed it) and every
window of a display workspace's own display. Of those the model learns everything: the
app, the title, the picture, the elements. Of every other window it learns only what this
policy allows; the user's own tools (the live view, an approval card, the trace's
`input` records) still name them.

Levels, strictest first (LEVELS):

  none      nothing: not even that another window is in front
  presence  only that another window is in front, nothing about it (the default)
  apps      the app (its process name) of the other windows too; windows() lists them
            with their app, so the agent can choose one to work in
  titles    their titles too

A rule ({level, session, agent, workspace, app, window}) sets the level where its scopes
match: a session, an agent, a workspace kind (desktop, apps, display), an app (its process
name, a glob: "code", "chrome*") and a window (a part of its title, or a glob). As in the
physical-input policy, the most specific matching rule wins (more scopes first, then the
narrower scope: window, app, workspace, agent, session; then the later rule); none
matching leaves the default level.

The user sets it in every frontend (the settings' `privacy` section: the app's Settings,
`harness settings`, /settings in harness) and per run (`harness chat --window-details LEVEL`, `harness
run --window-details LEVEL`: runtime.privacy). Standard library only.
"""

import fnmatch
from pathlib import Path

from harness_computer.physical import app_name

LEVELS = ("none", "presence", "apps", "titles")
DEFAULT_LEVEL = "presence"
# The scopes of a rule, narrowest first: on equal counts the narrower one wins.
SCOPES = ("window", "app", "workspace", "agent", "session")
WORKSPACES = ("desktop", "apps", "display")
MAX_RULES = 200
# How the model names a window it may not know more of.
OTHER = "another window"


def check_rule(rule) -> dict:
    """A rule as kept: its level and the scopes it sets (ValueError when it is not one)."""
    if not isinstance(rule, dict):
        raise ValueError("a rule is {level, session, agent, workspace, app, window}")
    unknown = set(rule) - {"level", "note", *SCOPES}
    if unknown:
        raise ValueError(f"a rule has no {', '.join(sorted(unknown))}")
    if rule.get("level") not in LEVELS:
        raise ValueError(f"a rule's level is one of {', '.join(LEVELS)}")
    checked = {"level": rule["level"]}
    for scope in SCOPES:
        value = rule.get(scope)
        if value is None or value == "":
            continue
        value = str(value).strip()
        if scope == "workspace" and value not in WORKSPACES:
            raise ValueError(f"a rule's workspace is one of {', '.join(WORKSPACES)}")
        if scope == "app":
            value = app_name(value) or value
        if len(value) > 200:
            raise ValueError(f"a rule's {scope} has at most 200 characters")
        checked[scope] = value
    if rule.get("note"):
        checked["note"] = str(rule["note"])[:200]
    return checked


def check_rules(rules) -> list[dict]:
    if not isinstance(rules, (list, tuple)):
        raise ValueError("rules are a list of {level, session, agent, workspace, app, window}")
    if len(rules) > MAX_RULES:
        raise ValueError(f"at most {MAX_RULES} rules")
    return [check_rule(rule) for rule in rules]


def _matches(rule: dict, where: dict) -> bool:
    for scope in SCOPES:
        wanted = rule.get(scope)
        if wanted is None:
            continue
        if scope == "app":
            if not where.get("app") or not fnmatch.fnmatchcase(app_name(where["app"]) or "", app_name(wanted) or ""):
                return False
        elif scope == "window":
            title, pattern = (where.get("title") or "").lower(), wanted.lower()
            if not title or not (fnmatch.fnmatchcase(title, pattern) if any(c in pattern for c in "*?[")
                                 else pattern in title):
                return False
        elif str(where.get(scope) or "") != wanted:
            return False
    return True


class Policy:
    """A default level and the rules over it."""

    def __init__(self, level: str = DEFAULT_LEVEL, rules=()):
        if level not in LEVELS:
            raise ValueError(f"the level is one of {', '.join(LEVELS)}")
        self.level = level
        self.rules = check_rules(list(rules))

    @classmethod
    def from_settings(cls, section: dict | None, extra=()) -> "Policy":
        """The policy of the settings' `privacy` section, with `extra` rules after the
        settings' (a run's)."""
        section = dict(section or {})
        return cls(section.get("level", DEFAULT_LEVEL), [*(section.get("rules") or []), *extra])

    def level_for(self, window: dict | None, **where) -> str:
        """The level for a window the agent does not own ({app, title}) in `where`
        (session, agent, workspace)."""
        where = {**where, "app": (window or {}).get("app"), "title": (window or {}).get("title")}
        found = [(len([scope for scope in SCOPES if scope in rule]),
                  tuple(-SCOPES.index(scope) for scope in SCOPES if scope in rule), position, rule)
                 for position, rule in enumerate(self.rules) if _matches(rule, where)]
        return max(found, key=lambda item: item[:3])[3]["level"] if found else self.level


def shown(window: dict | None, level: str) -> dict | None:
    """What the model may learn of a window it does not own at `level`: None (nothing), {}
    (that it is there), {"app"} or {"app", "title"} (those it has)."""
    if not window or level == "none":
        return None
    if level == "presence":
        return {}
    keys = ("app",) if level == "apps" else ("app", "title")
    return {key: window[key] for key in keys if window.get(key)}


class View:
    """The policy where windows are seen (a worker): the user's settings (read again when
    the file changes) and a run's level and rules over them."""

    def __init__(self, settings_file):
        self.settings_file = Path(settings_file)
        self._cached = (None, None)
        self.run_level, self.run_rules = None, []

    def identify(self, level=None, rules=()) -> dict:
        """A run's level (in place of the settings' default) and rules (after theirs)."""
        if level is not None and level not in LEVELS:
            raise ValueError(f"the window-details level is one of {', '.join(LEVELS)}")
        self.run_level, self.run_rules = level, check_rules(list(rules or []))
        return {"level": level, "rules": self.run_rules}

    def settings(self) -> dict:
        from harness.sdk import Settings

        try:
            status = self.settings_file.stat()
            stamp = (status.st_mtime_ns, status.st_ino, status.st_size)
        except OSError:
            stamp = None
        if stamp != self._cached[0] or self._cached[1] is None:
            self._cached = (stamp, Settings(self.settings_file.parent).get()["privacy"])
        return self._cached[1]

    def policy(self) -> Policy:
        section = self.settings()
        try:
            policy = Policy.from_settings(section, self.run_rules)
        except ValueError:
            policy = Policy(DEFAULT_LEVEL, self.run_rules)
        if self.run_level is not None:
            policy.level = self.run_level
        return policy

    def shown(self, window: dict | None, **where) -> dict | None:
        """What the model may learn of a window the agent does not own (see shown())."""
        if not window:
            return None
        return shown(window, self.policy().level_for(window, **where))
