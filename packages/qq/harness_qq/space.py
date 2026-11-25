"""A QQ account as an Agent Space Protocol space, over OneBot 11.

The account's chats are the space's state: the groups the owner let it into and the private
chats of the owner and of the people paired with it. A OneBot 11 implementation (NapCat,
LLOneBot, Lagrange...) logs in to QQ and serves a forward WebSocket; this space is its client.
It is a space of its own, written on the SDK's space skeleton, not a worker behind the
translation layer.

What the agent plan asks of a channel, here:

  identity     The account belongs to one identity of the agent (`identity` in its
               configuration), chosen with the policies before the QR code is scanned.
  groups       The account enters no group by default. The owner lets it into one
               (`qq.enter_group`), with `mention` (it is woken when named) or `all`. A message
               of a group it is not in is not recorded.
  owner        The owner's QQ is bound with a one-time code: `qq.owner_code` gives it, the
               owner sends it to the account in a private message.
  strangers    With the private-chat policy `pairing` (the default), a stranger's private
               message is answered with a pairing code, valid for an hour; the request is an
               event, `qq.pairing_requested`, and the stranger's messages are not kept while
               it waits. The owner approves it with `qq.pair`, revokes it with `qq.unpair`.
               `allowlist`: only paired people; `open`: everyone; `off`: nobody.
  named        A message names the account when it @-mentions it or replies to a message the
               account sent. Such a message, a private message to it, and any message of a
               group entered with `all`, is `addressed` (the event's data says so): the agent's
               reaction "named or addressed: wake it" reads that.

Outcomes of sending (`qq.send`, `qq.reply`): OneBot's receipt `ok` is done (with the message
ID), `async` (accepted, not confirmed) is unknown with what is known, `failed` is failed with
OneBot's code; no receipt within 20 seconds, or the connection lost while waiting, is
unknown: the message was handed to OneBot and its delivery is not confirmed. Without a
connection to OneBot nothing is sent: refused, `qq.offline`. Sending is of effect class
`send` (to someone new); replying in the chat a message came from is `change`.

    python -m harness.space.serve qq --onebot ws://127.0.0.1:3001 --config qq.json --listen ws://127.0.0.1:7900
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Any

from agent_space.space import Failed, Refused, Space, SqliteStore, Uncertain
from agent_space.transport import connect
from agent_space.util import now

RECEIPT_SECONDS = 20.0
PAIRING_SECONDS = 3600
OWNER_CODE_SECONDS = 600
RECENT = 30
DM_POLICIES = ("pairing", "allowlist", "open", "off")
GROUP_MODES = ("mention", "all")

TEXT = {"type": "object", "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 4500}},
        "required": ["text"], "additionalProperties": False}

VOCABULARY = {
    "namespaces": {"qq": {"version": "0.1.0", "line": "A QQ account: its groups and private chats (OneBot 11)"}},
    "types": {
        "qq.account": {"line": "The QQ account the agent speaks as: its number, nickname and whether it is online."},
        "qq.chat": {"line": "A group the account was let into, or a private chat: `kind` group or private, `mode` "
                            "mention or all for a group."},
        "qq.message": {"line": "A message in a chat: `from`, `name`, `text`, `addressed` (it names the account, or "
                               "is meant for it), `reply_to`."},
    },
    "verbs": {
        "qq.reply": {"line": "Reply to a message, in its chat, quoting it.", "object": "qq.message", "params": TEXT,
                     "effect": "change", "default": {"end": "refused", "reason": {"code": "qq.unknown_message"}},
                     "stale": "allow", "outcomes": ["done", "refused", "failed", "unknown"],
                     "reasons": ["qq.offline", "qq.unknown_message", "onebot.failed", "onebot.async",
                                 "onebot.timeout", "onebot.closed"]},
        "qq.send": {"line": "Send a message to a chat (a group it is in, or a private chat).", "object": "qq.chat",
                    "params": TEXT, "effect": "send", "default": {"end": "refused", "reason": {"code": "qq.unknown_chat"}},
                    "stale": "allow", "outcomes": ["done", "refused", "failed", "unknown"],
                    "reasons": ["qq.offline", "qq.unknown_chat", "onebot.failed", "onebot.async", "onebot.timeout",
                                "onebot.closed"]},
        "qq.owner_code": {"line": "A one-time code that binds the owner's QQ: the owner sends it to the account in "
                                  "a private message within ten minutes.", "effect": "change",
                          "default": {"end": "done"}, "stale": "allow"},
        "qq.pair": {"line": "Approve a stranger's pairing request by its code.",
                    "params": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
                    "effect": "change", "default": {"end": "refused"}, "stale": "allow"},
        "qq.unpair": {"line": "Revoke a person's pairing.",
                      "params": {"type": "object", "properties": {"user": {"type": "string"}}, "required": ["user"]},
                      "effect": "change", "default": {"end": "refused"}, "stale": "allow"},
        "qq.groups": {"line": "The groups the account is in, entered or not.", "effect": "read",
                      "default": {"end": "done"}, "stale": "allow"},
        "qq.enter_group": {"line": "Let the account into a group: mode mention (woken when named) or all.",
                           "params": {"type": "object", "properties": {"group": {"type": "string"},
                                                                     "mode": {"enum": list(GROUP_MODES)}},
                                      "required": ["group"]},
                           "effect": "change", "default": {"end": "refused"}, "stale": "allow"},
        "qq.leave_group": {"line": "Take the account out of a group (it stays a member on QQ).",
                           "params": {"type": "object", "properties": {"group": {"type": "string"}},
                                      "required": ["group"]},
                           "effect": "change", "default": {"end": "refused"}, "stale": "allow"},
    },
    "events": {
        "qq.message": {"line": "A message arrived in a chat the account is in (not its own).", "perceived": "all"},
        "qq.sent": {"line": "The account sent a message.", "perceived": "all"},
        "qq.pairing_requested": {"line": "A stranger asked to talk to the account: `user`, `code`, `expires`.",
                                 "perceived": "all"},
        "qq.paired": {"line": "A person was paired, or unpaired.", "perceived": "all"},
        "qq.owner_bound": {"line": "The owner's QQ was bound.", "perceived": "all"},
        "qq.online": {"line": "The account is online, or went offline (`online`).", "perceived": "all"},
    },
    "forms": {"text": {"media": "text/plain", "line": "The recent messages, one per line."}},
    "pages": {"qq": {"line": "How to talk in QQ",
                     "text": "Reply to the message that named you with qq.reply(message, text), in its chat. "
                             "qq.send(chat, text) starts a message in a chat; it counts as sending to someone and "
                             "may need the owner's approval. A message whose outcome is unknown may have arrived: "
                             "look at the chat before sending it again."}},
}

OWNER_VERBS = ["qq.owner_code", "qq.pair", "qq.unpair", "qq.groups", "qq.enter_group", "qq.leave_group"]
MEMBER_VERBS = ["qq.reply", "qq.send"]


class Settings:
    """The channel account's configuration and what it learned (owner, pairings), in one
    JSON file: identity, dm, groups {group: mode}, owner, paired [users], pending {code: ...}."""

    def __init__(self, path: Path | None):
        self.path = path
        data = json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else {}
        self.identity = data.get("identity")
        self.dm = data.get("dm", "pairing")
        if self.dm not in DM_POLICIES:
            raise ValueError(f"dm is one of {DM_POLICIES}, not {self.dm!r}")
        self.groups: dict[str, str] = {str(k): v for k, v in (data.get("groups") or {}).items()}
        self.owner: str | None = data.get("owner")
        self.paired: list[str] = list(data.get("paired") or [])
        self.pending: dict[str, dict[str, Any]] = dict(data.get("pending") or {})
        self.owner_codes: dict[str, float] = dict(data.get("owner_codes") or {})

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"identity": self.identity, "dm": self.dm, "groups": self.groups, "owner": self.owner,
                "paired": self.paired, "pending": self.pending, "owner_codes": self.owner_codes}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def prune(self) -> None:
        t = time.time()
        self.pending = {c: p for c, p in self.pending.items() if p["expires"] > t}
        self.owner_codes = {c: e for c, e in self.owner_codes.items() if e > t}


class QQSpace:
    """The space and its OneBot client."""

    def __init__(self, onebot: str, *, settings: Settings, token: str | None = None, data: Path | None = None,
                 owner_identity: str | None = None):
        self.onebot = onebot
        self.token = token
        self.settings = settings
        self.owner_identity = owner_identity
        self.conn = None
        self.online = False
        self.self_id: str | None = None
        self.nickname = ""
        self.sent_ids: deque[str] = deque(maxlen=500)
        self.sent_count: dict[str, int] = {}
        self.messages: dict[str, dict[str, Any]] = {}
        self.order: deque[str] = deque(maxlen=RECENT * 10)
        self._waiting: dict[str, asyncio.Future] = {}
        self._echo = 0
        self._closing = False
        store = SqliteStore(str(data / "record.db")) if data else None
        # The probes `agent-space check` acts with: sending to the first group it is in.
        profile: dict[str, Any] = {"role": "member", "owner": "owner",
                                   "forbidden": {"verb": "qq.owner_code", "role": "member"}}
        first = next(iter(sorted(settings.groups)), None)
        if first:
            probe = {"verb": "qq.send", "object": f"group:{first}", "args": {"text": "check"}}
            profile.update(done=probe, counter={**probe, "property": "sent"})
        self.space = Space(
            capabilities={
                "state": "external", "lifetime": "lasting",
                "participants": {
                    "roles": {
                        "owner": {"line": "The account's owner, through the host: every verb.", "verbs": ["*"],
                                  "consent": True},
                        "member": {"line": "The agent in the chats: reply and send.", "verbs": MEMBER_VERBS},
                        "guest": {"line": "Reads only.", "verbs": []},
                    },
                    "default_role": "member", "outside": True, "grace_seconds": 300},
                "forms": ["text"],
            },
            vocabulary=VOCABULARY, store=store, keep_seconds=90 * 86400 if store else None,
            hello={"inspector.profile": profile},
        )
        h = self.space.handlers
        h.observe = self._observe
        h.admit = self._admit
        h.verbs.update({"qq.reply": self._reply, "qq.send": self._send, "qq.owner_code": self._owner_code,
                        "qq.pair": self._pair, "qq.unpair": self._unpair, "qq.groups": self._groups,
                        "qq.enter_group": self._enter_group, "qq.leave_group": self._leave_group})

    # -- The space --------------------------------------------------------------------------

    def _admit(self, request):
        if request["role"] == "owner" and self.owner_identity and request.get("participant") != self.owner_identity:
            raise Refused("forbidden", "only the identity this account belongs to may take the owner role")
        return request["role"]

    def _chats(self) -> list[dict[str, Any]]:
        chats = [{"id": f"group:{g}", "type": "qq.chat", "kind": "group", "group": g, "mode": m,
                  "sent": self.sent_count.get(f"group:{g}", 0)} for g, m in sorted(self.settings.groups.items())]
        people = ([self.settings.owner] if self.settings.owner else []) + self.settings.paired
        chats += [{"id": f"private:{u}", "type": "qq.chat", "kind": "private", "user": u,
                   "owner": u == self.settings.owner, "sent": self.sent_count.get(f"private:{u}", 0)}
                  for u in dict.fromkeys(people)]
        return chats

    def _observe(self, ctx):
        account = {"id": "account", "type": "qq.account", "user": self.self_id, "nickname": self.nickname,
                   "online": self.online, "confirmed": now()}
        recent = [self.messages[m] for m in list(self.order)[-RECENT:] if m in self.messages]
        things = [account, *self._chats(), *recent]
        out: dict[str, Any] = {"structure": {"things": things}, "confirmed": account["confirmed"]}
        if "text" in ctx.forms:
            lines = [f"[{m['chat']}] {m['name']}: {m['text']}" for m in recent]
            out["forms"] = {"text": {"media": "text/plain", "data": "\n".join(lines) or "(no messages)"}}
        return out

    async def _reply(self, ctx):
        message = self.messages.get(ctx.object or "")
        if message is None:
            raise Refused("qq.unknown_message", f"no message {ctx.object} in the chats it is in")
        segments = [{"type": "reply", "data": {"id": message["message_id"]}},
                    {"type": "text", "data": {"text": ctx.args["text"]}}]
        return await self._deliver(ctx, message["chat"], segments, ctx.args["text"])

    async def _send(self, ctx):
        chat = ctx.object or ""
        if chat not in {c["id"] for c in self._chats()}:
            raise Refused("qq.unknown_chat", f"{chat} is not a chat the account is in")
        return await self._deliver(ctx, chat, [{"type": "text", "data": {"text": ctx.args["text"]}}], ctx.args["text"])

    async def _deliver(self, ctx, chat: str, segments, text: str):
        kind, target = chat.split(":", 1)
        action = "send_group_msg" if kind == "group" else "send_private_msg"
        params = {"group_id": int(target)} if kind == "group" else {"user_id": int(target)}
        receipt = await self._call(action, {**params, "message": segments})
        message_id = str((receipt.get("data") or {}).get("message_id"))
        self.sent_ids.append(message_id)
        self.sent_count[chat] = self.sent_count.get(chat, 0) + 1
        ctx.emit("qq.sent", {"chat": chat, "message_id": message_id, "text": text}, things=[chat])
        return {"result": {"message_id": message_id, "chat": chat}}

    async def _call(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """One OneBot action and its receipt, as an outcome."""
        if self.conn is None or self.conn.closed:
            raise Refused("qq.offline", "the account is not connected to OneBot; nothing was sent")
        self._echo += 1
        echo = f"asp-{self._echo}-{secrets.token_hex(3)}"
        waiter = asyncio.get_running_loop().create_future()
        self._waiting[echo] = waiter
        self.conn.send({"action": action, "params": params, "echo": echo})
        try:
            receipt = await asyncio.wait_for(waiter, RECEIPT_SECONDS)
        except asyncio.TimeoutError:
            raise Uncertain("onebot.timeout", f"no receipt from OneBot within {RECEIPT_SECONDS:g} s",
                            known={"handed_to_onebot": True}, unconfirmed=["delivered"]) from None
        except ConnectionError:
            raise Uncertain("onebot.closed", "the connection to OneBot closed before its receipt",
                            known={"handed_to_onebot": True}, unconfirmed=["delivered"]) from None
        finally:
            self._waiting.pop(echo, None)
        status = receipt.get("status")
        if status == "ok":
            return receipt
        if status == "async":
            raise Uncertain("onebot.async", "OneBot accepted it and did not confirm it",
                            known={"handed_to_onebot": True, "accepted": True}, unconfirmed=["delivered"])
        raise Failed("onebot.failed", f"OneBot answered {status} {receipt.get('retcode')}: "
                                      f"{receipt.get('wording') or receipt.get('msg') or ''}".strip(),
                     data={"retcode": receipt.get("retcode")})

    def _owner_code(self, ctx):
        code = f"{secrets.randbelow(10 ** 6):06d}"
        self.settings.prune()
        self.settings.owner_codes[code] = time.time() + OWNER_CODE_SECONDS
        self.settings.save()
        return {"result": {"code": code, "expires": int(self.settings.owner_codes[code]),
                           "how": "send this code to the account in a private QQ message"}}

    def _pair(self, ctx):
        self.settings.prune()
        request = self.settings.pending.pop(ctx.args["code"].strip().upper(), None)
        if request is None:
            raise Refused("qq.no_request", "no pairing request has that code (it may have expired)")
        if request["user"] not in self.settings.paired:
            self.settings.paired.append(request["user"])
        self.settings.save()
        ctx.emit("qq.paired", {"user": request["user"], "paired": True}, things=[f"private:{request['user']}"])
        return {"result": {"user": request["user"]}}

    def _unpair(self, ctx):
        user = str(ctx.args["user"])
        if user not in self.settings.paired:
            raise Refused("qq.not_paired", f"{user} is not paired")
        self.settings.paired.remove(user)
        self.settings.save()
        ctx.emit("qq.paired", {"user": user, "paired": False})
        return {"result": {"user": user}}

    async def _groups(self, ctx):
        receipt = await self._call("get_group_list", {})
        groups = [{"group": str(g.get("group_id")), "name": g.get("group_name"),
                   "entered": self.settings.groups.get(str(g.get("group_id")))} for g in receipt.get("data") or []]
        return {"result": {"groups": groups}}

    def _enter_group(self, ctx):
        mode = ctx.args.get("mode", "mention")
        self.settings.groups[str(ctx.args["group"])] = mode
        self.settings.save()
        return {"result": {"group": str(ctx.args["group"]), "mode": mode}}

    def _leave_group(self, ctx):
        if self.settings.groups.pop(str(ctx.args["group"]), None) is None:
            raise Refused("qq.not_entered", "the account is not in that group here")
        self.settings.save()
        return {"result": {"group": str(ctx.args["group"])}}

    # -- OneBot -----------------------------------------------------------------------------

    async def run_onebot(self) -> None:
        """Keep the connection to OneBot, reconnecting with backoff."""
        wait = 0.5
        while not self._closing:
            address = self.onebot + (("&" if "?" in self.onebot else "?") + f"access_token={self.token}" if self.token else "")
            try:
                conn = await connect(address)
            except Exception:
                await asyncio.sleep(wait)
                wait = min(wait * 2, 30)
                continue
            wait = 0.5
            self.conn = conn
            closed = asyncio.get_running_loop().create_future()
            conn.on_message = self._on_onebot
            conn.on_close = lambda: closed.done() or closed.set_result(None)
            asyncio.get_running_loop().create_task(self._login())
            await closed
            self.conn = None
            for waiter in list(self._waiting.values()):
                if not waiter.done():
                    waiter.set_exception(ConnectionError("closed"))
            self._set_online(False)

    async def _login(self):
        try:
            info = await self._call("get_login_info", {})
        except Exception:
            return
        data = info.get("data") or {}
        self.self_id, self.nickname = str(data.get("user_id")), data.get("nickname", "")
        self._set_online(True)

    def _set_online(self, online: bool) -> None:
        if online != self.online:
            self.online = online
            self.space.emit("qq.online", {"online": online, "user": self.self_id}, things=["account"], source="outside")

    def _on_onebot(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if "echo" in msg and msg.get("echo") in self._waiting:
            waiter = self._waiting[msg["echo"]]
            if not waiter.done():
                waiter.set_result(msg)
            return
        post = msg.get("post_type")
        if post == "meta_event":
            status = (msg.get("status") or {})
            if msg.get("meta_event_type") == "heartbeat" and "online" in status:
                self._set_online(bool(status["online"]))
            return
        if post == "message":
            self._on_message(msg)

    def _on_message(self, msg: dict[str, Any]) -> None:
        user = str(msg.get("user_id"))
        if self.self_id and user == self.self_id:
            return  # its own message, echoed back
        segments = msg.get("message")
        if isinstance(segments, str):
            segments = [{"type": "text", "data": {"text": segments}}]
        text = "".join(s["data"].get("text", "") for s in segments if s.get("type") == "text").strip()
        mentioned = any(s.get("type") == "at" and str(s["data"].get("qq")) == self.self_id for s in segments)
        reply_to = next((str(s["data"].get("id")) for s in segments if s.get("type") == "reply"), None)
        named = mentioned or (reply_to is not None and reply_to in self.sent_ids)
        sender = msg.get("sender") or {}
        name = sender.get("card") or sender.get("nickname") or user
        if msg.get("message_type") == "group":
            group = str(msg.get("group_id"))
            mode = self.settings.groups.get(group)
            if mode is None:
                return  # a group it was not let into: nothing is recorded
            self._record(f"group:{group}", msg, user, name, text, reply_to, named, named or mode == "all")
            return
        # A private chat.
        if self.settings.owner is None or user != self.settings.owner:
            self.settings.prune()
            if text in self.settings.owner_codes:
                del self.settings.owner_codes[text]
                self.settings.owner = user
                self.settings.save()
                self.space.emit("qq.owner_bound", {"user": user}, things=["account"], source="outside")
                self._spawn(self._call("send_private_msg", {"user_id": int(user), "message": "You are bound as the owner."}))
                return
        if user == self.settings.owner or user in self.settings.paired or self.settings.dm == "open":
            self._record(f"private:{user}", msg, user, name, text, reply_to, named, True)
            return
        if self.settings.dm == "pairing":
            request = next((c for c, p in self.settings.pending.items() if p["user"] == user), None)
            if request is None:
                request = secrets.token_hex(3).upper()
                expires = int(time.time() + PAIRING_SECONDS)
                self.settings.pending[request] = {"user": user, "name": name, "expires": expires}
                self.settings.save()
                self.space.emit("qq.pairing_requested", {"user": user, "name": name, "code": request, "expires": expires},
                                source="outside")
            self._spawn(self._call("send_private_msg", {"user_id": int(user), "message":
                        f"Pairing code {request}: the owner approves it within an hour; until then messages are not kept."}))
        # allowlist / off: a stranger's message is not kept.

    def _record(self, chat, msg, user, name, text, reply_to, named, addressed) -> None:
        mid = str(msg.get("message_id"))
        thing = {"id": f"msg:{mid}", "type": "qq.message", "chat": chat, "message_id": mid, "from": f"qq:{user}",
                 "name": name, "text": text, "time": now(), **({"reply_to": f"msg:{reply_to}"} if reply_to else {})}
        self.messages[thing["id"]] = thing
        self.order.append(thing["id"])
        while len(self.messages) > self.order.maxlen:
            self.messages.pop(next(iter(self.messages)))
        self.space.emit("qq.message", {**{k: v for k, v in thing.items() if k not in ("id", "type")},
                                       "message": thing["id"], "named": named, "addressed": addressed,
                                       "owner": user == self.settings.owner},
                        things=[thing["id"], chat], source="outside")

    def _spawn(self, coro) -> None:
        async def quietly():
            try:
                await coro
            except Exception:
                pass

        asyncio.get_running_loop().create_task(quietly())

    async def serve(self, listen: str, ready=None) -> None:
        task = asyncio.get_running_loop().create_task(self.run_onebot())
        listener = await self.space.listen(listen)
        if ready:
            ready(listener.address)
        try:
            await self.space.wait_closed()
        finally:
            self._closing = True
            task.cancel()
            if self.conn:
                self.conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="harness space qq", description="A QQ account (OneBot 11) as a space")
    parser.add_argument("--onebot", default=os.environ.get("HARNESS_QQ_ONEBOT", "ws://127.0.0.1:3001"),
                        help="the OneBot 11 implementation's forward WebSocket")
    parser.add_argument("--config", help="the account's settings and pairings (JSON)")
    parser.add_argument("--data", help="a folder for the record (in memory without)")
    parser.add_argument("--listen", default="ws://127.0.0.1:0")
    parser.add_argument("--owner", help="the identity (ed25519:...) that may take the owner role")
    parser.add_argument("--init", action="store_true", help="write --config with --identity, --dm and exit")
    parser.add_argument("--identity", help="the identity this account belongs to (with --init)")
    parser.add_argument("--dm", choices=DM_POLICIES, default="pairing", help="the private-chat policy (with --init)")
    args = parser.parse_args(argv)
    settings = Settings(Path(args.config) if args.config else None)
    if args.init:
        if not args.config:
            parser.error("--init needs --config")
        settings.identity, settings.dm = args.identity or settings.identity, args.dm
        settings.save()
        print(json.dumps({"config": args.config, "identity": settings.identity, "dm": settings.dm}))
        return 0
    data = Path(args.data) if args.data else None
    if data:
        data.mkdir(parents=True, exist_ok=True)
    space = QQSpace(args.onebot, settings=settings, token=os.environ.get("HARNESS_QQ_TOKEN"), data=data,
                    owner_identity=args.owner)

    def ready(address):
        if address != "stdio":
            print(json.dumps({"space": address}), flush=True)

    asyncio.run(space.serve(args.listen, ready))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
