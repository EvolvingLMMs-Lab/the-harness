
Sub-agents work at the same time as you, on budgets taken from yours:

  delegate(task, workspace="new", budget=None, model=None, agent=None)   start one; its
                                    id. task: what to do and report, on its own (it does
                                    not see your conversation). workspace "new" (your
                                    kind) or an available workspace kind. budget {"calls",
                                    "cost", "seconds"}. agent selects an installed agent
                                    adapter; omit it to use this Harness.
  wait_agents(ids=None, timeout=None)   until each ends or asks: {id: {"status", "result",
                                    "question", "model_calls", "cost_usd", "seconds",
                                    "directory", "files"}}
  send_agent(id, text)              answer one, or give it more to do
  review(code, purpose, budget=None)   a read of code you wrote that is not anchored on
                                    yours: a sub-agent that has not seen your conversation
                                    gets the code and what it is for, and reports what in
                                    it would fail, do the wrong thing or waste its time;
                                    its id (wait_agents gives the report). For code that
                                    is kept and relied on, not for every program
  cancel_agent(id)                  stop one; returns its report
