"""A OneBot 11 simulator: the forward WebSocket a OneBot implementation serves, with a made-up
account and chats, for tests and for trying the QQ space without logging in to QQ.

    python -m harness_qq.simulator --listen ws://127.0.0.1:3001

Lines on standard input make things happen:

    group GROUP USER TEXT        a group message; "@ " before TEXT mentions the account,
                                 "^ID " replies to message ID
    private USER TEXT            a private message
    mode ok|async|failed|silent|drop
                                 how it answers the next actions: ok, accepted only, failed,
                                 not at all (the network is gone), or by closing the connection
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from typing import Any

from agent_space.transport import listen


class Simulator:
    def __init__(self, self_id: int = 10001, nickname: str = "harness", groups: dict[int, str] | None = None):
        self.self_id = self_id
        self.nickname = nickname
        self.groups = groups or {123: "test group", 456: "another group"}
        self.mode = "ok"
        self.actions: list[dict[str, Any]] = []
        self.sent: list[dict[str, Any]] = []
        self.connections: list[Any] = []
        self._message_id = 1000
        self.address = ""
        self._listener = None

    async def start(self, address: str = "ws://127.0.0.1:0") -> str:
        self._listener = await listen(address, self._accept)
        self.address = self._listener.address
        return self.address

    async def close(self) -> None:
        if self._listener:
            await self._listener.close()

    def _accept(self, conn) -> None:
        self.connections.append(conn)
        conn.on_message = lambda text: self._on_action(conn, text)
        conn.on_close = lambda: self.connections.remove(conn) if conn in self.connections else None
        conn.send({"post_type": "meta_event", "meta_event_type": "lifecycle", "sub_type": "connect",
                   "self_id": self.self_id, "time": int(time.time())})

    def _on_action(self, conn, text: str) -> None:
        request = json.loads(text)
        self.actions.append(request)
        action, params, echo = request.get("action"), request.get("params") or {}, request.get("echo")
        if action == "get_login_info":
            conn.send({"status": "ok", "retcode": 0, "data": {"user_id": self.self_id, "nickname": self.nickname}, "echo": echo})
            return
        if action == "get_group_list":
            conn.send({"status": "ok", "retcode": 0, "echo": echo,
                       "data": [{"group_id": g, "group_name": n} for g, n in self.groups.items()]})
            return
        mode = self.mode
        if mode == "silent":
            return
        if mode == "drop":
            conn.drop()
            return
        if mode == "failed":
            conn.send({"status": "failed", "retcode": 1200, "wording": "the message could not be sent", "echo": echo})
            return
        if mode == "async":
            conn.send({"status": "async", "retcode": 1, "echo": echo})
            return
        self._message_id += 1
        self.sent.append({"action": action, **params, "message_id": self._message_id})
        conn.send({"status": "ok", "retcode": 0, "data": {"message_id": self._message_id}, "echo": echo})

    def _push(self, event: dict[str, Any]) -> int:
        self._message_id += 1
        event = {"time": int(time.time()), "self_id": self.self_id, "message_id": self._message_id, **event}
        for conn in list(self.connections):
            conn.send(event)
        return self._message_id

    def group_message(self, group: int, user: int, text: str, *, at_self: bool = False, reply_to: int | None = None,
                      name: str | None = None) -> int:
        segments: list[dict[str, Any]] = []
        if reply_to is not None:
            segments.append({"type": "reply", "data": {"id": str(reply_to)}})
        if at_self:
            segments.append({"type": "at", "data": {"qq": str(self.self_id)}})
        segments.append({"type": "text", "data": {"text": text}})
        return self._push({"post_type": "message", "message_type": "group", "sub_type": "normal", "group_id": group,
                           "user_id": user, "message": segments, "raw_message": text,
                           "sender": {"user_id": user, "nickname": name or f"user{user}"}})

    def private_message(self, user: int, text: str, *, name: str | None = None) -> int:
        return self._push({"post_type": "message", "message_type": "private", "sub_type": "friend", "user_id": user,
                           "message": [{"type": "text", "data": {"text": text}}], "raw_message": text,
                           "sender": {"user_id": user, "nickname": name or f"user{user}"}})

    def command(self, line: str) -> str:
        parts = line.strip().split(" ", 3)
        if not parts or not parts[0]:
            return ""
        if parts[0] == "mode" and len(parts) > 1:
            self.mode = parts[1]
            return f"mode {self.mode}"
        if parts[0] == "group" and len(parts) == 4:
            text, at, reply = parts[3], False, None
            if text.startswith("@ "):
                at, text = True, text[2:]
            if text.startswith("^"):
                head, _, text = text.partition(" ")
                reply = int(head[1:])
            return f"message {self.group_message(int(parts[1]), int(parts[2]), text, at_self=at, reply_to=reply)}"
        if parts[0] == "private" and len(parts) >= 3:
            return f"message {self.private_message(int(parts[1]), ' '.join(parts[2:]))}"
        return f"? {line.strip()}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m harness_qq.simulator")
    parser.add_argument("--listen", default="ws://127.0.0.1:3001")
    parser.add_argument("--self-id", type=int, default=10001)
    args = parser.parse_args(argv)

    async def run():
        simulator = Simulator(args.self_id)
        address = await simulator.start(args.listen)
        print(json.dumps({"onebot": address}), flush=True)
        loop = asyncio.get_running_loop()
        done = asyncio.Event()

        def read():
            for line in sys.stdin:
                answer = loop.call_soon_threadsafe(lambda line=line: print(simulator.command(line), flush=True))
                del answer
            loop.call_soon_threadsafe(done.set)

        threading.Thread(target=read, daemon=True).start()
        await done.wait()
        await simulator.close()

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
