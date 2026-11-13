# Changelog

## 0.3.1

- What the model is given has a limit everywhere, and says so where it leaves something out. - A conversation is compacted instead of cut: when the context a call read reaches `runtime.compact_at_tokens` (default 150000), the model writes a summary, which replaces the conversation before its recent messages (the last 10,000 to 40,000 tokens, at least five messages). After `runtime.clear_results_after_minutes` (default 60) without a reply, when the provider's cache is cold, the results of all programs but the last five are cleared. Requests to Anthropic's and Qwen's models on OpenRouter mark the system prompt and the last message for the provider's cache. `runtime.max_history_turns` is gone (a configuration that sets it is refused): set `compact_at_tokens` instead. The trace records `compaction`; `context_shortened` is gone. - What a unit printed or returned is told whole up to 30,000 characters (it was cut to 8,000 and 2,000); more is saved to a file a program can read, and the model is told the file and the first 2,000 characters. `output_of` reads up to 30,000 characters. - Every turn tells how many nodes act in the tree of reflexes and which changed since the model was last told (at most 10), not the whole tree. `reflexes()` gives the nodes at the top and `reflexes("name")` those under a node, at most 50 at a time; a node's `under` is now the names of the nodes under it. - The system prompt stays the same from call to call: what an active run has learned is told with a program's result, whole when it changed. The library's skills are listed within 8,000 characters (past that by name only) and its notes within 200 lines or 25,000 characters.
- A run is now one model and the units it starts. Every program the model writes runs as a unit beside the others, with its own output and result: the model's turn comes back at once (with the result when the program was over within `runtime.turn_grace_seconds`, 2 s by default, else while it still runs), and the model may start another program, cancel one, or reply `<wait>` until a unit ends, a message or an event reaches it, or its time is over (`runtime.longest_wait_seconds`). A rule is a condition, a priority and a program: `rule(begins, program, ends=..., priority=...)` starts the program as a unit when its condition comes to hold; `facts` is a store of named values that programs and rule conditions share. A unit of higher priority takes the environment from a lower one, whose call is started again afterwards. A sub-agent that ends wakes the model that started it. What breaks: the look-ahead during a program (`<assume>`), `watch(every=seconds)`, the reflex rule (`reflex`, `remove_reflex`, the named priorities) and the `USER_MESSAGE` event are gone; `runtime.think_while_acting`, `model.think_while_acting` and `--think` are still accepted and have no effect. A worker's profile says how it is driven with `max_hz` and `step_seconds` instead of `clock` (an old `clock` is still read); an environment that needs a command every period while nothing runs now needs a rule on time. A pause stops every unit and holds until the conversation is continued. The traces lose `ahead`, `side_program`, `side_program_end` and `program_stopped` and gain `unit_end`, `wait`, `wait_end`, `rule`, `fact` and `preempted`.

## 0.3.0

- For the harness 0.70: the Textual pages of the suites (`harness tui ROOT`: tui.py, actions.py, `runs_screens`, `open_page`, `running_here`) go with the Textual TUI. Suites are followed with `harness runs`, `harness inspect`, `harness view` and `harness timeline`; `harness run --resume` resumes one.

## 0.2.2

- For the harness 0.67: running a bench as a benchmark is this package's: the keys of bench.toml the core no longer reads (tasks, deploy, source, nested, assets, needs_files) are read and checked here (BENCHMARK_KEYS, benchmark(), Bench.benchmark); a benchmark's checkout and assets are installed here (provision.py: bench_checkout, bench_status, install_bench), and `harness checkout NAMES` does it ahead of time (the doctor points to it). A deploy's [benches.<name>] table is checked when a run reads it (bench_table).

## 0.2.1

- For the harness 0.65: skills are picked by the core's `resolve_skills(runtime, roles, embodiment)`; traces are read with `read_records`; files are written with `atomic_write` and TOML with `toml_dumps`; the code fingerprint reads the packages through the core's `packages()`. `bench.toml_inline` goes.

## 0.2.0

- For the harness 0.63: A bench's hooks (Bench, load_bench) are the package's (harness_eval/bench.py); bench_table reads a deploy's [benches.<name>] table as the bench takes it (its check_deploy). A suite's workers take ports from the core's allocator (free_ports): from the deploy's or the command line's base_port, else the system's; self-improve likewise.

## 0.1.2

- For the harness 0.62.2: The suite's metadata lock is the core's file_lock; a run's liveness uses pid_alive, which never signals, so it is checked on Windows too.

## 0.1.1

- For the harness 0.62: an active run gets its bench's practice sandbox (`harness run`); a task run never does.

## 0.1.0

- First release as a package of its own (moved out of the harness core): experiments,
  suites, the run pages, the lock's code fingerprint, the experiment doctor, the TUI's
  suite pages and self-improvement; `harness run EXPERIMENT`, program, config, lock, runs,
  inspect, view, serve and self-improve.
