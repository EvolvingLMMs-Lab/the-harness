"""Units a program starts (runtime/execution/entries.py): spawn() runs code as a unit of its
own, of the model; its handle waits for it, ends it and sends it messages. What a unit's
executions end with goes to the handlers, and only what nobody handles reaches the model,
as every unit's end does. Where the embodiment declares channels, units act at the same
time on their own channels: claim() and unclaim() say which a unit has."""


class Entries:
    def spawn(self, fn, name=None, claims=None, priority=None, restart=False, until=None):
        """Run fn() at the same time as this code, as a unit of its own, and return its
        handle: .wait(timeout=None) returns what fn returned (raises its failure, an
        ENTRY_FAILED event; None when it was cancelled or the timeout passed), .cancel()
        ends it, .send(message) gives it a message that its code reads with receive(),
        .output(chars=2000) is what it has printed so far, .state() says how it stands,
        .status is running, done, failed or cancelled. `name`
        labels it (default: fn's name). `priority`: what it holds the embodiment with
        (default: that of the unit that starts it); a unit of higher priority ends a lower
        unit's execution where it is, with the event PREEMPTED and what it had done, and
        holds the environment until it ends; the model is told at once. With restart=True
        the lower call is started again when the higher unit is over, instead.
        Units of equal priority take turns, in the order they start. `claims` names the
        channels it uses where the embodiment declares channels: it has them until it
        ends, and what it held on them is let go then; one another unit has makes it fail
        at once with a CHANNEL_CONFLICT event. The unit is the model's: it and the
        reflexes it sets go on after the program that started it, and end with the model.
        A unit that fails goes to whoever waits for it, else to a reflex that answers
        ENTRY_FAILED; the model hears of every unit's end. `until`: what the unit is for,
        a condition of the view that holds when its work is done; its end says whether it
        held (.ok)."""
        return self._entries.spawn(fn, name=name, claims=claims, priority=priority, restart=restart, until=until)

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
        `running` is False), oldest first; each has .id, .state(), .output(), .wait(),
        .cancel(), .send(); a program the model wrote is one of them (.cell is its number);
        a sub-agent's (delegate) has .agent."""
        tree = self._entries
        return [entry for entry in list(tree.entries.values())
                if entry is not tree.root and (entry.running or not running)]

    def output_of(self, unit, chars=2000):
        """What the unit `unit` (its id, such as "e27", or its handle) has printed so far:
        the last `chars` characters (at most 30000), while it runs or after it ended.
        Reading takes nothing away: the unit's result still has the whole output when it
        ends. "" when it has printed nothing."""
        tree = self._entries
        entry = unit if getattr(unit, "tree", None) is tree else tree.entries.get(str(unit))
        if entry is None or entry is tree.root:
            raise ValueError(f"no unit {unit!r}; entries(running=False) lists the units started so far")
        return entry.output(chars)


def exports(session):
    return {"spawn": session.spawn, "receive": session.receive, "entries": session.entries,
            "output_of": session.output_of, "claim": session.claim, "unclaim": session.unclaim, "channels": session.channel_board}
