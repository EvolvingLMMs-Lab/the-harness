"""First-turn automatic conversation title generation with clean fallback.

Rules:
- Generates a concise title in the conversation's own language (3-7 words / <= 48 chars).
- Uses a lightweight non-thinking model call when configured, with automatic fallback to
  cleaned truncation stripping quotes, markdown syntax, and conversational filler prefixes.
- Never raises on model or parsing failures.
"""
from __future__ import annotations

import re

MAX_TITLE_LEN = 48

_QUOTE_CHARS = "\"'\u201c\u201d\u2018\u2019\u300c\u300d\u300e\u300f`*"
_TITLE_PREFIX_RE = re.compile(r"^(?:title|标题|主题|conversation title)\s*[:：-]\s*", re.IGNORECASE)
_MD_PREFIX_RE = re.compile(r"^(?:#+\s*|[-*+>]\s+|\d+[.)]\s+)+")
_EN_FILLER_RE = re.compile(
    r"^(?:(?:hi|hello|hey)[,!.\s]+)?(?:(?:please|can you|could you|would you|will you|"
    r"help me(?: to)?|i want(?: to)?|i need(?: to)?|i'd like(?: to)?|let's)\s+)+",
    re.IGNORECASE,
)
_ZH_FILLER_RE = re.compile(r"^(?:你好[，,！!。\s]*|嗨[，,！!\s]*)?(?:请帮我|请你帮我|麻烦帮我|帮我|请问|请你|请|麻烦)+")

_TITLE_SYSTEM = (
    "Generate a concise conversation title (3 to 7 words, max 48 characters) in the EXACT "
    "same language as the user's message. Output ONLY the plain title text with no quotes, "
    "no markdown, no prefix, and no trailing period."
)


def _strip_quotes(text: str) -> str:
    s = text.strip()
    while len(s) >= 2 and ((s[0] in _QUOTE_CHARS and s[-1] in _QUOTE_CHARS) or (s[0] == "《" and s[-1] == "》")):
        s = s[1:-1].strip()
    return s.strip(_QUOTE_CHARS).strip()


def clean_title(raw: str, max_len: int = MAX_TITLE_LEN) -> str:
    """Clean a raw model-generated title into a single crisp line."""
    text = str(raw or "").strip()
    if not text:
        return ""
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    first_line = _TITLE_PREFIX_RE.sub("", first_line)
    first_line = _MD_PREFIX_RE.sub("", first_line)
    first_line = _strip_quotes(first_line)
    first_line = " ".join(first_line.split()).rstrip(".。:：;；")
    if len(first_line) > max_len:
        cut = first_line[: max_len - 1].rstrip()
        if " " in cut and cut.rfind(" ") >= max_len // 2:
            cut = cut[: cut.rfind(" ")].rstrip()
        first_line = cut + "…"
    return first_line


def fallback_title(seed_text: str, max_len: int = MAX_TITLE_LEN) -> str:
    """Deterministic fallback title: strip quotes, markdown, and filler prefixes, then truncate cleanly."""
    text = str(seed_text or "").strip()
    if not text:
        return ""
    # Pick first meaningful non-code-fence line
    line = ""
    for raw_line in text.splitlines():
        cand = raw_line.strip()
        if not cand or cand.startswith("```"):
            continue
        line = cand
        break
    if not line:
        return ""
    line = _MD_PREFIX_RE.sub("", line)
    line = _strip_quotes(line)
    # Strip filler prefixes only if meaningful text remains after stripping
    for pattern in (_ZH_FILLER_RE, _EN_FILLER_RE):
        stripped = pattern.sub("", line).strip(" ,，:：-—")
        if len(stripped) >= 3:
            line = stripped
    line = _strip_quotes(line)
    line = " ".join(line.split())
    if not line:
        return ""
    if len(line) > max_len:
        cut = line[: max_len - 1].rstrip()
        if " " in cut and cut.rfind(" ") >= max_len // 2:
            cut = cut[: cut.rfind(" ")].rstrip()
        line = cut + "…"
    return line


def complete_non_thinking(chat_model, seed_text: str) -> str | None:
    """Run a lightweight non-thinking completion if `chat_model` supports `.complete`."""
    if chat_model is None or not callable(getattr(chat_model, "complete", None)):
        return None
    snippet = str(seed_text or "").strip()[:600]
    if not snippet:
        return None
    messages = [{"role": "user", "content": snippet}]
    # Try with explicit non-thinking / low-budget kwargs first, gracefully degrading for minimal adapters
    for kwargs in (
        {"max_tokens": 32, "reasoning_effort": "none"},
        {"max_tokens": 32},
        {},
    ):
        try:
            reply = chat_model.complete(_TITLE_SYSTEM, messages, **kwargs)
            if isinstance(reply, str):
                return reply
            text = getattr(reply, "text", None)
            if isinstance(text, str):
                return text
            if isinstance(reply, dict) and isinstance(reply.get("text"), str):
                return reply["text"]
            return None
        except TypeError:
            continue
        except Exception:
            return None
    return None


def generate_title(seed_text: str, *, model_complete=None, max_len: int = MAX_TITLE_LEN) -> str:
    """Generate a concise title via `model_complete(seed_text)` when given, falling back cleanly."""
    snippet = str(seed_text or "").strip()
    if not snippet:
        return ""
    if callable(model_complete):
        try:
            raw = model_complete(snippet)
            cleaned = clean_title(raw or "", max_len=max_len)
            if cleaned:
                return cleaned
        except Exception:
            pass
    return fallback_title(snippet, max_len=max_len)
