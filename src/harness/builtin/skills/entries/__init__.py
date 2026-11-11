"""Entries: parts of a program that run at the same time, as a tree (runtime/execution/entries.py).
spawn() starts one; its handle waits for it, stops it and sends it messages. What an
entry's executions end with goes to its own handlers first, then up to the entry that
started it, and only what nobody handles reaches the model. Where the embodiment declares
channels (a game's keys, mouse and wheel in groups), entries run at the same time on their
own channels: claim() and unclaim() say which an entry has."""


class Entries:
    def spawn(self, fn, name=None, claims=None, priority=None, restart=True):
        """Run fn() at the same time as this code, as an entry of its own under this one,
        and return its handle: .wait(timeout=None) returns what fn returned (raises its
        failure, an ENTRY_FAILED event; None when it was cancelled or the timeout passed),
        .cancel() stops it and the entries it started, .send(message) gives it a message
        that its code reads with receive(), .state() says how it stands, .status is
        running, done, failed or cancelled. `name` labels it (default: fn's name); `claims`
        names the channels it uses (the game's CHANNELS; e.g. ["move", "look"]): it has them until it
        ends, and their keys and buttons are let go then; one another entry has makes it
        fail at once with a CHANNEL_CONFLICT event. Without channels, executions of entries
        take turns on the embodiment, in the order they start. Guards (when, watch) and handlers
        (on) set inside fn are the entry's: they watch its executions and those of the
        entries it starts, and end with it. An entry that fails goes to whoever waits for
        it, else to the handlers of the entry that started it (on("ENTRY_FAILED", ...)),
        then up; one nobody handles reaches you. Entries this program starts keep running
        after it ends, and you hear how they stand after each program; an entry's own
        entries end with it."""
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
        """The handles of the entries started so far (only those running, unless
        `running` is False), oldest first; each has .state(), .wait(), .cancel(),
        .send(); a sub-agent's (delegate) has .agent."""
        tree = self._entries
        return [entry for entry in list(tree.entries.values())
                if entry is not tree.root and (entry.running or not running)]


def exports(session):
    return {"spawn": session.spawn, "receive": session.receive, "entries": session.entries,
            "claim": session.claim, "unclaim": session.unclaim, "channels": session.channel_board}
