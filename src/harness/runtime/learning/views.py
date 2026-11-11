"""Read-only library projections used by task recall and trace viewers."""
import json
from pathlib import Path
from harness.runtime.learning.library import Library, LibrarySnapshot, admitted_by, executable, selects
from harness.runtime.task.context import entry


def _library_entry(key, text, row, version, *, evidence=None, sha256=None):
    section, _, filename = key.partition("/")
    if row.get("memory"):
        return entry({**row["memory"], "id": key, "version": version, "evidence": row["evidence"]}, "library")
    uses = (row.get("uses_by_revision") or {}).get(row.get("revision")) or {}
    revision = row.get("revision")
    history = [grade for grade in row.get("history", [])
               if (grade.get("revision") == revision if revision else grade.get("sha256", sha256) == sha256)]
    unknown = [grade for grade in row.get("history", []) if revision and not grade.get("revision")]
    source = row.get("origin") or "hand"
    if row.get("source") not in (None, "-"):
        source += f" ({row['source']})"
    shown = entry({"id": key, "kind": section, "name": Path(filename).stem, "text": text.strip(),
                  "evidence": evidence or row.get("evidence"), "source": source,
                  "seen": uses.get("ok", 0) + uses.get("failed", 0), "rate": uses.get("rate"),
                  "version": version, "summary": row.get("summary", ""), "history": history}, "library")
    if unknown:
        shown["history_unknown_revision"] = unknown
    if executable(key):
        # What verified this revision of a code entry: "own_test", "fixture", or None.
        shown["admitted_by"] = admitted_by(row)
        if row.get("demoted"):
            shown["demoted"] = row["demoted"]
    return shown


# How a code entry's provenance reads beside its evidence, in every frontend's table.
ADMITTED_BY = {"own_test": "own test", "fixture": "fixture"}


def admitted_entry(outcome, text):
    """The memory text or code preview, with its evidence at admission."""
    if not outcome["admitted"]:
        return None
    if outcome["key"].startswith(("skills/", "reactive/")):
        text = text[:400]
    return _library_entry(outcome["key"], text, outcome["row"], outcome["version_after"], sha256=outcome["sha256"])


def library_entries(library: Library, version=None, *, sections=("memory",)) -> list[dict]:
    """Project one captured library into the same rows used by recall and replay."""
    snapshot = library if isinstance(library, LibrarySnapshot) else library.capture()
    index, version = snapshot.index, version or snapshot.version
    found = []
    for item in snapshot.entries:
        key = item.key
        section = key.split("/", 1)[0]
        if section not in sections:
            continue
        row = index.get(key) or {}
        text = item.source.decode("utf-8")
        shown = _library_entry(key, text[:400] if section in ("skills", "reactive") else text,
                               row, version, evidence=row.get("evidence", "validated"), sha256=item.source_sha256)
        tests = row.get("tests") or []
        evidence = shown["evidence"]
        if tests:
            evidence = f"{evidence} {sum(bool(test.get('ok')) for test in tests)}/{len(tests)}"
        if shown.get("admitted_by"):
            evidence += f" ({ADMITTED_BY.get(shown['admitted_by'], shown['admitted_by'])})"
        name = shown["name"] or ""
        if not selects(section, shown["evidence"], snapshot.layers, snapshot.load):
            name += " (not loaded)"
        shown["cells"] = [evidence, name]
        found.append({**shown, "sha256": item.source_sha256, "revision": item.revision})
    return found


def overlay(startup, admitted, layers, load):
    """Apply only the revisions selected by this reader to its startup memory."""
    if not admitted:
        return startup
    found = {item["id"]: item for item in startup}
    for item in admitted:
        if selects("memory", item["evidence"], layers, load):
            found.pop(item["id"], None)
            if not item.get("forgotten"):
                found[item["id"]] = item
    return list(found.values())


def use_entries(active):
    """Usage statistics as read-only memory rows for the pinned executable revisions."""
    found = []
    for item, row in active.values():
        uses = (row.get("uses_by_revision") or {}).get(item.revision)
        if uses:
            result = {key: value for key, value in uses.items() if key != "runs"}
            result["runs"] = result["ok"] + result["failed"]
            result["revision"] = item.revision
            found.append(entry({"id": f"use:{item.revision}", "kind": "skill_use",
                                "name": Path(item.key).stem, "text": json.dumps(result), "source": "library"},
                               "library"))
    return found
