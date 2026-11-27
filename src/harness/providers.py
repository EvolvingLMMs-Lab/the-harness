"""Model providers the app connects to, after OpenHands' LLM settings: a provider, a
model, a key, and under Advanced a base URL, so any OpenAI-compatible endpoint works
(a self-hosted vLLM or SGLang server, Ollama, LM Studio, a company gateway).

OpenRouter runs on the harness's openrouter backend (usage cost reported); every other
provider on openai_chat with its base URL and key variable (runtime/decision/model.py MODEL_KEYS).
A model need not read images: each turn is text (the state, what programs returned), and a
view is sent only when a program looks. The model list keeps whether a model reads them
(model_list.py `images`, from the provider's catalog where it says, the user's to change);
one that reads none is sent none, and the choice of where a conversation works says so
beside the environments that have a screen.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
from urllib.error import HTTPError, URLError

from .core.http import open_url

_SHUTIL_WHICH = shutil.which


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
             note="vLLM, SGLang, LM Studio, a gateway: give the base URL; key optional"),
)}
DEFAULT = {"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash", "base_url": None}


@dataclass(frozen=True)
class AgentCli:
    """An agent's command line that can be the model under the user's own plan: the session
    host starts it through the Agent Client Protocol and it calls the model with its own
    sign-in, which stays its own (nothing of it is read or kept here)."""
    id: str           # its adapter in the ACP Registry: the model entry's provider is acp:<id>
    name: str
    executable: str   # the command that is on the PATH when it is installed
    status: tuple     # the arguments with which it ends 0 when signed in; () when it has none
    plan: str         # whose plan a call counts against, as the user knows it
    sign_in: str      # how to sign in
    install: str      # what installs it: a command, or the page that says how
    # Its adapter of the ACP Registry is the agent itself: it needs no command line on this
    # computer, and its user signs in through it (the ways it offers over ACP).
    standalone: bool = False
    # Optional direct ACP subcommand args (e.g. ("acp",) for `agy acp`) when the CLI speaks ACP natively.
    acp_args: tuple = ()

    @property
    def setup(self) -> str:
        """What to do when it is not on this computer."""
        return f"install {self.name} ({self.install}), {self.sign_in}, then choose it again"


# The agents' command lines people use most: every list of a model's sources names them,
# installed or not (one that is not says how to get it). Any other agent of the ACP Registry
# is one row further (onboarding.more_agents).
AGENTS = {agent.id: agent for agent in (
    AgentCli("claude-acp", "Claude Code", "claude", ("auth", "status"), "your Claude plan",
             "run claude and sign in (/login)", "https://code.claude.com/docs/en/setup"),
    AgentCli("codex-acp", "Codex", "codex", ("login", "status"), "your ChatGPT plan",
             "run codex login", "npm install -g @openai/codex"),
    AgentCli("antigravity", "Antigravity CLI", "agy", (), "your Google AI plan",
             "run agy acp --login (or agy) and sign in with Google",
             "irm https://antigravity.google/cli/install.ps1 | iex" if os.name == "nt"
             else "curl -fsSL https://antigravity.google/cli/install.sh | bash",
             acp_args=("acp",)),
    AgentCli("grok-build", "Grok", "grok", (), "your Grok plan",
             "run grok and sign in", "npm install -g @xai-official/grok", standalone=True),
)}


def _agent_bin_dirs(executable: str) -> list[Path]:
    """Per-user bin directories where agent CLI installers place binaries."""
    home = Path.home()
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA") or (home / "AppData" / "Roaming"))
        return [
            local / executable / "bin",
            local / "Programs" / executable / "bin",
            home / ".local" / "bin",
            roaming / "npm",
        ]
    return [
        home / ".local" / "bin",
        home / "bin",
        home / f".{executable}" / "bin",
    ]


def which_agent(executable: str) -> str | None:
    """Locate an agent CLI on PATH, or in its standard per-user install folder when the CLI
    was installed after the desktop app started (before PATH refreshed)."""
    found = shutil.which(executable)
    if found:
        return found
    if shutil.which is not _SHUTIL_WHICH:
        return None
    extra = [str(folder) for folder in _agent_bin_dirs(executable) if folder.is_dir()]
    return _SHUTIL_WHICH(executable, path=os.pathsep.join(extra)) if extra else None


def is_agent(provider) -> bool:
    """Whether a model entry's provider is an ACP agent that answers as the model (acp:<id>)."""
    return isinstance(provider, str) and provider.startswith("acp:")
# Every key variable a provider uses (the app loads them from its credentials).
KEY_NAMES = sorted({provider.key_env for provider in PROVIDERS.values() if provider.key_env})


def requires_key(identifier: str) -> bool:
    """Whether this provider requires credentials; Custom can use an unauthenticated endpoint."""
    return identifier in PROVIDERS and identifier != "custom" and bool(PROVIDERS[identifier].key_env)


def load(directory: Path) -> dict:
    """The model the user chose ({provider, model, base_url}: [model] of config.toml,
    settings.py), or the default."""
    from . import settings as config

    data = config.read(directory).get("model") or {}
    if isinstance(data, dict) and "provider" not in data:
        return dict(DEFAULT)
    from .model_list import SelectionError

    if not isinstance(data, dict):
        raise SelectionError(f"{config.path(directory)}: model must be a table")
    try:
        return check(data)
    except ValueError as error:
        raise SelectionError(f"{config.path(directory)}: model: {error}") from None


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
    if is_agent(settings.get("provider")):
        # An agent that answers as the model: its own default model unless one is named.
        return {"provider": settings["provider"], "model": str(settings.get("model") or "").strip() or "default",
                "base_url": None}
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
    base = settings.get("base_url") or provider.base_url
    if provider.backend == "openrouter":
        base = base or "https://openrouter.ai/api/v1"
    if not base:
        raise ValueError("give the base URL of the endpoint")
    base = base.rstrip("/").removesuffix("/chat/completions")
    return base + ("/key" if provider.backend == "openrouter" else "/models")


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
    """What a provider lists: [{id, name, efforts, base_url, images?}]. `efforts`: the model's
    reasoning effort levels, as a gateway's catalog names them for each model; for a
    provider's own endpoint, the levels its API tells apart (effort_levels)."""
    from .runtime.decision.model import effort_levels

    provider = PROVIDERS.get(identifier)
    if provider is None:
        raise ValueError("choose a model provider")
    chosen = load(directory)
    base = (chosen.get("base_url") if chosen["provider"] == identifier else None) or provider.base_url
    if provider.backend == "openrouter":
        url = (base or "https://openrouter.ai/api/v1").rstrip("/").removesuffix("/chat/completions") + "/models"
    elif base:
        url = base.rstrip("/").removesuffix("/chat/completions") + "/models"
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
        if provider.backend != "openrouter":
            # A provider's own list of models says nothing of effort: the levels its API tells apart.
            efforts = effort_levels(provider.backend, base, item["id"])
        # Whether it reads images, where the provider says (OpenRouter's input modalities).
        modalities = (item.get("architecture") or {}).get("input_modalities")
        models.append({"id": item["id"], "name": item.get("display_name") or item.get("name") or item["id"],
                       "efforts": efforts, "base_url": base if base != provider.base_url else None,
                       **({"images": "image" in modalities} if isinstance(modalities, list) else {})})
    return models


def model_file(settings: dict, directory: Path, advanced: dict | None = None) -> Path:
    """A model file (configs/models format) for the user's choice: the same model in
    every role the agent uses (main, vlm, verifier), as the default model file does.
    `advanced` (the app's model settings): reasoning_effort, max_output_tokens, and
    checker, another model of the provider for the verifier."""
    name = settings["provider"]
    advanced = advanced or {}
    role = model_role(settings, advanced)
    # The role that answers about images inside programs: the vision model when the main
    # one reads none and one is set.
    sees = viewer_role(settings, advanced) or role
    checker = {key: value for key, value in role.items() if key != "prices"} if advanced.get("checker") else role
    roles = {"main": role, "vlm": sees, "verifier": {**checker, **({"model": advanced["checker"]}
                                                                   if advanced.get("checker") else {})}}
    from .config import dumps

    from .core import atomic_write, sha256

    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", f"{name}-{settings['model']}")[:100]
    slug += "-" + sha256(roles)[:16]
    path = directory / "models" / (slug + ".toml")
    label = name if is_agent(name) else PROVIDERS[name].name
    atomic_write(path, dumps({"description": f"{label}: {settings['model']} (the app's model)", **roles}))
    return path


def model_role(settings: dict, advanced: dict | None = None) -> dict:
    """The model role (runtime/decision/model.py MODEL_KEYS) of the user's choice with the
    advanced settings; `images` false when the model list says it reads none."""
    advanced = advanced or {}
    role = {"model": settings["model"]}
    provider = None if is_agent(settings["provider"]) else PROVIDERS[settings["provider"]]
    if provider is None:
        # An ACP agent answers as the model (the external-agents package's backend).
        role.update(backend="acp", agent=settings["provider"])
    elif provider.backend == "openrouter":
        # Streamed, as configs/models' OpenRouter files are: chunks keep coming while the
        # model thinks, so a dropped connection shows within the read timeout.
        role.update(backend="openrouter", stream=True)
        if settings.get("base_url"):
            role["base_url"] = settings["base_url"]
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
    if advanced.get("images") is False:
        role["images"] = False
    if settings.get("prices"):
        # The entry's prices (model_list.py), for this model only.
        role["prices"] = dict(settings["prices"])
    return role


def viewer_role(settings: dict, advanced: dict | None = None) -> dict | None:
    """The role of the vision model (the setting model.vision: another model of the same
    provider) that describes a view for a main model that reads no images; None when the
    main model reads them or none is set."""
    advanced = advanced or {}
    if advanced.get("images") is not False or not advanced.get("vision"):
        return None
    role = model_role(settings, {key: value for key, value in advanced.items()
                                 if key not in ("images", "reasoning_effort")})
    role.pop("prices", None)
    return {**role, "model": str(advanced["vision"])}


def described() -> list[dict]:
    """The providers as the page lists them."""
    return [{"id": provider.id, "name": provider.name, "base_url": provider.base_url, "key_env": provider.key_env,
             "note": provider.note} for provider in PROVIDERS.values()]


def ready(directory: Path) -> dict:
    """Whether the actual enabled default model is ready, with its missing requirement.
    Credentials come from the environment before [keys] of config.toml."""
    from .model_list import SelectionError, select
    from .settings import Credentials

    try:
        selected = select(directory)
        chosen = selected or load(directory)
    except SelectionError as error:
        return {"ready": False, "provider": None, "model": None, "key_env": None,
                "detail": str(error), "selection_error": True}
    provider = PROVIDERS.get(chosen["provider"])
    key_env = provider.key_env if provider else None
    if key_env:
        Credentials(directory, [key_env]).load()
    has_key = not requires_key(chosen["provider"]) or bool(os.environ.get(key_env))
    detail = None
    if selected is None:
        detail = f"add an enabled model in {directory / 'models.json'}"
        if not (directory / "models.json").exists() and not has_key:
            detail = f"{key_env} is not set"
    elif not has_key:
        detail = f"{key_env} is not set"
    return {"ready": selected is not None and has_key, "provider": chosen["provider"],
            "model": chosen["model"], "key_env": key_env, "detail": detail}
