"""Model providers the app connects to, after OpenHands' LLM settings: a provider, a
model, a key, and under Advanced a base URL, so any OpenAI-compatible endpoint works
(a self-hosted vLLM or SGLang server, Ollama, LM Studio, a company gateway).

OpenRouter runs on the harness's openrouter backend (usage cost reported); every other
provider on openai_chat with its base URL and key variable (runtime/decision/model.py MODEL_KEYS).
The agent on a computer reads screenshots, so the model must take images; `vision` lists
models known to, and the page says so for the rest.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError

from .core.http import open_url


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base_url: str | None
    key_env: str | None
    backend: str = "openai_chat"
    # The request field of the output limit, when not max_tokens.
    max_tokens_key: str | None = None
    note: str = ""
    extra: dict = field(default_factory=dict)


PROVIDERS = {provider.id: provider for provider in (
    Provider("openrouter", "OpenRouter", None, "OPENROUTER_API_KEY",
             backend="openrouter", note="one key for most models"),
    Provider("openai", "OpenAI", "https://api.openai.com/v1", "OPENAI_API_KEY",
             max_tokens_key="max_completion_tokens"),
    Provider("anthropic", "Anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY"),
    Provider("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    Provider("xai", "xAI", "https://api.x.ai/v1", "XAI_API_KEY"),
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    Provider("dashscope", "Qwen (DashScope)", "https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
    Provider("zhipu", "Zhipu GLM", "https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY"),
    Provider("moonshot", "Moonshot Kimi", "https://api.moonshot.cn/v1", "MOONSHOT_API_KEY"),
    Provider("ollama", "Ollama (this computer)", "http://localhost:11434/v1", None,
             note="no key; the model must be pulled in Ollama"),
    Provider("custom", "Custom (OpenAI-compatible)", None, "HARNESS_LLM_API_KEY",
             note="vLLM, SGLang, LM Studio, a gateway: give the base URL"),
)}
DEFAULT = {"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash", "base_url": None}
# Every key variable a provider uses (the app loads them from its credentials).
KEY_NAMES = sorted({provider.key_env for provider in PROVIDERS.values() if provider.key_env})


def load(directory: Path) -> dict:
    """The model the user chose ({provider, model, base_url}: [model] of config.toml,
    settings.py), or the default."""
    from . import settings as config

    data = config.read(directory).get("model") or {}
    if data.get("provider") not in PROVIDERS:
        return dict(DEFAULT)
    return {"provider": data["provider"], "model": data.get("model") or "", "base_url": data.get("base_url")}


def save(directory: Path, settings: dict) -> None:
    from . import settings as config

    def apply(data):
        # [model] also holds the model's advanced settings (settings.SCHEMA "model").
        section = data.setdefault("model", {})
        for key in ("provider", "model", "base_url"):
            section.pop(key, None)
        section.update({key: value for key, value in settings.items() if value is not None})

    config.change(directory, apply)


def check(settings: dict) -> dict:
    """Whether the provider answers with the key: {settings} normalized, or ValueError."""
    provider = PROVIDERS.get(settings.get("provider"))
    if provider is None:
        raise ValueError(f"no provider {settings.get('provider')!r}")
    model = str(settings.get("model") or "").strip()
    if not model:
        raise ValueError("name a model")
    base_url = str(settings.get("base_url") or "").strip() or provider.base_url
    if provider.backend != "openrouter" and not base_url:
        raise ValueError("give the base URL of the endpoint")
    if base_url and not re.match(r"^https?://", base_url):
        raise ValueError("the base URL starts with http:// or https://")
    return {"provider": provider.id, "model": model,
            "base_url": base_url if base_url != provider.base_url else None}


def models_url(settings: dict) -> str:
    provider = PROVIDERS[settings["provider"]]
    if provider.backend == "openrouter":
        return "https://openrouter.ai/api/v1/key"
    return (settings.get("base_url") or provider.base_url).rstrip("/") + "/models"


def reach(settings: dict, key: str | None, timeout: float = 20.0) -> dict:
    """Ask the provider whether the key works (OpenRouter's key endpoint, else the
    OpenAI-compatible model list): {ok, detail}; the key goes to that provider only."""
    headers = {"authorization": f"Bearer {key}", "x-api-key": key, "anthropic-version": "2023-06-01"} if key else {}
    try:
        with open_url(models_url(settings), headers=headers, timeout=timeout) as response:
            body = json.load(response)
    except HTTPError as error:
        if error.code in (401, 403):
            return {"ok": False, "detail": "refused"}
        # Some endpoints have no model list; the key may still be right.
        return {"ok": True, "detail": f"connected (the model list answered HTTP {error.code})"}
    except (URLError, OSError, ValueError) as error:
        return {"ok": False, "detail": f"unreachable: {error}"}
    if PROVIDERS[settings["provider"]].backend == "openrouter":
        remaining = (body.get("data") or {}).get("limit_remaining")
        return {"ok": True, "detail": None if remaining is None else f"${remaining:.2f} left"}
    ids = [item.get("id") for item in body.get("data") or [] if isinstance(item, dict)]
    known = settings["model"] in ids if ids else None
    return {"ok": True, "detail": None if known is not False else f"{settings['model']} is not in the provider's list",
            "models": ids[:200]}


def catalog(directory: Path, identifier: str) -> list[dict]:
    provider = PROVIDERS.get(identifier)
    if provider is None:
        raise ValueError("choose a model provider")
    chosen = load(directory)
    base = (chosen.get("base_url") if chosen["provider"] == identifier else None) or provider.base_url
    if provider.backend == "openrouter":
        url = "https://openrouter.ai/api/v1/models"
    elif base:
        url = base.rstrip("/") + "/models"
    else:
        raise ValueError("configure the endpoint before looking up models")
    key = os.environ.get(provider.key_env) if provider.key_env else None
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if identifier == "anthropic":
        headers = {"x-api-key": key or "", "anthropic-version": "2023-06-01"}
    try:
        with open_url(url, headers=headers, timeout=12) as response:
            raw = json.load(response)
    except (OSError, ValueError) as error:
        raise ValueError(f"{provider.name} model catalog is unavailable: {error}") from error
    models = []
    for item in raw.get("data", []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            continue
        reasoning = item.get("reasoning") or {} if provider.backend == "openrouter" else {}
        efforts = reasoning.get("supported_efforts", [])
        if efforts is None:
            # Null explicitly means all the gateway's documented effort values.
            efforts = ["max", "xhigh", "high", "medium", "low", "minimal", "none"]
        efforts = [level for level in efforts if level != "none" or not reasoning.get("mandatory")]
        models.append({"id": item["id"], "name": item.get("display_name") or item.get("name") or item["id"],
                       "efforts": efforts, "base_url": base if base != provider.base_url else None})
    return models


def model_file(settings: dict, directory: Path, advanced: dict | None = None) -> Path:
    """A model file (configs/models format) for the user's choice: the same model in
    every role the agent uses (main, vlm, verifier), as the default model file does.
    `advanced` (the app's model settings): reasoning_effort, max_output_tokens, and
    checker, another model of the provider for the verifier."""
    provider = PROVIDERS[settings["provider"]]
    advanced = advanced or {}
    role = {"model": settings["model"]}
    if provider.backend == "openrouter":
        # Streamed, as configs/models' OpenRouter files are: chunks keep coming while the
        # model thinks, so a dropped connection shows within the read timeout.
        role.update(backend="openrouter", stream=True)
    else:
        role.update(backend="openai_chat", base_url=settings.get("base_url") or provider.base_url)
        if provider.key_env:
            role["api_key_env"] = provider.key_env
        if provider.max_tokens_key:
            role["max_tokens_key"] = provider.max_tokens_key
    effort = advanced.get("reasoning_effort")
    if effort and effort != "default":
        # Sent in the field the provider reads (runtime/decision/model.py effort_fields).
        role["reasoning_effort"] = effort
    if advanced.get("max_output_tokens"):
        role["max_output_tokens"] = int(advanced["max_output_tokens"])
    roles = {"main": role, "vlm": role, "verifier": {**role, **({"model": advanced["checker"]}
                                                               if advanced.get("checker") else {})}}
    from .config import dumps

    from .core import atomic_write, sha256

    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", f"{provider.id}-{settings['model']}")[:100]
    slug += "-" + sha256(roles)[:16]
    path = directory / "models" / (slug + ".toml")
    atomic_write(path, dumps({"description": f"{provider.name}: {settings['model']} (the app's model)", **roles}))
    return path


def described() -> list[dict]:
    """The providers as the page lists them."""
    return [{"id": provider.id, "name": provider.name, "base_url": provider.base_url, "key_env": provider.key_env,
             "note": provider.note} for provider in PROVIDERS.values()]


def ready(directory: Path) -> dict:
    """Whether a model is chosen and its key is there (the environment, [keys] of
    config.toml): {ready, provider, model, key_env}."""
    from .settings import Credentials, read

    chosen = load(directory)
    provider = PROVIDERS[chosen["provider"]]
    if provider.key_env:
        Credentials(directory, [provider.key_env]).load()
    configured = bool((read(directory).get("model") or {}).get("provider"))
    has_key = not provider.key_env or bool(os.environ.get(provider.key_env))
    return {"ready": has_key and (configured or provider.id == DEFAULT["provider"]), "provider": provider.id,
            "model": chosen["model"], "key_env": provider.key_env}


def setup(directory: Path, read=input, secret=None, write=print, check_key=True) -> dict:
    """The first run in a terminal: which provider and model, and the key; checked with
    the provider (check_key), then kept in config.toml ([model], [keys]). Returns the
    choice."""
    import getpass

    secret = secret or getpass.getpass
    ids = list(PROVIDERS)
    write("Which model should the agent use? (the key stays in ~/.harness/config.toml, readable by you only)")
    for number, provider in enumerate(PROVIDERS.values(), 1):
        write(f"  {number:2}. {provider.name}" + (f"  ({provider.note})" if provider.note else ""))
    while True:
        answer = read(f"Provider [1-{len(ids)}, default 1 {PROVIDERS[ids[0]].name}]: ").strip()
        if not answer:
            provider = PROVIDERS[ids[0]]
        elif answer.isdigit() and 1 <= int(answer) <= len(ids):
            provider = PROVIDERS[ids[int(answer) - 1]]
        elif answer in PROVIDERS:
            provider = PROVIDERS[answer]
        else:
            write(f"  {answer!r} is not one of them")
            continue
        suggested = DEFAULT["model"] if provider.id == DEFAULT["provider"] else ""
        model = read(f"Model{f' [{suggested}]' if suggested else ''}: ").strip() or suggested
        base_url = read("Base URL of the endpoint: ").strip() if provider.base_url is None and \
            provider.backend != "openrouter" else None
        key = secret(f"{provider.key_env}: ").strip() if provider.key_env else None
        try:
            chosen = check({"provider": provider.id, "model": model, "base_url": base_url})
        except ValueError as error:
            write(f"  {error}")
            continue
        if provider.key_env and not key:
            write("  a key is needed for this provider")
            continue
        if check_key:
            result = reach(chosen, key)
            if not result["ok"]:
                write(f"  {provider.name} did not take it: {result['detail']}")
                continue
        save(directory, chosen)
        if key:
            from .settings import Credentials

            Credentials(directory, [provider.key_env]).save(key, provider.key_env)
        from . import model_list

        if not any(row["id"] == model_list.entry(chosen)["id"] for row in model_list.models(directory)):
            model_list.models(directory, {"action": "save", **chosen})
        write(f"Saved: {provider.name}, {chosen['model']} (~/.harness/models.json).")
        return chosen
