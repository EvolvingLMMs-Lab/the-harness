"""How every frontend shows money, time and long text (ui/static/format.js: the same money and
time): cost(0.0342) "$0.0342", duration(64.2) "64 s", clock(75) "1:15", timestamp(epoch or ISO)."""

from datetime import datetime
import math


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def clip(text, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def clip_lines(text, lines: int = 20, width: int = 160) -> list[str]:
    """`text`'s first `lines` lines, each at most `width` characters, and how many more."""
    rows = str(text).rstrip().splitlines()
    return [clip(row, width) for row in rows[:lines]] + ([f"… {len(rows) - lines} more lines"] if len(rows) > lines else [])


def cost(usd) -> str:
    usd = _number(usd)
    return "" if usd is None else f"${usd:.4f}" if abs(usd) < 1 else f"${usd:.2f}"


def duration(seconds, whole_until: int = 600) -> str:
    """One decimal under 10 s, whole seconds under `whole_until`, then [h:]m:ss; "" for no number."""
    seconds = _number(seconds)
    if seconds is None:
        return ""
    seconds = max(seconds, 0.0)
    if seconds < 10:  # halves up, as JavaScript's Math.round
        return f"{math.floor(seconds * 10 + 0.5) / 10:.1f} s"
    if seconds < whole_until:
        return f"{math.floor(seconds + 0.5)} s"
    hours, rest = divmod(math.floor(seconds), 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


def clock(seconds) -> str:
    return duration(seconds, 60)


def timestamp(when) -> str:
    try:
        moment = datetime.fromisoformat(when) if isinstance(when, str) else datetime.fromtimestamp(_number(when))
        return (moment.astimezone() if moment.tzinfo else moment).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""
