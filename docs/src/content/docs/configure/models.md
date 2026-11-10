---
title: "Models and providers"
description: "Connect a hosted model from any provider, or a model you run yourself, and choose which model does what."
---

The agent works with any language model. Every provider is set up the same way: get a key, give it to The Harness, and name a model.

## Saved models

In the terminal, `/models` opens the model list and `/model` selects an enabled model.

Edit `~/.harness/models.json` directly (or `models.json` inside `HARNESS_DATA`):

```json
[
  { "provider": "ollama", "model": "my-model", "name": "Local model", "enabled": true }
]
```

Set `base_url` for a custom endpoint and `efforts` to an array of reasoning
option IDs when the endpoint supports them. An absent effort selection uses the
provider's default. Keep credentials in the provider settings or environment.

## Set up and change the model

The first run of `harness` asks for the provider, the model and the key, checks the key
with the provider, and keeps them in `~/.harness/config.toml`:

```toml
[model]
provider = "openrouter"
model = "deepseek/deepseek-v4.1-flash"
reasoning_effort = "low"           # optional: low, medium, high
# base_url = "https://..."         # another address for the provider, such as a proxy

[keys]
OPENROUTER_API_KEY = "sk-or-..."
```

Edit the file to change the model, or use **Settings → Model** in the app, which also
checks the key and suggests the models the provider lists. A key in your environment
wins over `[keys]`. `[model]` also takes `max_output_tokens`, `checker` (another model of
the same provider that checks the result) and `think_while_acting`
([settings reference](/docs/reference/settings/)).

## Providers

| Provider | Key variable | Address |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | one key for most models (the default) |
| OpenAI | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| Anthropic | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` |
| Google Gemini | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| xAI | `XAI_API_KEY` | `https://api.x.ai/v1` |
| DeepSeek | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` |
| Qwen (DashScope) | `DASHSCOPE_API_KEY` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| Zhipu GLM | `ZHIPU_API_KEY` | `https://open.bigmodel.cn/api/paas/v4` |
| Moonshot Kimi | `MOONSHOT_API_KEY` | `https://api.moonshot.cn/v1` |
| Ollama | none | `http://localhost:11434/v1` |
| Custom | `HARNESS_LLM_API_KEY` | any OpenAI-compatible server: vLLM, SGLang, LM Studio, a gateway |

For every provider the steps are the same:

1. **Get a key** from the provider's console.
2. **Give it to The Harness**: on the first run of `harness`, in `[keys]`, in the app,
   or as the variable in your shell (`export OPENROUTER_API_KEY=...`).
3. **Name a model**: in `[model]`, or in a model file for a benchmark's runs (below).

## Model files

The runs of a benchmark, and any run that needs another model per role, take their
models from a **model file**, which gives each role of the agent a model:

| Role | Does |
|---|---|
| `main` | writes the agent's replies and programs |
| `vlm` | answers questions about images from programs |
| `pointer` | points at things in an image |
| `verifier` | checks the result before the agent finishes |

Only `main` is required, and `verifier` takes `main`'s settings with its own on top. A
model file of your own:

```toml
# my-model.toml
description = "Claude through Anthropic's API"

[main]
backend = "openai_chat"                    # any OpenAI-compatible endpoint
base_url = "https://api.anthropic.com/v1"
api_key_env = "ANTHROPIC_API_KEY"          # the variable that holds the key
model = "claude-sonnet-5-5"
reasoning_effort = "medium"
max_output_tokens = 8192
```

```bash
harness run experiment my-experiment.toml --model my-model.toml
```

`backend = "openrouter"` (the default) uses OpenRouter, where `model` is OpenRouter's
id, such as `deepseek/deepseek-v4.1-flash`. The keys of a role:

| Key | |
|---|---|
| `backend` | `openrouter` (default) or `openai_chat` |
| `model` | the provider's model id |
| `base_url`, `base_url_env` | the endpoint, or the variable that holds it |
| `api_key_env` | the variable that holds the key (default `OPENROUTER_API_KEY`) |
| `reasoning_effort` | `low`, `medium` or `high`, where the model has it |
| `max_output_tokens`, `temperature` | the usual sampling limits |
| `stream` | stream the reply; the timeline then shows its text as it comes |
| `timeout_seconds`, `retries`, `retry_seconds` | how long to wait, and how often to try again |
| `extra_body` | fields added to every request, for provider-specific options |
| `service` | a model The Harness runs itself (below), in place of a hosted one |

Keys are only read from the environment, never from a file. A base URL can come from
the environment too (`base_url_env`), so the same configuration points at another
server without changing its identity.

## A model on your own computer

**With a server you run**, such as Ollama, vLLM, SGLang or LM Studio, choose **Ollama**
or **Custom** on the first run (or set `provider` and `base_url` in `[model]`), or write
a model file with `backend = "openai_chat"` and its `base_url`:

```toml
[main]
backend = "openai_chat"
base_url = "http://localhost:11434/v1"
model = "qwen3-vl:32b"
api_key_env = "HARNESS_LLM_API_KEY"   # any value; the server ignores it
```

**Or let The Harness run it**: the `local-models` package provides model services that
install their own environment and weights and start on a GPU when a run needs them. A
role names such a service instead of a hosted model:

```toml
[main]
service = "qwen3-vl-32b"
max_output_tokens = 2048
```

[Services](/docs/configure/services/) describes how services start and stop.

## Models that read no images

A model does not have to read images. Every turn is text, and a picture is sent only
when the agent looks ([Multimodal first](/docs/concepts/multimodal/)). The model list
keeps whether each model reads images: **Discover** takes it from the provider's catalog
where the provider says, and you can change it under **Model details → Reads images** or
with `"images": false` on the entry in `~/.harness/models.json`. A model without the
flag is taken to read them.

A model that reads none is sent none:

- In a project folder or without an environment it works as any other model.
- In an environment with a screen it works from the state, the elements and the page
  text. When it looks, the vision model named in `model.vision` (another model of the
  same provider) describes the view in text; without one it is told the view was not
  sent.
- The choice of where a conversation works says so beside the environments that have a
  screen, before you choose.

## Choosing a model

- Match the model to the task. Work in a terminal, on files or with a window's
  elements is text; a game, a drawing canvas or a camera scene is known through images,
  and needs a model that reads them or a vision model beside it (below).
- Fast models with low reasoning effort keep the agent responsive; it asks the model
  again whenever something new happens, so many short calls beat a few long ones.
- `[limits] max_cost_usd` caps what a conversation spends, whatever the model.
- A sub-agent can use another model of the same provider, for a cheaper or a stronger
  helper ([sub-agents](/docs/use/sessions/#sub-agents)).
