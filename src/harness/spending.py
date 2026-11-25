"""What model calls cost, and the spending accounts they are charged to.

A call's cost is what the provider reported (OpenRouter reports it); else an estimate from
the model's prices (a model entry's `prices`: US dollars per million input and output
tokens); else it has no price. A model on this computer or this network (its URL's host is
a loopback or private address, or `localhost`) costs $0 and has no price either.

An account is a folder that whoever starts the calls keeps (the agent package keeps one per
identity):

    limits.json          {"daily_budget": dollars, "daily_calls": calls, "reserve": dollars}:
                         its limits; `reserve` is the part of the budget kept for the
                         owner's matters, which calls for its own work (whose "own") may
                         not use
    raised.json          {"date": "YYYY-MM-DD", "daily_budget": dollars}: a higher budget
                         for that day only
    YYYY-MM-DD.jsonl     that day's calls, one line each: time, model, cost_usd, priced,
                         basis (reported, estimated, local, unpriced), source

A day runs from 0:00 to 0:00 local time. Priced calls count against the daily budget,
calls with no price against the daily call cap; before a call the one that applies to it
is checked (Account.check): a call already made always finishes and is charged, so a day can end a
little over its budget, and no call starts after that until 0:00.

Standard library only."""

from datetime import date as Date, timedelta
import ipaddress
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from .core import atomic_write
from .core.procs import file_lock

DAILY_BUDGET, DAILY_CALLS = 2.0, 500


class SpendingLimit(RuntimeError):
    """A model call refused: today's budget or call cap of its account is used up."""


def local(url) -> bool:
    """Whether a model's URL is on this computer or this network."""
    host = urlsplit(str(url or "")).hostname or ""
    if host == "localhost" or host.endswith((".localhost", ".local")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def cost(chat, usage: dict) -> dict:
    """What one call of `chat` (a ChatModel, or anything with model, base_url, prices) cost:
    {cost_usd, priced, basis}. cost_usd is None when it has no price."""
    reported = usage.get("cost_usd")
    if reported is not None:
        return {"cost_usd": float(reported), "priced": True, "basis": "reported"}
    prices = getattr(chat, "prices", None) or {}
    if prices:
        estimate = (int(usage.get("input_tokens") or 0) * float(prices.get("input") or 0)
                    + int(usage.get("output_tokens") or 0) * float(prices.get("output") or 0)) / 1e6
        return {"cost_usd": estimate, "priced": True, "basis": "estimated"}
    if local(getattr(chat, "base_url", None) or getattr(chat, "url", None)):
        return {"cost_usd": 0.0, "priced": False, "basis": "local"}
    return {"cost_usd": None, "priced": False, "basis": "unpriced"}


def priced(chat) -> bool:
    """Whether a call of `chat` will have a price: prices set, or a provider that reports
    what a call cost (OpenRouter); a local model and others have none."""
    if getattr(chat, "prices", None):
        return True
    url = getattr(chat, "base_url", None) or getattr(chat, "url", None)
    if local(url):
        return False
    return getattr(chat, "provider", None) == "openrouter" or urlsplit(str(url or "")).hostname == "openrouter.ai"


def check_prices(value) -> dict:
    """A model entry's prices as kept: {input, output} in dollars per million tokens."""
    if not isinstance(value, dict) or set(value) - {"input", "output"} or not value:
        raise ValueError("prices is {input, output}: US dollars per million tokens")
    checked = {}
    for key, number in value.items():
        if type(number) not in (int, float) or not 0 <= number < 10000:
            raise ValueError(f"prices.{key} is dollars per million tokens, 0 or more")
        checked[key] = float(number)
    return checked


def usd(dollars) -> str:
    """Dollars as a person reads them: cents, or more digits below a cent."""
    dollars = float(dollars or 0)
    return f"${dollars:.2f}" if dollars == 0 or dollars >= 0.01 else f"${dollars:.6f}".rstrip("0")


def today() -> str:
    return Date.today().isoformat()


class Account:
    """A spending account (the module's docstring)."""

    def __init__(self, directory):
        self.directory = Path(directory)

    def _read(self, name, default):
        path = self.directory / name
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default
        except ValueError:
            return default

    def set_limits(self, daily_budget: float, daily_calls: int, reserve: float = 0.0) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        limits = {"daily_budget": float(daily_budget), "daily_calls": int(daily_calls),
                  **({"reserve": float(reserve)} if reserve else {})}
        if self._read("limits.json", None) != limits:
            atomic_write(self.directory / "limits.json", json.dumps(limits) + "\n")

    def limits(self, day: str | None = None) -> dict:
        """{daily_budget, daily_calls, raised}: today's (or `day`'s) limits."""
        day = day or today()
        saved = self._read("limits.json", {})
        budget = float(saved.get("daily_budget", DAILY_BUDGET))
        raised = self._read("raised.json", {})
        lifted = raised.get("date") == day and float(raised.get("daily_budget") or 0) > budget
        return {"daily_budget": float(raised["daily_budget"]) if lifted else budget,
                "daily_calls": int(saved.get("daily_calls", DAILY_CALLS)), "raised": lifted,
                "reserve": float(saved.get("reserve") or 0.0)}

    def raise_today(self, dollars: float) -> dict:
        """Today's budget becomes `dollars` (more than it is); tomorrow it is the setting again."""
        if type(dollars) not in (int, float) or not 0 < dollars < 100000:
            raise ValueError("a budget is a number of dollars above 0")
        if dollars <= self.limits()["daily_budget"]:
            raise ValueError(f"today's budget is {usd(self.limits()['daily_budget'])} already; raise it above that")
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_write(self.directory / "raised.json", json.dumps({"date": today(), "daily_budget": float(dollars)}) + "\n")
        return self.day()

    def calls(self, day: str | None = None) -> list:
        path = self.directory / f"{day or today()}.jsonl"
        if not path.is_file():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue  # a line cut off by a crash
        return rows

    def day(self, day: str | None = None) -> dict:
        """One day's spending: {date, cost_usd, calls, priced_calls, unpriced_calls,
        daily_budget, daily_calls, raised, left_usd, calls_left, by_source}."""
        day = day or today()
        rows, limits = self.calls(day), self.limits(day)
        spent = sum(float(row.get("cost_usd") or 0) for row in rows)
        unpriced = sum(1 for row in rows if not row.get("priced"))
        by_source = {}
        for row in rows:
            source = row.get("source") or {}
            key = f"{source.get('kind', 'other')}:{source.get('id', '')}"
            entry = by_source.setdefault(key, {**source, "cost_usd": 0.0, "calls": 0})
            entry["cost_usd"] += float(row.get("cost_usd") or 0)
            entry["calls"] += 1
        own = sum(float(row.get("cost_usd") or 0) for row in rows if (row.get("source") or {}).get("whose") == "own")
        return {"date": day, "cost_usd": round(spent, 6), "calls": len(rows), "priced_calls": len(rows) - unpriced,
                "unpriced_calls": unpriced, **limits, "left_usd": round(max(0.0, limits["daily_budget"] - spent), 6),
                "own_usd": round(own, 6),
                "own_left_usd": round(max(0.0, limits["daily_budget"] - limits["reserve"] - spent), 6),
                "calls_left": max(0, limits["daily_calls"] - unpriced),
                "by_source": sorted(by_source.values(), key=lambda entry: -entry["cost_usd"])}

    def week(self) -> list:
        """The last seven days, today first."""
        start = Date.today()
        return [self.day((start - timedelta(days=offset)).isoformat()) for offset in range(7)]

    def refusal(self, chat=None, whose="owner") -> str | None:
        """Why a model call (of `chat`; None: any) may not start now, or None. A priced call
        needs budget left, a call without a price calls left: a model on this computer keeps
        working when the day's dollars are gone. A call for its own work (`whose` "own") may
        not use the reserve kept for the owner."""
        spent = self.day()
        kinds = (True, False) if chat is None else (priced(chat),)
        if whose == "own" and True in kinds and spent["reserve"] and                 spent["cost_usd"] >= spent["daily_budget"] - spent["reserve"]:
            return (f"the part of today's budget for its own work is used up ({usd(spent['cost_usd'])} of "
                    f"{usd(spent['daily_budget'])}, {usd(spent['reserve'])} kept for the owner): asleep until 0:00")
        if True in kinds and spent["cost_usd"] >= spent["daily_budget"]:
            return (f"today's budget of {usd(spent['daily_budget'])} is used up ({usd(spent['cost_usd'])} spent); "
                    f"no model call until 0:00, or raise today's budget")
        if False in kinds and spent["unpriced_calls"] >= spent["daily_calls"]:
            return (f"today's {spent['daily_calls']} model calls without a price are used up; no such call until "
                    "0:00, or raise agent.daily_calls")
        return None

    def check(self, chat=None) -> None:
        """SpendingLimit when a model call (of `chat`) may not start now."""
        why = self.refusal(chat)
        if why is not None:
            raise SpendingLimit(why)

    def charge(self, chat, usage: dict, source: dict | None = None) -> dict:
        """Keep one call that was made (its usage, as ChatReply.usage) in today's ledger."""
        priced = cost(chat, usage or {})
        row = {"time": time.time(), "model": getattr(chat, "model", None), **priced, "source": source or {}}
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{today()}.jsonl"
        with file_lock(self.directory / ".ledger.lock"):
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row


def line(spent: dict) -> str:
    """A day's spending in a few words (a status line): "today $0.46", with the calls that
    have no price when there are any."""
    text = f"today {usd(spent['cost_usd'])}"
    if spent.get("unpriced_calls"):
        text += f" · {spent['unpriced_calls']} unpriced calls"
    if spent["cost_usd"] >= spent["daily_budget"] or spent["unpriced_calls"] >= spent["daily_calls"]:
        text += " (limit reached)"
    return text


def report(account: Account, *, week: bool = False) -> list[str]:
    """Lines for /usage and harness usage: today's spending and limits, by conversation
    and task, and with `week` the last seven days."""
    spent = account.day()
    lines = [f"Today ({spent['date']}): {usd(spent['cost_usd'])} of {usd(spent['daily_budget'])}"
             + (" (raised for today)" if spent["raised"] else "")
             + f"; {spent['priced_calls']} priced calls, {spent['unpriced_calls']} of {spent['daily_calls']} "
               "calls without a price"]
    if refusal := account.refusal():
        lines.append("  Limit reached: " + refusal)
    for source in spent["by_source"]:
        name = source.get("title") or source.get("id") or source.get("kind")
        lines.append(f"  {source.get('kind', 'other'):<6} {str(name)[:48]:<48} {usd(source['cost_usd']):>10}  "
                     f"{source['calls']} calls")
    if week:
        lines.append("Last seven days:")
        for day in account.week():
            lines.append(f"  {day['date']}  {usd(day['cost_usd']):>10}  {day['calls']} calls")
    return lines
