"""Fold observed outcomes into the explicitly bound library."""
from pathlib import Path


USES = ("learn", "on", "off")


def fold_uses(learner, run) -> int:
    """Fold each run's versioned outcomes into the library exactly once."""
    from harness.core.episodes import read_records

    uses = {}
    active = {}
    for record in read_records(Path(run)):
        if record.get("event") == "library" and record.get("action") == "activated":
            active = record.get("revisions") or {}
        if record.get("testing"):
            continue
        if record.get("event") == "skill_step" and record.get("what") in ("done", "gave up"):
            key, revision = record.get("library_key"), record.get("library_revision")
        elif record.get("event") == "library_use":
            key, revision = record.get("key"), record.get("revision")
        else:
            continue
        if revision and active.get(key) == revision:
            uses.setdefault((key, revision), []).append((bool(record.get("ok")), record.get("reason"),
                                                          record.get("seconds", 0)))
    run_id = str(Path(run).resolve())
    return sum(learner.record_uses(key, results, revision=revision, run=run_id)
               for (key, revision), results in uses.items())
