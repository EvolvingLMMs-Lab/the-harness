guide("tree"): how to design and set the tree of reflexes.

The tree acts for the agent while you are not there. Your reply takes seconds; during
those seconds only the tree can act. Build it before the agent starts work that depends
on it.

1. Plan the whole tree.

- List everything that can happen to the agent during the whole task, not only during
  the part it is in now: to its own condition, to the place it stands on, from what is
  around it, and to what it is doing.
- Group the list from wide to narrow. Make one node for each wide kind of thing that
  can happen. Under it, put one node for each narrower case that you know a better
  action for.
- Check the plan: for each thing on the list, name the node it falls into. Add a node
  for whatever falls into none.
- Put only what happens to the agent into the tree. What you set out to do belongs in
  your programs and skills.

2. Write each node. Every node needs these four things.

The condition (when=).
- It is true exactly while the agent is in the situation, and false once the situation
  is over and stays over.
- Write it from what is happening to the agent, as the state shows it.
- Put what several nodes share into the node above them. Each node under it then tests
  only what makes it different.
- It must work on every state, also when a value it reads is missing. When you set a
  node, its condition is run once on the current state. If it raises, the node is
  refused and nothing is set.

The action (do=).
- A function that gets the agent out of the situation. Every node has one. A node
  without one is refused.
- Write it for the worst form of the situation you expect.
- If you do not know the right action yet, write what you would do yourself at that
  moment. A rough action is better than none; improve it later.
- A node that has nodes under it needs an action that works whatever the cause. It runs
  in two cases: when no node under it applies, and when a node under it ran and the
  agent is still in the situation.
- Do not give such a node the name of an event as its action. That only tells you, and
  by the time you reply it is too late.

What happens to the work it interrupts (ends=). Decide this for each node, by asking
whether that work is still correct after the node's action.
- ends=False: after the action, the interrupted work goes on from where it stopped. Use
  it when the action leaves everything that work relies on as it was.
- ends=True: the interrupted work is ended and you are told at once. Use it when the
  action changes something that work relies on, so that going on from where it stopped
  would be wrong.

What you are told (tell=, tell_failed=). Decide this for each node, by asking what you
would do with the news.
- tell is for when the action worked.
  "never": you are not told. Use it when you would do nothing with the news.
  "first": you are told the first time only. This is the default.
  "later" or "next": you are told every time, without being interrupted. Use it when you
  want the news for later decisions and nothing you are doing now depends on it.
  "now": you are told every time, and each time the reply you are writing is dropped.
  Use it only when the news means you have to change what you are doing right now.
- tell_failed is for when the action did not get the agent out of the situation and no
  other node took over. It takes "now" (the default), "next", "later" or "never", with
  the same meaning as for tell.

3. Set the tree.

- Set every node you planned: the wide ones first, then the ones under them. Do not stop
  to perfect one node before the rest are set. A situation with no node has nothing
  acting for it.
- A test is optional. To test a node, pass test= a function that creates the node's
  situation once, in an ordinary form, where a failure costs little. set_reflex runs it
  at once and returns what happened: whether the node reacted, how long that took, and
  whether the situation was over afterwards.
- If the situation was over, the node has passed. Move on. Do not test it again to make
  it better, and do not add protection that goes beyond getting the agent out.
- If the situation was not over, fix the node.
- If the test passed but the agent is plainly still in the situation, the condition is
  wrong. Fix the condition.
- The first time a node acts for real, you are told what it did, unless its tell says
  otherwise. Compare that with what you intended.

4. Watch your own work.

Every program reports when it ends, whether it succeeded or not. To hear before the end
that something you started is getting nowhere, set a node whose condition says "this
should have happened by now and has not", and give it the name of an event as do=. You
are told that event. This is the only place to use an event name as do=.

5. Revise the tree.

Fix one node when only that node is wrong: its action failed, or it acted differently
from what you intended.

Go back to step 1 and check the whole plan when one of these happens. Each of them means
the plan missed something, and fixing one node will not cover it.
- Something happened to the agent that no node covered.
- A problem you already fixed in a node shows up again, in that node or in another.
- You are told that a part of the state has a value it has not had before in this run
  (the message names it and gives the value). The agent is now in conditions the plan
  was not made for. List what can happen to it there and add the nodes that are missing.

6. Reference: every call and setting of the tree.

There is one tree of reflexes, empty at first.
- A node has a condition (when it acts) and an action (what it does).
- A node can have nodes under it. A node under another is checked only while the upper
  node's condition is true, and it goes first. The upper node's own action runs when no
  node under it is acting, and gives way when one of them starts.
- Among the nodes at one place, the earlier takes the environment from the later and
  gives it back when it is done.
- A value that several nodes read is defined once, as a sense. An action that several
  nodes take is written once, as a function they call.
- set_reflex(name, when, do, under=None, priority=0, every=None, again_seconds=0,
  ends=False, tell=None, tell_failed="now", test=None):
  put the node `name` into the tree, in place of a node of that name.
  when: a function of the view: the node has its turn while it holds. It is judged
  without you, and the node takes the environment as soon as it holds. Beside the state
  as it is, the view holds what a state alone does not show: view["was"][key], what that
  part of the state was before it last changed; view["unchanged"][key], for how many
  seconds it has not changed (the senses under ["sensed"] in both); and view["units"], the
  units that run, each {"name", "kind", "reflex", "priority", "seconds"}. Or the name of
  an event: the node answers that event when it happens, and you are not told of it then.
  do: a program (a function): started as a unit when the node's turn comes; what it is
  for is that the node's situation is over: its condition, or that of a node it is under,
  no longer holds. It begins again while the turn lasts,
  not before again_seconds after it ended; a program that answers an event gets the event
  when it takes an argument. Or the name of an event: you are told it, once each time
  its turn comes, which is when its condition holds and no node under it or before it at
  its place is answering. Or "stop": what runs is ended.
  Every node needs a do=: a node set without one is refused. For anything that happens
  to the agent, do= is a function, also on a node that has nodes under it: there it runs
  when no node under it applies, and when one of them ran and the agent is still in the
  situation. Use the name of an event as do= only to watch your own work (the page says
  how).
  under: the node `name` is a narrower situation within that one. A node may be put
  under any node whose `when` is a condition, whatever that node does itself and without
  setting it again.
  priority (a whole number, 0 or more): the node's own, wherever it is in the tree. Of
  two nodes whose turn it is the higher has the environment, among equals the earlier in
  the tree; and it is the number a program's at_priority(n) is compared with. A node's
  program takes the environment from your programs.
  every: the seconds between judgements of its condition; without it the condition is
  judged when the state or the facts change.
  ends: what becomes of what runs when the node's turn comes. With a program: False, the
  unit it takes the environment from is resumed where it stopped when the program is
  over; True, that unit is ended there, and you are told at once which node took the
  environment, from which unit, and the state. With an event: True ends what runs with
  that event, which is how you are told; False tells you and lets it run on.
  tell: what you hear when the node's program has done its work, which the node says for
  itself. "never": nothing, the tree's line counts it. "first": the first time only,
  with your next turn (what a node gets when it says nothing). "later", "next" or "now":
  every time, as a notice at that place in your queue: later (with the first call after
  a wait of yours), next (with your next call), now (the reply you are writing is set
  aside and you are asked again). For a node that tells an event, tell is the place of
  that event in the queue, "now" when it says nothing.
  tell_failed: what you hear when its program did not do its work and nothing else took
  the situation (below): "now" when it says nothing, or "next", "later", "never".
  test: a trial of the node, where you want one; none is required. A function that
  brings the node's situation about: it is run at once, and set_reflex returns what it
  showed: {"name", "tried": True, "turn" (the node had its turn), "seconds" (from the
  trial's start to its turn), "done" (its program left the situation over, as the node's
  condition says it; None for a node that tells), "last" (its program's report), "error"
  (what the trial itself raised, or why the condition could not be judged)}.
  When a node is set its condition is judged once on the state as it is (a node under
  others: while the conditions above it hold). A condition that raises is refused and
  nothing is set: a condition answers on every state it can be given.
  A condition is read, not computed: the conditions judged in one moment share a few
  milliseconds between them, and may not open files, use the network, sleep or start
  anything. One the moment had no time for is judged in the next. A condition that
  raises does not hold that once: its node stays in the tree and is judged again the next
  time. One that is slower than that time after time is no longer judged, nor are the
  nodes under it, until you set the node again. In both cases you are told what went
  wrong, once for each reason (the event REACTIVE_FAULT), and the node's line says how
  often.
  What you are told of a node's work is what the node said (tell, tell_failed). When its
  program ends and its situation is not over, or it fails, a later node at its place
  whose condition holds has the environment, and then the node above it with its own
  program. When none has, the tree could not handle what happened: you are told with the
  program's report (the event REFLEX_FAILED), once until the node has done its work
  again. When a node's program has done its work and the node says you are told, that is
  the event REFLEX_ACTED.
- reflexes(name=None): the nodes at the top of the tree, or the nodes under the node
  name (the node itself where it has none under it), at most 50 at a time: each with
  whether its condition holds, whether its program runs, how often it began, the report
  of its last run and the names of the nodes under it. What the tree did without waking
  you is told with your next turn: how many nodes it has, how many of them never had
  their turn, how many only tell you, and of those that changed since you were last
  told, how often each one's program began, did its work and did not (at most 10;
  reflexes() has the rest). When nothing changed and there is nothing of that to say,
  nothing is said. drop_reflex(names=None): remove nodes with the nodes under them (None:
  all).
- facts.set(name, value), facts.get(name, default=None), facts.drop(name): what the run
  knows, shared by your programs and reflexes (view["facts"]). Keep progress there, so that
  what you start again goes on from what was done.
- sense(name, code): have the environment compute a value itself, each time it reports
  its state: view["sensed"][name] for conditions, get_state()["sensed"][name] for
  programs. `code` is in the environment's own language and reads the environment
  directly (the environment's own page says what the code has). It returns {"value": as
  computed now, "error"}. senses(): those defined, with their code and values;
  drop_sense(name).
- at_priority(n): `with at_priority(n):` around one action of a program keeps reflexes
  whose priority is below n from taking the environment while that action lasts.
  guide("units") says how.
