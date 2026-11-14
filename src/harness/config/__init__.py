"""Configuration: TOML files that include others, with paths relative to the file
that names them, and `--set key.path=value` overrides.

Layers, later ones winning (configs/README.md):

    code defaults            the values the code uses when a file names none
    default.toml             the agent: prompt, skills, services, runtime, budget, and
                             its default model (other agent files may include it)
    models/<name>.toml       model roles: main, vlm, pointer, verifier (an API model or a
                             service), plus the runtime settings a model needs
    experiments/<name>.toml  the agent with a model on a benchmark: tasks, seeds,
                             layouts, budgets, worker options, overrides
    --model, --set           the command line

and configs/deploy/<machine>.toml says where services run (the local-models package). Keys
live in environment variables, never in these files.
"""

import copy
import json
import os
from pathlib import Path
import re
import tomllib

from ..embodiments import KINDS


def read_toml(path: Path) -> dict:
    """One TOML file as a tree, without following its includes."""
    with Path(path).open("rb") as handle:
        return tomllib.load(handle)


def deep_merge(base: dict, override: dict) -> dict:
    """`override` on top of `base`: tables merge key by key, anything else replaces."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


# Keys whose values are paths, as dotted paths into a file's tree. They are made
# absolute against the directory of the file that sets them, before files merge.
PATH_KEYS = ("prompt", "runtime.task_descriptions", "runtime.library.path", "agent",
             "overrides.agent.prompt", "overrides.agent.runtime.task_descriptions",
             "overrides.agent.runtime.library.path",
             # The agent's table of each embodiment kind.
             *(f"{prefix}{kind}.runtime.{key}" for prefix in ("", "overrides.agent.") for kind in KINDS
               for key in ("task_descriptions", "library.path")))


def _absolutize(tree: dict, base: Path) -> dict:
    tree = copy.deepcopy(tree)
    for dotted in PATH_KEYS:
        *parents, last = dotted.split(".")
        node = tree
        for part in parents:
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
        if not isinstance(node, dict) or last not in node:
            continue
        node[last] = _absolute(node[last], base)
    return tree


def _absolute(value, base: Path):
    """A path value made absolute: a string, a list of them, or a table of either (a
    prompt by embodiment kind). A path under the harness's home ($HARNESS_HOME/...) stays
    as it is (runtime/learning/learner.py library_path)."""
    from ..paths import locate

    if isinstance(value, str):
        return value if value.startswith(("$HARNESS_HOME/", "${HARNESS_HOME}/")) else \
            str(locate((base / value).resolve()).resolve())
    if isinstance(value, list):
        return [str(locate((base / item).resolve()).resolve()) if isinstance(item, str) else item for item in value]
    if isinstance(value, dict):
        return {key: _absolute(item, base) for key, item in value.items()}
    return value


def load_layered(path, _seen=()) -> dict:
    """A TOML file with its `include = [...]` files merged under it (in order; the
    file's own keys win), path keys made absolute."""
    from ..paths import locate

    # A path under the repository that moved into a package is found there (paths.locate).
    path = locate(Path(path)).resolve()
    if path in _seen:
        raise ValueError(f"Include cycle through {path}")
    data = read_toml(path)
    includes = data.pop("include", [])
    includes = [includes] if isinstance(includes, str) else list(includes)
    merged = {}
    for include in includes:
        from ..paths import locate

        merged = deep_merge(merged, load_layered(locate(path.parent / include), (*_seen, path)))
    return deep_merge(merged, _absolutize(data, path.parent))


def parse_set(text: str) -> tuple[list[str], object]:
    """`a.b.c=value` as (["a", "b", "c"], value); the value is read as TOML (a number,
    true, "text", [1, 2], {k = 1}) and as a plain string when it is not valid TOML."""
    if "=" not in text:
        raise ValueError(f"--set needs key.path=value, got {text!r}")
    key, raw = text.split("=", 1)
    try:
        value = tomllib.loads(f"value = {raw}")["value"]
    except tomllib.TOMLDecodeError:
        value = raw
    return [part for part in key.strip().split(".") if part], value


def apply_sets(tree: dict, sets) -> dict:
    """A copy of `tree` with `--set` items written into it, in order. An item is a
    `key.path=value` string or a parsed (keys, value) pair; missing tables on the path
    are created, and a path through a value that is not a table is an error."""
    tree = copy.deepcopy(tree)
    for item in sets or ():
        keys, value = parse_set(item) if isinstance(item, str) else item
        node = tree
        for key in keys[:-1]:
            node = node.setdefault(key, {})
            if not isinstance(node, dict):
                raise ValueError(f"--set {'.'.join(keys)}: {key} is not a table")
        node[keys[-1]] = value
    return tree


BASE_URL_ENV = "OPENROUTER_BASE_URL"
RELAY_URL_ENV = "OPENROUTER_RELAY_URL"
RELAY_TOKEN_ENV = "OPENROUTER_RELAY_TOKEN"


def route_openrouter(tree, environ=os.environ):
    """Point every OpenRouter model in a harness at another base URL, when asked.

    Applies to each model config with `backend = "openrouter"` and no `base_url` (so
    the openrouter.ai default) or an openrouter.ai `base_url`:

    - OPENROUTER_BASE_URL (e.g. https://my-proxy.example/api/v1) replaces the URL;
      the key is still read from the model's `api_key_env` (OPENROUTER_API_KEY).
    - OPENROUTER_RELAY_URL replaces the URL with scripts/openrouter_relay.py and
      reads the key from OPENROUTER_RELAY_TOKEN.

    Setting both is an error. Models elsewhere (self-hosted servers, other providers)
    are left alone. The rewritten configs go into the run snapshot, so a run records
    the URL it called.
    """
    base = environ.get(BASE_URL_ENV, "").strip()
    relay = environ.get(RELAY_URL_ENV, "").strip()
    if base and relay:
        raise ValueError(f"Set {BASE_URL_ENV} or {RELAY_URL_ENV}, not both")
    if not (base or relay):
        return tree
    if isinstance(tree, list):
        return [route_openrouter(item, environ) for item in tree]
    if not isinstance(tree, dict):
        return tree
    tree = {key: route_openrouter(value, environ) for key, value in tree.items()}
    base_url = tree.get("base_url")
    direct = isinstance(base_url, str) and "openrouter.ai" in base_url
    if tree.get("backend") == "openrouter" and (base_url is None or direct):
        tree["base_url"] = relay or base
        if relay:
            tree["api_key_env"] = RELAY_TOKEN_ENV
    return tree


def dumps(data: dict, comment: str = "") -> str:
    """A tree as a TOML file: values, then tables, lists of tables as [[...]]; None is
    left out (TOML has no null). The one TOML writer: the user's configuration, package
    lists and locks, model and option files."""
    lines = [f"# {comment}"] if comment else []
    _table(lines, [], data)
    return "\n".join(lines).strip("\n") + "\n"


def toml_key(name) -> str:
    """A key as TOML: bare when it can be, quoted otherwise."""
    name = str(name)
    return name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else toml_value(name)


def toml_value(value) -> str:
    """A value as TOML (inline tables and arrays, None left out of them)."""
    if value is None:
        raise TypeError("TOML has no null")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(item) for item in value if item is not None) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{toml_key(key)} = {toml_value(item)}" for key, item in value.items()
                                if item is not None) + " }"
    # JSON's escapes are TOML's; DEL is a control character TOML wants escaped too.
    return json.dumps(str(value), ensure_ascii=False).replace("\x7f", "\\u007f")


def _is_tables(item) -> bool:
    return isinstance(item, list) and bool(item) and all(isinstance(part, dict) for part in item)


def _table(lines, where, table) -> None:
    values = {k: v for k, v in table.items() if v is not None and not isinstance(v, dict) and not _is_tables(v)}
    tables = {k: v for k, v in table.items() if isinstance(v, dict)}
    arrays = {k: v for k, v in table.items() if _is_tables(v)}
    if where and (values or not (tables or arrays)):
        lines += ["", f"[{'.'.join(toml_key(part) for part in where)}]"]
    lines += [f"{toml_key(k)} = {toml_value(v)}" for k, v in values.items()]
    for k, v in tables.items():
        _table(lines, [*where, k], v)
    for k, items in arrays.items():
        for item in items:
            lines += ["", f"[[{'.'.join(toml_key(part) for part in [*where, k])}]]"]
            lines += [f"{toml_key(name)} = {toml_value(value)}" for name, value in item.items() if value is not None]
