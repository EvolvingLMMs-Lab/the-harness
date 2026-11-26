"""The host's conversation control, as the terminal chat calls it: the reply while it is
written, the messages that wait their turn, stopping a turn, and a chat's name. Every call
of that part of the host's /api/agent routes is here and nowhere else in the terminal.

    live(answer)                          GET chat's "live": {job, text, reasoning, since} or None
    context(answer)                       GET chat's "context": the last call's tokens, the model's window
    compact(client, chat, instructions)   POST compact -> {compacted, messages, summary}
    queue(client, chat)                   GET queue  -> {chat, held, running, queued: [{id, text, queued}]}
    change(client, chat, action, ...)     POST queue {action: edit | remove | clear | send_now | resume}
    stop(client, chat)                    POST stop {hold: false} -> {stopped, queued, held}
    chats(client, ...), chat_change(...)  GET / POST chats (rename, pin, archive, delete)

`client` is tui.agent.Client (get(name, **query), post(name, body)). A host from before
these routes answers "no such route": missing(error) tells that apart from a failure, so
the chat can say that this host cannot do it instead of failing."""


def missing(error) -> bool:
    """Whether `error` is a host that has no such route (an earlier agent package)."""
    return "no such route" in str(error)


def live(answer: dict):
    """The reply being written, from a GET chat answer: None when none is."""
    found = answer.get("live")
    if not isinstance(found, dict):
        return None
    return {"job": found.get("job"), "text": str(found.get("text") or ""),
            "reasoning": str(found.get("reasoning") or ""), "since": found.get("since")}


def context(answer: dict):
    """How much of the model's context the chat used at its last call, from a GET chat
    answer: {tokens, window, messages, summarized, model}, None before any call (or from a
    host that does not say)."""
    found = answer.get("context")
    if not isinstance(found, dict) or found.get("input_tokens") is None:
        return None
    return {"tokens": int(found.get("input_tokens") or 0) + int(found.get("output_tokens") or 0),
            "window": found.get("window"), "messages": found.get("messages"), "summarized": bool(found.get("summarized")),
            "model": found.get("model")}


def compact(client, chat: str, instructions: str = "") -> dict:
    """Have the earlier part of the chat made into a summary now (it waits its turn in the
    chat's queue); {compacted, messages, summary}."""
    answer = client.post("compact", {"chat": chat, "wait": True, **({"instructions": instructions} if instructions else {})})
    return {"compacted": bool(answer.get("compacted")), "messages": int(answer.get("messages") or 0),
            "summary": str(answer.get("summary") or "")}


def queue(client, chat: str) -> dict:
    """What waits in `chat`: the turn that runs and the owner's messages after it, in order."""
    return _queue(client.get("queue", chat=chat), chat)


def change(client, chat: str, action: str, id=None, text=None) -> dict:
    """Change the queue (edit, remove, clear, send_now, resume); the queue after it."""
    body = {"chat": chat, "action": action, **({"id": id} if id is not None else {}),
            **({"text": text} if text is not None else {})}
    return _queue(client.post("queue", body), chat)


def _queue(answer: dict, chat: str) -> dict:
    return {"chat": answer.get("chat") or chat, "held": bool(answer.get("held")), "running": answer.get("running") or None,
            "queued": [{"id": row.get("id"), "text": str(row.get("text") or ""), "queued": row.get("queued")}
                       for row in answer.get("queued") or ()]}


def stop(client, chat: str) -> dict:
    """Stop the turn that runs in `chat`, keeping what it did; what waits goes on after it
    (hold false, as Esc does in Claude Code). {stopped, queued, held}."""
    answer = client.post("stop", {"chat": chat, "hold": False})
    return {"stopped": bool(answer.get("stopped")), "queued": int(answer.get("queued") or 0),
            "held": bool(answer.get("held"))}


def chats(client, archived: bool = False, q: str = "") -> list:
    """The identity's chats (pinned first); with `q`, those with the text in them."""
    return client.get("chats", archived=1 if archived else None, q=q or None)["chats"]


def chat_change(client, action: str, chat: str, title=None) -> list:
    """rename (with `title`), pin, unpin, archive, unarchive or delete a chat; the list after it."""
    return client.post("chats", {"action": action, "chat": chat, **({"title": title} if title is not None else {})})["chats"]
