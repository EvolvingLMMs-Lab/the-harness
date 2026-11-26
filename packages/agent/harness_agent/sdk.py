"""harness.sdk.Agent: the identities in Python, one to one with harness agent.

    from harness.sdk import Agent
    work = Agent.new("work", name="工作助手")
    work.say("Remember that PRs are in English")     # into its main conversation; the answer
    work.say("and tidy the notes", wait=False)       # queued behind it: {"queued": id, "chat"}
    work.queue()                                     # what waits, what runs, whether it is held
    work.stop()                                      # the turn in progress, as Esc does
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

    def usage(self, range="today", *, start=None, end=None, week=False) -> dict:
        """What it spent over a stretch: `range` today, week (the last 7 days) or month (the
        last 30), or the days `start` to `end` (YYYY-MM-DD). {identity, range, start, end,
        cost_usd, plan_usd, seconds, calls: {total, priced, plan, unpriced}, days: [{date,
        cost_usd, calls, ...}], by_chat: [{chat, title, cost_usd, calls}], by_task: [{kind, id,
        title, cost_usd, calls}], by_model, today: {cost_usd, daily_budget, reserve, left_usd,
        ...}} (harness usage, /usage). The lists are empty when nothing was spent."""
        return self._client().usage(week, range, start, end)

    def raise_today(self, dollars) -> dict:
        """Today's budget becomes `dollars`; tomorrow it is the setting again."""
        return self._identity.account().raise_today(dollars)

    def settings(self) -> dict:
        """What holds for it of every setting an identity may have its own value of:
        {values: {"section.key": value}, own: the ones it sets itself, schema: each setting
        as a frontend draws it (title, description, type, choices), spaces: {place: off |
        learn | do}} (harness config show --identity ID)."""
        found = self._client().settings()
        return {key: found[key] for key in ("values", "own", "schema", "spaces")}

    def set(self, key, value) -> dict:
        """Its own value of the setting `key` ("agent.daily_budget", "learning.mode",
        "agent.model", "spaces.<place>.proactive"); None: the global one again. What holds
        after it, as settings() (harness config set KEY VALUE --identity ID)."""
        found = self._client().set_setting(key, value)
        return {name: found[name] for name in ("values", "own", "schema", "spaces")}

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

    # Its chats and what runs in them, over the session host: every frontend sees one life.

    def chats(self, *, archived=False, q=None) -> list:
        """Its chats, the main conversation first, then the pinned, then the newest: [{chat, kind,
        title, place, updated, unread, waiting, busy, pinned, archived}] (harness sessions,
        /sessions). `archived`: the archived ones instead; `q`: those whose title or words hold
        that text (each with `match`, where it was found)."""
        return self._client().chats(archived, q)

    def new_chat(self, title=None) -> str:
        """A new chat for one piece of work: its id."""
        return self._client().new_chat(title)

    def chat(self, chat="main", *, after=0) -> dict:
        """A chat's record after the number `after` and the reply being written there:
        {chat, meta, records: [{seq, event, time, ...}], live: None | {job, text, reasoning, since}}."""
        return self._client().chat(chat, after)

    def rename_chat(self, chat, title) -> list:
        """Give a chat another title; the list after it."""
        return self._client().chat_change("rename", chat, title)

    def pin_chat(self, chat, on=True) -> list:
        """Keep a chat on top of the list (on=False: no longer)."""
        return self._client().chat_change("pin" if on else "unpin", chat)

    def archive_chat(self, chat, on=True) -> list:
        """Take a chat out of the list (on=False: back into it). Not the main conversation."""
        return self._client().chat_change("archive" if on else "unarchive", chat)

    def chat_model(self, chat, model=None, *, effort=None) -> list:
        """A chat uses the model list's entry `model` (and the reasoning effort `effort`) from
        its next turn on (None: the identity's model, the model's own effort); the list after it."""
        return self._client().chat_change("model", chat, model=model, effort=effort)

    def attach(self, path, *, chat="main") -> dict:
        """Keep a file of this computer for a message of the chat: {id, name, size, type}."""
        return self._client().attach(path, chat)

    def delete_chat(self, chat) -> list:
        """Remove a chat and its record. Not the main conversation, not the chat of a place
        that is still connected, not while a turn runs in it."""
        return self._client().chat_change("delete", chat)

    def say(self, text, *, chat="main", wait=True, timeout=900, files=(), session=None, model=None,
            workspace="auto", folder=None) -> dict:
        """Say `text` to it in `chat`: it joins the one queue of its life in the session host,
        behind what every other frontend said. With `wait` the answer when its turn is over:
        {identity, session, answer} (`interrupted` when the turn was stopped); without,
        {queued: the message's id, chat} at once.

        With `session`, `model`, `folder` or a `workspace`, the earlier form: one turn of a
        dialogue of its own in this process, outside the queue ({identity, session, answer})."""
        if session is None and model is None and folder is None and workspace == "auto":
            if files:
                # `files`: paths here, given to the model with the message (images as images).
                return self._client().say(text, chat, False, timeout, files)
            return self._client().say(text, chat, wait, timeout)
        from .cli import model as chat_model
        from .session import Session
        from .tasks import Tasks

        self._identity.live()
        tasks = Tasks(model=model, workspace=workspace, folder=str(folder) if folder else None, identity=self._identity)
        dialogue = Session(self._identity, chat_model(model), tasks, session=session)
        return {"identity": self.id, "session": dialogue.id, "answer": dialogue.turn(text)}

    def compact(self, chat="main", instructions="") -> dict:
        """Compact a chat's context now: what was said before its last messages becomes a
        summary it goes on from; `instructions` say what the summary should keep. {compacted,
        messages, summary, chat} (harness agent compact, /compact)."""
        return self._client().compact(chat, instructions)

    def context(self, chat="main") -> dict:
        """How full a chat's context is: {input_tokens, output_tokens: of its last model call,
        window: what its model reads at most (None when it does not say), model, messages,
        summarized} (/context)."""
        return self._client().chat(chat, after=10 ** 12)["context"]

    def queue(self, chat="main") -> dict:
        """What waits in a chat: {chat, held, running: None | {id, kind, text, since}, queued:
        [{id, text, queued}]}: your messages whose turn has not begun, in order."""
        return self._client().queue(chat)

    def queue_edit(self, id, text, *, chat="main") -> dict:
        """Change the text of a message that waits; the queue after it."""
        return self._client().queue_change("edit", chat, id, text)

    def queue_remove(self, id, *, chat="main") -> dict:
        """Take a message out of the queue."""
        return self._client().queue_change("remove", chat, id)

    def queue_clear(self, *, chat="main") -> dict:
        """Take every message of yours out of the chat's queue."""
        return self._client().queue_change("clear", chat)

    def send_now(self, id, *, chat="main") -> dict:
        """Stop the turn in progress and do the waiting message `id` next."""
        return self._client().queue_change("send_now", chat, id)

    def queue_resume(self, *, chat="main") -> dict:
        """Let a held queue go on, in order."""
        return self._client().queue_change("resume", chat)

    def stop(self, chat="main", *, hold=False) -> dict:
        """Stop the turn in progress in a chat: its model call is cut off and its task
        cancelled, what was done stands, the record says "interrupted". {stopped, queued,
        held}. `hold`: the messages that wait stay until queue_resume() or send_now()."""
        return self._client().stop(chat, hold)

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
        """Its calendar between two times (this week by default; any stretch): {start, end,
        entries: [{id, title, start, end, kind, by, who, outcome, refused, planned, ...}],
        paused_own} (harness calendar list)."""
        return self._client().calendar(start, end)

    def calendar_add(self, title, at, *, until=None, kind="task", repeat=None, note="") -> dict:
        """Put an entry on its calendar (harness calendar add); the week after it."""
        return self._client().calendar_change("add", title=title, at=at, until=until, kind=kind, repeat=repeat,
                                              note=note)

    def calendar_update(self, entry, **changes) -> dict:
        """Change an entry: any of title, at, until (None: no end), kind, repeat, note. The
        week after it; `result` is the entry (harness calendar update)."""
        return self._client().post("calendar", {"action": "update", "id": entry, **changes})

    def calendar_move(self, entry, at, *, until=None) -> dict:
        return self._client().calendar_change("move", id=entry, at=at, until=until)

    def calendar_remove(self, entry) -> dict:
        """Take an entry off the calendar; calendar_restore puts it back."""
        return self._client().calendar_change("remove", id=entry)

    def calendar_restore(self, entry=None) -> dict:
        """Put back an entry that was removed (None: the one removed last)."""
        return self._client().calendar_change("restore", id=entry)

    def pause_own(self, on=True) -> dict:
        """Pause what it does on its own (it still answers you and mentions); on=False resumes it
        (harness calendar pause [--off])."""
        return self._client().calendar_change("pause_own" if on else "resume_own")

    @staticmethod
    def channel_kinds() -> list:
        """The kinds of channel the installed packages declare: [{kind, package, name: {en, zh},
        about, fields: [{id, kind, label, help, default, choices}], steps, login, groups, owner,
        pairing, messages}] (harness channels kinds). Empty when no package provides one: channels
        come from packages (harness install NAME)."""
        from .channels import kinds

        return list(kinds()[0].values())

    def channels(self, account=None) -> list:
        """Its chat channel accounts: [{account, kind, name, state: starting | waiting_login |
        logged_in, online, values, entered, owner, paired, pending, login}] (harness channels
        list). With `account`: that one, with its `groups` and what its login shows now."""
        return self._client().channels(account)

    def channel_add(self, kind, *, title=None, **values) -> dict:
        """Connect an account of the channel `kind` to this identity (harness channels add):
        `values` are the fields the kind declares (channel_kinds()). Then it logs in as its
        declaration says (channels(account)[0]["login"]), then channel_groups and
        channel_owner_code. {account, channels: [its row], ...}."""
        return self._client().channel("add", kind=kind, values=values, title=title)

    def channel_set(self, account, **values) -> dict:
        """Change an account's settings (the fields its kind declares); its space starts again."""
        return self._client().channel("set", account=account, values=values)

    def channel_groups(self, account, groups, *, mode=None) -> dict:
        """Let the account into these groups (none by default); `mode`: one the kind declares
        (default: its first)."""
        return self._client().channel("groups", account=account, groups=list(groups), mode=mode)

    def channel_leave_group(self, account, group) -> dict:
        return self._client().channel("leave_group", account=account, group=group)

    def channel_owner_code(self, account) -> str:
        """A one-time code the owner sends the account from their own account to be bound."""
        return (self._client().channel("owner_code", account=account).get("result") or {}).get("code")

    def channel_test(self, account) -> dict:
        """Whether a channel account works now: {account, ok, state, owner, groups}; raises
        with what is missing (harness channels test)."""
        return self._client().channel("test", account=account)["result"]

    # Skill sources: where its skills are taken from (harness skills).

    def skill_sources(self) -> dict:
        """{sources: [{id, from, kind, added, checked, skills: [{name, evidence, there}]}],
        shared: [{name, package, entries, read_only}]}: the sources added to it, and the
        shared libraries (harness skills sources)."""
        found = self._client().skill_sources()
        return {"sources": found["sources"], "shared": found["shared"]}

    def skill_source_add(self, source) -> dict:
        """Add a source (a folder or SKILL.md here, github:OWNER/REPO[#FOLDER], git:URL, the
        address of an archive or of a SKILL.md) and take its skills in at evidence proposed:
        {id, from, kind, added, skipped} (harness skills add)."""
        return self._client().skill_source("add", **{"from": str(source)})["result"]

    def skill_source_test(self, source) -> dict:
        """Read a source (or one added, by its id) without taking anything: {from, kind,
        skills: [{name, description, program}], seconds} (harness skills test)."""
        return self._client().skill_source("test", **{"from": str(source)})["result"]

    def skill_source_update(self, id=None) -> dict:
        """Read the sources again and take in the skills that are new: {updated: {id: [names]}}."""
        return self._client().skill_source("update", id=id)["result"]

    def skill_source_remove(self, id, *, keep=False) -> dict:
        """Forget a source; the skills it brought go with it unless `keep`."""
        return self._client().skill_source("remove", id=id, keep=keep)["result"]

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
