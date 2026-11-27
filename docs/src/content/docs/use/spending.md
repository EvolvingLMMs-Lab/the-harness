---
title: "Limit what an identity spends"
description: "Each agent identity has a daily budget for model calls and a daily cap on calls without a price; see what it spent and raise today's budget."
---

An agent identity spends money every time it calls a model: in a conversation, in a task
it starts, when a program asks the model something. Each identity can have an optional **daily budget**
(unset / `0` by default — no limit until you set one), checked before every one of those calls.
The day resets at 0:00 local time.

## What a call costs

- **OpenRouter** reports what each call cost, and that is what counts.
- **Another provider** reports nothing: give the model's prices in its entry of the model
  list (`"prices": {"input": 0.27, "output": 1.1}`, US dollars per million tokens,
  [Models and providers](/docs/configure/models/)) and the cost is estimated from the tokens.
- **A model on your computer** or your network (Ollama, a vLLM server) costs $0.

A call that has no price, a local model's or one of a provider without prices, counts
against the identity's optional **daily calls** cap instead (unset / `0` by default). When
set, a local model keeps working when the day's dollars are gone, and a provider that reports
nothing still has a limit.

## At the limit

When the budget is used up, a call already made finishes and is counted, even when it
ends a little over. After that the model is not called until 0:00:

- a conversation's turn ends with *today's spending limit is reached*; the programs and
  reactive rules that run in it go on, and their results wait for the next turn;
- `the-harness agent say` answers with the limit and exit status 3.

## See what it spent

```sh
the-harness usage
the-harness usage --range week --identity work
the-harness usage --range month
the-harness usage --from 2026-11-01 --to 2026-11-15 --json
```

It shows today's spending against the budget, the calls with and without a price, and
each conversation and task that spent. `--range week` and `--range month` cover the last
7 and 30 days (`--from` and `--to` any days): the total, the calls by kind (with a price;
under your own plan, with what they would cost at list prices, which is not charged;
without a price), every day of the stretch, and the split by conversation and by task. In the
terminal chat, `/usage` shows the same, and the status line shows the identity with what
it spent today, for example `工作 (work) · today $0.46`.

## Raise or change the limit

```sh
the-harness usage --raise-today 5
the-harness usage --budget 3 --identity work
the-harness usage --calls 1000
```

`--raise-today` raises today's budget only; tomorrow it is the setting again. In the
terminal chat, `/usage raise 5` does the same. `--budget` and `--calls` change this
identity's own limits from now on. The settings `agent.daily_budget` and
`agent.daily_calls` ([Settings](/docs/reference/settings/#agent)) are the limits of every
identity that has none of its own.

OpenRouter can also put a limit with a daily reset on the key itself, which holds for
everything that uses the key.

## In Python

```python
from harness.sdk import Agent

work = Agent("work")
week = work.usage("week")          # "today", "week", "month", or start= and end= days
print(week["cost_usd"], week["calls"], [day["cost_usd"] for day in week["days"]])
print(week["by_chat"], week["by_task"], week["today"]["left_usd"])
work.raise_today(5)
work.set_budget(3)
```
