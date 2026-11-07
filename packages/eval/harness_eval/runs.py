"""Read suite metadata and episode outcomes without resolving or executing an agent.

A summary records a terminal outcome, including unsuccessful outcomes. A directory
without a summary is incomplete. Liveness comes from OUTPUT/.running, the processes
running the suite (written by run_suite), checked only on the host that wrote them.
"""

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shlex
import socket

from harness.sdk import episodes, pid_alive

# OUTPUT/.running: {"schema_version": 1, "processes": [{host, pid, started, boot_id}]}, one
# entry per `harness run` process sharing the output; each removes its own when it ends.
RUNNING = ".running"


def _object(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _pairs(tasks, seeds):
    if not isinstance(tasks, list) or not isinstance(seeds, list):
        raise ValueError("suite tasks and seeds must be lists")
    return [{"task": task, "seed": seed} for task in tasks for seed in seeds]


def _pair(entry):
    if not isinstance(entry, dict):
        raise ValueError("suite episodes must contain task/seed objects")
    task, seed = entry.get("task"), entry.get("seed")
    if not isinstance(task, str) or not task or task in (".", "..") or "/" in task or "\\" in task:
        raise ValueError(f"invalid suite task: {task!r}")
    if type(seed) is not int:
        raise ValueError(f"invalid suite seed: {seed!r}")
    return task, seed


def _utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="microseconds")


def _boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def running_entry():
    """This process's entry in OUTPUT/.running."""
    return {"host": socket.gethostname(), "pid": os.getpid(),
            "started": _utc(datetime.now(timezone.utc).timestamp()), "boot_id": _boot_id()}


def running_processes(directory):
    """The entries of DIRECTORY/.running; [] when there is none. Raises ValueError when it is malformed."""
    path = Path(directory) / RUNNING
    if not path.exists():
        return []
    processes = _object(path).get("processes")
    if not isinstance(processes, list) or not all(isinstance(entry, dict) for entry in processes):
        raise ValueError(f"{path}: processes must be a list of objects")
    return processes


def _alive(entry, boot_id):
    """Whether a process of this host still runs. A different boot means it ended with the
    previous boot (its pid may now be another process's)."""
    if entry.get("boot_id") and boot_id and entry["boot_id"] != boot_id:
        return False
    pid = entry.get("pid")
    if type(pid) is not int or pid <= 0:
        return False
    return pid_alive(pid)


def liveness(directory):
    """running: a process in .running still runs on this host. stale: every process in it was
    of this host and is gone (killed or crashed without removing its entry). unknown: one ran
    on another host, which cannot be checked from here, or there is no evidence either way.
    stopped: no process is registered and a run ended here (outcome.json)."""
    directory = Path(directory)
    try:
        processes = running_processes(directory)
    except (OSError, ValueError):
        return "unknown"
    if not processes:
        return "stopped" if (directory / "outcome.json").exists() else "unknown"
    host, boot_id = socket.gethostname(), _boot_id()
    local = [entry for entry in processes if entry.get("host") == host]
    if any(_alive(entry, boot_id) for entry in local):
        return "running"
    return "stale" if len(local) == len(processes) else "unknown"


def last_outcome(directory):
    """The end of the latest finished `harness run` in DIRECTORY (outcome.json), or None."""
    path = Path(directory) / "outcome.json"
    try:
        result = _object(path)
    except (OSError, ValueError):
        return None
    return {key: result.get(key) for key in ("exit_code", "result", "ended")}


def inspect_suite(directory):
    """Read one suite's selection, outcomes, replacement layouts and evidence time.

    Legacy task/seed unions are candidates, not proof of requested pairs. Missing
    legacy candidates are unknown. Costs cover unique current summaries only, not
    archived attempts or calls that never wrote a summary. Liveness: see liveness().
    The result is `harness inspect --json` (schema_version: its format, documented in
    reference/cli-json); next_steps.resume is `harness run --resume` once suite.json
    recorded the command line (`invocation`).
    """
    directory = Path(directory).resolve()
    metadata = directory / "suite.json"
    suite = _object(metadata)
    execution = suite.get("execution") or {}
    if not isinstance(execution, dict):
        raise ValueError(f"{metadata}: execution must be a JSON object")
    entries = {}
    legacy = suite.get("legacy_selection")
    if legacy is not None and not isinstance(legacy, dict):
        raise ValueError(f"{metadata}: legacy selection must be a JSON object")
    if "episodes" not in suite:
        legacy = {"tasks": suite.get("tasks", []), "seeds": suite.get("seeds", [])}
    if not isinstance(suite.get("episodes", []), list):
        raise ValueError(f"{metadata}: episodes must be a list")
    if legacy:
        for entry in _pairs(legacy.get("tasks", []), legacy.get("seeds", [])):
            entries[_pair(entry)] = False
    for entry in suite.get("episodes", []):
        entries[_pair(entry)] = True
    warnings = []
    if legacy:
        warnings.append("Legacy task/seed unions do not establish exact requested coverage; "
                        "absent legacy candidates are unknown.")
    modified = metadata.stat().st_mtime
    rows, counted = [], set()
    cost, cost_missing = 0.0, 0
    mappings = {}
    for task, _ in entries:
        if task in mappings:
            continue
        maps = []
        try:
            for name in ("unstable", "displaced"):
                path = directory / task / f"{name}.json"
                mapping = _object(path) if path.exists() else {}
                maps.append({int(key): value for key, value in mapping.items()})
                if any(type(value) is not int for value in mapping.values()):
                    raise ValueError(f"{path}: replacement layouts must be integers")
                if path.exists():
                    modified = max(modified, path.stat().st_mtime)
            for start in maps[0]:
                actual, seen = start, set()
                while actual in maps[0]:
                    if actual in seen:
                        raise ValueError("cycle in unstable-layout replacements")
                    seen.add(actual)
                    actual = maps[0][actual]
            mappings[task] = maps
        except (OSError, ValueError) as error:
            mappings[task] = str(error)
            warnings.append(f"{task}: cannot read replacement metadata: {error}")
    for (task, seed), requested in entries.items():
        row = {"task": task, "seed": seed, "requested": requested, "actual_seed": seed,
               "state": "missing" if requested else "unknown", "status": None, "success": None,
               "cost_usd": None, "error": None}
        rows.append(row)
        maps = mappings[task]
        if isinstance(maps, str):
            row.update(state="unreadable", error=maps)
            continue
        replaced, displaced = maps
        if seed in {*replaced.values(), *displaced.values()} and seed not in displaced:
            row.update(actual_seed=None, reason="layout already used as a replacement; awaiting a new layout")
            continue
        actual, seen = displaced.get(seed, seed), set()
        while actual in replaced and actual not in seen:
            seen.add(actual)
            actual = replaced[actual]
        if actual in seen:
            row.update(state="unreadable", error="cycle in unstable-layout replacements")
            warnings.append(f"{task} seed {seed}: cycle in unstable-layout replacements")
            continue
        row["actual_seed"] = actual
        episode = directory / task / f"seed-{actual}"
        row["directory"] = str(episode)
        for name in ("events.jsonl", "manifest.json", "summary.json"):
            path = episode / name
            try:
                if path.exists():
                    modified = max(modified, path.stat().st_mtime)
            except OSError as error:
                warnings.append(f"{path}: {error}")
        summary = episode / "summary.json"
        if not summary.exists():
            if episode.exists():
                row["state"] = "incomplete"
            continue
        try:
            result = _object(summary)
            status = result.get("status")
            if not isinstance(status, str) or not status:
                raise ValueError("summary has no outcome status")
            if result.get("task", task) != task or result.get("seed", actual) != actual:
                raise ValueError("summary task/seed differs from its directory")
            row.update(state="error" if episodes.ending(result) == "error" else "completed", status=status,
                       success=result.get("success"), error=result.get("error"))
            amount = result.get("cost_usd")
            valid_cost = type(amount) in (int, float) and math.isfinite(amount) and amount >= 0
            if valid_cost:
                row["cost_usd"] = amount
            if episode not in counted:
                counted.add(episode)
                if valid_cost:
                    cost += amount
                else:
                    cost_missing += 1
        except (OSError, ValueError) as error:
            row.update(state="unreadable", error=str(error))
            warnings.append(f"{summary}: {error}")
    counts = {state: sum(row["state"] == state for row in rows)
              for state in ("completed", "error", "incomplete", "missing", "unknown", "unreadable")}
    try:
        processes = running_processes(directory)
    except (OSError, ValueError) as error:
        processes = []
        warnings.append(f"{directory / RUNNING}: {error}")
    invocation = suite.get("invocation")
    resume = (shlex.join(["harness", "run", "--resume", str(directory)]) if isinstance(invocation, dict) else
              "Use the original run flags with --dry-run first; this suite.json does not record its command line.")
    return {
        "schema_version": 1, "suite_schema_version": suite.get("schema_version", 1),
        "output": str(directory), "observed_at": _utc(datetime.now(timezone.utc).timestamp()),
        "evidence_updated": _utc(modified), "liveness": liveness(directory), "processes": processes,
        "last_outcome": last_outcome(directory),
        "agent": suite.get("agent"), "agent_version": suite.get("agent_version") or suite.get("version"),
        "agent_id": execution.get("agent_id", suite.get("agent_id")),
        "bench": execution.get("bench"), "layout_source": execution.get("layout_source", suite.get("layout_source")),
        "layout_pack_seed": execution.get("layout_pack_seed", suite.get("layout_pack_seed")),
        "execution": execution, "invocation": invocation, "experiment": suite.get("run"),
        "deploy": suite.get("deploy"),
        "selection_exact": not bool(legacy), "requested_episodes": sum(entries.values()),
        "candidate_episodes": len(entries), "counts": counts, "episodes": rows,
        "recorded_cost_usd": cost, "summaries_without_cost": cost_missing,
        "cost_scope": "unique current summaries; excludes archived attempts and unrecorded calls",
        "legacy_unchecked_fields": suite.get("legacy_unchecked_fields", []), "warnings": warnings,
        "next_steps": {"report": shlex.join(["harness", "report", str(directory)]),
                       "view": shlex.join(["harness", "view", str(directory)]),
                       "resume": resume},
    }


def list_suites(root, limit=20):
    """Find suites under a directory, newest inspected evidence first.

    Unreadable suites remain visible with their path and error rather than disappearing
    from the inventory. Neither discovery nor inspection loads model configuration. A row
    is inspect_suite's result without its episodes, execution, invocation and format
    version (`harness runs --json` gives the version once, for the list).
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"No runs directory {root}")
    if limit < 1:
        raise ValueError("--limit must be positive")
    rows = []
    for path in root.rglob("suite.json"):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            result = inspect_suite(path.parent)
            rows.append({key: value for key, value in result.items()
                         if key not in ("episodes", "execution", "invocation", "schema_version")})
        except (OSError, ValueError, TypeError, AttributeError) as error:
            rows.append({"output": str(path.parent), "error": str(error),
                         "evidence_updated": _utc(path.stat().st_mtime)})
    rows.sort(key=lambda row: (row["evidence_updated"], row["output"]), reverse=True)
    return rows[:limit]
