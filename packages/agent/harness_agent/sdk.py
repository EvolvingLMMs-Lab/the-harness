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

    def memory(self) -> dict:
        return self._identity.memory()

    def chats(self) -> list:
        """Its conversations, newest first."""
        return self._identity.sessions()

    def say(self, text, *, session=None, model=None, workspace="auto", folder=None) -> dict:
        """One dialogue turn: {identity, session, answer}. Tasks it starts run in the session host."""
        from .cli import model as chat_model
        from .session import Session
        from .tasks import Tasks

        self._identity.live()
        tasks = Tasks(model=model, workspace=workspace, folder=str(folder) if folder else None, identity=self._identity)
        dialogue = Session(self._identity, chat_model(model), tasks, session=session)
        return {"identity": self.id, "session": dialogue.id, "answer": dialogue.turn(text)}
