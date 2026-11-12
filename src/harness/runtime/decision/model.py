"""Multi-turn text completion for the high level.

Chat Completions covers OpenRouter and self-hosted OpenAI-compatible servers
(vLLM, SGLang) through `openai_chat` with a `base_url`. Messages use the
harness content parts (`input_text`, `input_image`).
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit

from harness.core.http import open_url, post_json, read_sse, redact


# The usage of model calls, one call's (ChatReply.usage, with its finish_reason) or a
# total of several (an episode's summary, a vision model's, which add a count of calls):
# tokens in and out, and the cost in US dollars when the provider reports it.
USAGE = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


def add_usage(total: dict, usage: dict) -> None:
    """Add `usage` (one call's or a total) to `total`, key by key of USAGE."""
    for key, zero in USAGE.items():
        total[key] = total.get(key, zero) + type(zero)(usage.get(key) or zero)


@dataclass
class ChatReply:
    """One completion: its text, usage (USAGE and finish_reason; cost_usd None when the
    provider does not report it), the provider's response id, and the seconds the request
    took with its retries."""

    text: str
    usage: dict = field(default_factory=dict)
    response_id: str | None = None
    seconds: float = 0.0
    # Reasoning text or summary, when the provider returns one (e.g. DeepSeek, GPT-6
    # Luna on OpenRouter); for the trace only, never sent back to the model.
    reasoning: str = ""


# The keys of a model role (configs/models/<name>.toml: [main], [vlm], [pointer],
# [verifier]). Documentation; ChatModel reads them.
MODEL_KEYS = {
    "service": "a service of the deploy instead of a hosted model: its client config, with this role's keys on top",
    "backend": "openrouter (default), openai_chat (any OpenAI-compatible server) or one a package provides "
               "(acp: an ACP agent answers as the model, the external-agents package)",
    "agent": "acp: the agent, acp:<id> as harness agents ls names it",
    "mode": "acp: the agent's session mode (default: the first it offers that asks before it acts)",
    "session_meta": "acp: fields added to the _meta of the agent's new sessions",
    "model": "the model id",
    "base_url": "openai_chat: the server's URL, e.g. http://127.0.0.1:8800/v1",
    "base_url_env": "openai_chat: environment variable holding the server URL; overrides base_url when set",
    "api_key_env": "the environment variable that holds the key (default OPENROUTER_API_KEY for openrouter)",
    "reasoning_effort": "the model provider’s reasoning option ID (effort_fields); omit to use its default",
    "max_output_tokens": "tokens per reply, reasoning included on OpenRouter (default 8192)",
    "max_tokens_key": "the request field of that limit (default max_tokens; OpenAI's newer models take "
                      "max_completion_tokens)",
    "temperature": "sampling temperature (default: the provider's)",
    "stream": "stream the reply: a dead connection shows within the read timeout while a model thinks",
    "timeout_seconds": "read timeout of one request (default 300)",
    "retries": "retries of a failed request (default 2)",
    "retry_seconds": "keep retrying transient failures until this long after the request started",
    "extra_body": "extra request fields for OpenAI-compatible servers (e.g. max_image_side)",
    "images": "false for a model that reads no images: none is sent to it (default: it reads them)",
    "on_demand": "written by the resolution for an on-demand service: the broker starts it first",
}


# Thinking tokens for providers that take a budget instead of a level.
BUDGETS = {"low": 2000, "medium": 8000, "high": 24000}


def valid_effort(value):
    return isinstance(value, str) and (not value or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) is not None)


def effort_fields(backend: str, base_url, model: str, effort, max_tokens: int) -> dict:
    """The request fields that set `effort` (none, low, medium, high) for this provider,
    each in the field its API reads; {} when unset. OpenAI, Gemini, Ollama and other
    OpenAI-compatible servers take OpenAI's reasoning_effort."""
    if not effort:
        return {}
    if backend == "openrouter":
        return {"reasoning": {"enabled": False} if effort == "none" else {"effort": effort}}
    host = str(base_url or "")
    budget = max(1024, min(BUDGETS.get(effort, 0), max_tokens - 1024))
    if "anthropic.com" in host:
        # Its OpenAI-compatible endpoint ignores reasoning_effort; thinking takes a budget.
        return {"thinking": {"type": "disabled"} if effort == "none" else {"type": "enabled", "budget_tokens": budget}}
    if "dashscope" in host:
        return {"enable_thinking": False} if effort == "none" else {"enable_thinking": True, "thinking_budget": budget}
    if "bigmodel.cn" in host or "z.ai" in host:
        return {"thinking": {"type": "disabled" if effort == "none" else "enabled"}}
    if "deepseek.com" in host:
        # Levels low, high and max; thinking is a switch of its own.
        return {"thinking": {"type": "disabled"}} if effort == "none" else {
            "thinking": {"type": "enabled"}, "reasoning_effort": "low" if effort == "low" else "high"}
    if "moonshot" in host:
        if "k3" in model:
            return {} if effort == "none" else {"reasoning_effort": "low" if effort == "low" else "high"}
        return {"thinking": {"type": "disabled" if effort == "none" else "enabled"}}
    if "x.ai" in host:
        # Grok takes low or high, on the models that accept it.
        return {} if effort == "none" else {"reasoning_effort": "low" if effort == "low" else "high"}
    return {"reasoning_effort": effort}


CHAT_COMPLETIONS = "/chat/completions"


def chat_url(provider, base_url):
    """The Chat Completions URL of a model config (backend, base_url)."""
    if provider == "openrouter" and not base_url:
        return "https://openrouter.ai/api/v1/chat/completions"
    if not base_url:
        raise ValueError("openai_chat requires base_url")
    root = base_url.rstrip("/")
    if root.endswith(CHAT_COMPLETIONS):
        return root
    return root + CHAT_COMPLETIONS


def chat_part(part):
    if part["type"] == "input_text":
        return {"type": "text", "text": part["text"]}
    if part["type"] == "input_image":
        return {"type": "image_url", "image_url": {"url": part["image_url"]}}
    raise ValueError(f"Unsupported content part: {part['type']}")


BUILT_IN = ("openrouter", "openai_chat")
# Prompt caching. Most providers cache the prefix of a request by themselves; those here
# cache up to a mark (OpenRouter: Anthropic's models and Alibaba's Qwen). The request
# marks the system prompt and the last part of its last message, so that what a call read
# the next one reads from the cache as long as the conversation only grows.
CACHE_MARK = {"type": "ephemeral"}


def marks_cache(model: str) -> bool:
    return model.startswith("anthropic/") or "qwen" in model.lower()


def package_transport(config: dict):
    """The transport of a backend a package provides (extensions.py model_backend)."""
    from harness.extensions import modules

    for module in modules():
        factory = getattr(module, "model_backend", None)
        transport = factory(config) if factory else None
        if transport is not None:
            return transport
    backend = config.get("backend")
    raise ValueError(f"no installed package provides the {backend} model backend"
                     + (": harness install external-agents" if backend == "acp" else ""))


class ChatModel:
    """A Chat Completions client for one model role (MODEL_KEYS): OpenRouter, an
    OpenAI-compatible server, or a backend of a package, which answers the same request
    (package_transport). The openrouter backend needs its key in the environment;
    `transport` replaces the HTTP call (tests)."""

    def __init__(self, config: dict, transport=None):
        self.provider = config.get("backend", "openrouter")
        self.packaged = self.provider not in BUILT_IN
        if self.packaged and transport is None:
            transport = package_transport(config)
        self.model = config["model"]
        # A URL in base_url_env is resolved with the agent (config/agent.py _role).
        self.base_url = config.get("base_url")
        if self.provider == "openai_chat" and not self.base_url:
            named = config.get("base_url_env")
            raise ValueError(f"openai_chat requires base_url.{f' Set {named}.' if named else ''}")
        # A self-hosted model placed on demand is started by the deploy's broker first.
        self.on_demand = config.get("on_demand")
        self.url = "" if self.packaged else chat_url(self.provider, self.base_url)
        self.timeout = float(config.get("timeout_seconds", 300.0))
        self.max_output_tokens = int(config.get("max_output_tokens", 8192))
        self.max_tokens_key = str(config.get("max_tokens_key") or "max_tokens")
        self.reasoning_effort = config.get("reasoning_effort")
        self.temperature = config.get("temperature")
        self.retries = int(config.get("retries", 2))
        # Keep retrying transient failures until this many seconds have passed since the
        # request started (at least `retries` times). The simulator does not advance while
        # the model is being called, so waiting out an outage costs wall time only.
        self.retry_seconds = config.get("retry_seconds")
        self.retry_seconds = None if self.retry_seconds is None else float(self.retry_seconds)
        # Extra request fields for OpenAI-compatible servers (e.g. max_image_side for serve_vlm.py).
        self.extra_body = dict(config.get("extra_body") or {})
        # Streaming keeps bytes flowing while a reasoning model thinks; some networks reset
        # a connection that stays silent for minutes waiting for a non-streamed reply.
        self.stream = bool(config.get("stream", False))
        self.transport = transport or (sse_transport if self.stream else urllib_transport)
        key_env = config.get("api_key_env") or ("OPENROUTER_API_KEY" if self.provider == "openrouter" else None)
        self._api_key = os.environ.get(key_env) if key_env else None
        if self.provider == "openrouter" and not self._api_key:
            raise ValueError(f"Set {key_env} before selecting the openrouter backend")
        self._api_key = self._api_key or "EMPTY"

    def payload(self, system: str, messages: list[dict]) -> dict:
        """The request body: `system` and the harness messages as chat messages, the output
        limit and extra_body fields, and on OpenRouter usage accounting and reasoning."""
        # Some models (Molmo2) take no system message; an empty one is left out.
        converted = [{"role": "system", "content": system}] if system else []
        for message in messages:
            content = message["content"]
            if isinstance(content, str):
                converted.append({"role": message["role"], "content": content})
            else:
                converted.append({"role": message["role"],
                                  "content": [chat_part(part) for part in content]})
        if (self.provider == "openrouter" or urlsplit(self.url).hostname == "openrouter.ai") and marks_cache(self.model):
            for message in ([converted[0]] if system else []) + converted[-1:]:
                if isinstance(message["content"], str):
                    message["content"] = [{"type": "text", "text": message["content"]}]
                if message["content"]:
                    message["content"][-1] = {**message["content"][-1], "cache_control": CACHE_MARK}
        payload = {"model": self.model, "messages": converted, self.max_tokens_key: self.max_output_tokens,
                   **self.extra_body}
        if self.stream:
            payload["stream"] = True
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.provider == "openrouter":
            payload["usage"] = {"include": True}
        payload.update(effort_fields(self.provider, self.base_url, self.model, self.reasoning_effort,
                                     self.max_output_tokens))
        return payload

    def close(self) -> None:
        """Let go of what the transport holds (a package backend's process; nothing for HTTP)."""
        close = getattr(self.transport, "close", None)
        if callable(close):
            close()

    @property
    def streams_text(self) -> bool:
        """Whether complete() can hand over the reply's text as it streams (on_text)."""
        return self.stream and self.transport is sse_transport or bool(getattr(self.transport, "streams_text", False))

    def complete(self, system: str, messages: list[dict], on_text=None, *, cancellation=None) -> ChatReply:
        """One completion of `messages` under `system`, starting an on-demand service through
        the broker first. Failed requests are retried (`retries` times, or until
        `retry_seconds` have passed), except client errors other than HTTP 429; the last
        failure is raised as a RuntimeError. When it streams (streams_text), `on_text(kind,
        text)` gets each piece of the reply ("text") and of its reasoning ("reasoning") as
        it comes. A cancellation closes built-in transports and stops retries."""
        if cancellation is not None:
            cancellation.check()
        if self.on_demand:
            from harness.services.broker import ensure

            ensure({"on_demand": self.on_demand})
        payload = self.payload(system, messages)
        headers = {"authorization": f"Bearer {self._api_key}"}
        # Explicit OpenRouter backends include relays; compatible clients can also
        # target OpenRouter directly. Match the hostname, never URL substrings.
        if self.provider == "openrouter" or urlsplit(self.url).hostname == "openrouter.ai":
            headers.update({"http-referer": "https://harness.lmms-lab.com/",
                            "x-openrouter-title": "the-harness"})
        started = time.perf_counter()
        last_error = None
        # A completion has no side effects, so transient provider failures may be retried.
        attempt = 0
        while True:
            if attempt:
                waited = time.perf_counter() - started
                if attempt > self.retries and (self.retry_seconds is None or waited >= self.retry_seconds):
                    raise last_error
                delay = min(2 ** (attempt - 1) * 5, 30 if self.retry_seconds is None else 60)
                if cancellation is None:
                    time.sleep(delay)
                else:
                    cancellation.event.wait(delay)
            if cancellation is not None:
                cancellation.check()
            attempt += 1
            try:
                body = self.transport(self.url, headers, payload, self.timeout,
                                      **({"cancellation": cancellation} if cancellation is not None
                                         and (self.transport in (sse_transport, urllib_transport)
                                              or getattr(self.transport, "cancellable", False)) else {}),
                                      **({"on_text": on_text} if on_text is not None and self.streams_text else {}))
            except Exception as error:
                if cancellation is not None:
                    cancellation.check()
                last_error = RuntimeError(redact(str(error), self._api_key))
                if "Provider HTTP 4" in str(error) and "HTTP 429" not in str(error):
                    raise last_error from None  # a client error will not pass on retry
                continue
            if isinstance(body, dict) and body.get("error"):
                detail = body["error"]
                text = detail.get("message", str(detail)) if isinstance(detail, dict) else str(detail)
                last_error = RuntimeError(f"{self.provider} error: {redact(text, self._api_key)}")
                continue
            choices = body.get("choices") or []
            if len(choices) != 1:
                raise ValueError(f"Expected one completion choice, got {len(choices)}")
            message = choices[0].get("message") or {}
            usage = body.get("usage") or {}
            return ChatReply(
                text=(message.get("content") or "") + _tool_blocks(message.get("tool_calls")),
                reasoning=message.get("reasoning") or "",
                usage={"input_tokens": usage.get("prompt_tokens", 0),
                       "output_tokens": usage.get("completion_tokens", 0),
                       "cost_usd": usage.get("cost"),
                       "finish_reason": choices[0].get("finish_reason"),
                       # What of the input came from the provider's cache, where it says.
                       **({"cached_tokens": usage["prompt_tokens_details"]["cached_tokens"]}
                          if (usage.get("prompt_tokens_details") or {}).get("cached_tokens") is not None else {}),
                       # An ACP agent: whether its session went on or a new one took the whole conversation.
                       **({"session": usage["session"]} if usage.get("session") else {})},
                response_id=body.get("id"),
                seconds=time.perf_counter() - started,
            )


# DeepSeek models sometimes answer with a tool call of the provider's own where the text
# should hold the block (finish_reason "tool_calls", no tools offered): on agent 1.51's
# Minecraft practice (accept8, seed 0) two calls ran nothing so, one reply prose only and
# one empty. A call named for a block (python, or a name with python, code or exec in it)
# is read as that block, its program the one text argument.
_TOOL_KINDS = ("python", "verify", "finish", "action", "wait")
_TOOL_ARGUMENTS = ("code", "program", "source", "script", "python", "input", "content", "text", "claim", "result")


def _tool_blocks(calls) -> str:
    """Native tool calls of a reply as the blocks they name, after its text."""
    blocks = []
    for call in calls or []:
        function = (call or {}).get("function") or {}
        name = str(function.get("name") or "").strip()
        body = function.get("arguments")
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except ValueError:
                pass
        if isinstance(body, dict):
            texts = [body[key] for key in _TOOL_ARGUMENTS if isinstance(body.get(key), str)]
            others = [value for value in body.values() if isinstance(value, str)]
            body = texts[0] if texts else others[0] if len(others) == 1 else json.dumps(body)
        kind = (name if name in _TOOL_KINDS else
                "python" if re.search(r"python|code|exec", name, re.IGNORECASE) else name or "python")
        program = str(body if body is not None else "").strip("\n")
        blocks.append(f"\n<{kind}>\n{program}\n</{kind}>")
    return "".join(blocks)


def urllib_transport(url, headers, payload, timeout, *, cancellation=None):
    """POST a chat completion and return the provider's response."""
    with _provider_errors():
        return post_json(url, payload, headers, timeout, **({"cancellation": cancellation} if cancellation else {}))


def sse_transport(url, headers, payload, timeout, on_text=None, *, cancellation=None):
    """POST a streamed chat completion and assemble the chunks into the non-streamed
    response shape. `timeout` bounds each read, so keep-alive comments reset it.
    `on_text(kind, text)` gets each piece as it comes (ChatModel.complete)."""
    options = {"cancellation": cancellation} if cancellation is not None else {}
    with _provider_errors(), open_url(url, payload, headers, timeout, **options) as response:
        return _read_sse(response, on_text)


@contextmanager
def _provider_errors():
    """A failed request as a RuntimeError that says what the provider answered."""
    try:
        yield
    except HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Provider HTTP {error.code}: {detail}") from error
    except OSError as error:
        raise RuntimeError(f"Provider request failed: {getattr(error, 'reason', error)}") from error


def _read_sse(lines, on_text=None):
    response_id, usage = None, None
    content, reasoning = [], []
    finish = None
    # Native tool calls, by index: their name and the pieces of their arguments.
    tools = {}
    for event, data in read_sse(lines):
        if event is None:
            # ": keep-alive" comments, which a provider sends while the model has not
            # begun: on_text hears of them as an empty piece, so a caller can cut off a
            # reply that has not started (runtime/conversation.py).
            if on_text is not None:
                on_text("", "")
            continue
        data = data.strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        if chunk.get("error"):
            return {"error": chunk["error"]}
        response_id = response_id or chunk.get("id")
        usage = chunk.get("usage") or usage
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            content.append(delta.get("content") or "")
            reasoning.append(delta.get("reasoning") or "")
            for piece in delta.get("tool_calls") or []:
                tool = tools.setdefault(piece.get("index", 0), {"name": "", "arguments": ""})
                function = piece.get("function") or {}
                tool["name"] += function.get("name") or ""
                arguments = function.get("arguments")
                tool["arguments"] += arguments if isinstance(arguments, str) else json.dumps(arguments or "")
            if on_text is not None:
                for kind, piece in (("reasoning", reasoning[-1]), ("text", content[-1])):
                    if piece:
                        on_text(kind, piece)
            finish = choice.get("finish_reason") or finish
    if finish is None:
        # The connection closed before the completion finished (the provider dropped the
        # stream): a transport failure to retry, not an empty reply.
        raise OSError(f"stream ended before the reply finished ({len(''.join(content))} characters received)")
    return {"id": response_id, "usage": usage or {},
            "choices": [{"message": {"content": "".join(content),
                                     **({"reasoning": "".join(reasoning)} if any(reasoning) else {}),
                                     **({"tool_calls": [{"function": tools[index]} for index in sorted(tools)]}
                                        if tools else {})},
                         "finish_reason": finish}]}


def scripted_models(script) -> dict:
    """The models of a scripted episode: `script` is a list of replies, or
    {"replies": [...], "verifier": [...]} as scripts/replay_script.py writes it; without
    recorded verifier answers the verifier says YES."""
    if isinstance(script, list):
        script = {"replies": script}
    return {"chat": ScriptedChat(script["replies"]),
            "verifier": ScriptedChat(script.get("verifier") or ["YES (scripted verifier)"] * 100)}


# The end of a request that says the model's program still runs and nothing else happened.
_STILL_RUNNING = re.compile(r"Program \d+ is still running")
_WAIT_OVER = re.compile(r"^Wait ended after [\d.]+ s: its time is over")


def still_running(messages: list[dict]) -> bool:
    """Whether the final content part says a program still runs and nothing reached the
    model: it was just started, or a wait's time is over while units run (a wait whose time
    is over with nothing running is the script's own to answer)."""
    content = messages[-1].get("content") if messages else None
    last = content if isinstance(content, str) else (content[-1].get("text", "") if content else "")
    last = last or ""
    return bool(_STILL_RUNNING.match(last) or (_WAIT_OVER.match(last) and "\nUnits running:" in last))


class ScriptedChat:
    """Replays fixed replies in order. For pipeline checks without model calls. A turn that
    comes back while a program still runs is answered <wait> without taking a reply (`waits`
    counts them), so the script is the replies after each program's result; with
    `waits=False` every call takes the next reply."""

    def __init__(self, replies: list[str], waits: bool = True):
        self.replies = list(replies)
        self.calls = 0
        self.waits = 0
        self._waits = waits

    def complete(self, system: str, messages: list[dict]) -> ChatReply:
        """The next scripted reply (a `<finish>` block once they run out), with zero usage."""
        if self._waits and still_running(messages):
            self.waits += 1
            return ChatReply(text="<wait></wait>", usage=dict(USAGE))
        if self.calls >= len(self.replies):
            text = "<finish>scripted replies exhausted</finish>"
        else:
            text = self.replies[self.calls]
        self.calls += 1
        return ChatReply(text=text, usage=dict(USAGE))
