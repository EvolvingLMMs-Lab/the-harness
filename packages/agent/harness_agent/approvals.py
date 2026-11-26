"""Approval requests must reach the owner, and only the owner answers them.

A request gets a short code (A7) and goes:
  - into the main conversation as an approval card, and into the chat it came from; the list
    marks them;
  - to a system notification (notifications(): the desktop shell polls them) when no
    frontend is open;
  - to the owner's private chat in a bound channel: "A7 approve" or "A7 reject" there is
    parsed by the channel side (parse()) and answers it through the same interface; the
    model never judges it.
The first answer wins; the others see "handled elsewhere". A request left unanswered for
approvals.timeout_minutes (30) ends as cancelled, never as done.

System notifications are only for what the owner must decide or know: approval requests,
the spending limit reached, an action that failed or ended unknown, an expired channel
login. Everything else is only marked in the list; general.notifications switches them."""
import re
import threading
import time

from .chats import MAIN
from .state import read, save

NOTIFY = ("approval", "limit", "failed", "login")
KEEP = 200
CODE = re.compile(r"^\s*([A-Za-z]\d{1,3})\s+(approve|approved|yes|ok|reject|rejected|no|同意|批准|拒绝|不同意)\b",
                  re.I)
ACCEPT = ("approve", "approved", "yes", "ok", "同意", "批准")


def parse(text):
    """("A7", True | False) for "A7 approve" / "A7 reject" (and 同意 / 拒绝), else None."""
    found = CODE.match(str(text or ""))
    if not found:
        return None
    return found.group(1).upper(), found.group(2).lower() in ACCEPT


class Approvals:
    """One identity's approval requests and notifications (its life's)."""

    def __init__(self, life):
        self.life = life
        self.path = life.identity.directory / "approvals.json"
        saved = read(self.path, {})
        self.rows = saved.get("requests") or []
        self.notes = saved.get("notifications") or []
        self._waits = {}
        self._lock = threading.RLock()
        self._next = int(saved.get("next") or 1)
        # Requests still waiting from before a restart cannot be answered by the turn that
        # asked (it ended with the process): they end as cancelled.
        for row in self.rows:
            if row["state"] == "waiting":
                row.update(state="cancelled", reason="the host restarted while it waited", answered=time.time())
        self._save()

    def _save(self) -> None:
        with self._lock:
            save(self.path, {"requests": self.rows[-KEEP:], "notifications": self.notes[-KEEP:],
                             "next": self._next})

    def timeout(self) -> float:
        from harness.sdk import Settings, data

        try:
            return float(Settings(data()).get().get("approvals", {}).get("timeout_minutes", 30)) * 60
        except Exception:
            return 1800.0

    def pending(self) -> list:
        return [row for row in self.rows if row["state"] == "waiting"]

    def _code(self) -> str:
        used = {row["code"] for row in self.pending()}
        while True:
            code = f"A{self._next % 100 or 1}"
            self._next += 1
            if code not in used:
                return code

    def ask(self, chat, what, *, verb=None, place=None, effect=None, timeout=None) -> tuple:
        """Put a request to the owner and wait: ("approved" | "rejected" | "cancelled", reason)."""
        with self._lock:
            code = self._code()
            now = self.life.clock()
            row = {"code": code, "chat": chat, "what": what, "verb": verb, "place": place, "effect": effect,
                   "created": now, "expires": now + (timeout if timeout is not None else self.timeout()),
                   "state": "waiting"}
            self.rows.append(row)
            # Kept here: an answer may come (and take it from _waits) before the card is out.
            waited = self._waits[code] = threading.Event()
            self._save()
        card = {"code": code, "what": what, "verb": verb, "state": "waiting", "expires": row["expires"]}
        self.life.chats.record(MAIN, "approval", **card, **({"in_chat": chat} if chat != MAIN else {}))
        if chat != MAIN:
            self.life.chats.record(chat, "approval", **card)
        self.notify("approval", f"{self.life.identity.name} asks: {code}", f"{what} — reply \"{code} approve\" or "
                    f"\"{code} reject\"", chat=chat)
        self._to_channel(f"{code} — {what}\nReply \"{code} approve\" or \"{code} reject\".")
        # The tree hears it too: the built-in node reminds the owner.
        self.life.tell(None, {"type": "approval.waiting", "data": {"code": code, "what": what, "chat": chat},
                              "source": "agent"})
        while not waited.wait(1.0):
            if self.life.clock() >= row["expires"] or self.life.closing.is_set():
                self._end(code, "cancelled", "nobody answered in time" if not self.life.closing.is_set()
                          else "the host quit")
                break
        with self._lock:
            return row["state"], row.get("reason") or ""

    def answer(self, code, accept, reason="", by="app") -> dict:
        """The owner's answer. The first one wins: {state, handled_elsewhere}."""
        code = str(code).upper()
        with self._lock:
            row = next((r for r in reversed(self.rows) if r["code"] == code), None)
            if row is None:
                raise ValueError(f"no approval request {code}")
            if row["state"] != "waiting":
                return {"code": code, "state": row["state"], "handled_elsewhere": True}
        self._end(code, "approved" if accept else "rejected", reason or ("approved" if accept else "rejected"), by=by)
        return {"code": code, "state": row["state"], "handled_elsewhere": False}

    def _end(self, code, state, reason, by=None) -> None:
        with self._lock:
            row = next((r for r in reversed(self.rows) if r["code"] == code), None)
            if row is None or row["state"] != "waiting":
                return
            row.update(state=state, reason=reason, answered=self.life.clock(), **({"by": by} if by else {}))
            self._save()
            waited = self._waits.pop(code, None)
        card = {"code": code, "what": row["what"], "state": state, "reason": reason}
        self.life.chats.record(MAIN, "approval", **card)
        if row["chat"] != MAIN:
            self.life.chats.record(row["chat"], "approval", **card)
        if waited is not None:
            waited.set()

    def _to_channel(self, text) -> None:
        """To the owner's private chat in each channel with a bound owner."""
        for place in list(self.life.places.values()):
            owner = (getattr(place, "row", {}) or {}).get("owner")
            if owner and hasattr(place, "act") and getattr(place, "online", False):
                try:
                    place.act("qq.send", {"text": text}, f"private:{owner}")
                except Exception:
                    pass

    # System notifications: four kinds only.

    def notify(self, kind, title, body, *, chat=None) -> dict | None:
        if kind not in NOTIFY:
            return None
        from harness.sdk import Settings, data

        try:
            on = Settings(data()).get().get("general", {}).get("notifications", True)
        except Exception:
            on = True
        if not on:
            return None
        with self._lock:
            row = {"id": (self.notes[-1]["id"] + 1) if self.notes else 1, "kind": kind, "title": title, "body": body,
                   "chat": chat, "identity": self.life.identity.id, "time": self.life.clock()}
            self.notes.append(row)
            self._save()
        return row

    def notifications(self, after=0) -> list:
        return [row for row in self.notes if row["id"] > int(after or 0)]
