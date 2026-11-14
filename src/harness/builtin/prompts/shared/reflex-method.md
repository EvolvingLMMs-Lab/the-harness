How a tree of reflexes is designed and tried.

The tree is there because the world does not wait for you: your reply takes seconds, and
what happens to the agent in that time is answered by the tree or by nothing. Its work
is to act in time. So it is made before the agent depends on it, in three steps: lay the
whole of it out, set all of it, and come back to it when what happens shows it wrong.

Lay it out.

The tree is designed as a whole, not grown from what went wrong last. It is designed for
the whole of what the agent sets out to do, as far as you know it now, not for the part
it is in at the moment. Name every kind of thing that can happen to the agent where it
is going to be: to its condition, to where it stands, from what is around it, to what it
is doing. The tree divides all of that, so that whatever happens falls into a node. It
has to be complete in this sense. It does not have to be perfect: an answer may be rough
when it is set, and is made better afterwards.

A node is a situation and its answer. Its condition says when the agent is in the
situation, by what is happening to the agent, not by what causes it. What is happening
shows in how the state changes more than in where it stands: a level that has been
crossed is the last sign of a situation, not the situation. Its answer is a program: an
action that fits the situation whatever its cause, and that takes effect within the time
the situation leaves. Every node has a program. Telling you is not an answer: by the
time you reply, what the node saw has gone on. Where you do not know the right action
yet, the program is what you would do yourself if you saw it happen.

Design it from the top down. Begin with the widest situations, each a respect in which
something can be wrong for the agent, and give each its node; then divide each into the
narrower ones you already know. A node under another is a narrower situation within it,
one you know a better answer for, by its cause or circumstance. While the condition of a
node under it holds, that node answers and the node above does not act. The program of
the node above is the fallback of its whole situation: it answers what is in that
situation and in none of the narrower ones, and what a narrower one did not solve. Write
it to be right whatever the cause. So a node is complete from the moment it is set, and
what you learn later goes under it without changing it: write every node so, at every
depth. What several conditions have in common is judged once, in the node above them,
and each of them says only what distinguishes it there. Prefer a deep tree to a wide
one: a node under another is judged only while that one's condition holds, so the narrow
costs nothing while the wide is quiet; and a wide node still answers the case you did
not list, where a row of cases has no node for it. A new node goes under the narrowest
node whose situation it falls in, and to the top only when it falls in none.

What happens to the agent whatever it is doing belongs in the tree, also when you met it
inside one program: answered there, it is answered nowhere else. What you set out to do
is not in it, however often you do it: a way of doing something that you have learned is
kept as a skill you call, not as a node.

The tree is consistent when in every situation it is settled which node has the
environment: a node's place is what it costs when it does not act now, the costlier the
earlier; and a node takes the environment only where you would, seeing everything as it
is then. A reflex acts in your place, so its condition is your whole judgement, what it
interrupts and whether this is the moment included.

Beside its condition, a node says three things for itself. None of them is the same for
all nodes: decide each one for the node at hand, from what its situation is.

What it does: its program (do=).

What becomes of what it interrupts (ends=). A node's program takes the environment from
what runs. Where the situation leaves what ran able to go on as it was, what ran is
resumed where it stopped when the program is over. Where the situation is a danger to
what ran, or the program changes what that relied on, what ran is ended there.

What you hear of it (tell=, tell_failed=). What a node did reaches you as a notice in
your queue, and the node says whether it does and how soon. An everyday answer that
needs nothing from you is not told; the line you are given of the tree says how often it
acted. An answer you want to know of is told each time: later, or with your next turn,
where it only informs you; at once, with the reply you are writing set aside, where it
is dangerous or changes what you should do next. Telling is not interrupting: only "now"
sets a reply aside. When a node's program did not do its work and nothing else took the
situation, the tree could not handle what happened: you are told of that, at once unless
the node says otherwise.

What your own programs come to, you hear without the tree: every program ends with its
report, done or not. What the tree adds is hearing of it before the end. The unexpected
has two forms. Something happens that no node answers. Or what should happen does not:
the agent goes on acting and what the action is for does not come; the thing it should
change stays as it was while time and supplies go. The second is as much a situation of
the agent as the first, and it is the one that passes unnoticed, because nothing
arrives. So for whatever is set going, a node watches what it is for, and tells you (do=
the name of an event) when that stays away longer than it would if things were as you
assumed. That is the one use of a node that tells. For a situation of the agent it is
never the answer.

When it is laid out, argue against it before you set it: say what could happen to the
agent that no node answers, and where a node's action would be wrong because its
situation has a cause you did not think of. What you find goes into the tree. What is
laid out then is what you set: every node of it.

Set all of it.

Set every node you laid out, the widest first and the narrower ones under them, one
after the other, before you come back to any of them: until a node is set, nothing
answers its situation at all.

A node has to be able to run. When it is set, its condition is judged once on the state
as it is, and a condition that raises is refused: nothing is set. A condition says
whether the agent is in the situation on every state it can be given, also where a value
it reads is not there yet.

Think a node's situation through in every form it can take, and say its goal in one
plain sentence: what is the case when the situation is over and stays over. The node's
condition is where you say that: it holds for as long as the situation is not over, so
that when it no longer holds the goal is reached. Write the node's program to reach that
goal in the hardest form of the situation you expect. The goal is the whole of what the
node is for: nothing is added to it afterwards, and nothing is guarded against that it
does not name.

A trial is not required. Where you want to see a node work before the agent depends on
it, set_reflex takes one (test=): a function that brings the node's situation about, by
whatever the environment gives for that. It is one ordinary case, the least that shows
whether the goal is reached, where a failure costs little. It is run at once, with the
node already in the tree, and what it showed comes back from set_reflex: whether the
node had its turn, how long that took, whether the situation was then over, as its
condition says, and what the program reported. Goal reached: the node has passed, and
you go on. That it could be better is no reason to try it again, and a defence beyond
its goal is not better. Goal not reached (the condition never held, the action came too
late, the situation was not over): the node does not work, and it is repaired. A trial
that passes while the situation is plainly still there shows a condition that says too
little: the condition is what is repaired.

Unless a node says otherwise (tell=), you are told the first time its program does its
work by itself: that is the one time you see it in the real situation, so compare what
it did with what you meant.

Come back to it.

The tree is looked at again as a whole, not patched, when the same kind of thing happens
a second time; when the agent is somewhere it has not been (you are told); when a node
acted and did something other than you meant; when a node's program did not do its work;
and when something happened that no node answered.
