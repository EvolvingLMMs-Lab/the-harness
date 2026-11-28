"""Where the package keeps things, and its settings.

    install_dir()   $HARNESS_HOME/minebot: what is installed for the body on first use
                    (Node and the body's libraries); never part of the package itself
    data_dir()      $HARNESS_DATA/minebot: runs/, the routine store of a body started by
                    hand (store/), frames/, logs/ and state/ (the records of what was started)

The settings are the section [minebot] of the app's settings (settings.toml of this package
says what each is). The password of the server's command port is never a setting:
$MINEBOT_RCON_PASSWORD.
"""

import json
import os
from pathlib import Path
import shlex
import tomllib

from harness.sdk import Settings, data, home


PACKAGE = Path(__file__).resolve().parents[1]
BODY = PACKAGE / "body"
WINDOW = PACKAGE / "window"
SECTION = "minebot"
RCON_PASSWORD = "MINEBOT_RCON_PASSWORD"


def install_dir() -> Path:
    return home() / "minebot"


def data_dir() -> Path:
    return data() / "minebot"


def schema() -> dict:
    """The rows of settings.toml: {key: {default, kind, bounds or choices, about}}."""
    with (PACKAGE / "settings.toml").open("rb") as handle:
        return {key: row for key, row in tomllib.load(handle)[SECTION].items() if isinstance(row, dict)}


def _typed(key: str, row: dict, value):
    """`value` as the setting `key` takes it; ValueError says what it takes."""
    kind = row.get("kind", "text")
    if kind == "int":
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{SECTION}.{key} is a whole number, not {value!r}") from None
        low, high = row["bounds"]
        if not low <= number <= high:
            raise ValueError(f"{SECTION}.{key} is between {low} and {high}")
        return number
    if kind == "choice":
        if value not in row["choices"]:
            raise ValueError(f"{SECTION}.{key} is one of {', '.join(row['choices'])}, not {value!r}")
        return value
    return str(value if value is not None else "").strip()


def settings(overrides=None, *, store=None) -> dict:
    """The package's settings as they are now, `overrides` ({key: value}, a run's own) over them.
    `store`: the settings of a session host (default: those of the user's data folder)."""
    rows = schema()
    kept = ((store or Settings(data())).get().get(SECTION) or {})
    values = {key: _typed(key, row, kept.get(key, row["default"])) for key, row in rows.items()}
    for key, value in (overrides or {}).items():
        if key not in rows:
            raise ValueError(f"no setting {SECTION}.{key}; the settings are {', '.join(sorted(rows))}")
        values[key] = _typed(key, rows[key], value)
    return values


def command(text) -> list[str] | None:
    """A command a setting gives, as its arguments: a JSON list, or a line as a shell
    writes it (quote a path that has spaces; write / in paths). Empty: None."""
    if isinstance(text, (list, tuple)):
        return [str(part) for part in text] or None
    text = str(text or "").strip()
    if not text:
        return None
    if text.startswith("["):
        parts = json.loads(text)
        if not isinstance(parts, list) or not all(isinstance(part, str) for part in parts):
            raise ValueError("a command given as JSON is a list of strings")
        return parts or None
    return shlex.split(text) or None


def rcon(values: dict) -> dict:
    """The environment of the server's command port, where the body was given one."""
    password = os.environ.get(RCON_PASSWORD, "")
    if not values.get("rcon_port") or not password:
        return {}
    return {"MC_RCON_PORT": str(values["rcon_port"]), "MC_RCON_PASSWORD": password}
