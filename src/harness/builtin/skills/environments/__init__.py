"""Another environment for one conversation, and sub-agents on request.

A conversation works in the environment its user chose. When a step cannot be done there
(it needs something only another kind of environment has), the program
asks for another kind with use_environment(kind, why). The session host decides as the
user's settings say (environments.attach and its rules): it may ask the user, showing
`why`; where nobody can be asked and the settings require asking, it refuses with the
reason. Once taken, that environment's calls are name.call(...) until release_environment(name) or the end of the
conversation. The host keeps every attachment and its reason in the trace.

Sub-agents are off unless the user switched them on: request_agents(why) asks the user to.
"""

from harness.sdk import control


class Environments:
    def _ask_conversation(self, operation, **detail):
        return control.ask_host("environment", action=operation, **detail)

    def use_environment(self, kind, why, folder=None):
        """Take another environment into this conversation: `kind` is one the user's
        installation has (environment_kinds() lists them), `why` one
        sentence the user reads when they are asked. A kind that works in a folder needs `folder`. Returns the
        environment, whose calls are then kind.call(...); raises ValueError with the reason
        when the user or their settings refuse. None when the user paused first."""
        name = str(kind).strip()
        if name in self._attached:
            return self.namespace[name]
        given = self._ask_conversation("use", environment=name, why=str(why or "").strip(),
                                   **({"folder": str(folder)} if folder else {}))
        if given is None:
            return None
        try:
            proxy = self.attach(name, given["session"])
        except Exception as error:
            # The host took a workspace for it: give it back.
            control.ask_host("environment", action="release", environment=name, failed=f"{type(error).__name__}: {error}")
            raise
        print(given.get("about") or f"{name} is attached: call it as {name}.NAME(...)")
        return proxy

    def environment_kinds(self):
        """The kinds of environment this conversation can take: [{"kind", "about", "folder"}]
        (folder: it works in one folder, which use_environment is given)."""
        return self._ask_conversation("kinds") or []

    def release_environment(self, kind):
        """Give an environment taken with use_environment back. True when it was attached."""
        name = str(kind).strip()
        if not self.detach(name):
            return False
        self._ask_conversation("release", environment=name)
        return True

    def request_agents(self, why):
        """Ask the user to switch sub-agents on for this conversation (`why`: one sentence
        they read). True once they are on (delegate, wait_agents, send_agent and cancel_agent
        are then calls of this conversation); ValueError with the reason when refused."""
        given = self._ask_conversation("agents", why=str(why or "").strip())
        if given is None:
            return None
        added = self.load_skills(given.get("skills") or [])
        if given.get("about"):
            print(given["about"])
        return bool(added) or "agents" in self.skills
