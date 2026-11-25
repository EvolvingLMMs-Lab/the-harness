"""The QQ space against the OneBot 11 simulator: who gets in, what is addressed, and one outcome
for every message sent."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from agent_space import End, Participant, generate_key

from harness_qq import space as qq
from harness_qq.simulator import Simulator


class World:
    def __init__(self, dm="pairing", groups=None):
        self.dm, self.groups = dm, groups

    async def __aenter__(self):
        self.folder = tempfile.TemporaryDirectory()
        config = Path(self.folder.name) / "qq.json"
        config.write_text(json.dumps({"identity": "default", "dm": self.dm, "groups": self.groups or {}}))
        self.settings = qq.Settings(config)
        self.onebot = Simulator()
        await self.onebot.start()
        self.owner_key = generate_key()
        self.qq = qq.QQSpace(self.onebot.address, settings=self.settings, owner_identity=self.owner_key.identity)
        self.listening = asyncio.Event()
        self.task = asyncio.get_running_loop().create_task(self.qq.serve("ws://127.0.0.1:0", self._ready))
        await asyncio.wait_for(self.listening.wait(), 10)
        await self.until(lambda: self.qq.online)
        self.agent = await Participant.connect(self.address, key=generate_key())
        await self.agent.join("member")
        self.events = []
        self.agent.on("event", self.events.append)
        await self.agent.subscribe()
        return self

    def _ready(self, address):
        self.address = address
        self.listening.set()

    async def owner(self):
        p = await Participant.connect(self.address, key=self.owner_key)
        await p.join("owner")
        return p

    async def until(self, ready, seconds=10.0):
        for _ in range(int(seconds / 0.02)):
            if ready():
                return True
            await asyncio.sleep(0.02)
        raise AssertionError("it did not happen")

    def messages(self):
        return [e for e in self.events if e["type"] == "qq.message"]

    async def __aexit__(self, *exc):
        await self.agent.close()
        await self.qq.space.close()
        await asyncio.wait_for(self.task, 10)
        await self.onebot.close()
        self.folder.cleanup()


def run(coro):
    return asyncio.run(coro)


class Chats(unittest.TestCase):
    def test_a_group_it_was_not_let_into_is_not_recorded(self):
        async def go():
            async with World(groups={"123": "mention"}) as w:
                w.onebot.group_message(456, 7, "nobody let it in here")
                w.onebot.group_message(123, 7, "just talking")
                await w.until(lambda: len(w.messages()) == 1)
                await asyncio.sleep(0.2)
                (only,) = w.messages()
                self.assertEqual(only["data"]["chat"], "group:123")
                self.assertFalse(only["data"]["addressed"])
                self.assertEqual(only["source"], "outside")
        run(go())

    def test_an_at_or_a_reply_to_its_message_addresses_it(self):
        async def go():
            async with World(groups={"123": "mention"}) as w:
                w.onebot.group_message(123, 7, "hey you", at_self=True)
                await w.until(lambda: len(w.messages()) == 1)
                named = w.messages()[0]
                self.assertTrue(named["data"]["named"] and named["data"]["addressed"])
                out = await w.agent.act("qq.reply", named["data"]["message"], {"text": "hello"})
                self.assertIs(out.end, End.DONE)
                sent = w.onebot.sent[-1]
                self.assertEqual((sent["action"], sent["group_id"]), ("send_group_msg", 123))
                self.assertEqual(sent["message"][0], {"type": "reply", "data": {"id": named["data"]["message_id"]}})
                w.onebot.group_message(123, 8, "answering the bot", reply_to=int(out.result["message_id"]))
                await w.until(lambda: len(w.messages()) == 2)
                self.assertTrue(w.messages()[1]["data"]["addressed"])
                # Its own message is an event of its own presence, not a message to react to.
                own = [e for e in w.events if e["type"] == "qq.sent"]
                self.assertTrue(own and own[0]["source"].startswith("presence/"))
        run(go())

    def test_a_group_entered_with_all_addresses_every_message(self):
        async def go():
            async with World(groups={"123": "all"}) as w:
                w.onebot.group_message(123, 7, "anything")
                await w.until(lambda: len(w.messages()) == 1)
                self.assertTrue(w.messages()[0]["data"]["addressed"])
                self.assertFalse(w.messages()[0]["data"]["named"])
        run(go())


class Sending(unittest.TestCase):
    def setUp(self):
        self.receipt = qq.RECEIPT_SECONDS
        qq.RECEIPT_SECONDS = 0.5

    def tearDown(self):
        qq.RECEIPT_SECONDS = self.receipt

    def test_every_receipt_is_one_outcome(self):
        async def go():
            async with World(groups={"123": "mention"}) as w:
                send = lambda: w.agent.act("qq.send", "group:123", {"text": "hi"})  # noqa: E731
                self.assertIs((await send()).end, End.DONE)
                for mode, end, code in (("async", End.UNKNOWN, "onebot.async"), ("failed", End.FAILED, "onebot.failed"),
                                        ("silent", End.UNKNOWN, "onebot.timeout")):
                    w.onebot.mode = mode
                    out = await send()
                    self.assertEqual((out.end, out.reason.code), (end, code), mode)
                self.assertEqual(out.known, {"handed_to_onebot": True})
                self.assertEqual(out.unconfirmed, ["delivered"])
                w.onebot.mode = "drop"
                out = await send()
                self.assertEqual((out.end, out.reason.code), (End.UNKNOWN, "onebot.closed"))
                await w.until(lambda: not w.qq.online)
                await w.onebot.close()
                out = await send()
                self.assertEqual((out.end, out.reason.code), (End.REFUSED, "qq.offline"))
                # A chat it is not in.
                out = await w.agent.act("qq.send", "group:456", {"text": "hi"})
                self.assertEqual((out.end, out.reason.code), (End.REFUSED, "qq.unknown_chat"))
        run(go())


class People(unittest.TestCase):
    def test_the_owner_binds_with_a_one_time_code(self):
        async def go():
            async with World() as w:
                member_try = await w.agent.act("qq.owner_code")
                self.assertEqual(member_try.reason.code, "forbidden")
                owner = await w.owner()
                code = (await owner.act("qq.owner_code")).result["code"]
                w.onebot.private_message(99, code)
                await w.until(lambda: any(e["type"] == "qq.owner_bound" for e in w.events))
                self.assertEqual(w.settings.owner, "99")
                w.onebot.private_message(99, "hello it's me")
                await w.until(lambda: len(w.messages()) == 1)
                self.assertTrue(w.messages()[0]["data"]["owner"])
                await owner.close()
        run(go())

    def test_a_stranger_gets_a_pairing_code_and_waits_for_the_owner(self):
        async def go():
            async with World() as w:
                w.onebot.private_message(55, "who are you")
                await w.until(lambda: any(e["type"] == "qq.pairing_requested" for e in w.events))
                request = next(e for e in w.events if e["type"] == "qq.pairing_requested")["data"]
                await w.until(lambda: any(s.get("user_id") == 55 for s in w.onebot.sent))
                self.assertIn(request["code"], w.onebot.sent[-1]["message"])
                w.onebot.private_message(55, "still waiting")
                await asyncio.sleep(0.2)
                self.assertEqual(w.messages(), [])  # not kept while it waits
                owner = await w.owner()
                self.assertIs((await owner.act("qq.pair", args={"code": request["code"]})).end, End.DONE)
                w.onebot.private_message(55, "now?")
                await w.until(lambda: len(w.messages()) == 1)
                self.assertEqual(w.messages()[0]["data"]["chat"], "private:55")
                await owner.close()
        run(go())


if __name__ == "__main__":
    unittest.main()
