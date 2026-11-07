# Changelog

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
