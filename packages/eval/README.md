# eval

Evaluate the agent: an experiment (`configs/experiments/<name>.toml`) runs the agent with
a model over a benchmark's tasks and seeds. `harness run EXPERIMENT` starts the workers
and runs every episode into a suite directory that resumes where it stopped; `harness
program` runs a task's seeds against a worker that already runs. `harness config` and
`harness lock` say what the agent resolves to and what decides its behaviour, `harness
runs`, `harness inspect`, `harness view` and the TUI's suite pages read the suites, and
`harness self-improve` grows a library on development seeds, and `harness checkout NAMES`
installs a benchmark's checkout and assets ahead of its first run. Every benchmark package
depends on it.

```bash
harness install eval
harness run dev --model grok-low --tasks stack_bowls --seeds 0-2
```
