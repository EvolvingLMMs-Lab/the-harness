# qq

The `qq` package makes a QQ account a space the agent lives in: the groups the owner lets it
into and the private chats of the owner and of the people paired with it. It speaks the
[Agent Space Protocol](https://github.com/agent-space-protocol/agentspaceprotocol) itself (it
is not a worker behind the translation layer) and reaches QQ through a
[OneBot 11](https://github.com/botuniverse/onebot-11) implementation, such as NapCat, that has
logged in to the account and serves a forward WebSocket.

## Use

Choose the identity and the private-chat policy first, then log in (scan the QR code in the
OneBot implementation), then start the space:

```bash
python -m harness.space.serve qq --init --config ~/.harness/channels/qq.json --identity default --dm pairing
python -m harness.space.serve qq --onebot ws://127.0.0.1:3001 --config ~/.harness/channels/qq.json \
    --listen ws://127.0.0.1:7900
harness --workspace space --space ws://127.0.0.1:7900
```

`HARNESS_QQ_TOKEN` is OneBot's access token when it has one.

| What | How |
| --- | --- |
| Groups | none by default; the owner lets it into one with `qq.enter_group` (mode `mention` or `all`) |
| Owner | `qq.owner_code` gives a one-time code; the owner sends it to the account in a private message |
| Strangers | `dm = pairing` (default): a pairing code, valid an hour; `qq.pair` approves it, `qq.unpair` revokes; `allowlist`, `open`, `off` |
| Named | an @-mention of the account or a reply to its message; the event `qq.message` says `addressed` |

Sending (`qq.send`, effect class `send`) and replying (`qq.reply`, effect class `change`) end
with exactly one outcome: OneBot's `ok` is done, `async` is unknown (accepted, delivery not
confirmed), `failed` is failed, no receipt within 20 seconds or a lost connection is unknown,
and with no connection to OneBot it is refused (`qq.offline`) and nothing was sent.

## Without QQ

`python -m harness_qq.simulator --listen ws://127.0.0.1:3001` is a OneBot 11 simulator: lines
on its standard input make messages arrive (`group 123 456 @ hello`, `private 789 hi`) and
change how it answers (`mode silent` is a network that is gone). The tests use it.
