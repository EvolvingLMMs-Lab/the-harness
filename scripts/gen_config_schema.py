"""The JSON schema of an experiment file, for editors: completion and descriptions of its
keys, from the same dictionaries the validators and the configuration reference use.

    python scripts/gen_config_schema.py           # write docs/public/schema/experiment.json
    python scripts/gen_config_schema.py --check   # exit 1 when the file is not current

An editor that reads JSON schemas for TOML (Taplo, Even Better TOML) takes it from a first
line `#:schema https://harness.lmms-lab.com/docs/schema/experiment.json`. The schema
describes; it never forbids a key, since packages add their own."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]
OUT = ROOT / "docs" / "public" / "schema" / "experiment.json"
URL = "https://harness.lmms-lab.com/docs/schema/experiment.json"
BUDGET = {
    "max_model_calls": "model calls per episode",
    "max_wall_seconds": "seconds per episode, checked before each model call",
    "max_cost_usd": "dollars per episode",
    "max_total_cost_usd": "dollars for the whole run: no new episode once spent",
}


def _table(keys: dict, extra: dict | None = None) -> dict:
    properties = {name: {"description": str(text)} for name, text in sorted(keys.items())}
    properties.update(extra or {})
    return {"type": "object", "properties": properties, "additionalProperties": True}


def schema() -> dict:
    from harness.config.agent import AGENT_KEYS, ROLE_DOCS, RUNTIME_KEYS
    from harness_eval.experiments import EXPERIMENT_KEYS
    from harness.runtime.decision.model import MODEL_KEYS

    runtime = _table(RUNTIME_KEYS)
    role = _table(MODEL_KEYS)
    model = _table({name: text for name, text in ROLE_DOCS.items()},
                   {name: {**role, "description": str(text)} for name, text in ROLE_DOCS.items()})
    agent = _table(AGENT_KEYS, {"runtime": {**runtime, "description": str(AGENT_KEYS["runtime"])}})
    overrides = {"type": "object", "properties": {"agent": {**agent, "description": "changes of the agent for this experiment"},
                                                  "model": {**model, "description": "changes of the model roles"}},
                 "additionalProperties": True, "description": str(EXPERIMENT_KEYS["overrides"])}
    budget = {**_table({}, {name: {"type": "number", "description": text} for name, text in BUDGET.items()}),
              "description": str(EXPERIMENT_KEYS["budget"])}
    top = _table(EXPERIMENT_KEYS, {"budget": budget, "overrides": overrides,
                                   "include": {"description": "other files merged under this one, in order",
                                               "type": ["string", "array"]}})
    return {"$schema": "http://json-schema.org/draft-07/schema#", "$id": URL,
            "title": "The Harness experiment", **top}


def text() -> str:
    return json.dumps(schema(), indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the schema file is not current")
    args = parser.parse_args()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text():
            print(f"{OUT.relative_to(ROOT)} is not current: run python scripts/gen_config_schema.py")
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text(), encoding="utf-8", newline="\n")
    print(OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
