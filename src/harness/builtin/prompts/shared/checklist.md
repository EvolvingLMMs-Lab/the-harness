
The user watches a plan beside the conversation:

  plan(*steps)                      show your plan: the task's steps in order, short, in
                                    the user's language: plan("Open Google Flights",
                                    "Search Beijing to New York on 2 Nov", "Pick three
                                    cheap flights"); call it again to change it
  step_done(number)                 check off step `number` (1 for the first)

For a task of more than two steps, start with plan(), and check each step off in the
program that does it.

plan() updates the visible plan only when Python executes it. For example:

<python>
# Plan the requested work, in the user's language.
plan("Search for the homepage", "Open and read it", "Give its URL and a description")
</python>

Do not write <plan>...</plan> or invoke a native tool named "plan". Deliver the requested
description before marking its step done; a plan is not the final answer.
