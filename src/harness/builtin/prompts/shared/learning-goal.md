This run is practice for a task: you do not do the task itself in it. The task: {task}

You have {minutes} minutes of live time. When it is over, what your library holds and what the environment keeps for you is all that the runs that do the task start with; they run where a failure counts, and nobody repairs anything for them. Something is learned when you saw it work in the situations the task will have; what was only written is not.

Code you propose (a skill, a reflex) stays pending until the host has verified it: with a fixture of its own or, where the host allows it, by running your test itself between programs. After each program you are told which of the two applies here, what the library holds and what is still pending.
<!-- if: legacy_memory -->
A memory entry named "situations" (library.propose("memory", "situations", text)) is shown to you again after each program, its lines marked [ ] or [unknown] first, and at the start of the runs that do the task.
<!-- else -->
A memory entry named "situations" (remember("plan", text, name="situations", keep=True)) is shown to you again after each program, its lines marked [ ] or [unknown] first, and at the start of the runs that do the task.
<!-- end -->
{probe}
{sandbox}
