# workspace

Operate project files and processes with the Harness's own Python control programs.
The target project has its own files, dependencies and processes; importing a module
in the controller does not import the target project. No coding agent is delegated to.

Install with `harness install workspace`, or from this checkout with
`harness install ./packages/workspace --link`. Start a native task with
`harness run "Fix the failing parser and verify the change" --folder ./project`.
The project must already exist. There is no browser, display or screenshot dependency.

The model uses `read_file`, `write_file`, `run_command`, `start_process`, `process_status`,
`read_output` and `cancel_process` from Python. An execution belongs to the existing
tick and ends with a receipt. Foreground commands suspend that execution while the
worker owns the target process; no second planner or job service is involved.

Each command starts in the requested project directory with a fresh shell/environment.
Files persist; `cd` and `export` do not persist between commands. Use the project's
actual interpreter (for example `.venv/bin/python`), never assume the controller's
Python or installed dependencies are the target's. The target receives basic OS
environment variables and explicit overrides, not the controller's PYTHONPATH or model
API credentials. The backend is **trusted local execution**, with the OS user's
authority. The directory bounds the file API, not arbitrary commands. Use a dedicated
OS user or container around the worker if an OS security boundary is required.

File reads return a complete-file hash. Replacements must supply that hash; an observed
conflict leaves the file intact. Writes replace files atomically. This is optimistic
conflict detection, not a transaction with arbitrary external writers.

Commands have a wall deadline; `start_process` explicitly creates a task-owned server.
`run_command` belongs to its execution and is cancelled when that execution stops. Results distinguish
running, exited, cancelled, timeout and session_closed, and retain the exit code.
Nonzero exits are normal results for the agent to inspect. Complete combined stdout
and stderr and final receipts live in the run's artifacts; model previews are bounded
and `read_output` can retrieve any byte range. Budget exhaustion does not erase these
outputs or turn an unknown task outcome into success.

The session owns background processes and cleans them up on release. On POSIX the
worker kills the process group; programs deliberately detaching into another session
are outside this guarantee. Windows cancellation uses taskkill's tree operation while
the parent is alive and is reported as best effort; it cannot guarantee cleanup of
already detached descendants. No backend claims cancellation merely because a request
was sent. Files already changed are not rolled back on cancellation.

Operation values return to the caller, while execution events stream to the run trace.
The next model decision receives program output, event counts and unresolved events.
Raw evidence lives under `artifacts/evidence`: an append-only index references immutable
payloads by hash. Repeated reads share stored content. The worker reserves at most
256 MiB for evidence and process output, with 16 MiB per process and 16 concurrent
processes. Exhaustion is explicit; a possibly executed action is never automatically
retried. Program output has a separate 1 MiB character limit ; the model is told up to 30,000 characters of it, and of more the file it was saved to.

The package owns project selection, directory inheritance, toolchain provisioning and
process release through its host provider. Set `[workspace] workers = 4` in user settings
to limit concurrent project workers. Install this package before using `--folder`; the
core does not select or install a particular environment backend implicitly.
