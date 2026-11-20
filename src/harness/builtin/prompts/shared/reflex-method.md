guide("tree"): how to design and set the tree of reflexes.

The tree acts for the agent while you are not there. Your reply takes seconds; during
those seconds only the tree can act. Build it before the agent starts work that depends
on it.

1. Plan the whole tree.

- List everything that can happen to the agent during the whole task, not only during
  the part it is in now: to its own condition, to the place it stands on, from what is
  around it, and to what it is doing. Give the list to situations(...), one line for
  each: set_reflex is refused until you have.
- Group the list from wide to narrow. Make one node for each wide kind of thing that
  can happen. Under it, put one node for each narrower case that you know a better
  action for.
- Check the plan: for each thing on the list, name the node it falls into. Add a node
  for whatever falls into none. Each node names the lines it answers (covers=), and
  situations() returns the lines nothing answers yet. A line that needs no node is given
  with its reason: (line, reason). While a line has nothing that answers it, a program
  that acts on the environment is refused.
- Put only what happens to the agent into the tree. What you set out to do belongs in
  your programs and skills.

The tree is a behaviour tree. It is judged from its top, in order, each time the state
changes. A node is a sequence: its condition, then its action. A node with nodes under it
is a selector: the nodes under it in order, then its own action. The first that is in its
situation acts; one that fails is not tried again in that occurrence of the situation,
and the next acts. Nothing is tried again because time passed.

2. Write each node. Every node needs these five things.

The condition (when=).
- It says when the agent comes into the situation. It decides only whether the action
  begins: once the action has begun, it runs until it has a result, whatever the
  condition does meanwhile.
- Write it from what is happening to the agent, as the state shows it.
- Put what several nodes share into the node above them. Each node under it then tests
  only what makes it different.
- It must work on every state, also when a value it reads is missing. When you set a
  node, its condition is run once on the current state. If it raises, the node is
  refused and nothing is set.

When the situation is past (over=).
- A function of the view that is true when what happened to the agent is really over.
  It is another question than the condition: the condition says when to begin, over says
  when it is done. (A threat that came near is not past the moment it is one step
  further off.)
- While the action runs and over comes to hold, the action is ended there and has
  succeeded. An action that returns while over does not hold has failed.
- Without over, the action has succeeded when it returned and the condition no longer
  holds. Give over wherever the action itself changes what the condition reads.

The action (do=).
- A function that gets the agent out of the situation. Every node has one. A node
  without one is refused.
- Name the ways to answer the situation: keep out of its way, leave it behind, deal
  with it. Compare what each costs the task, in time and in risk, as the situation is at
  that moment, and have the action take the cheapest. An action that always answers one
  way is right only where that way is always the cheapest.
- Write it for the worst form of the situation you expect.
- If you do not know the right action yet, write what you would do yourself at that
  moment. A rough action is better than none; improve it later.
- A node that has nodes under it needs an action that works whatever the cause. It runs
  in two cases: when no node under it is in its situation, and when one of them acted and
  failed.
- What a failure leads to: the next node at that place, then the action of the node
  above, and so on upward; when nothing is left, you are told. So an action that cannot do
  its work returns at once and lets the next one act: it is not started again for this
  occurrence.
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

What you read when you are told (about=, report=). Write both for every node that tells
you anything: every node but one with tell="never" and tell_failed="never". A node that
tells and has not both is refused.
- about: one sentence, the situation the node answers. You read it in every message about
  the node.
- report: the message you read when you are told of this node. Write it for this node's
  situation: put in it what you will need at that moment to judge whether the situation
  is over and to decide what to do next.
  It is a function, called at the moment you are told as report(view, returned): view
  is the state then, returned is what the node's program returned (None for a node
  without a program).
  A message is text, plain data, a picture, a file, or a list of these in the order you
  want them: a picture is what look(...) or get_observation() returns, or an image you
  made; a file is a pathlib.Path (an image file is shown, a folder is listed, any other
  file is given as its text). At most 2000 characters of text, 4 pictures and 4 files.
- A message about a node says, in this order: the node with its sentence and how its
  program ended; which of your programs it took the environment from, how often so far
  and for how long; the node's report; that program's own report (guide("units"):
  until(report=)).

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
- A node acted when it should not have, or took the environment from work it should have
  left alone: change that node. Narrow its condition, change its action, or put it under
  the node whose situation it belongs to. Then run the work again.

Before the agent enters conditions it has not been in (another place, another stage of
the task), do step 1 for those conditions: add their lines to situations(...) and set
the nodes, then enter. Where the environment names a part of its state as the agent's
situation, the list counts for the values that part had when you gave the list: once it
has another value, a program that acts is refused until you give the list again.

Go back to step 1 and check the whole plan when one of these happens. Each of them means
the plan missed something, and fixing one node will not cover it.
- Something happened to the agent that no node covered.
- A problem you already fixed in a node shows up again, in that node or in another.
- You are told that a part of the state has a value it has not had before in this run
  (the message names it and gives the value). The agent is now in conditions the plan
  was not made for. List what can happen to it there and add the nodes that are missing.

6. Reference: every call and setting of the tree.

There is one tree of reflexes, empty at first, judged as a behaviour tree.
- A node has a condition (when its action begins), an action (what it does) and when
  its situation is past (over).
- A node can have nodes under it. A node under another is judged only while the upper
  node is in its situation, and it goes first. The upper node's own action runs when no
  node under it is acting or left to act, and gives way when one of them begins.
- Among the nodes at one place, the earlier takes the environment from the later and
  gives it back when it has its result. The order is the order they were set in, unless
  a node says before=.
- A node whose action failed is not tried again in that occurrence of its situation. It
  may act again when the situation was past and has come anew (over held, or for a node
  without over its condition stopped holding; for a node under another, also when the
  upper node's situation was past), or when the node is set again.
- While the agent cannot act (the environment says when), nothing of the tree is judged.
- A value that several nodes read is defined once, as a sense. An action that several
  nodes take is written once, as a function they call.
- set_reflex(name, when, do, over=None, under=None, before=None, every=None,
  ends=False, tell=None, tell_failed="now", about=None, report=None, test=None,
  covers=None, claims=None):
  put the node `name` into the tree, in place of a node of that name.
  covers: the lines of situations() this node answers, each by its text or by its
  number (1 for the first).
  when: a function of the view: the agent comes into the node's situation when it
  holds. It is judged without you, and the node's action begins as soon as it holds and
  its turn has come. Beside the state
  as it is, the view holds what a state alone does not show: view["was"][key], what that
  part of the state was before it last changed; view["unchanged"][key], for how many
  seconds it has not changed (the senses under ["sensed"] in both); and view["units"], the
  units that run, each {"name", "kind", "reflex", "priority", "seconds"}. Or the name of
  an event: the node answers that event when it happens, and you are not told of it then.
  do: a program (a function): started as a unit when the node's turn comes. Once begun
  it runs until it has a result: it returns, it fails, or over comes to hold. A program
  that answers an event gets the event when it takes an argument. Or the name of an
  event: you are told it, once for each occurrence, when its condition holds and no node
  under it or before it at its place is acting. Or "stop": what runs is ended.
  over: a function of the view that holds when the situation is past. While the program
  runs and over comes to hold, the program is ended there, its work done, and gives the
  environment back at once. A program that returns while over does not hold has failed.
  The node's action does not begin while over holds. Without over: the work is done when
  the program returned and when no longer holds (or the condition of a node it is under).
  Every node needs a do=: a node set without one is refused. For anything that happens
  to the agent, do= is a function, also on a node that has nodes under it: there it runs
  when no node under it applies, and when one of them ran and the agent is still in the
  situation. Use the name of an event as do= only to watch your own work (section 4).
  under: the node `name` is a narrower situation within that one. A node may be put
  under any node whose `when` is a condition, whatever that node does itself and without
  setting it again.
  before: the name of a node at the same place (under the same node, or at the top):
  this node comes just before it. Without it a node comes after those set there earlier.
  Of two nodes in their situations the earlier has the environment. Every node's
  program takes the environment from your programs.
  every: the seconds between judgements of its condition; without it the condition is
  judged when the state or the facts change.
  ends, tell, tell_failed, about, report: section 2 says what they are and how to choose
  them. report is called as report(view, returned). For a
  node that tells an event: ends=True ends what runs with that event, ends=False lets it
  run on; tell is the place of that event in your queue ("now" when it says nothing).
  The places in your queue: later (with the first call after a wait of yours), next (with
  your next call), now (it ends a wait and is told first with your next call; the reply
  you are writing when it comes is still used).
  claims: where the environment has channels (CHANNELS, units.md), the channels the
  node's program uses: it takes only those, and what runs on the other channels goes on
  beside it. None: it takes the whole environment. []: none: a program that acts on
  nothing of the environment (it sets a fact, or a rule that other code reads) takes the
  environment from nobody and runs beside everything, for as long as its situation lasts.
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
  program has failed (it returned and the situation is not past, or it raised), a later
  node at its place that is in its situation has the environment, and then the node
  above it with its own program; the failed node is not started again for this
  occurrence. When none has, the tree could not handle what happened: you are told with
  the program's report (the event REFLEX_FAILED), once until the node has done its work
  again. When a node's program has done its work and the node says you are told, that is
  the event REFLEX_ACTED.
- situations(*lines): say what can happen to the agent during the whole task: one line
  for each, a sentence, or (sentence, reason) for one that needs no node. The list given
  takes the place of the one before; without arguments nothing changes. Returns
  {"lines": [{"line", "answered": the nodes that name it in covers=, or "no node:
  REASON"}], "unanswered": the lines nothing answers}.
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
- at_priority(node=None): `with at_priority("name"):` around one action of a program
  keeps the nodes that come after the node `name` in the tree from taking the
  environment while that action lasts; that node and the ones before it still take it.
  Without a name no node takes it. It is for rare cases. Before you use it, ask whether the tree is wrong: when a node breaks
  off your work, look at that node first and change it (section 5). guide("units") says
  how.
