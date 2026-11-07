"""The editable model list shared by the assistant's frontends."""

import json

from . import providers, settings
from .core import atomic_write, sha256
from .core.procs import file_lock
from harness.runtime.decision.model import valid_effort


def entry(raw):
    provider = raw.get("provider")
    model = str(raw.get("model") or "").strip()
    if isinstance(provider, str) and provider in providers.PROVIDERS:
        route = providers.check(raw)
    elif isinstance(provider, str) and provider.startswith(("acp:", "terminal:", "cloud:")):
        if provider.startswith("cloud:") and (model or raw.get("efforts")):
            raise ValueError("choose the cloud adapter's configured model")
        if provider.startswith("acp:") and not model:
            raise ValueError("choose the adapter's model")
        route = {"provider": provider, "model": model, "base_url": None}
    else:
        raise ValueError("choose a model provider")
    efforts = raw.get("efforts", [])
    enabled = raw.get("enabled", True)
    if not isinstance(efforts, list) or any(not level or not valid_effort(level) for level in efforts):
        raise ValueError("efforts must be a list of provider option IDs")
    if type(enabled) is not bool:
        raise ValueError("enabled must be true or false")
    return {**route, "id": sha256(route), "name": str(raw.get("name") or model or provider),
            "enabled": enabled, "efforts": list(dict.fromkeys(efforts))}


def _read(path):
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, list) or any(not isinstance(row, dict) for row in raw):
                raise ValueError("expected an array of model entries")
            rows = [entry(row) for row in raw]
            if len({row["id"] for row in rows}) != len(rows):
                raise ValueError("duplicate model entries")
            return rows
        except (ValueError, TypeError) as error:
            raise ValueError(f"{path}: {error}") from error
    config = settings.read(path.parent)
    chosen = providers.load(path.parent)
    configured = (config.get("model") or {}).get("provider") or providers.ready(path.parent)["ready"]
    legacy = str((config.get("taptab") or {}).get("models") or "").split(",")
    return [entry({**chosen, "model": model}) for model in dict.fromkeys(
        [chosen["model"]] * bool(configured) + [value.strip() for value in legacy if value.strip()]) if model]


def models(directory, change=None):
    path = directory / "models.json"
    if change is None and path.exists():
        return _read(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path.with_suffix(".lock")):
        rows = _read(path)
        if change is not None:
            action = change.get("action")
            if action == "save":
                row = entry(change)
                previous = change.get("id")
                if previous and previous != row["id"] and any(item["id"] == row["id"] for item in rows):
                    raise ValueError("this model is already saved")
                existing = next((index for index, item in enumerate(rows)
                                 if item["id"] == (previous or row["id"])), len(rows))
                rows[existing:existing + 1] = [row]
            else:
                index = next((i for i, row in enumerate(rows) if row["id"] == change.get("id")), None)
                if index is None:
                    raise ValueError("model entry no longer exists")
                if action == "enable" and type(change.get("enabled")) is bool:
                    rows[index]["enabled"] = change["enabled"]
                elif action == "remove":
                    del rows[index]
                else:
                    raise ValueError("unknown model list operation")
        atomic_write(path, json.dumps([{key: value for key, value in row.items() if key != "id"} for row in rows],
                                      indent=2, ensure_ascii=False) + "\n")
    return rows


def select(directory, identifier=None, *, native=False):
    """Resolve a model for a new run. An ambiguous name must be qualified with the provider or entry ID."""
    rows = [row for row in models(directory) if row["enabled"]
            and (not native or row["provider"] in providers.PROVIDERS)]
    if identifier is None:
        chosen = providers.load(directory)
        return next((row for row in rows if all(row[key] == chosen[key] for key in chosen)), rows[0] if rows else None)
    matches = [row for row in rows if identifier in (row["id"], row["model"], row["provider"] + "/" + row["model"])]
    if len(matches) != 1:
        raise ValueError(f"choose one enabled model from {directory / 'models.json'}; "
                         "use provider/model if the name is ambiguous, or the entry ID for multiple endpoints")
    return matches[0]
