"""Units a program starts (runtime/execution/entries.py): spawn() runs code as a unit of its
own, of the model; its handle waits for it, ends it and sends it messages. What a unit's
executions end with goes to the handlers, and only what nobody handles reaches the model,
as every unit's end does. Where the embodiment declares channels, units act at the same
time on their own channels: claim() and unclaim() say which a unit has."""


class Entries:
    def spawn(self, fn, name=None, claims=None, priority=None, restart=False):
        """Run fn() at the same time as this code, as a unit of its own, and return its
        handle: .wait(timeout=None) returns what fn returned (raises its failure, an
        ENTRY_FAILED event; None when it was cancelled or the timeout passed), .cancel()
        ends it, .send(message) gives it a message that its code reads with receive(),
        .state() says how it stands, .status is running, done, failed or cancelled. `name`
        labels it (default: fn's name). `priority`: what it holds the embodiment with
        (default: that of the unit that starts it); a unit of higher priority ends a lower
        unit's execution where it is, with the event PREEMPTED and what it had done, and
        holds the environment until it ends; the model is told at once. With restart=True
        the lower call is started again when the higher unit is over, instead.
        Units of equal priority take turns, in the order they start. `claims` names the
        channels it uses where the embodiment declares channels: it has them until it
        ends, and what it held on them is let go then; one another unit has makes it fail
        at once with a CHANNEL_CONFLICT event. The unit is the model's: it and the rules
        and handlers it sets go on after the program that started it, and end with the
        model. A unit that fails goes to whoever waits for it, else to the handlers
        (on("ENTRY_FAILED", ...)); the model hears of every unit's end."""
        return self._entries.spawn(fn, name=name, claims=claims, priority=priority, restart=restart)

    def receive(self, timeout=None):
        """The oldest message sent to the entry this code runs in (handle.send), waiting at
        most `timeout` seconds for one (None: as long as it takes); None when none came."""
        return self._entries.current().receive(timeout)

    def claim(self, *channels):
        """Claim channels for the entry this code runs in until it unclaims them or ends;
        no other entry may use them meanwhile, its own entries may. True; when one is
        another entry's, a CHANNEL_CONFLICT event goes to this entry's handlers and up
        (False when a handler took it)."""
        return self._entries.claim(list(channels))

    def unclaim(self, *channels):
        """Let go of channels (none named: all this entry has): its claims, and the keys
        and buttons it holds down on them."""
        self._entries.release(list(channels) or None)

    def channel_board(self):
        """Who has each channel now: {channel: {"entry", "how": "claimed" | "driving" |
        "holding"}}, None for a free one (at its default)."""
        return self._entries.channels()

    def entries(self, running=True):
        """The handles of the units started so far (only those running, unless
        `running` is False), oldest first; each has .state(), .wait(), .cancel(),
        .send(); a sub-agent's (delegate) has .agent."""
        tree = self._entries
        return [entry for entry in list(tree.entries.values())
                if entry is not tree.root and (entry.running or not running)]


def exports(session):
    return {"spawn": session.spawn, "receive": session.receive, "entries": session.entries,
            "claim": session.claim, "unclaim": session.unclaim, "channels": session.channel_board}
