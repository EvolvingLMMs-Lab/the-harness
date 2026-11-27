"""/usage: what an identity spent, as Claude Code's /usage is a view of its own: today, the
last seven days or the last thirty (t, w, m), with the same numbers the app's Usage page
has (the host's usage route): the total, the calls apart by how they are paid for (a call
under your own plan is a call, never invented dollars), each day, each chat, each other
thing it did, each model. r raises today's limit. A stretch without a model call says so."""

import asyncio

from ..core import format as formats
from . import views

RANGES = {"t": ("today", "Today"), "w": ("week", "Last 7 days"), "m": ("month", "Last 30 days")}
BAR = 24


def _money(value) -> str:
    value = float(value or 0)
    return f"${value:.2f}" if value >= 0.01 or value == 0 else f"${value:.4f}"


def _calls(count) -> str:
    return f"{int(count or 0)} call{'' if int(count or 0) == 1 else 's'}"


def _bar(value, top) -> str:
    filled = max(1, round(BAR * float(value) / top)) if value and top else 0
    return "█" * filled + " " * (BAR - filled)


def rows(answer: dict, label: str) -> list[str]:
    """The lines of the view for one answer of the usage route."""
    today = answer.get("today") or {}
    spent, budget = float(today.get("cost_usd") or 0), float(today.get("daily_budget") or 0)
    if budget > 0:
        filled = round(BAR * min(1.0, spent / budget))
        head = (f"Today's limit   {_money(spent)} of {_money(budget)}  {'█' * filled}{'░' * (BAR - filled)}  "
                f"{_money(today.get('left_usd'))} left" + (" (raised for today)" if today.get("raised") else ""))
        sub = (f"  on its own {_money(today.get('own_usd'))} · {_money(today.get('reserve'))} kept for you"
               + (f" · calls without a price: {int(today.get('unpriced_calls') or 0)} of {int(today['daily_calls'])} today"
                  if today.get("daily_calls") else ""))
    else:
        head = f"Today's limit   no daily limit set ({_money(spent)} spent today)"
        sub = (f"  on its own {_money(today.get('own_usd'))}"
               + (f" · calls without a price: {int(today.get('unpriced_calls') or 0)} of {int(today['daily_calls'])} today"
                  if today.get("daily_calls") else ""))
    out = [head, sub, ""]
    calls = answer.get("calls") or {}
    out.append(f"{label} · {answer.get('start')} – {answer.get('end')}" if answer.get("start") else label)
    if not answer.get("days"):
        return out + ["  No model calls in this stretch yet."]
    parts = [f"{int(calls.get('priced') or 0)} with a price" if calls.get("priced") else "",
             f"{int(calls.get('plan') or 0)} under your own plan" if calls.get("plan") else "",
             f"{int(calls.get('unpriced') or 0)} without a price" if calls.get("unpriced") else ""]
    out.append(f"  {_money(answer.get('cost_usd'))} · {_calls(calls.get('total'))} ("
               + " · ".join(part for part in parts if part) + f") · {formats.duration(answer.get('seconds'))} of model time")
    if calls.get("plan"):
        out.append(f"  under your plan: {_calls(calls['plan'])}, not charged here (listed at {_money(answer.get('plan_usd'))})")
    days = answer["days"]
    if len(days) > 1:
        top = max(float(day.get("cost_usd") or 0) for day in days) or 0
        most = max(int(day.get("calls") or 0) for day in days) or 0
        out += ["", "By day"]
        for day in days:
            bar = _bar(day.get("cost_usd"), top) if top else _bar(day.get("calls"), most)
            out.append(f"  {day['date']}  {bar} {_money(day.get('cost_usd')):>8}  {_calls(day.get('calls'))}")
    for name, title, key in (("by_chat", "By chat", "title"), ("by_task", "By task", "title"), ("by_model", "By model", "model")):
        found = answer.get(name) or []
        if not found:
            continue
        top = max(float(row.get("cost_usd") or 0) for row in found) or 0
        most = max(int(row.get("calls") or 0) for row in found) or 0
        out += ["", title]
        for row in found:
            label_ = str(row.get(key) or row.get("id") or row.get("chat") or "")
            if name == "by_chat" and row.get("there") is False:
                label_ += " (deleted)"
            if name == "by_task" and row.get("kind") not in (None, "task"):
                label_ = f"{row['kind']}: {label_}" if label_ else str(row["kind"])
            how = {"plan": "under your plan", "local": "on this computer", "unpriced": "no price",
                   "estimated": "estimated"}.get(row.get("basis"), "")
            bar = _bar(row.get("cost_usd"), top) if top else _bar(row.get("calls"), most)
            out.append(f"  {formats.clip(label_, 30):<30} {bar} {_money(row.get('cost_usd')):>8}  {_calls(row.get('calls'))}"
                       + (f"  {how}" if how else ""))
    return out


async def usage_view(client, note, stretch: str = "today") -> None:
    key = next((key for key, (name, _) in RANGES.items() if name == stretch), "t")
    while True:
        name, label = RANGES[key]
        try:
            answer = await asyncio.to_thread(client.get, "usage", range=name)
        except Exception as error:  # noqa: BLE001
            await views.failed("The usage could not be read", error)
            return
        listed = rows(answer, label)
        picked = await views.browse(f"Usage · {client.identity} · {label}", listed, headers=range(len(listed)),
                                    keys=["t", "w", "m", "r"],
                                    hint="t today · w 7 days · m 30 days · r raise today's limit · esc back")
        if picked is None:
            return
        if picked[0] in RANGES:
            key = picked[0]
        elif picked[0] == "r":
            dollars = await views.ask("Today's limit in dollars (for today only)",
                                      f"{float((answer.get('today') or {}).get('daily_budget') or 0):.2f}",
                                      hint="Enter raise · Esc cancel")
            if not dollars:
                continue
            try:
                await asyncio.to_thread(client.post, "usage", {"raise_today": float(dollars)})
                note(f"today's limit is ${float(dollars):.2f}")
            except Exception as error:  # noqa: BLE001
                await views.failed("The limit was not raised", error)
