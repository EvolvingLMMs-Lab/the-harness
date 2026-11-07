"""Import old hints and unattributed skill statistics into the library's memory format."""

import hashlib
import json
from pathlib import Path


MIGRATION = "@experience_imported"


def hint_key(topic, name):
    return f"memory/experience_{_id([topic, name])}.md"


def _id(fields):
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]


def legacy_entries(directory, index):
    def read(name):
        path = Path(directory) / "experience" / name
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            return {}

    for topic, hints in read("hints.json").items():
        for name, hint in hints.items():
            yield {"id": hint_key(topic, name), "kind": f"hint:{topic}", "name": name,
                   "text": json.dumps(hint["value"], ensure_ascii=False), "seen": hint.get("seen"),
                   "source": "legacy"}
    for skill, stats in read("skills.json").items():
        yield {"id": f"memory/historical_use_{_id(skill)}.md", "kind": "historical_use", "name": skill,
               "text": json.dumps(stats, ensure_ascii=False), "seen": stats.get("runs"), "source": "legacy",
               "summary": "Historical results, revision unknown"}

    for key, row in index.items():
        if not key.startswith(("skills/", "reactive/")):
            continue
        old = [item["previous_uses"] for item in row.get("history", []) if item.get("previous_uses")]
        if row.get("uses"):
            old.append(row["uses"])
        for number, stats in enumerate(old):
            yield {"id": f"memory/historical_use_{_id([key, number, stats])}.md",
                   "kind": "historical_use", "name": Path(key).stem,
                   "text": json.dumps(stats, ensure_ascii=False),
                   "seen": stats.get("ok", 0) + stats.get("failed", 0),
                   "source": "legacy library index", "summary": "Historical results, revision unknown"}
