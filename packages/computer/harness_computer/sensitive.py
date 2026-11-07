"""Sensitive steps: an input step that would enter credentials, pay, send in the user's name,
delete, or do what cannot be undone, told from what it acts on: the element (an act's, the
one under the pointer, the field text goes into), the window's app, the keys, and in a
background browser the page itself (password and card fields, a form's submit). Never from
a URL's words: loading a page is never sensitive.

A sensitive step is refused, nothing done, with an approval request ({"id", "sensitive":
kind, "target", "actions", "app", "window", "retry": "host_tick"}). Only the host can
retry after user assent. The worker claims the request before checking the cursor, then
checks the originating execution, exact command and freshly resolved target before input.
"""

from dataclasses import dataclass
import hashlib
import json
import re
import secrets
import time

from harness_computer.physical import ONCE_SECONDS

KINDS = ("credentials", "payment", "sending", "deleting", "irreversible")
# What pressing a button or menu item does, by the words its name starts with.
PRESSES = (("irreversible", r"(permanently|factory reset|erase all|format)\b"),
           ("payment", r"(pay|buy|purchase|place (your )?order|check ?out|complete (purchase|order)|subscribe)\b"),
           ("sending", r"(send|submit|post|publish)\b"),
           ("deleting", r"(delete|move to (the )?trash|empty (the )?trash)\b"))
PRESSABLE = ("button", "menuitem", "link", "checkbox")
# Apps whose keys send or delete: mail clients (ctrl/command + enter sends) and file
# managers (delete moves the selection to the trash, shift + delete deletes it).
MAIL = ("thunderbird", "outlook", "mail", "evolution", "geary", "kmail", "mailspring")
FILES = ("nautilus", "files", "explorer", "finder", "dolphin", "thunar", "nemo", "pcmanfm", "caja")
CARD = re.compile(r"\b(card ?number|credit card|debit card|cvc|cvv|security code|expiration|expiry)\b", re.I)


def kind_of(command: dict, element: dict | None, app: str | None) -> tuple[str, str] | None:
    """(kind, what it acts on in words) of a sensitive step, or None. `element`: what it acts
    on ({"role", "name", "states", and from a page "autocomplete", "submits"}); `app`: the
    window's app."""
    step = command.get("type")
    action = command.get("action")
    element = element or {}
    role, name = str(element.get("role") or ""), " ".join(str(element.get("name") or "").split())
    what = f'{role} "{name}"' if name else role or "the focused field"
    keys = {str(key).lower() for key in command.get("keys") or ()}
    enters_text = (step == "type" or (step == "act" and action == "set_value")
                   or (step == "key" and (keys in ({"ctrl", "v"}, {"command", "v"}, {"shift", "insert"})
                                          or (not keys & {"ctrl", "command", "alt", "win"}
                                              and any(len(key) == 1 for key in keys)))))
    if enters_text:
        if "password" in (element.get("states") or ()):
            return "credentials", f"the password field {what}"
        if any(token.startswith("cc-") for token in str(element.get("autocomplete") or "").lower().split()) or CARD.search(name):
            return "payment", f"the card field {what}"
    if step in ("key", "type"):
        if step == "type" and "\n" in command["text"]:
            keys = {"enter"}
        program = str(app or "").lower()
        if keys & {"enter", "return"} and element.get("enter_submits"):
            return element["enter_submits"], f"Enter in {what}, which submits its form"
        if keys & {"enter", "return"} and keys & {"ctrl", "command"} and any(word in program for word in MAIL):
            return "sending", f"{'+'.join(sorted(keys))} in {app}, which sends the message"
        if keys & {"delete", "del"} and any(word in program for word in FILES):
            return "deleting", f"{'+'.join(sorted(keys))} in {app}, which deletes the selection"
    activates = ((step == "click" and command.get("button", "left") == "left")
                 or (step == "act" and action in ("click", "invoke", "toggle", "select", "expand", "collapse"))
                 or (step == "key" and keys in ({"enter"}, {"return"}, {"space"})))
    if activates:
        if element.get("submits"):
            return element["submits"], f"{what}, which submits its form"
        if role in PRESSABLE:
            for kind, pattern in PRESSES:
                if re.match(pattern, name, re.I):
                    return kind, what
    return None


@dataclass(frozen=True)
class Pending:
    request: dict
    command: str
    target: str
    expires: float


@dataclass(frozen=True)
class Attempt:
    episode_id: str
    step: int
    execution_id: str | None
    command: dict
    cameras: tuple = ()
    action_id: str | None = None
    pending: Pending | None = None


class Approvals:
    """One pending sensitive tick per originating execution."""

    def __init__(self):
        self.pending = {}

    def request(self, attempt: Attempt, kind, target, actions, *, binding, app, window) -> dict:
        """Only a tick with an originating execution can be retried by the host."""
        now = time.monotonic()
        self._expire(now)
        request = {"id": secrets.token_hex(16), "sensitive": kind, "target": target, "actions": list(actions),
                   "app": app, "window": window, "episode_id": attempt.episode_id,
                   "execution_id": attempt.execution_id, "step": attempt.step, "retry": "host_tick"}
        if attempt.action_id is not None:
            request["action_id"] = attempt.action_id
        if attempt.execution_id is not None:
            self.pending[request["id"]] = Pending(request, fingerprint((attempt.command, attempt.cameras)), binding,
                                                   now + ONCE_SECONDS)
        return request

    def supersede(self, execution_id) -> None:
        if execution_id is not None and self.pending:
            self.pending = {identifier: entry for identifier, entry in self.pending.items()
                            if entry.request["execution_id"] != execution_id}

    def get(self, request_id, episode_id, execution_id, *, claim=False):
        """Claim once at retry entry, including when the retry later fails validation."""
        self._expire(time.monotonic())
        pending = self.pending.pop(request_id, None) if claim else self.pending.get(request_id)
        if pending is not None and (pending.request["episode_id"], pending.request["execution_id"]) == (
                episode_id, execution_id):
            return pending
        return None

    def discard(self, request_id) -> bool:
        """Discard a pending sensitive id; used by a missing target or old answer RPC."""
        self._expire(time.monotonic())
        return self.pending.pop(str(request_id), None) is not None

    def _expire(self, now):
        self.pending = {identifier: entry for identifier, entry in self.pending.items() if entry.expires > now}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
