# Changelog

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
