"""The suites under a runs directory, read the way harness runs and
harness inspect read them (harness_eval/runs.py); standard library only, so it is tested
on its own. Reads, never writes."""

import os
from pathlib import Path

from harness.sdk import episodes, format as formats
from harness_eval.runs import inspect_suite, list_suites

# The states of an episode (inspect_suite) as a cell of the tasks x seeds grid: its mark
# and its style. A completed episode is marked by its success.
STATES = ("completed", "error", "incomplete", "missing", "unknown", "unreadable")
MARKS = {"success": ("✓", "green"), "failure": ("✗", "yellow"), "error": ("!", "bold red"),
         "incomplete": ("…", "cyan"), "missing": ("·", "dim"), "unknown": ("?", "dim"),
         "unreadable": ("‼", "magenta")}


def when(text) -> str:
    """An ISO time as local time (formats.timestamp); '' when there is none."""
    return formats.timestamp(text)


def suites(root: Path, limit=1000) -> list[dict]:
    """The suites under `root` as the first view lists them, newest evidence first: each
    harness runs row with its name (relative to root) and the cells of its line."""
    root = Path(root).resolve()
    rows = []
    for row in list_suites(root, limit):
        output = Path(row["output"])
        name = output.relative_to(root).as_posix() if output != root and root in output.parents else output.name
        counts = row.get("counts") or {}
        cost = row.get("recorded_cost_usd")
        agent = " ".join(str(part) for part in (row.get("agent"), row.get("agent_version")) if part)
        rows.append({**row, "name": name, "cells": [
            name, agent, row.get("liveness", "unknown"),
            *(str(counts.get(state, "")) for state in ("completed", "error", "incomplete", "missing")),
            formats.cost(cost), when(row.get("evidence_updated")),
            row.get("error", "")]})
    return rows


SUITE_COLUMNS = ["suite", "agent", "liveness", "completed", "error", "incomplete", "missing", "cost", "updated",
                 "problem"]


def matches(row: dict, text: str) -> bool:
    """Whether a suite's line holds `text` (the / filter), ignoring case."""
    return not text or text.lower() in " ".join(row["cells"]).lower()


def suite(directory: Path) -> dict:
    """One suite (harness inspect) with its grid: tasks in order of first appearance,
    seeds in order, and the episode of each (task, seed)."""
    result = inspect_suite(directory)
    tasks, seeds, cells = [], [], {}
    for row in result["episodes"]:
        if row["task"] not in tasks:
            tasks.append(row["task"])
        if row["seed"] not in seeds:
            seeds.append(row["seed"])
        cells[(row["task"], row["seed"])] = row
    return {**result, "tasks": tasks, "seeds": sorted(seeds), "cells": cells}


def mark(row: dict | None) -> tuple[str, str]:
    """The mark and style of an episode's cell ('' for a pair the suite does not hold)."""
    if row is None:
        return "", ""
    state = row["state"]
    if state == "completed":
        state = "success" if row.get("success") else "failure"
    return MARKS[state]


def header(result: dict) -> list[str]:
    """The lines above a suite's grid: agent and configuration, liveness, last run, counts,
    cost, and how to resume it (harness inspect's next step)."""
    def fields(*pairs):
        return "  ".join(f"{name} {value}" for name, value in pairs if value not in (None, ""))

    counts = result["counts"]
    last = result.get("last_outcome")
    processes = "".join(f"  pid {process.get('pid')} on {process.get('host')}"
                        for process in result.get("processes") or [])
    lines = [result["output"],
             fields(("agent", " ".join(str(part) for part in (result.get("agent"), result.get("agent_version"))
                                       if part)), ("identity", result.get("agent_id"))),
             fields(("bench", result.get("bench")), ("layouts", result.get("layout_source")),
                    ("pack", result.get("layout_pack_seed")), ("experiment", result.get("experiment"))),
             f"liveness {result['liveness']}{processes}"
             + (f"  last run: {last.get('result')} (exit {last.get('exit_code')}) at {when(last.get('ended'))}"
                if last else ""),
             "  ".join(f"{state} {counts[state]}" for state in STATES if counts.get(state))
             + (f"  of {result['requested_episodes']} requested" if result.get("selection_exact")
                else f"  of {result['candidate_episodes']} candidates (legacy selection, not confirmed)")
             + f"  cost {formats.cost(result['recorded_cost_usd'])}  updated {when(result.get('evidence_updated'))}",
             f"resume: {(result.get('next_steps') or {}).get('resume', '')}"]
    return [line for line in lines if line]


def details(row: dict | None) -> list[str]:
    """The side panel of the selected cell: the episode's state, success, error or
    reason, cost and steps."""
    if row is None:
        return ["no episode"]
    done = episodes.summary(row.get("directory")) if row.get("directory") else {}
    spent = episodes.usage(done) if done else None
    ended = episodes.ending(done)
    lines = [f"{row['task']}", f"seed {row['seed']}" + (f" (layout {row['actual_seed']})"
                                                        if row.get("actual_seed") not in (None, row["seed"]) else ""),
             f"state    {row['state']}", f"status   {row.get('status')}",
             f"ended    {episodes.ENDING_WORDS.get(ended, ended or '')}", f"success  {row.get('success')}",
             f"cost     {formats.cost(spent['cost_usd'] if spent else row.get('cost_usd'))}",
             f"steps    {done.get('steps', '')}", f"calls    {spent['model_calls'] if spent else ''}"]
    strategy = done.get("strategy") or {}
    if strategy.get("strategy"):
        lines.append(f"strategy {strategy['strategy']} {strategy.get('policy') or ''}".rstrip())
    problem = row.get("error") or row.get("reason")
    if problem:
        lines += ["", str(problem)]
    if row.get("directory"):
        lines += ["", row["directory"]]
    return lines


def log_tail(path: Path, lines=200, chunk=65536) -> list[str]:
    """The last `lines` lines of a file (suite.log), [] when there is none."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - chunk))
            data = handle.read()
    except OSError:
        return []
    text = data.decode("utf-8", "replace").splitlines()
    return text[-lines:] if size <= chunk else text[1:][-lines:]


def latest(result: dict) -> Path | None:
    """The episode of a suite whose trace changed last (the one a running suite is
    writing), or None."""
    newest, found = -1.0, None
    for row in result["episodes"]:
        trace = Path(row["directory"]) / "events.jsonl" if row.get("directory") else None
        try:
            modified = trace.stat().st_mtime if trace else -1.0
        except OSError:
            continue
        if modified > newest:
            newest, found = modified, trace.parent
    return found


def view_page(root: Path, directory: Path, name="view.html") -> tuple[Path, str]:
    """The harness view page of an episode (or a suite's index.html) and its address
    when `harness view ROOT` serves ROOT."""
    page = Path(directory) / name
    try:
        relative = page.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        relative = page.name
    return page, f"http://127.0.0.1:8000/{relative}"
