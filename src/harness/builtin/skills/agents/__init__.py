"""Sub-agents: a program hands parts of its task to agents of its own, which work at the
same time, each in a workspace of its own (or with the windows this agent hands over),
and waits for their results. The conversation that runs the program starts and keeps
them (runtime/task/delegation.py): every call here is a request to it, sent as a note, and its
answer comes back through the kernel (runtime/execution/control.py). Each turn of a sub-agent is
a unit of the model (runtime/execution/entries.py): when it ends, the conversation tells the kernel,
the model hears of it, and a turn that ended without an answer is an ENTRY_FAILED event for
the handlers first."""

import uuid

from harness.sdk import spans
from harness.sdk import control


# A sub-agent's statuses while it works on (runtime/task/delegation.py state()).


# What a reviewer is asked (Agents.review).
REVIEW = ("Review the code below. It is for: {purpose}\n\nYou have not seen how it was written: read it as it "
          "is. Report, the most serious first, what in it would make it fail, do something other than what it is "
          "for, or do its work much more slowly or wastefully than it could; for each, the place in the code and "
          "what would show it when the code runs. Where it calls something you can read (its documentation, its "
          "source), check the call against that. Do not rewrite the code. If you find nothing, say so.\n\n"
          "```\n{code}\n```")


class Agents:
    def _agents(self, operation, **detail):
        if not spans.connected():
            raise RuntimeError("sub-agents need the conversation that runs this program; none is connected")
        identifier = uuid.uuid4().hex[:12]
        spans.note("agents", action=operation, id=identifier, **detail)
        answer = control.wait_answer(identifier)
        if answer is None:
            return None
        if answer.get("error"):
            raise ValueError(answer["error"])
        return answer.get("value")

    def delegate(self, task, workspace="new", budget=None, model=None, agent=None, multi_turn=False):
        """Start a sub-agent on `task` (what it is to do and what to report back); returns its
        id. `workspace`: "new" (a workspace of its own, of this one's kind), the name
        of another kind the installation has (a new one of that kind), or "share" (it takes over the windows this agent
        holds now and hands them back when its turn ends). `budget`: {"calls", "cost", "seconds"},
        taken from this agent's own (default: all that is left). `model`: another model of
        the same provider. `agent`: another harness's agent ("claude-code", "codex") that does
        the task in its own bounded directory. `multi_turn=True` keeps a supported external
        agent available for `send_agent` within the original budget; cancel it when done."""
        agent = self._agents("delegate", task=str(task), workspace=str(workspace),
                             budget=budget if budget is None or isinstance(budget, (int, float)) else dict(budget),
                             model=None if model is None else str(model), agent=None if agent is None else str(agent),
                             multi_turn=multi_turn)
        tree = getattr(self, "_entries", None)
        if agent is not None and tree is not None:
            tree.adopt_agent(agent, task)
        return agent

    def review(self, code, purpose, budget=None):
        """Have code read by a sub-agent that has not seen how it was written; returns its id
        (wait_agents gives its report). It is given the code and what the code is for, not
        the author's conclusions, as Claude Code has code reviewed."""
        return self.delegate(REVIEW.format(purpose=" ".join(str(purpose).split()), code=str(code)), budget=budget)

    def wait_agents(self, ids=None, timeout=None):
        """Wait until the turn of each sub-agent in `ids` (default: all this agent started) is
        over, at most `timeout` seconds; returns {id: {"status", "result", "model_calls",
        "cost_usd", "seconds", "directory", "files"}}, or None when the user paused this
        agent first."""
        ids = [ids] if isinstance(ids, str) else (list(ids) if ids else None)
        ids = [self._agent_id(item) for item in ids] if ids else ids
        return self._agents("wait", ids=ids, timeout=timeout)

    def send_agent(self, agent, text):
        """Send sub-agent `agent` a message (more to do, or the answer to what it asked). One
        whose turn was over goes on with what it has, and the end of that turn reaches this
        agent as the end of its first did."""
        agent = self._agent_id(agent)
        tree = getattr(self, "_entries", None)
        # The turn the message starts is a unit of this agent, unless one of it still runs.
        turn = tree.adopt_agent(agent, text) if tree is not None and not tree.agent_runs(agent) else None
        try:
            return self._agents("send", agent=agent, text=str(text))
        except Exception:
            if turn is not None:
                tree.agent_ended(agent, {"status": "cancelled"}, cancelled=True)
            raise

    def cancel_agent(self, agent):
        """Stop sub-agent `agent` (and those it started); returns its report."""
        return self._agents("cancel", agent=self._agent_id(agent))

    def _agent_id(self, agent) -> str:
        """A sub-agent by its id (a3), or by the id of its entry (e3: a program's output lists
        the entries of the sub-agents it started), as the model may name it."""
        tree = getattr(self, "_entries", None)
        entry = tree.entries.get(str(agent)) if tree is not None else None
        if entry is not None and entry.kind == "agent" and entry.agent:
            return entry.agent
        return str(agent)


def exports(session):
    return {"delegate": session.delegate, "wait_agents": session.wait_agents, "send_agent": session.send_agent,
            "cancel_agent": session.cancel_agent, "review": session.review}
