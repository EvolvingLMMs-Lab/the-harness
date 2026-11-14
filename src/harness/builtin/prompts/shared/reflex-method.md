How to design and set the tree of reflexes.

The tree acts for the agent while you are not there. Your reply takes seconds; during
those seconds only the tree can act. Build it before the agent starts work that depends
on it.

1. Plan the whole tree.

- List everything that can happen to the agent during the whole task, not only during
  the part it is in now: to its own condition, to the place it stands on, from what is
  around it, and to what it is doing.
- Group the list from wide to narrow. Make one node for each wide kind of trouble. Under
  it, put one node for each narrower case that you know a better action for.
- Check the plan: for each thing on the list, name the node it falls into. Add a node
  for whatever falls into none.
- Put only what happens to the agent into the tree. What you set out to do belongs in
  your programs and skills.

2. Write each node. Every node needs these four things.

The condition (when=).
- It is true exactly while the agent is in the situation, and false once the situation
  is over and stays over.
- Write it from what is happening to the agent: how the state is changing. Do not write
  it from a guess at the cause, and do not rely only on a number crossing a level: by
  then it is late.
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
  action changes something that work relies on (for example where the agent is, or what
  it holds), so that going on from where it stopped would be wrong.

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
  other node took over. The default is "now". Lower it only when hearing later is
  enough.

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
