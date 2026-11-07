"""Project recorded task context and library holdings for replay and frontends."""
import json
from pathlib import Path
from harness.runtime.task.context import WorkingMemory, entry
from harness.runtime.learning.library import LAYERS, SECTIONS, Library, Revision, executable, selects
from harness.runtime.learning.views import _library_entry, library_entries, overlay


COLUMNS = ("scope", "kind", "name", "where", "evidence", "source", "seen", "text")


def from_records(records) -> WorkingMemory:
    """A run's working memory as its trace's `world` records left it."""
    memory = WorkingMemory(clock=lambda: 0.0)
    for record in records:
        if (record.get("event") != "world" or "id" not in record
                or record.get("action") not in ("remember", "seen", "carried", "forget")):
            continue
        if record.get("action") == "forget":
            memory.items.pop(record["id"], None)
            continue
        seen_at = record.get("time") or 0.0
        item = memory.items.setdefault(record["id"], {"first": seen_at})
        # Before runtime/task/context.py, the world memory's records said pos, note and by.
        item.update({{"by": "source", "pos": "where", "note": "text"}.get(key, key): value for key, value in record.items()
                     if key not in ("event", "seq", "time", "action", "who", "source", "view")}, last=seen_at)
        item.setdefault("text", "")
        for key in ("where", "name", "space", "confidence", "source", "seen", "version"):
            item.setdefault(key, None)
    return memory


def rows(run=None, library=None, *, at=None) -> list[dict]:
    """What every frontend shows of memory, in the one format: a run's working memory (from
    its trace; `run` a run directory) and a library's entries (`library` a directory; by
    default the run's own, as its trace recorded it), each with its "cells" (COLUMNS)."""
    from harness.core.episodes import read_records
    from harness.runtime.learning.learner import Learner

    found = []
    if run is not None:
        run = Path(run)
        def history(path):
            return [record for record in read_records(path)
                    if at is None or (record.get("time") or 0) <= at]

        main = history(run) if (run / "events.jsonl").is_file() else []
        children = {trace.parent: history(trace.parent) for trace in sorted(run.glob("agents/**/events.jsonl"))}
        records = sorted([*main, *(record for trace in children.values() for record in trace)],
                         key=lambda record: record.get("time") or 0)
        found += [dict(entry(item), cells=None) for item in from_records(records).items.values()]
        if library is None:
            return _cells(list({item["id"]: item for item in [*found, *_started_with(run, main, children)]}.values()))
    if library is not None and Path(library).is_dir():
        store = Library(library)
        captured = store.capture(include_unselected=True)
        found.extend(library_entries(captured, sections=SECTIONS))
        for key, row in captured.index.items():
            if not key.startswith("candidates/") or not row.get("revision"):
                continue
            item = Revision.read(store.directory, row["revision"])
            candidate = _library_entry(item.key, item.source.decode("utf-8"), row, captured.version,
                                       evidence="proposed", sha256=item.source_sha256)
            found.append({**candidate, "id": key, "revision": item.revision, "status": "pending"})
    return _cells(found)


def _library_table(run) -> dict:
    try:
        manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        return manifest["config"]["runtime"]["library"] or {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _started_with(run, records, children) -> list[dict]:
    """Historical holdings. Older manifests can name entries but cannot supply their text."""
    table = _library_table(run)
    library = table.get("manifest") or {}
    opened = next((r for r in records if r.get("event") == "library" and r.get("action") == "opened"), None)
    if opened is not None:
        found = {item["id"]: {**entry(item, "library"), **item} for item in opened["entries"]}
    else:
        found = {}
        for section, names in (library.get("entries") or {}).items():
            for name in names:
                key = f"{section}/{name}"
                found[key] = _library_entry(key, "", {}, library.get("version"), evidence="unrecorded")
    versioned = opened is not None and opened.get("revision_schema") == 1
    for record in records:
        if record.get("event") == "library" and record.get("action") == "activated" and "entries" in record:
            found.update({item["id"]: item for item in record["entries"]})
    if table.get("learn", "on" if library.get("learns") else "off") != "on":
        return list(found.values())
    directory = library.get("directory")
    layers = library.get("layers", table.get("layers", LAYERS))
    load = library.get("load", table.get("load", "proposed"))
    sections = (opened or {}).get("sections", SECTIONS)
    since = (opened or {}).get("time") or 0
    related = (record for child, trace in children.items()
               if directory and (_library_table(child).get("manifest") or {}).get("directory") == directory
               for record in trace if record.get("event") == "library")
    # Keep the latest known revision even below the floor, in case it earns a qualifying grade.
    latest = dict(found)
    for record in sorted([*records, *related], key=lambda record: record.get("time") or 0):
        if record.get("event") != "library" or (record.get("time") or 0) < since:
            continue
        if record.get("action") == "memory":
            item = record["holding"]
            found = {row["id"]: row for row in overlay(found.values(), [item], layers, load)}
            continue
        section = record.get("section") or str(record.get("key", "")).partition("/")[0]
        if section not in sections or versioned and executable(section + "/"):
            continue
        evidence, digest = record.get("evidence"), record.get("sha256")
        selected = selects(section, evidence, layers, load)
        if record.get("action") == "admitted" and record.get("admitted"):
            key = f"{record['section']}/{record['name']}"
            item = record.get("holding") or _library_entry(key, "", {"origin": record.get("origin")},
                                                           record.get("version"), evidence=evidence)
            latest[key] = {**item, "sha256": digest}
            if selected:
                found.pop(key, None)
                found[key] = latest[key]
        elif record.get("action") == "promoted" and digest:
            key = record["key"]
            item = latest.get(key)
            if item is None or item.get("sha256") != digest:
                continue
            history = [*(item.get("history") or ()), *(record.get("history") or ())[-1:]]
            latest[key] = {**item, "evidence": evidence, "history": history}
            if selected:
                found[key] = latest[key]
            elif found.get(key, {}).get("sha256") == digest:
                del found[key]
    return list(found.values())


def _cells(found) -> list[dict]:
    for row in found:
        where, given = row["where"], row.get("cells") or [row["evidence"], row["name"] or ""]
        rate = row.get("rate")
        row["cells"] = [row["scope"], row["kind"], given[1], " ".join(f"{v:g}" for v in where)
                        if isinstance(where, list) else where or "", given[0], row["source"] or "",
                        str(row["seen"] or "") + (f" ({rate:.0%} ok)" if rate is not None else ""),
                        (row["text"] or "")[:80]]
    return found
