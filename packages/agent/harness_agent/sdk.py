"""harness.sdk.Agent: the identities in Python, one to one with harness agent.

    from harness.sdk import Agent
    work = Agent.new("work", name="工作助手")
    work.say("Remember that PRs are in English")
    Agent("work").memory()

Agent() with no id is the current identity (or the only one); with several and none
chosen it raises, as a script does: nothing is guessed."""
from . import state
from .state import Identity


class Agent:
    def __init__(self, id=None):
        self._identity = Identity(state.resolve(id), create=False)

    def __repr__(self):
        return f"Agent({self.id!r})"

    @property
    def id(self) -> str:
        return self._identity.id

    @property
    def name(self) -> str:
        return self._identity.name

    @property
    def folder(self):
        return self._identity.directory

    @property
    def fingerprint(self) -> str:
        return self._identity.fingerprint

    @classmethod
    def new(cls, id, *, name=None, clone=None, card=None) -> "Agent":
        """A new identity (harness agent new): `clone` copies another's persona, skills and
        reactions, never its memory; `card` takes a character card's name, persona and avatar."""
        state.create(id, display=name, source=clone, card=card)
        return cls(id)

    @staticmethod
    def list() -> list:
        """The identities: [{id, name, folder, current}]."""
        chosen = state.current()
        return [{**Identity(name, create=False).to_dict(), "current": name == chosen} for name in state.identities()]

    @staticmethod
    def use(id) -> None:
        """Make `id` the current identity (harness agent use)."""
        state.use(id)

    def rename(self, name) -> None:
        """Change the display name; the id stays."""
        self._identity.rename(name)

    def delete(self) -> None:
        """Remove this identity, its memory, conversations, library and key pair."""
        state.delete(self.id)

    def usage(self, *, week=False) -> dict:
        """What it spent: {identity, today: {cost_usd, daily_budget, reserve, own_usd, by_source,
        ...}, week: [...]} (harness usage, /usage), from the session host."""
        return self._client().usage(week)

    def raise_today(self, dollars) -> dict:
        """Today's budget becomes `dollars`; tomorrow it is the setting again."""
        return self._identity.account().raise_today(dollars)

    def set_budget(self, dollars=None, *, calls=None) -> dict:
        """Its own daily budget and calls without a price (None: the global setting again)."""
        if dollars is not None or calls is None:
            self._identity.set_setting("daily_budget", dollars)
        if calls is not None:
            self._identity.set_setting("daily_calls", calls)
        return self._identity.settings()

    def memory(self) -> dict:
        """Its memory: {revision, entries: {key: {text, scope, source, chat, ...}}} (harness
        library memory, /library), from the session host."""
        return self._client().memory()

    def chats(self) -> list:
        """Its chats, the main conversation first: [{chat, kind, title, place, updated, unread,
        waiting, busy}] (harness sessions, /sessions), from the session host."""
        return self._client().chats()

    def say(self, text, *, session=None, model=None, workspace="auto", folder=None) -> dict:
        """One dialogue turn: {identity, session, answer}. Tasks it starts run in the session host."""
        from .cli import model as chat_model
        from .session import Session
        from .tasks import Tasks

        self._identity.live()
        tasks = Tasks(model=model, workspace=workspace, folder=str(folder) if folder else None, identity=self._identity)
        dialogue = Session(self._identity, chat_model(model), tasks, session=session)
        return {"identity": self.id, "session": dialogue.id, "answer": dialogue.turn(text)}

    # Over the session host, one to one with harness library, calendar and channels.

    def _client(self):
        from .frontends import Client

        return Client(self.id)

    def reactions(self, path="") -> dict:
        """One level of its tree of reactions, like a folder: {path, nodes: [{name, about, when,
        do, source, evidence, enabled, uses, done, children, lit}]}; `path`: node names from the
        root ("a/b" or a list) (harness library tree PATH)."""
        return self._client().reactions(path)

    def learned(self) -> dict:
        """What it learned: {skills: [{name, description, evidence, uses, source, ...}], memory,
        mode, shared_libraries} (harness library skills)."""
        return self._client().learned()

    def undo(self, name) -> dict:
        """Undo a skill it learned: no longer loaded, the revision kept (harness library undo)."""
        return self._client().undo(name)

    def calendar(self, start=None, end=None) -> dict:
        """A week of its calendar (this one by default): {start, end, entries: [{id, title, start,
        end, kind, by, who, outcome, refused, planned, ...}], paused_own} (harness calendar list)."""
        return self._client().calendar(start, end)

    def calendar_add(self, title, at, *, until=None, kind="task", repeat=None, note="") -> dict:
        """Put an entry on its calendar (harness calendar add); the week after it."""
        return self._client().calendar_change("add", title=title, at=at, until=until, kind=kind, repeat=repeat,
                                              note=note)

    def calendar_move(self, entry, at, *, until=None) -> dict:
        return self._client().calendar_change("move", id=entry, at=at, until=until)

    def calendar_remove(self, entry) -> dict:
        return self._client().calendar_change("remove", id=entry)

    def pause_own(self, on=True) -> dict:
        """Pause what it does on its own (it still answers you and mentions); on=False resumes it
        (harness calendar pause [--off])."""
        return self._client().calendar_change("pause_own" if on else "resume_own")

    def channels(self) -> list:
        """Its chat channel accounts: [{account, kind, online, dm, entered, owner, paired,
        pending}] (harness channels list)."""
        return self._client().channels()

    def channel_add(self, kind="qq", *, dm="pairing", groups="mention", onebot=None) -> dict:
        """Connect a channel account to this identity (harness channels add): it logs in through
        its OneBot implementation at `onebot`; then channel_groups and channel_owner_code."""
        return self._client().channel("add", kind=kind, dm=dm, groups=groups, onebot=onebot)

    def channel_groups(self, account, groups, *, mode="mention") -> dict:
        """Let the account into these groups (none by default)."""
        return self._client().channel("groups", account=account, groups=list(groups), mode=mode)

    def channel_owner_code(self, account) -> str:
        """A one-time code the owner sends the account in a private chat to be bound."""
        return (self._client().channel("owner_code", account=account).get("result") or {}).get("code")

    def channel_pair(self, account, code) -> dict:
        """Approve a stranger's pairing request (harness channels pair approve)."""
        return self._client().channel("pair", account=account, code=code)

    def channel_unpair(self, account, user) -> dict:
        return self._client().channel("unpair", account=account, user=user)

    def channel_remove(self, account) -> dict:
        """Disconnect a channel account (harness channels remove)."""
        return self._client().channel("remove", account=account)

    # Taking it with you, one to one with harness agent share, adopt, backup, restore,
    # retire and import (take.py).

    def share(self, to, *, with_memory=False, public=False, card=False, confirm=None, **options) -> dict:
        """Share it as a package at `to` (as harness share sends a library), or with `card` a
        Character Card V3 file. `confirm(preview)` sees every text that becomes public first;
        without it nothing is sent ({"needs_consent": True, ...}). The private key and
        credentials never go; a GitHub repository it creates is private unless `public`."""
        from . import take

        if card:
            return take.share_card(self._identity, to, confirm=confirm)
        return take.share(self._identity, to, with_memory=with_memory, public=public, confirm=confirm, **options)

    @classmethod
    def adopt(cls, source, *, id=None, test=False) -> "Agent":
        """A new identity (new id, new key) from a shared one or a character card; its skills are
        proposed until their own tests pass here (`test` runs them now), its reactions off."""
        from . import take

        adopted = cls(take.adopt(source, id=id)["identity"])
        if test:
            take.test_adopted(adopted._identity)
        return adopted

    def test_adopted(self, names=None) -> list:
        """Run the own tests of its adopted skills that wait for them."""
        from . import take

        return take.test_adopted(self._identity, names)

    def backup(self, path, passphrase, *, with_keys=False) -> dict:
        """A full backup at `path` encrypted with `passphrase`: its folder, private key, memory and
        channel credentials; the model keys only `with_keys`."""
        from . import take

        return take.backup(self._identity, path, passphrase, with_keys=with_keys)

    @classmethod
    def restore(cls, path, passphrase, *, replace=False) -> "Agent":
        """The identity of a backup, restored here; log in to its channels again."""
        from . import take

        return cls(take.restore(path, passphrase, replace=replace)["identity"])

    def retire(self) -> dict:
        """Stop it on this computer after it moved; opening it here then says so."""
        from . import take

        return take.retire(self._identity)

    @classmethod
    def import_from(cls, kind, folder=None, *, id=None) -> "Agent":
        """A new identity from an OpenClaw workspace or a Hermes profile: persona, memory and
        skills, never channel tokens or keys."""
        from . import take

        return cls(take.import_from(kind, folder, id=id)["identity"])
