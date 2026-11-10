# local-models

The local-models package runs open vision-language models on your own GPU as services, so a model role (the main model, the `vlm` role) can use them with no API spend, and lets a role use any OpenAI-compatible server you run yourself.

## Install

```bash
harness install local-models
```

A run whose model file names one of its services installs it by itself the first time (`packages.auto_install`, see [Packages](https://harness.lmms-lab.com/docs/configure/packages/)).

Each model is a service with an environment of its own, built the first time a run calls it; its weights (from ModelScope) are downloaded then too. To do it ahead of time:

```bash
harness install qwen3-vl-32b     # environment and weights, without starting anything
```

Outside Python you need an NVIDIA GPU with a driver recent enough for CUDA 12.8 builds of PyTorch, and room for the model:

| Service | Role | Model | GPU memory |
|---|---|---|---|
| `qwen3-vl-32b` | main (writes programs) and vlm | Qwen3-VL-32B-Instruct, 4 bit | about 21 GB |
| `qwen3-vl-8b` | vlm (questions about images, pointing) | Qwen3-VL-8B-Instruct, bf16 | about 18 GB |

The environments are built with [uv](https://docs.astral.sh/uv/) when it is on `PATH`, else with `venv` and pip.

## Use

Run an experiment with the self-hosted model file:

```bash
harness run dev --model qwen3-vl-32b --output runs/local
```

The run installs the service if it is missing, places it on a GPU with room for it, starts it, and waits until it answers. The model file `configs/models/qwen3-vl-32b.toml` points each role at the service:

```toml
[main]
service = "qwen3-vl-32b"
max_output_tokens = 2048
temperature = 0.6
timeout_seconds = 600

[vlm]
service = "qwen3-vl-32b"
timeout_seconds = 300

[pointer]
service = "molmo2"            # from the perception package

[runtime]
keep_images = 1
max_history_turns = 3
task_descriptions = false
```

A role that names a service takes its URL and model id from the service; the role's own keys (`temperature`, `timeout_seconds`, `max_output_tokens`, `extra_body`) go on top.

### Keep a model loaded between runs

To install ahead of time, keep a model loaded across runs, or see what is running, use the service commands. A run uses a service whose port already answers as it is.

```bash
harness services                 # every manifest: kind, protocol, port, GPU memory
harness doctor qwen3-vl-32b      # installed or not, what is missing, GPUs and free memory
harness up qwen3-vl-32b          # start it, and wait until it answers
harness status                   # where each service runs, whether it answers
harness down qwen3-vl-32b        # stop what harness up started
```

Every command takes `--deploy NAME` (a file `configs/deploy/<name>.toml`) or a path when you place services yourself:

```toml
[services.qwen3-vl-32b]
gpu = "auto"
mode = "resident"
```

### Any other OpenAI-compatible server

vLLM, SGLang, a local proxy or any server that speaks the OpenAI chat API can take a role:

```toml
[main]
backend = "openai_chat"
base_url_env = "MY_SERVER_URL"      # e.g. http://<host>:8000/v1, read from the environment
model = "Qwen/Qwen3-VL-235B-A22B-Instruct"
api_key_env = "MY_SERVER_KEY"       # optional; "EMPTY" without one
```

Save it as a file of `configs/models/` (or anywhere) and pass it with `--model`. See [Models](https://harness.lmms-lab.com/docs/configure/models/).

## What it provides

Services:

- `qwen3-vl-32b`: Qwen3-VL-32B-Instruct in 4 bit (kind `llm`), the self-hosted model that writes programs and answers questions about images.
- `qwen3-vl-8b`: Qwen3-VL-8B-Instruct (kind `vlm`), questions about images and pointing.

Both run one OpenAI-compatible server built on transformers alone, which serves one request at a time.

Model files:

- `qwen3-vl-32b`: main and vlm roles on the `qwen3-vl-32b` service, Molmo2 as the pointer, with a short history that fits a 24 GB GPU.

## Configuration

Model file, per role:

| Key | Meaning |
|---|---|
| `service` | a service of the deploy instead of a hosted model |
| `backend` | `openai_chat` for any OpenAI-compatible server |
| `base_url`, `base_url_env` | the server's URL, or the environment variable that holds it (the variable wins when set) |
| `model` | the model id the server reports |
| `api_key_env` | the environment variable that holds the key |
| `temperature`, `max_output_tokens`, `timeout_seconds` | sampling, reply length, read timeout of one request |
| `extra_body` | extra request fields, e.g. `{ max_image_side = 768 }` to downscale images on the server |

Model file, `[runtime]`: `keep_images` (with a standing watch, `runtime.cameras`: images of the most recent turns kept), `max_history_turns` (exchanges kept after the first message), `task_descriptions = false`.

Deploy file, `[services.<name>]`: `gpu` (an index or `"auto"`), `mode` (`resident`, `on_demand`, `external`, `off`), `swap`, `idle_seconds`, `port`, `url` (for `external`). See [Services](https://harness.lmms-lab.com/docs/configure/services/).

## Limits and known issues

- The 32B model in 4 bit runs out of memory above about 7k prompt tokens on a 24 GB GPU. Its model file keeps the history short (`keep_images = 1`, `max_history_turns = 3`, no task descriptions). When a request still runs out of GPU memory, the driver drops one more turn and retries.
- The server handles one request at a time: parallel workspaces or sub-agents that share one service wait for each other.
- Self-hosted services report no cost, so a run's `cost_usd` counts only hosted calls.
- A small model can fall into exact-repeat loops at temperature 0; the model file samples at 0.6.
- When a service does not start:
  - `NAME: its environment did not install (...)`: read the install log named in the message; the next run continues from where it stopped.
  - `NAME: installed, but these are still missing: [...]`: the weights are not where the manifest expects them. To use weights you already have, symlink their directory into the weights root.
  - `No GPU of [...] has N GB left for NAME`: move a service, put services on demand in one swap group, or turn one off.
