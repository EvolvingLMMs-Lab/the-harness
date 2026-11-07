"""The physical-input policy: when an agent may use the user's real mouse and keyboard.

Physical input is one way an input step reaches a window, the last one tried (after a
semantic action and input sent to the window itself, which leave the user's mouse
alone). A policy is a level, scoped by rules, under conditions; the user sets it in every
frontend (the settings' `physical` section: the app's Settings, `harness settings`, the
terminal chat's /settings), per run (`harness chat --physical LEVEL --allow-app APP --deny-app APP`, `harness run
--physical LEVEL`), and in the conversation itself, when they answer an agent that asks.

Levels, strictest first (LEVELS):

  never             no physical input; a step that needs it is refused with the reason
  ask_each          ask before every step
  ask_once_app      ask the first time in each app, in this session
  ask_once_session  ask the first time in this session
  when_idle         only once the user has left the computer alone for `idle_seconds`,
                    and stop the moment they touch it
  allow             allowed; still in turn for the input lock, still yielding to the user

A run's level replaces the default for its session; its rules come after the user's.
A rule ({level, session, agent, app, window, action}) sets the level where its scopes
match: a session, an agent, an app (its process name, a glob: "wechat", "chrome*"), a
window (a part of its title, or a glob) and a kind of action (ACTIONS). The most specific
matching rule wins: more scopes first, then the narrower scope (window, app, agent,
session, action), then the later rule; none matching leaves the default level. A step of
several kinds (typing text is keys and the clipboard) takes the strictest of them.

Conditions: `idle_seconds` (when_idle; a rule may carry its own), `max_hold_seconds` (one
holder of the input lock gives it to the next in line after this long, between the pieces
of a long step), `yield_on_user_input` (a step is refused while the user uses the
computer) and `corner_stop` (the pointer in a corner of the screen stops the episode).

The default: ask_once_app, idle 2 s.

When a level asks, the worker refuses the step with a request (an id, the app, the window,
the actions); the agent's session asks the user (runtime/desktop.py, the conversation's
approval); the answer comes back to the worker (Gate.answer) as a grant for this session:
this step (once), this app (app), every app (session), or as a rule kept in the settings
(always). A grant lasts as long as the session; grants live in DATA/locks/sessions, so
every agent of a session shares them.

A worker that sends the user's real input (the computer worker, Minecraft) meets it all
through a PhysicalStep: the verdict, the user's hand (presence.py), the input lock (at
most LOCK_WAIT_SECONDS) and the window again once it is held, the step's record and
delivery, and the worker's `physical` method. Standard library only.
"""

from dataclasses import dataclass, field
import fnmatch
import json
import os
from pathlib import Path
import secrets
import time

from harness.sdk import REMEMBER, approval, atomic_write
from harness_computer.coordination import InputLock, WindowOwners, locks_dir, owner_name  # noqa: F401 (owner_name: for the workers)

LEVELS = ("never", "ask_each", "ask_once_app", "ask_once_session", "when_idle", "allow")
ASKING = ("ask_each", "ask_once_app", "ask_once_session")
# What an input step does physically: the pointer (a click, a scroll), a drag, keys, the
# clipboard (text is pasted through it) and bringing a window to the front.
ACTIONS = ("pointer", "drag", "keyboard", "clipboard", "foreground")
# The scopes of a rule, narrowest first: on equal counts the narrower one wins.
SCOPES = ("window", "app", "agent", "session", "action")
DEFAULT_LEVEL = "ask_once_app"
CONDITIONS = {"idle_seconds": 2.0, "max_hold_seconds": 3.0, "yield_on_user_input": True, "corner_stop": True}
# How long a step waits for the input lock, and (when_idle) for the user to leave the
# computer alone, before it is refused.
LOCK_WAIT_SECONDS = 120.0
IDLE_WAIT_SECONDS = 30.0
# A worker's `physical` option: the directory whose settings and locks it uses, and for every
# episode until its session identifies itself (physical op "identify"): session, agent,
# level, rules, interactive.
OPTIONS = ("data", "session", "agent", "level", "rules", "interactive")
# A one-step grant not used within this long lapses.
ONCE_SECONDS = 300.0
# Rules a list may hold.
MAX_RULES = 200


def check_rule(rule) -> dict:
    """A rule as kept: its level and the scopes it sets (ValueError when it is not one)."""
    if not isinstance(rule, dict):
        raise ValueError("a rule is {level, session, agent, app, window, action}")
    unknown = set(rule) - {"level", "idle_seconds", "note", *SCOPES}
    if unknown:
        raise ValueError(f"a rule has no {', '.join(sorted(unknown))}")
    level = rule.get("level")
    if level not in LEVELS:
        raise ValueError(f"a rule's level is one of {', '.join(LEVELS)}")
    checked = {"level": level}
    for scope in SCOPES:
        value = rule.get(scope)
        if value is None or value == "":
            continue
        value = str(value).strip()
        if scope == "action" and value not in ACTIONS:
            raise ValueError(f"a rule's action is one of {', '.join(ACTIONS)}")
        if scope == "app":
            value = app_name(value) or value
        if len(value) > 200:
            raise ValueError(f"a rule's {scope} has at most 200 characters")
        checked[scope] = value
    if rule.get("idle_seconds") is not None:
        seconds = rule["idle_seconds"]
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 <= seconds <= 3600:
            raise ValueError("a rule's idle_seconds is between 0 and 3600")
        checked["idle_seconds"] = float(seconds)
    if rule.get("note"):
        checked["note"] = str(rule["note"])[:200]
    return checked


def check_rules(rules) -> list[dict]:
    if not isinstance(rules, (list, tuple)):
        raise ValueError("rules are a list of {level, session, agent, app, window, action}")
    if len(rules) > MAX_RULES:
        raise ValueError(f"at most {MAX_RULES} rules")
    return [check_rule(rule) for rule in rules]


def app_name(name) -> str | None:
    """An app as rules name it: its process name, lowercase, without .exe or .app."""
    if not name:
        return None
    name = str(name).replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    for suffix in (".exe", ".app"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name or None


def actions_of(command: dict) -> list[str]:
    """What a desktop input step (runtime/safety/shield.py DESKTOP_COMMANDS) does physically; none
    for a wait."""
    kind = command.get("type")
    if kind in ("click", "scroll", "move"):
        return ["pointer"]
    if kind == "drag":
        return ["drag"]
    if kind == "key":
        return ["keyboard"]
    if kind == "type":
        return ["keyboard", "clipboard"]
    if kind == "focus":
        return ["foreground"]
    return []


def strictest(levels) -> str:
    return min(levels, key=LEVELS.index)


@dataclass
class Target:
    """Where a step goes: the window (`handle`, when the system gives one), its app and
    title, the session and agent the step is for, the kinds of action."""

    session: str | None = None
    agent: str | None = None
    app: str | None = None
    title: str | None = None
    handle: str | None = None
    actions: list = field(default_factory=list)

    def describe(self) -> dict:
        return {key: value for key, value in (("app", self.app), ("window", self.title), ("handle", self.handle),
                                              ("actions", list(self.actions))) if value}


def _matches(rule: dict, target: Target, action: str) -> bool:
    for scope in SCOPES:
        wanted = rule.get(scope)
        if wanted is None:
            continue
        if scope == "action":
            if wanted != action:
                return False
        elif scope == "app":
            if not target.app or not fnmatch.fnmatchcase(app_name(target.app), app_name(wanted) or ""):
                return False
        elif scope == "window":
            title = (target.title or "").lower()
            pattern = wanted.lower()
            if not title or not (fnmatch.fnmatchcase(title, pattern) if any(c in pattern for c in "*?[")
                                 else pattern in title):
                return False
        elif str(getattr(target, scope) or "") != wanted:
            return False
    return True


def _specificity(rule: dict, position: int) -> tuple:
    indices = sorted(SCOPES.index(scope) for scope in SCOPES if scope in rule)
    return (len(indices), tuple(-index for index in indices), position)


@dataclass
class Decision:
    """The level for a step: the rule that set it (None: the default), its idle time."""

    level: str
    rule: dict | None
    idle_seconds: float

    def describe(self) -> dict:
        return {"level": self.level, "rule": self.rule, **({"idle_seconds": self.idle_seconds}
                                                            if self.level == "when_idle" else {})}


class Policy:
    """A default level, the rules over it and the conditions (see the module docstring)."""

    def __init__(self, level: str = DEFAULT_LEVEL, rules=(), **conditions):
        if level not in LEVELS:
            raise ValueError(f"the level is one of {', '.join(LEVELS)}")
        self.level = level
        self.rules = check_rules(list(rules))
        self.conditions = {**CONDITIONS, **{key: value for key, value in conditions.items() if key in CONDITIONS}}

    @classmethod
    def from_settings(cls, section: dict | None, extra=()) -> "Policy":
        """The policy of the settings' `physical` section, with `extra` rules after the
        settings' (a run's)."""
        section = dict(section or {})
        return cls(section.get("level", DEFAULT_LEVEL), [*(section.get("rules") or []), *extra],
                   **{key: section[key] for key in CONDITIONS if key in section})

    def decide(self, target: Target) -> Decision:
        """The level for a step to `target`: the strictest over its actions."""
        decisions = [self._one(target, action) for action in (target.actions or ["pointer"])]
        return min(decisions, key=lambda decision: LEVELS.index(decision.level))

    def _one(self, target: Target, action: str) -> Decision:
        found = [(_specificity(rule, position), rule) for position, rule in enumerate(self.rules)
                 if _matches(rule, target, action)]
        idle = float(self.conditions["idle_seconds"])
        if not found:
            return Decision(self.level, None, idle)
        rule = max(found, key=lambda item: item[0])[1]
        return Decision(rule["level"], rule, float(rule.get("idle_seconds", idle)))


class Grants:
    """What the user granted (or refused) a session: one file under locks/sessions."""

    def __init__(self, session: str, directory=None):
        self.session = str(session)
        safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in self.session)[:80] or "_"
        self.path = locks_dir(directory) / "sessions" / f"{safe}.json"

    def _read(self) -> list[dict]:
        try:
            items = json.loads(self.path.read_text(encoding="utf-8")).get("grants") or []
        except (OSError, ValueError, AttributeError):
            return []
        now = time.time()
        return [item for item in items if not item.get("expires") or item["expires"] > now]

    def _write(self, items) -> None:
        atomic_write(self.path, json.dumps({"session": self.session, "grants": items}, ensure_ascii=False))

    def listed(self) -> list[dict]:
        return self._read()

    def add(self, kind: str, accept: bool, target: Target) -> dict:
        """Keep the user's answer: kind once (this step's app and actions), app or session."""
        item = {"kind": kind, "accept": bool(accept), "at": time.time()}
        if kind in ("once", "app"):
            item["app"] = app_name(target.app)
        if kind == "once":
            item.update(actions=list(target.actions), expires=time.time() + ONCE_SECONDS)
        self._write([*self._read(), item])
        return item

    def answer(self, level: str, target: Target) -> bool | None:
        """What the user said that covers a step at `level` (an asking one) to `target`:
        True (a grant; a once grant is used up), False (they refused it for the session),
        None (nothing: ask)."""
        items = self._read()
        app = app_name(target.app)
        for index, item in enumerate(items):
            if item["kind"] == "once" and item.get("app") == app and set(target.actions) <= set(item.get("actions")
                                                                                                  or []):
                if item["accept"]:
                    del items[index]
                    self._write(items)
                return item["accept"]
        if level == "ask_each":
            return None
        app_items = [item for item in items if item["kind"] == "app" and item.get("app") == app]
        session_items = [item for item in items if item["kind"] == "session"]
        # The latest answer that applies wins.
        chosen = (app_items + session_items) if level == "ask_once_app" else (session_items + app_items)
        if not chosen:
            return None
        return max(chosen, key=lambda item: item["at"])["accept"]


class Gate:
    """The policy where physical input happens (a worker): the user's settings (read again
    when the file changes), a run's rules, the session's grants, the input lock and the
    window owners, for one identity (session, agent) at a time."""

    def __init__(self, data=None, rules=(), level=None, session=None, agent="main", settings_file=None):
        from harness.sdk import data as data_dir

        self.data = Path(data) if data is not None else data_dir()
        self.locks = locks_dir(self.data / "locks")
        from harness.sdk import SETTINGS_FILE as FILE

        self.settings_file = Path(settings_file) if settings_file else self.data / FILE
        self.lock = InputLock(self.locks)
        self.windows = WindowOwners(self.locks)
        self._cached = (None, None)
        self.pending = {}
        self.interactive = True
        self.identify(session or f"worker-{os.getpid()}", agent, rules=rules, level=level)

    def identify(self, session, agent="main", rules=(), level=None, interactive=True) -> dict:
        """The session and agent the steps are for from now on, with the run's rules (a
        level for the whole run, rules over it); gives up the windows the one before owned."""
        previous = getattr(self, "owner", None)
        if previous is not None:
            self.windows.release_all(previous)
        self.session, self.agent = str(session), str(agent or "main")
        self.owner = {"session": self.session, "agent": self.agent}
        if level is not None and level not in LEVELS:
            raise ValueError(f"the level is one of {', '.join(LEVELS)}")
        # A run's level is its default (the user's rules still hold over it); its rules
        # come after the user's, so they win over equal ones.
        self.run_level = level
        self.run_rules = check_rules(list(rules or []))
        self.interactive = bool(interactive)
        self.grants = Grants(self.session, self.locks)
        self.pending = {}
        return {"session": self.session, "agent": self.agent, "level": level, "rules": self.run_rules}

    def settings(self) -> dict:
        """The settings' `physical` section (settings.py: checked, defaults where unset),
        read again when the file changes."""
        from harness.sdk import Settings

        try:
            # Each change replaces the file (settings.py), so its inode changes too: a
            # time of a second (ext3, network drives) alone misses a change within it.
            status = self.settings_file.stat()
            stamp = (status.st_mtime_ns, status.st_ino, status.st_size)
        except OSError:
            stamp = None
        if stamp != self._cached[0] or self._cached[1] is None:
            self._cached = (stamp, Settings(self.settings_file.parent).get()["physical"])
        return self._cached[1]

    def policy(self) -> Policy:
        section = self.settings()
        try:
                policy = Policy.from_settings(section, self.run_rules)
        except ValueError:
            # A settings file that no longer checks: its rules are left out, not the run's.
            policy = Policy.from_settings({key: value for key, value in section.items() if key in CONDITIONS},
                                          self.run_rules)
        if self.run_level is not None:
            policy.level = self.run_level
        return policy

    def target(self, window: dict | None, actions) -> Target:
        window = window or {}
        return Target(self.session, self.agent, window.get("app"), window.get("title"),
                      str(window["handle"]) if window.get("handle") is not None else None, list(actions))

    def decide(self, target: Target, shown: Target | None = None) -> dict:
        """What may happen to a step to `target` now: {"verdict": "allow" | "when_idle" |
        "refuse" | "ask", "level", "rule", ...}; an ask carries the request to put to the
        user (kept here until it is answered). The reasons name the window as `shown` has
        it (what the model may learn of it, privacy.py), the request as `target` does."""
        policy = self.policy()
        decision = policy.decide(target)
        result = {**decision.describe(), "conditions": dict(policy.conditions)}
        where = _where(shown or target)
        if decision.level == "never":
            return {**result, "verdict": "refuse",
                    "reason": f"the physical-input policy is never for {where}"}
        if decision.level in ASKING:
            answer = self.grants.answer(decision.level, target)
            if answer is False:
                return {**result, "verdict": "refuse", "reason": f"the user said no to physical input in "
                                                                  f"{where} for this session"}
            if answer is None:
                if not self.interactive:
                    return {**result, "verdict": "refuse",
                            "reason": f"the policy ({decision.level}) asks the user before physical input in "
                                      f"{where}, and nobody is there to ask in this run; allow it "
                                      "for the run (--physical allow) or with a rule"}
                request = {"id": secrets.token_hex(6), "level": decision.level, **target.describe()}
                self.pending = {request["id"]: (request, target)}
                return {**result, "verdict": "ask", "request": request,
                        "reason": f"physical input in {where} needs the user's approval "
                                  f"({decision.level})"}
        if decision.level == "when_idle":
            return {**result, "verdict": "when_idle"}
        return {**result, "verdict": "allow"}

    def answer(self, request_id: str, accept: bool, remember: str = "once") -> dict:
        """The user's answer to a request decide() made: kept as a grant of this session
        (once, app, session) or as a rule in the settings (always: this app, else every
        app, allowed or never)."""
        if remember not in REMEMBER:
            raise ValueError(f"remember is one of {', '.join(REMEMBER)}")
        found = self.pending.pop(str(request_id), None)
        if found is None:
            raise ValueError(f"no physical-input request {request_id} waits for an answer")
        request, target = found
        if remember == "always" and target.app:
            rule = {"level": "allow" if accept else "never", "app": app_name(target.app)}
            self.keep_rule(rule)
            return {"kept": "rule", "rule": rule}
        if remember == "always":
            remember = "session"
        if remember == "once" and not accept:
            # No to this step: it was not done, and the next one is asked again.
            return {"kept": None}
        item = self.grants.add(remember, accept, target)
        return {"kept": "grant", "grant": item}

    def keep_rule(self, rule: dict) -> None:
        """Add `rule` to the settings' rules (at the end: it wins over equal ones)."""
        from harness.sdk import Settings

        settings = Settings(self.settings_file.parent)
        rules = [item for item in settings.get()["physical"]["rules"]
                 if {k: v for k, v in item.items() if k != "level"} != {k: v for k, v in rule.items() if k != "level"}]
        settings.update({"physical": {"rules": [*rules, rule]}})
        self._cached = (None, None)


def _where(target: Target) -> str:
    what = "/".join(target.actions) or "input"
    if target.app:
        return f"{target.app} ({what})"
    if target.title:
        return f"{approval.say('label.the_window', title=repr(target.title))} ({what})"
    return f"{approval.say('label.this_window')} ({what})"


def run_rules(level=None, allow_apps=(), deny_apps=(), ask_apps=()) -> dict:
    """A run's physical-input policy from its flags: {"level", "rules"} (runtime.physical)."""
    rules = [*({"level": "allow", "app": app_name(app)} for app in allow_apps),
             *({"level": "ask_each", "app": app_name(app)} for app in ask_apps),
             *({"level": "never", "app": app_name(app)} for app in deny_apps)]
    if level is not None and level not in LEVELS:
        raise ValueError(f"--physical is one of {', '.join(LEVELS)}")
    return {**({"level": level} if level else {}), **({"rules": rules} if rules else {})}


def about(window) -> dict:
    """A window as a step's delivery names it: its app and title."""
    return {key: window[key] for key in ("app", "title") if window and window.get(key)}


def identity(window):
    """What tells two windows apart: the handle, else the app and title."""
    if not window:
        return None
    return window.get("handle") if window.get("handle") is not None else (window.get("app"), window.get("title"))


def refused(reason: dict, window=None, waited=None, approval=None, mechanism="physical") -> dict:
    """A step that did not reach the computer: the shield's reason and the delivery (the
    worker adds its state)."""
    result = {"executed": False, "shield": {"verdict": "rejected", "command": None, "reasons": [reason]},
              "delivery": {"mechanism": mechanism, "status": "not_delivered", **about(window),
                           **({"waited": round(waited, 3)} if waited is not None else {})}}
    if approval is not None:
        result["approval"] = approval
    return result


class PhysicalStep:
    """One worker's physical input: the gate, the user's hand (presence.UserPresence of
    `watch`, `pointer`, `front`) and the input lock. `options`: the worker's `physical`
    option (OPTIONS); `actions`: what a check names when it names none."""

    def __init__(self, options=None, watch=None, pointer=None, front=None, actions=("pointer",)):
        from harness_computer.presence import UserPresence

        options = dict(options or {})
        unknown = set(options) - set(OPTIONS)
        if unknown:
            raise ValueError(f"Unknown physical options: {sorted(unknown)}")
        self.defaults = {"session": options.get("session") or f"worker-{os.getpid()}",
                         "agent": options.get("agent") or "main", "level": options.get("level"),
                         "rules": options.get("rules") or (), "interactive": bool(options.get("interactive", True))}
        self.gate = Gate(data=options.get("data"))
        self.gate.identify(**self.defaults)
        self.presence = UserPresence(watch, pointer=pointer, front=front, lock=self.gate.lock,
                                     owner=lambda: self.gate.owner)
        self.actions = list(actions)

    def reset(self) -> None:
        """A new episode is the worker's own until its session identifies itself (and gives
        up the windows the one before owned)."""
        self.gate.identify(**self.defaults)

    def decide(self, window, actions, shown=None) -> dict:
        """The policy's verdict for a step into `window`, its reasons naming the window as
        `shown` has it (what the model may learn of it, privacy.py)."""
        target = self.gate.target(window, actions)
        return self.gate.decide(target, shown=self.gate.target(shown, actions) if shown is not None else None)

    def refusal(self, verdict, window=None, shown=None, idle_wait=True) -> dict | None:
        """The refusal a verdict makes of a step (None: it may go on): an asking level's
        carries the request (the model's copy names the window as `shown` does); when_idle
        waits up to IDLE_WAIT_SECONDS (with `idle_wait`) for the user to leave it alone."""
        reason = {"check": "physical", "level": verdict["level"], **({"rule": verdict["rule"]} if verdict.get("rule")
                                                                      else {})}
        if verdict["verdict"] == "refuse":
            return refused({**reason, "reason": verdict["reason"] + "; nothing was done"}, window)
        if verdict["verdict"] == "ask":
            asked = {key: value for key, value in verdict["request"].items() if key not in ("app", "window", "handle")}
            shown = shown or {}
            asked.update({key: shown[name] for key, name in (("app", "app"), ("window", "title")) if shown.get(name)})
            return refused({**reason, "approval": asked, "reason": verdict["reason"] + "; nothing was done"}, window,
                           approval=verdict["request"])
        if verdict["verdict"] == "when_idle":
            seconds = float(verdict.get("idle_seconds", 2.0))
            if not self.presence.idle_for(seconds, IDLE_WAIT_SECONDS if idle_wait else 0.0):
                return refused({**reason, "check": "user_input", "wait_seconds": seconds,
                                "reason": f"physical input here waits until the user leaves the computer alone for "
                                          f"{seconds:g} s (when_idle), and they did not; nothing was done"}, window)
        return None

    def take(self, window, actions, verdict, again=None, shown=None):
        """The input lock in turn (at most LOCK_WAIT_SECONDS), then the window again
        (`again`: the one the step would reach now, decided anew if another): (held, window,
        verdict), or a refusal with the lock let go."""
        held = self.gate.lock.acquire(self.gate.owner, timeout=LOCK_WAIT_SECONDS)
        if held is None:
            holder = self.gate.lock.holder()
            return refused({"check": "input_lock", "reason": f"the input lock stayed with "
                            f"{holder['owner'] if holder else 'another agent'} for {LOCK_WAIT_SECONDS:g} s; "
                            "nothing was done"}, window)
        if again is not None:
            now = again()
            if identity(now) != identity(window):
                window = now
                verdict = self.decide(window, actions, shown(window) if shown else None)
                refusal = self.refusal(verdict, window, shown(window) if shown else None, idle_wait=False)
                if refusal is not None:
                    held.release()
                    return refusal
        return held, window, verdict

    def delivered(self, held, began, window=None, pointer=None, stopped=False, extra=None) -> dict:
        """After the step: its record in the lock's history, the lock let go, the input
        marked as the agent's, and its delivery."""
        if not held.released:
            held.record(began, time.time(), pointer, (window or {}).get("handle"))
            held.release()
        self.presence.mark()
        return {"mechanism": "physical", "status": "unverified" if stopped else "delivered",
                "waited": round(held.waited, 3), **about(window), **(extra or {})}

    def call(self, op, window=None, shown=None, **arguments) -> dict:
        """The worker's `physical` method: status; identify (session, agent, level, rules,
        interactive); check (actions, app: what a step into `window` or that app would
        meet); answer (id, accept, remember)."""
        if op == "status":
            return {"owner": self.gate.owner, "level": self.gate.policy().level, "holder": self.gate.lock.holder(),
                    "queue": self.gate.lock.queue()}
        if op == "identify":
            unknown = set(arguments) - {"session", "agent", "level", "rules", "interactive"}
            if unknown:
                raise ValueError(f"identify takes session, agent, level, rules and interactive, not {sorted(unknown)}")
            return self.gate.identify(arguments.get("session") or self.defaults["session"],
                                      arguments.get("agent") or "main", rules=arguments.get("rules") or (),
                                      level=arguments.get("level"), interactive=bool(arguments.get("interactive", True)))
        if op == "check":
            actions = list(arguments.get("actions") or self.actions)
            unknown = set(actions) - set(ACTIONS)
            if unknown:
                raise ValueError(f"actions are of {', '.join(ACTIONS)}")
            if arguments.get("app"):
                window, shown = {"app": app_name(arguments["app"]), "title": None}, None
            verdict = self.decide(window, actions, shown)
            return {key: verdict[key] for key in ("verdict", "level", "rule", "request", "reason") if key in verdict}
        if op == "answer":
            return self.gate.answer(arguments.get("id"), bool(arguments.get("accept")), arguments.get("remember") or "once")
        raise ValueError(f"Unknown physical op {op!r}: identify, check, answer or status")
