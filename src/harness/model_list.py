"""The editable model list shared by the assistant's frontends.

An entry may say whether its model reads images (`images`: true or false). The provider's
catalog gives it where it says (providers.catalog); the user may change it in the list.
Without it the model is taken to read them. A model that reads none is sent none
(runtime/task/run.py): it works from the state and what the environment's calls return as
text, and a view it looks at is described by the vision model when one is set
(the setting model.vision)."""

import json
import os

from . import providers, settings
from .core import atomic_write, sha256
from .core.procs import file_lock
from harness.runtime.decision.model import valid_effort


class SelectionError(ValueError):
    """The selected route is unavailable; management can open without starting a new task."""


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
    images = raw.get("images")
    if images is not None and type(images) is not bool:
        raise ValueError("images must be true or false (whether the model reads images)")
    return {**route, "id": sha256(route), "name": str(raw.get("name") or model or provider),
            "enabled": enabled, "efforts": list(dict.fromkeys(efforts)),
            **({"images": images} if images is not None else {})}


def reads_images(directory, choice: dict) -> bool:
    """Whether the model of `choice` ({provider, model, base_url}) reads images, as its
    entry of the list says; True without an entry or without the flag."""
    for row in models(directory):
        if all(row.get(key) == choice.get(key) for key in ("provider", "model", "base_url")):
            return row.get("images") is not False
    return True


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
            raise SelectionError(f"{path}: {error}") from error
    config = settings.read(path.parent)
    chosen = providers.load(path.parent)
    provider = providers.PROVIDERS[chosen["provider"]]
    if provider.key_env:
        settings.Credentials(path.parent, [provider.key_env]).load()
    configured = (config.get("model") or {}).get("provider") or not providers.requires_key(provider.id) or \
        bool(os.environ.get(provider.key_env))
    legacy = str((config.get("taptab") or {}).get("models") or "").split(",")
    return [entry({**chosen, "model": model}) for model in dict.fromkeys(
        [chosen["model"]] * bool(configured) + [value.strip() for value in legacy if value.strip()]) if model]


def models(directory, change=None):
    path = directory / "models.json"
    if change is None:
        rows = _read(path)
        # An unsuccessful first-run readiness check is not an explicitly empty list.
        # Leave it absent so exporting a key can still initialize the default later.
        if path.exists() or not rows:
            return rows
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
            and (not native or row["provider"] in providers.PROVIDERS or providers.is_agent(row["provider"]))]
    if identifier is None:
        chosen = providers.load(directory)
        matched = next((row for row in rows if all(row[key] == chosen[key] for key in chosen)), None)
        if matched is not None or not rows:
            return matched
        if (settings.read(directory).get("model") or {}).get("provider"):
            raise SelectionError(f"{directory / 'config.toml'} selects {chosen['provider']}/{chosen['model']}, "
                             f"which is not enabled in {directory / 'models.json'}; correct the configuration "
                             "or model list, or select an enabled model with --model")
        return rows[0]
    matches = [row for row in rows if identifier in (row["id"], row["model"], row["provider"] + "/" + row["model"])]
    if len(matches) != 1:
        raise ValueError(f"choose one enabled model from {directory / 'models.json'}; "
                         "use provider/model if the name is ambiguous, or the entry ID for multiple endpoints")
    return matches[0]
