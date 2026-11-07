"""Compatibility names for old programs. Hints and results use the library's memory."""

import json

from skills.memory import Memory


class Experience:
    def hint(self, kind, key):
        rows = Memory._memory(self, "recall", kind=f"hint:{kind}", k=0)
        return next((json.loads(row["text"]) for row in rows if row["name"] == str(key)), None)

    def keep_hint(self, kind, key, value):
        kind, key = f"hint:{kind}", str(key)
        if value is None:
            rows = Memory._memory(self, "recall", kind=kind, k=0)
            return any(Memory._memory(self, "forget", id=row["id"]) for row in rows if row["name"] == key)
        text = json.dumps(value, ensure_ascii=False)
        settings = (getattr(self, "library_given", None) or {}).get("settings") or {}
        return Memory._memory(self, "remember", kind=kind, name=key, text=text, keep=settings.get("learn") == "on")

    def experience(self, skill=None):
        rows = Memory._memory(self, "recall", kind="historical_use", k=0)
        found = {row["name"]: {**json.loads(row["text"]), "revision": None} for row in rows}
        found.update({row["name"]: json.loads(row["text"])
                      for row in Memory._memory(self, "recall", kind="skill_use", k=0)})
        return found if skill is None else found.get(skill)
