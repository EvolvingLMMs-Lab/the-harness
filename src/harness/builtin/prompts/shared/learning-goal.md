Get to know this environment for this task, then stop: do not do the task itself in this run. The task you are learning for: {task}

You have {minutes} minutes of live time. Learn the environment the way a careful person learns a new game, app, website or machine before using it for real, and put what you learn into your library with library.propose, so the runs that do the task start with it. Nobody will tell you what to watch out for: working that out is your job.

1. Read what there is: its help, its manual, its tutorial, its settings or controls screen. Note what you read but have not seen yet as something to check.
2. Try every control and see what it does: compare what you see and what you read before and after each one.
   {probe}
<!-- if: legacy_memory -->
3. Think the task through before you build anything, as hard as you can, and write it down as the memory entry "situations" (library.propose("memory", "situations", text)):
<!-- else -->
3. Think the task through before you build anything, as hard as you can, and write it down as the memory entry "situations" (remember("plan", text, name="situations", keep=True)):
<!-- end -->
   - the path: the steps from where you are to the goal, each a milestone you can check by what you see or read;
   - for each step, what you must be able to do (a skill each, built on the basic moves of this body: {skills}), and its hardest version you can expect: the toughest material or target, the longest distance, an action that must last or repeat, a screen or layout that differs, a slow or missing response;
   - how each step can fail, and how you would notice from what you see that it did not really work;
   - what can happen faster than you can think: being hurt or attacked, falling, losing what you hold, a window, dialog or error that appears, something coming at you; each of these needs a reactive rule, not a skill;
   - then argue against your own plan: what would most likely make it fail? Add that too.
   Mark each line with its state: [ ] not covered, [skill name] or [rule name] when an entry covers it and its test passed, [unknown] when you cannot test it here. Keep this entry up to date: propose it again whenever it changes.
4. Cover the list. For each line, write the skill or the rule it needs:
   - a skill is a closed loop (ClosedLoop) whose test calls it on the hardest version of its case and asserts on the real result in the environment (calling the class runs it: r = Walk(...); assert r.ok, r.reason), not on its return value alone;
   - a reactive rule is proposed with library.propose("reactive", name, code, test=...); its test feeds it the views or events of its situation and checks that it acts then and only then;
   - code proposals stay pending until the host has verified them: with a fixture of its own or, where the host allows it, by running your test itself between programs. After each program you are told which of the two applies here and what is still pending. Mark pending cases [unknown] and record what you observed in practice.
   {sandbox}
<!-- if: legacy_memory -->
5. Drill toward the task, from the first milestone on, as a player or a new user would, and seek out the hard and the dangerous situations on your list instead of waiting for them: {drills}. Use your skills; when a drill fails or something happens that your list did not foresee, add it to "situations", rewrite the entry that failed, and propose it again. Keep each drill's outcome as a memory entry (what you tried, what happened, what to do instead) as the run records skill results by revision.
<!-- else -->
5. Drill toward the task, from the first milestone on, as a player or a new user would, and seek out the hard and the dangerous situations on your list instead of waiting for them: {drills}. Use your skills; when a drill fails or something happens that your list did not foresee, add it to "situations", rewrite the entry that failed, and propose it again. Keep each drill's outcome as a memory entry (remember(kind, text, name=..., keep=True): what you tried, what happened, what to do instead); each result of your closed loops counts as a use of its skill by itself.
<!-- end -->
6. Stop when every line of "situations" is covered or marked [unknown], or when the time is nearly up. Finish with a short note of what you learned and what is still unknown.

After each program you are told what you have learned so far, your "situations" list and what to do next. Spend your time on controls, skills, rules and drills, not on long thinking: the live time is the budget.
