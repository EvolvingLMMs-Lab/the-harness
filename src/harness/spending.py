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
                         basis (reported, estimated, local, plan, unpriced), source, and
                         seconds (how long the call took) where it is known; a call under
                         a plan carries plan_usd, what it would cost at list prices

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

DAILY_BUDGET, DAILY_CALLS = 0.0, 0
# The stretches a frontend asks for by name, in days up to and including today.
RANGES = {"today": 1, "week": 7, "month": 30}


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
    if getattr(chat, "plan", False):
        # An agent under the user's own plan: what it reports is what the call would cost at
        # list prices, not a charge. The call counts against the day's calls, not its dollars.
        return {"cost_usd": 0.0, "priced": False, "basis": "plan",
                **({"plan_usd": float(reported)} if reported is not None else {})}
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
    if getattr(chat, "plan", False):
        return False
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
        current = self.limits()["daily_budget"]
        if current <= 0:
            raise ValueError("no daily budget is set; there is no limit to raise")
        if dollars <= current:
            raise ValueError(f"today's budget is {usd(current)} already; raise it above that")
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
        budget = limits["daily_budget"]
        calls_cap = limits["daily_calls"]
        return {"date": day, "cost_usd": round(spent, 6), "calls": len(rows), "priced_calls": len(rows) - unpriced,
                "unpriced_calls": unpriced, **limits,
                "left_usd": round(max(0.0, budget - spent), 6) if budget > 0 else None,
                "own_usd": round(own, 6),
                "own_left_usd": round(max(0.0, budget - limits["reserve"] - spent), 6) if budget > 0 else None,
                "calls_left": max(0, calls_cap - unpriced) if calls_cap > 0 else None,
                "by_source": sorted(by_source.values(), key=lambda entry: -entry["cost_usd"])}

    def week(self) -> list:
        """The last seven days, today first."""
        start = Date.today()
        return [self.day((start - timedelta(days=offset)).isoformat()) for offset in range(7)]

    def span(self, name: str = "today", *, start: str | None = None, end: str | None = None) -> dict:
        """What was spent over a stretch of days: `name` today, week (the last 7 days) or
        month (the last 30), ending today; or the days `start` to `end` (YYYY-MM-DD, both
        included). {range, start, end, cost_usd, plan_usd, seconds, calls: {total, priced,
        plan, unpriced}, days, by_source, by_model}:

            calls      priced: with a price (reported or estimated); plan: under a plan the
                       user has (no charge; plan_usd is what they would cost at list
                       prices); unpriced: a model on this computer, or no price known
            days       one row for every day of the stretch, oldest first; empty when no
                       call was made in it
            by_source  what the calls were for, largest first: {kind, id, title, whose,
                       cost_usd, plan_usd, calls, seconds, last}
            by_model   {model, basis, cost_usd, plan_usd, calls}"""
        if start is None and end is None:
            if name not in RANGES:
                raise ValueError(f"a range is one of {', '.join(RANGES)}")
            last = Date.today()
            first = last - timedelta(days=RANGES[name] - 1)
        else:
            try:
                last = Date.fromisoformat(end) if end else Date.today()
                first = Date.fromisoformat(start) if start else last
            except ValueError:
                raise ValueError("a day is written YYYY-MM-DD") from None
            if first > last or (last - first).days > 3660:
                raise ValueError("the first day is not after the last, and a stretch is at most ten years")
            name = "days"
        total = {"cost_usd": 0.0, "plan_usd": 0.0, "seconds": 0.0}
        calls = {"total": 0, "priced": 0, "plan": 0, "unpriced": 0}
        days, sources, models = [], {}, {}
        for offset in range((last - first).days + 1):
            day = (first + timedelta(days=offset)).isoformat()
            row = {"date": day, "cost_usd": 0.0, "plan_usd": 0.0, "calls": 0, "priced_calls": 0, "plan_calls": 0,
                   "unpriced_calls": 0}
            for call in self.calls(day):
                kind = "priced" if call.get("priced") else "plan" if call.get("basis") == "plan" else "unpriced"
                spent, listed = float(call.get("cost_usd") or 0), float(call.get("plan_usd") or 0)
                seconds = float(call.get("seconds") or 0)
                row["cost_usd"] += spent
                row["plan_usd"] += listed
                row["calls"] += 1
                row[f"{kind}_calls"] += 1
                calls["total"] += 1
                calls[kind] += 1
                total["cost_usd"] += spent
                total["plan_usd"] += listed
                total["seconds"] += seconds
                source = call.get("source") or {}
                entry = sources.setdefault(f"{source.get('kind', 'other')}:{source.get('id', '')}",
                                           {"kind": source.get("kind", "other"), "id": source.get("id", ""),
                                            "title": source.get("title"), "whose": source.get("whose"),
                                            "cost_usd": 0.0, "plan_usd": 0.0, "calls": 0, "seconds": 0.0, "last": 0})
                entry["cost_usd"] += spent
                entry["plan_usd"] += listed
                entry["calls"] += 1
                entry["seconds"] += seconds
                entry["last"] = max(entry["last"], float(call.get("time") or 0))
                if source.get("title"):
                    entry["title"] = source["title"]
                model = models.setdefault((call.get("model"), call.get("basis")),
                                          {"model": call.get("model"), "basis": call.get("basis"), "cost_usd": 0.0,
                                           "plan_usd": 0.0, "calls": 0})
                model["cost_usd"] += spent
                model["plan_usd"] += listed
                model["calls"] += 1
            days.append(row)

        def rounded(rows):
            for row in rows:
                for key in ("cost_usd", "plan_usd"):
                    row[key] = round(row[key], 6)
                if "seconds" in row:
                    row["seconds"] = round(row["seconds"], 1)
            return rows

        return {"range": name, "start": first.isoformat(), "end": last.isoformat(),
                "cost_usd": round(total["cost_usd"], 6), "plan_usd": round(total["plan_usd"], 6),
                "seconds": round(total["seconds"], 1), "calls": calls,
                "days": rounded(days) if calls["total"] else [],
                "by_source": rounded(sorted(sources.values(), key=lambda row: (-row["cost_usd"], -row["calls"]))),
                "by_model": rounded(sorted(models.values(), key=lambda row: (-row["cost_usd"], -row["calls"])))}

    def refusal(self, chat=None, whose="owner") -> str | None:
        """Why a model call (of `chat`; None: any) may not start now, or None. A priced call
        needs budget left (when daily_budget > 0), a call without a price calls left (when
        daily_calls > 0): a model on this computer keeps working when the day's dollars are
        gone. A call for its own work (`whose` "own") may not use the reserve kept for the
        owner. Zero means no limit is set."""
        spent = self.day()
        kinds = (True, False) if chat is None else (priced(chat),)
        budget = spent["daily_budget"]
        calls_cap = spent["daily_calls"]
        if whose == "own" and True in kinds and budget > 0 and spent["reserve"] and spent["cost_usd"] >= budget - spent["reserve"]:
            return (f"the part of today's budget for its own work is used up ({usd(spent['cost_usd'])} of "
                    f"{usd(budget)}, {usd(spent['reserve'])} kept for the owner): asleep until 0:00")
        if True in kinds and budget > 0 and spent["cost_usd"] >= budget:
            return (f"today's budget of {usd(budget)} is used up ({usd(spent['cost_usd'])} spent); "
                    f"no model call until 0:00, or raise today's budget")
        if False in kinds and calls_cap > 0 and spent["unpriced_calls"] >= calls_cap:
            return (f"today's {calls_cap} model calls without a price are used up; no such call until "
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
        row = {"time": time.time(), "model": getattr(chat, "model", None), **priced, "source": source or {},
               **({"seconds": round(float(usage["seconds"]), 2)} if (usage or {}).get("seconds") is not None else {})}
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
    over_budget = spent.get("daily_budget", 0) > 0 and spent["cost_usd"] >= spent["daily_budget"]
    over_calls = spent.get("daily_calls", 0) > 0 and spent["unpriced_calls"] >= spent["daily_calls"]
    if over_budget or over_calls:
        text += " (limit reached)"
    return text


def span_lines(span: dict, titles: dict | None = None) -> list[str]:
    """A stretch of spending (Account.span) as lines for /usage and harness usage: the total,
    the calls by kind, the days, and what it was for. `titles`: {source id: what to call it}."""
    calls = span["calls"]
    if not calls["total"]:
        return [f"No model calls from {span['start']} to {span['end']}."]
    lines = [f"{span['start']} to {span['end']}: {usd(span['cost_usd'])} in {calls['total']} calls"
             + f" ({calls['priced']} priced" + (f", {calls['plan']} under your plan" if calls["plan"] else "")
             + (f", {calls['unpriced']} without a price" if calls["unpriced"] else "") + ")"]
    if span["plan_usd"]:
        lines.append(f"  under your plan: {calls['plan']} calls, {usd(span['plan_usd'])} at list prices (not charged)")
    if len(span["days"]) > 1:
        top = max(day["cost_usd"] for day in span["days"]) or 1.0
        for day in span["days"]:
            bar = "█" * round(20 * day["cost_usd"] / top)
            lines.append(f"  {day['date']}  {usd(day['cost_usd']):>10}  {day['calls']:>4} calls  {bar}")
    for source in span["by_source"]:
        name = (titles or {}).get(source["id"]) or source.get("title") or source.get("id") or source["kind"]
        lines.append(f"  {source['kind']:<8} {str(name)[:44]:<44} {usd(source['cost_usd']):>10}  {source['calls']} calls")
    return lines


def report(account: Account, *, week: bool = False) -> list[str]:
    """Lines for /usage and the-harness usage: today's spending and limits, by conversation
    and task, and with `week` the last seven days."""
    spent = account.day()
    budget_text = (f"{usd(spent['cost_usd'])} of {usd(spent['daily_budget'])}"
                   + (" (raised for today)" if spent["raised"] else "")
                   if spent["daily_budget"] > 0 else f"{usd(spent['cost_usd'])} (no daily limit)")
    calls_text = (f"{spent['unpriced_calls']} of {spent['daily_calls']} calls without a price"
                  if spent["daily_calls"] > 0 else f"{spent['unpriced_calls']} calls without a price (no limit)")
    lines = [f"Today ({spent['date']}): {budget_text}; {spent['priced_calls']} priced calls, {calls_text}"]
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
