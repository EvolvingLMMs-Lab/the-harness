You read what an agent did in one finished episode, and its library. Propose at most one addition to the library that would help later episodes on any task.
The agent acts in its environment by writing Python programs that call the functions of its skills.
What you can propose:
- A note: a short general lesson. Not something that holds in this one episode only.
- A memory entry: one specific situation and what worked or failed in it. The agent looks it up with recall(query).
- A skill: one public Python function with a docstring, written with the calls the agent uses. In the docstring, cite the outcomes in the episode that support it. After the skill, write <test>a Python call of the function and the result that shows it worked</test>. The host runs that test before the skill is used.
Propose a skill when the episode shows the same judgment working more than once.
<!-- if: experience -->
Do not propose tallies of how often a skill worked or where something was found: practice counts those by itself in the library's experience, which skills read as hints.
<!-- end -->
Reply with exactly one of <note name="snake_case">...</note>, <memory name="snake_case">...</memory>, <skill name="snake_case">...</skill>, or <none/>. Reply <none/> when the episode does not support an addition.
A note is at most {note_max_chars} characters, a memory entry at most {memory_max_chars}; a longer one is discarded.
