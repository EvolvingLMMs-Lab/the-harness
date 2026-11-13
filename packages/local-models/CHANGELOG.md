# Changelog

## 0.3.6

- What the model is given has a limit everywhere, and says so where it leaves something out. - A conversation is compacted instead of cut: when the context a call read reaches `runtime.compact_at_tokens` (default 150000), the model writes a summary, which replaces the conversation before its recent messages (the last 10,000 to 40,000 tokens, at least five messages). After `runtime.clear_results_after_minutes` (default 60) without a reply, when the provider's cache is cold, the results of all programs but the last five are cleared. Requests to Anthropic's and Qwen's models on OpenRouter mark the system prompt and the last message for the provider's cache. `runtime.max_history_turns` is gone (a configuration that sets it is refused): set `compact_at_tokens` instead. The trace records `compaction`; `context_shortened` is gone. - What a unit printed or returned is told whole up to 30,000 characters (it was cut to 8,000 and 2,000); more is saved to a file a program can read, and the model is told the file and the first 2,000 characters. `output_of` reads up to 30,000 characters. - Every turn tells how many nodes act in the tree of reflexes and which changed since the model was last told (at most 10), not the whole tree. `reflexes()` gives the nodes at the top and `reflexes("name")` those under a node, at most 50 at a time; a node's `under` is now the names of the nodes under it. - The system prompt stays the same from call to call: what an active run has learned is told with a program's result, whole when it changed. The library's skills are listed within 8,000 characters (past that by name only) and its notes within 200 lines or 25,000 characters.

## 0.3.5

- For the harness 0.67: a deploy's [benches.<name>] tables are kept as they are (the eval package checks them); the doctor checks services only.

## 0.3.4

- For the harness 0.66.1: the doctor loads the API keys it checks through the core's `Credentials`, so a key in `~/.harness_env` is found.

## 0.3.3

- For the harness 0.65: serve_vlm decodes images with the core's `decode_data_url` (same error text).

## 0.3.2

- For the harness 0.65: deploy files are written with the core's `toml_dumps`.

## 0.3.1

- For the harness 0.64: The download scripts check files with the core's `digest()`.

## 0.3.0

- For the harness 0.63: A deploy's [benches.<name>] tables are checked against the bench's bench.toml keys only; the bench reads its table in the eval package. Ports come from the core (free_port).

## 0.2.1

- For the harness 0.62.2: The supervisor's liveness check is the core's pid_alive (it reaps its exited servers).

## 0.2.0

- For the harness 0.59: Where services run (deploys), starting and stopping them, the broker's server, installing a service's environment, the doctor and the downloads, the VLM server, the CUDA toolkit and pins, the example deploys and the self-hosted model presets are the package's; harness services, up, down, status and fetch are its commands.

## 0.1.0

- First release as a package of its own (moved out of the harness core).
