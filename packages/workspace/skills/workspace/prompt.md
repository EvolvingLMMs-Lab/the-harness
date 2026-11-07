- read_file(path, offset=0, limit=12000): UTF-8 text, byte offsets, next_offset and
  sha256 of the complete file. Relative paths use the bound project root.
- write_file(path, text, expected=None): atomically write UTF-8. To replace a file,
  supply its sha256 from read_file as expected; None requires a new file. A changed
  file is refused rather than overwriting somebody else's work.
- run_command(command, cwd=".", timeout=120, env=None): execute
  an argv list, or a shell string, in the target environment. Returns process_id,
  status, exit_code, elapsed time, output preview and complete output location.
  timeout is a wall deadline (up to 3600 seconds), including task-owned services.
- start_process(command, cwd=".", timeout=120, env=None): explicitly start a task-owned
  service which survives the current program. Use process_status to observe it.
- process_status(process_id): current result, including whether it is still running.
- read_output(process_id, offset=0, limit=12000): recover complete combined stdout
  and stderr by byte offset. Read again at next_offset while a process runs.
- cancel_process(process_id): stop its process tree and return the observed result.
- get_state(): the bound environment and running processes. finish(summary): deliver
  your answer. Processes are cleaned up when this conversation ends.
