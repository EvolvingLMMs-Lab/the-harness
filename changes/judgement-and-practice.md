---
core: minor
---
The principles of the core prompt are written anew as one whole, in place of three separate paragraphs. The world goes on by itself; three things act for the model at three speeds (the model with judgement, a program step by step, a reflex at once), and the work is to give every situation that can arise to the one that fits it. From that: start from what is there and say what the task needs as things that must be true, not as a sequence; say what can arise (a danger, a need that returns, something needed that comes within reach, an action that fails) and give what cannot wait to a reflex before it can arise; design the tree of reflexes as a whole, complete (every situation has a node) and consistent (a node's place is what it costs when it does not act now, and its condition is the model's whole judgement); build and test in proportion to what a failure costs, and repair the kind a failure belongs to.

The instruction of a learning run says what practice time is for: what does not work yet, from the ground up, each part made reliable before what depends on it, with time in proportion to how likely a part is to fail and what its failure costs, in a situation set up directly where the environment allows it.

Every unit ends with the same report, whoever started it: how it ended (`ended`: by itself, an error, an event, cancelled, its time limit) and whether what it was for is the case (`done`), which are two things. What a unit is for is its completion condition: `until(condition)` in a program, `spawn(fn, until=condition)`, and for a reflex's program that the reflex's condition no longer holds. A reflex whose program ended with its situation not over has not done its work: a later node at its place has the environment, or the model is told with the program's report (before, only a program that raised counted as failed, and a reflex could act for a long time without effect and without the model knowing). What the model is told of a program begins `Program N ended: by itself; done: no` instead of `Program N status: ok`. A reflex's priority is 0 or more, and every reflex takes the environment from the model's programs: what the model pursues is its own program, not a reflex.

The instruction of a learning run is three short paragraphs: that it is practice, its live time and what remains of it, and what counts as learned: something has done its work without help, more than once, starting from what the parts before it really leave. It no longer says in which order to practise, how code is admitted, or anything of the situations entry.

An environment that pauses is told who takes it (`pause(episode_id, by)`), so that what it holds can know, when it goes on, that it was interrupted and by what.

The core prompt says what the reactive layer is for. An agent does two kinds of things: it answers what happens to it and around it and is then where it was (its tree of reflexes, acting by itself, without the model), and it sets out to make something the case that is not (the model's, done by its programs). The tree is designed as a whole, not grown from what went wrong last: every kind of thing that can happen to the agent gets a node, and a kind the model cannot answer yet gets one that tells it; a way of doing something that was learned is a skill, not a node. Every turn the model is told how the tree stands: its nodes and how often each one's program began, did its work and did not, and that it is empty when it is.
<!-- zh -->
核心提示词里的原则整体重写成一套，取代原来分开的三段。世界自己在走；替模型行动的有三样，快慢不同（模型带着判断、程序一步步、反射立刻），工作就是把每一种可能出现的情况交给合适的那一样。由此推出：从现有的出发，把任务需要的东西说成一组必须成立的事，而不是一串步骤；说清会出现什么（危险、反复出现的需要、恰好够得着的所需之物、失败的动作），不能等的在它出现之前交给反射；把反射树作为整体来设计，做到完备（每种情况都有节点）和自洽（节点的先后由此刻不出手的代价决定，条件是模型的完整判断）；造和测的力度与失败代价相称，出了问题修它所属的那一类。

学习运行的指令说明练习时间用来做什么：还做不成的事，自下而上，每一部分做到可靠再去学依赖它的；一个部分花多少时间与它失败的可能和代价成比例；环境允许时直接布置出要练的情境。

每个单元结束时都给出同一份报告，不论是谁启动的：怎么结束的（`ended`：自己跑完、出错、某个事件、被取消、到了时限）和它要办的事办成了没有（`done`），这是两回事。单元要办的事是它的完成条件：程序里的 `until(condition)`、`spawn(fn, until=condition)`；反射的程序则是"反射的条件不再成立"。反射的程序结束时情况还没过去，就算没办成：同一处后面的节点得到环境，或者把程序的报告告诉模型（以前只有抛出异常的程序才算失败，反射可以长时间无效地行动而模型不知情）。模型看到的程序结果开头从 `Program N status: ok` 变为 `Program N ended: by itself; done: no` 这样的形式。反射的优先级为 0 或更大，每个反射都从模型的程序手里接管环境：模型主动要做的事是它自己的程序，不是反射。

学习运行的指令是三小段：这是练习、有多少实时时间及其留下什么、什么算学会：一件事不靠帮助办成了不止一次，而且起点是它前面那些部分真正留下的状态。它不再规定按什么顺序练习，也不再说明代码如何被采纳和 situations 条目。

能暂停的环境会被告知是谁接管的（`pause(episode_id, by)`），被保持的一方恢复时可以知道自己被打断过、被谁打断。

核心提示词说明了反应层是做什么的。Agent 做两种事：应对发生在它身上和身边的事、应对完还在原处（它的反射树，自己运行，不经过模型）；以及主动去让一件原本不成立的事成立（模型的事，由它的程序去做）。树要整体设计，不是出了什么事就长一块：会发生在 agent 身上的每一类事都有节点，模型还不会应对的那一类有一个告诉它的节点；学会的做事方法是技能，不是节点。每一轮都会告诉模型树的近况：有哪些节点，每个节点的程序启动、办成、没办成各几次；树是空的也会明说。
