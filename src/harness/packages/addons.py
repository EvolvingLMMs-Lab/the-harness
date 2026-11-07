"""Skills in packages, in the two formats a package can hold:

- Harness skills: skills/<name>/ with skill.toml and Python, run in the kernel like the
  built-in ones (runtime/execution/skills.py). Its `requirements` are installed into the skill's
  own .deps folder with the kernel's Python when the package is installed.
- Agent Skills: agent-skills/<name>/ with SKILL.md (name and description in its front
  matter, then instructions), the format of Claude's and OpenAI's skills. The agent is
  told each one's name and description (the prompt's installed section,
  runtime/decision/prompts.py), and reads the rest with read_skill() when a task needs it
  (skills/instructions).

A folder or archive with skills but no package.toml (what the app's "Add a skill" took)
becomes one package per skill (find_skills(), manager.py).
"""

import os
from pathlib import Path
import re
import tomllib


NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def front_matter(text: str) -> dict:
    """The front matter of a SKILL.md (between --- lines): key: value lines, quotes
    stripped, a `>` or `|` value taking the indented lines after it."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data, key, block = {}, None, None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if block is not None and (line.startswith((" ", "\t")) or not line.strip()):
            block.append(line.strip())
            data[key] = " ".join(part for part in block if part)
            continue
        block = None
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if value in (">", "|", ">-", "|-"):
            block = []
            data[key] = ""
        else:
            data[key] = value.strip("\"'")
    return data


def agent_skill(folder: Path) -> dict:
    """An Agent Skill folder: {name, format, summary, code, requirements, folder}."""
    text = (folder / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    meta = front_matter(text)
    name = (meta.get("name") or folder.name).strip().lower()
    if not NAME.match(name):
        raise ValueError(f"{folder.name}: the skill's name {name!r} is not a short lowercase name")
    if not meta.get("description"):
        raise ValueError(f"{name}: SKILL.md has no description in its front matter")
    return {"name": name, "format": "agent", "summary": meta["description"][:500], "code": False,
            "requirements": [], "folder": folder}


def harness_skill(folder: Path) -> dict:
    """A Harness skill folder: {name, format, summary, code, requirements, embodiments, folder}."""
    from harness.runtime.execution.skills import _skill

    skill = _skill(folder / "skill.toml")
    if not NAME.match(skill.name) or "_" in skill.name:
        raise ValueError(f"{skill.name}: not a short lowercase name")
    if not skill.mixin.startswith(f"skills.{skill.name}"):
        raise ValueError(f"{skill.name}: its mixin must be in its own package (skills.{skill.name})")
    with (folder / "skill.toml").open("rb") as handle:
        requirements = list(tomllib.load(handle).get("requirements", []))
    return {"name": skill.name, "format": "harness", "summary": skill.summary, "code": True,
            "requirements": requirements, "embodiments": list(skill.embodiments), "folder": folder}


def find_skills(folder: Path) -> tuple[list[dict], list[str]]:
    """The skills in a folder and its subfolders (a folder with skill.toml or SKILL.md is
    one skill), and the problems of the ones that do not check."""
    found, problems = [], []
    for current, directories, files in os.walk(folder):
        directories[:] = sorted(name for name in directories if not name.startswith(".") and name != "__pycache__")
        current = Path(current)
        try:
            if "skill.toml" in files:
                found.append(harness_skill(current))
            elif "SKILL.md" in files:
                found.append(agent_skill(current))
            else:
                continue
        except (ValueError, OSError, KeyError, tomllib.TOMLDecodeError) as error:
            problems.append(str(error))
        directories[:] = []
    return found, problems


def skills(packages) -> list[dict]:
    """The skills of the enabled packages: [{name, format, summary, code, requirements,
    package, path}] (with a problem when one does not check)."""
    rows = []
    for package in packages.enabled():
        for kind, check in (("skills", harness_skill), ("agent_skills", agent_skill)):
            for name in package.provides.get(kind, ()):
                path = package.folder(kind) / name
                try:
                    row = {key: value for key, value in check(path).items() if key != "folder"}
                except (ValueError, OSError, KeyError, tomllib.TOMLDecodeError) as error:
                    row = {"name": name, "format": "harness" if kind == "skills" else "agent", "summary": "",
                           "code": kind == "skills", "requirements": [], "problem": str(error)}
                rows.append({**row, "package": package.name, "path": str(path)})
    return rows


def agent_skill_options(packages, names) -> dict:
    """The kernel's options for read_skill: {name: {"description", "path"}} of the
    Agent Skills `names`."""
    rows = {row["name"]: row for row in skills(packages) if row["format"] == "agent" and "problem" not in row}
    return {name: {"description": rows[name]["summary"], "path": rows[name]["path"]} for name in names if name in rows}
