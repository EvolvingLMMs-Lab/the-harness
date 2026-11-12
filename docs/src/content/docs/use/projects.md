---
title: Work on a project
description: Run native coding and other file-and-process tasks in an explicitly bound project.
---

The workspace package lets the Harness's own agent operate project files and processes.
It uses the same model-written Python programs and bounded executions as other tasks.

```sh
harness install workspace
harness run "Reproduce the parser bug, fix it and run focused checks" --folder ./project
```

From a checkout, install the local package with `harness install ./packages/workspace --link`.
The folder must already exist. `--folder` selects the native project workspace unless an
external `--agent` is explicitly selected; `--agent harness` makes that choice explicit.
The CLI resolves the folder on the client. The host must be able to access that path.
The host API accepts the same `folder` with `workspace="project"` and `agent="harness"`.
This does not create a git worktree, install project dependencies or choose a test command.

In the terminal and the app, choose **Project folder** when the conversation starts and
name the folder; inside a repository the current directory is filled in. A project has
no screen. When a task must see something, such as how a changed page renders, the agent
asks to take a browser or your desktop into the same conversation
([Another environment](/docs/configure/permissions/#another-environment)); if you say no,
it goes on and tells you what it could not confirm.

## Read, change and verify

The model reads project instructions and toolchain configuration, reproduces the failure,
changes the files and tests them in the target environment. These calls are available
inside its Python programs:

```python
current = read_file("src/parser.py")
# Compute a complete replacement from the actual content.
updated = current["text"].replace("old expression", "new expression")
print(write_file("src/parser.py", updated, expected=current["sha256"]))
check = run_command([".venv/bin/python", "-m", "pytest", "tests/test_parser.py"], timeout=120)
print(check["exit_code"], check["output"])
```

Reads are UTF-8 byte windows (default 12,000 bytes, maximum 64,000) with `next_offset`,
`bytes`, `truncated` and a whole-file hash. Read all windows before replacing a large
file. `write_file` accepts `expected=None` only for a new file; a changed hash returns
`error="conflict"` without replacement. Atomic replacement and an optimistic hash check
are not a transaction against other editors. These file APIs resolve paths inside the
project; commands have the user's OS authority.

An argv list launches a program directly. A string runs `/bin/sh -c` on POSIX or
PowerShell on Windows. Each invocation has its own `cwd` (relative to the root) and
fresh environment. Files persist; shell `cd` and `export` do not. Use the target's
actual interpreter and dependencies. The controller's `sys.executable` and imports
belong to the Harness, not necessarily to this project.

The target inherits a small set of OS environment variables plus explicit `env`
overrides. Controller PYTHONPATH and model credentials are not automatically inherited.
This is **trusted local execution**, not an OS sandbox: commands can read other files,
use the network and launch the user's tools. Sensitive shell actions are not automatically
classified for approval. Use program approval if every generated program must be reviewed,
or put the worker under a separate OS authority when stronger containment is needed.

## Processes, evidence and endings

`run_command(..., timeout=120)` waits for the actual receipt through the existing
scheduler. `start_process(...)` explicitly creates a task-owned service and returns its process ID; `process_status(id)`,
`read_output(id, offset=0, limit=12000)` and `cancel_process(id)` inspect or stop it.
Every command has a wall deadline greater than zero and at most 3,600 seconds.

Receipts distinguish `running`, `exited`, `cancelled`, `timeout` and `session_closed`,
with an exit code and elapsed time. A nonzero exit is a result, not a transport error.
The preview contains the last 6,000 bytes. Full combined stdout/stderr and final JSON
receipts remain under the conversation's `artifacts` directory; page through output
when an error is absent from the preview. Program output is streamed into `program_output` trace records, with a 1 MiB character
limit per program and an 8,000-character model preview. Reaching the limit ends the program
with an explicit error. Successful execution events are streamed separately; the model
gets counts and up to 32 recent non-nominal events, not another copy of every file read. A lost transport response is not automatically retried.

An answer ends a turn; the workspace remains available until the conversation
closes. `harness run` closes after the turn: the answer, or the limit that ended it. The host releases
processes even if the controller is killed. POSIX cleanup covers the process group;
programs deliberately detaching into another session are outside that guarantee.
Windows uses best-effort `taskkill /T /F` while the parent is alive, and cannot guarantee
cleanup of already detached descendants. File changes are not rolled back.

Project sub-agents inherit the root, with their own process and output ownership.
They do not automatically get separate checkouts: coordinate edits explicitly. Other
workspace kinds can still be delegated to when installed. An unbound parent cannot
silently grant a project to a sub-agent.

A command exiting successfully, the model answering, and independently
verified task completion are distinct. The workspace reports no automatic success score.
Budget exhaustion remains visible and never becomes a success claim; a CLI turn that
uses its budget without an answer exits unsuccessfully instead of waiting forever.

## Resource and evidence boundaries

A target permits 16 concurrent processes. Each process retains at most 16 MiB of combined
output; reaching that limit requests termination and reports `output_limit`. Evidence and
process output share a 256 MiB reservation budget. Immutable JSON payloads are addressed by
hash under `artifacts/evidence`; `index.jsonl` relates them to requests, action IDs and
terminal results. Repeated content shares bytes. Evidence exhaustion before an operation
prevents it; exhaustion after an operation invalidates its cursor instead of inviting a retry.

`limits.target_workers` bounds native worker leases (default 4); computer-specific pool
limits still apply to browser/display workers. There is no implicit global transaction or
rollback across these resources. Unknown cleanup and incomplete evidence are reported as
such. A lost worker cannot certify that all detached target descendants have stopped.
