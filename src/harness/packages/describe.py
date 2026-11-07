"""One package as every frontend shows it: describe() of an installed row, a registry row,
info() or install()'s found gives its columns, its facts [{key, label, value}] and its lines."""

from ..core.format import clip

# The columns of a list of installed packages and of a list of the registry's.
COLUMNS = {"installed": ("name", "version", "scope", "on", "source", "provides", "problem"),
           "available": ("name", "version", "installed", "provides", "summary")}
# The labels of the facts whose key does not say them.
LABELS = {"depends": "depends on", "services": "services it can start", "environment": "installs an environment for",
          "skill": "installs for the skill", "code": "contains Python code", "platforms": "runs on"}


def describe(found: dict, width: int = 0) -> dict:
    """`found` as text; `width` cuts the provides column."""
    versions, installed, listed = found.get("versions") or [], found.get("installed"), "enabled" in found
    version = found.get("version") or (versions[-1]["version"] if versions else "")
    provides = "; ".join(f"{kind.replace('_', ' ')}: {', '.join(map(str, names))}"
                         for kind, names in (found.get("provides") or {}).items() if names)
    facts = [{"key": key, "label": LABELS.get(key, key), "value": str(value)} for key, value in [
        ("installed", f"{installed['version']} ({installed.get('scope', 'user')}) from "  # info()'s
                      f"{str(installed.get('source') or '').replace('registry:', 'registry ', 1)}: {installed.get('path', '')}"
         if isinstance(installed, dict) else installed),
        ("problem", found.get("problem")), ("provides", provides),
        ("depends", ", ".join(f"{name} {spec}".rstrip() for name, spec in (found.get("depends") or {}).items())),
        ("services", ", ".join(found.get("services") or [])),
        *(("environment", f"{environment['for']}: {', '.join(environment.get('requirements') or []) or '-'}")
          for environment in found.get("environments") or []),
        *(("skill", f"{skill}: {', '.join(wanted)}") for skill, wanted in (found.get("skill_requirements") or {}).items()),
        ("commands", ", ".join(found.get("commands") or [])), ("code", "yes" if found.get("code") else ""),
        ("platforms", ", ".join(found.get("platforms") or [])),
        ("versions", ", ".join(row["version"] + ("" if row.get("fits", True) else " (not for this harness)") for row in versions)),
        ("registry", versions and found.get("registry")),
        ("problem", found.get("registry_problem") and f"registry: {found['registry_problem']}")] if value]
    title = f"{found['name']} {version}".rstrip() + (f": {found['summary']}" if found.get("summary") else "")
    return {"name": found["name"], "version": version, "summary": found.get("summary") or "",
            "scope": found.get("scope", "user") if listed else "", "on": ("on" if found.get("enabled") else "off") if listed else "",
            "source": str(found.get("source") or "").replace("registry:", "registry ", 1) + (" (linked)" if found.get("link") else ""),
            "installed": installed.get("version", "") if isinstance(installed, dict) else installed or "",
            "provides": clip(provides, width) if width else provides, "problem": found.get("problem") or "",
            "facts": facts, "lines": [title, *(f"{item['label']}: {item['value']}" for item in facts)]}


def rows(found: list[dict], columns: str = "installed", width: int = 0) -> list[dict]:
    """A list of packages as the rows of a table of COLUMNS[columns]."""
    return [{column: described[column] for column in COLUMNS[columns]} for described in (describe(item, width) for item in found)]
