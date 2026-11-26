---
title: "Models and providers"
description: "Connect a hosted model from any provider, or a model you run yourself, and choose which model does what."
---

A model comes from one of three kinds of source, and any of them alone is enough: an agent's
command line that is signed in on this computer (Claude Code, Codex, Gemini CLI, Grok and others: it runs under your own
plan, no key), a provider's API key, or a model that runs on this computer.

Three things are kept apart everywhere: the **source** (whose account it runs under), the
**model** (one of those the source offers) and the **reasoning effort** (one of the levels
that model has). Choosing a source keeps one of its models, by the model's own name: an
agent's is the one the agent itself is set to. Every other model of the source is one
choice away (**More models of …** in the app's model picker and in Settings › Model,
`/model` in the terminal chat), and an agent's models are the ones it declares through ACP.
The effort's choices are those of the model in use, so they change with the model; a model
that has none shows none. An agent declares its models' levels; a gateway's catalog
(OpenRouter) names each model's; a provider's own endpoint has the levels its API tells
apart (OpenAI and Gemini: low, medium, high; Anthropic and Qwen: none, low, medium, high;
DeepSeek: none, low, high; xAI: low, high).

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

OpenRouter reports what each call cost. For another provider, `"prices": {"input": 0.27,
"output": 1.1}` (US dollars per million tokens) lets an agent identity's daily budget
count that model's calls; without prices they count against its daily calls instead
([Limit what an identity spends](/docs/use/spending/)).

## Set up and change the model

The first run of `harness` (and of the app) lists what on this computer can be the model:
agents that are signed in here, keys found in the environment or kept before, local
models, and a provider to add by hand. The one you choose is asked for one word and kept
only when it answers. `harness setup` runs the first run again, `harness model` changes the
model only, and `harness model --list` prints what was found as JSON. A provider and its
key are kept in `~/.harness/config.toml`:

```toml
[model]
provider = "openrouter"
model = "deepseek/deepseek-v4.1-flash"
reasoning_effort = "low"           # optional: low, medium, high
# base_url = "https://..."         # another address for the provider, such as a proxy

[keys]
OPENROUTER_API_KEY = "sk-or-..."
```

Use **Settings → Model** in the app to select a default and check its key. If you edit `[model]` directly, its provider, model and endpoint must match an enabled entry in `models.json`. A mismatch reports both file paths instead of silently choosing another model; update the entry too, or use `--model` to select an enabled route explicitly. An absent `[model]` uses the first enabled entry. An explicitly empty list disables all models; add an entry with `/models` to enable one. A key in your environment
wins over `[keys]`. `[model]` also takes `max_output_tokens` and `checker` (another model of
the same provider that checks the result)
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

## A coding agent as the model

An agent that speaks the Agent Client Protocol (Claude Code, Codex and the others of the
ACP Registry) can be the model. The Harness agent then decides with it like with any
other model: the same programs, workspaces, learning and libraries. The agent signs in
its own way, so a subscription works without a provider key. The Harness starts the agent
you are signed in to and talks to it; it never reads or keeps the agent's sign-in.

Claude Code, Codex, Gemini CLI and Grok are always listed by the first run, `harness model`
and **Settings → Model**, each with its state, and **More agents…** in the same list offers
every other agent of the ACP Registry. Choosing an agent installs what connects it (the
`external-agents` package, which the desktop app brings with it, and the agent's adapter
from the ACP Registry). Gemini CLI, Grok and the agents of the registry need no command
line of theirs on this computer: the adapter is the agent, and when it is not signed in you
sign in to it through the ways it offers (`harness agents login NAME` lists them; the app
and the terminal offer them where the agent said it is not signed in). Claude Code and
Codex go through their own command line and its sign-in (`claude`, `codex`). Its calls count against the
identity's daily calls, not its dollars.

An agent of the registry can also be added from the command line:

```sh
harness install external-agents
harness agents update
harness agents list --registry
harness agents add ACP_REGISTRY_ID
harness agents test ACP_REGISTRY_ID
```

Add an entry to `~/.harness/models.json`. `model` and `efforts` are values the agent
offers for its model and reasoning options:

```json
[
  { "provider": "acp:ACP_REGISTRY_ID", "model": "MODEL", "name": "My agent", "enabled": true,
    "efforts": ["low", "high"] }
]
```

```sh
harness run "Rename the photos by date" --folder ./photos --model MODEL
```

Each call is one turn of a session of the agent, and its text is the reply. The agent
does nothing itself: it gets an empty directory, no client capabilities and, where it
accepts that, no built-in tools; its requests for permission are refused, and a turn in
which it starts a tool of its own fails. A call that continues the conversation sends
only the new messages to the agent's session. A call with a shortened or rewritten
history, or a second call at the same time, takes a session of its own with the whole
conversation.

What an agent reports as cost is the list price of the call under your plan, not a charge:
a spending account counts the call against the day's calls and keeps the reported amount
beside it. Images go to agents that say they read them.

`--agent acp:ACP_REGISTRY_ID` is a different thing: the agent's own conversation in a
folder, with its own tools ([external coding sessions](/docs/use/sessions/#external-coding-sessions)).

## Models that read no images

A model does not have to read images. Every turn is text, and a picture is sent only
when the agent looks ([Observations and views](/docs/reference/observations/#the-model-looks-when-it-needs-to)). The model list
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
- `[limits]` bounds a conversation by model calls and minutes. The app and the terminal
  show no cost and set no dollar limit: only OpenRouter reports what a call cost.
- A sub-agent can use another model of the same provider, for a cheaper or a stronger
  helper ([sub-agents](/docs/use/sessions/#sub-agents)).
