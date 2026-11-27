"""Skill sources: where an identity's skills are taken from, besides what it learns itself.

A skill is a folder with a SKILL.md (the format Agent Skills, OpenClaw, Hermes and Claude Code
share), so skills written elsewhere can be brought in. A source is named the way harness
install and harness agent adopt name where something comes from:

    a folder or a SKILL.md on this computer       ~/skills/expenses, ./SKILL.md
    a repository                                  github:OWNER/REPO[#FOLDER], git:URL[@REF][#FOLDER],
                                                  https://github.com/OWNER/REPO[/tree/REF/FOLDER]
    an archive or one SKILL.md at an address      https://example.com/skills.zip, https://example.com/SKILL.md

It holds one skill (a SKILL.md at its top) or several (every folder in it with a SKILL.md).
What comes from a source is someone else's: each skill enters as instructions at evidence
"proposed", and a program it brings waits (program.proposed.py) until its own test passes
here, as an adopted identity's skills do. The identity keeps its sources in
skill-sources.json: where each is from, when it was added and read, and the skills it brought.

    listing   the sources with their skills; and the shared libraries ($HARNESS_HOME/libraries,
              what harness install brought as a library), read only
    add       read the source and take its skills in
    remove    forget the source; its skills go with it unless they are kept
    test      read the source without taking anything: the skills it holds
    update    read it again and take in the skills that are new

The host route /api/agent/skill_sources is skill_sources(); harness skills and
harness.sdk.Agent do the same."""
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from harness.sdk import Problem

from .learning import parse_skill_md
from .state import read, save

FILE = "skill-sources.json"
# How deep in a source a SKILL.md is looked for, and how many skills one source may bring.
DEPTH, MOST = 5, 200
SKIPPED = {".git", "node_modules", "__pycache__", ".venv"}


def _kept(identity) -> list:
    return [dict(row) for row in read(identity.directory / FILE, [])]


def _slug(name) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(name).lower()).strip("_")[:60] or "skill"


def _spec(text: str) -> str:
    """The source as harness.packages.sources parses it (github:OWNER/REPO[#FOLDER] is its git form)."""
    github = re.match(r"^github:([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?(?:#(.*))?$", text)
    if github:
        return f"git:github.com/{github.group(1)}/{github.group(2)}" + (f"#{github.group(3)}" if github.group(3) else "")
    return text


def _fetched(text: str, into: Path, log) -> tuple:
    """(the folder holding what the source `text` has, its kind: path, git or url)."""
    from harness.packages import sources

    text = str(text or "").strip()
    if not text:
        raise Problem("name where the skills come from", "a folder, a SKILL.md, github:OWNER/REPO, or an address",
                      code="no_source")
    local = Path(os.path.expanduser(text))
    try:
        if local.is_file() and local.suffix.lower() == ".md":
            folder = into / "one"
            folder.mkdir(parents=True)
            shutil.copyfile(local, folder / "SKILL.md")
            return folder, "path"
        if re.match(r"^https?://", text) and text.split("?")[0].lower().endswith(".md"):
            from harness.sdk import open_url

            log(f"downloading {text}")
            with open_url(text, timeout=60) as response:
                data = response.read(1_000_001)
            if len(data) > 1_000_000:
                raise ValueError("larger than 1 MB")
            folder = into / "one"
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_bytes(data)
            return folder, "url"
        parsed = sources.parse(_spec(text))
        if parsed.kind == "registry":
            raise ValueError("this names a package of the registry, not a place skills are kept")
        folder, _ = sources.fetch(parsed, into, log=log)
        return Path(folder), parsed.kind
    except Problem:
        raise
    except (ValueError, OSError) as error:
        raise Problem(f"{text} could not be read: {' '.join(str(error).split())[:300]}",
                      "give a folder or a SKILL.md here, github:OWNER/REPO[#FOLDER], or the address of an archive "
                      "or of a SKILL.md", code="source_unreadable") from None


def _skills_in(folder: Path) -> list:
    """The skills a source holds: [(folder, {name, description, body})], itself when it has a
    SKILL.md at its top, else every folder in it that has one."""
    found = []
    tops = [folder] if (folder / "SKILL.md").is_file() else []
    if not tops:
        for root, folders, files in os.walk(folder):
            folders[:] = sorted(name for name in folders if name not in SKIPPED)
            if len(Path(root).relative_to(folder).parts) >= DEPTH:
                folders[:] = []
            if "SKILL.md" in files:
                tops.append(Path(root))
                folders[:] = []  # a skill's own folders are its files
    for top in tops[:MOST]:
        try:
            found.append((top, parse_skill_md((top / "SKILL.md").read_text(encoding="utf-8", errors="replace"))))
        except ValueError:
            continue
    return found


def test(life, source, log=None) -> dict:
    """Read a source without taking anything in: {from, kind, skills: [{name, description,
    program}], seconds}. `source`: where it is, or the id of one that was added."""
    log = log or (lambda message: None)
    text = next((row["from"] for row in _kept(life.identity) if row["id"] == source), str(source or ""))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="harness-skills-") as temporary:
        folder, kind = _fetched(text, Path(temporary), log)
        skills = [{"name": parsed["name"], "description": parsed["description"],
                   "program": (top / "program.py").is_file()} for top, parsed in _skills_in(folder)]
    if not skills:
        raise Problem(f"{text} holds no skill", "a skill is a folder with a SKILL.md that names it (name: in its "
                      "front matter)", code="no_skills")
    return {"from": text, "kind": kind, "skills": skills, "seconds": round(time.monotonic() - started, 1)}


def _take(life, top: Path, parsed: dict, source: dict) -> str:
    """One skill of a source into the identity: its folder, its program set aside, its origin."""
    name = _slug(parsed["name"])
    target = life.learning.skills_root / name
    shutil.copytree(top, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*SKIPPED))
    waits = (target / "program.py").is_file()
    if waits:
        os.replace(target / "program.py", target / "program.proposed.py")
    save(target / "origin.json", {"source": "installed", "from": source["from"], "skill_source": source["id"],
                                  "time": life.clock(), "evidence": "proposed",
                                  **({"waits": "its own test here"} if waits else {})})
    life.chats.record("main", "learned", kind="skill", name=name, evidence="proposed",
                      note=f"from the skill source {source['from']}")
    return name


def _read_in(life, row: dict, log) -> tuple:
    """Read the source of `row` and take in the skills the identity does not have: (the
    names taken, the names left because a skill of that name is there already)."""
    have = {skill["name"] for skill in life.learning.skills()}
    taken, left = [], []
    with tempfile.TemporaryDirectory(prefix="harness-skills-") as temporary:
        folder, kind = _fetched(row["from"], Path(temporary), log)
        row["kind"] = kind
        found = _skills_in(folder)
        if not found:
            raise Problem(f"{row['from']} holds no skill", "a skill is a folder with a SKILL.md that names it "
                          "(name: in its front matter)", code="no_skills")
        for top, parsed in found:
            name = _slug(parsed["name"])
            if name in have:
                left.append(name)  # what it has, its own or another source's, is not overwritten
                continue
            taken.append(_take(life, top, parsed, row))
            have.add(name)
    row["checked"] = life.clock()
    row["skills"] = sorted({*row.get("skills", []), *taken})
    return taken, [name for name in left if name not in row["skills"]]


def add(life, source, log=None) -> dict:
    """Add a source and take its skills in, each at evidence proposed: {id, from, kind, added:
    [names], skipped: [names that are there already]}."""
    log = log or (lambda message: None)
    text = str(source or "").strip()
    rows = _kept(life.identity)
    if any(row["from"] == text for row in rows):
        raise Problem(f"{text} is a skill source already", "harness skills update reads it again", code="source_exists")
    taken = {row["id"] for row in rows}
    base = _slug(Path(text.split("#")[-1].rstrip("/")).stem or "source")[:24]
    identifier = base if base not in taken else next(f"{base}_{n}" for n in range(2, 1000) if f"{base}_{n}" not in taken)
    row = {"id": identifier, "from": text, "added": life.clock(), "skills": []}
    added, skipped = _read_in(life, row, log)
    save(life.identity.directory / FILE, [*rows, row])
    return {"id": identifier, "from": text, "kind": row["kind"], "added": added, "skipped": skipped}


def update(life, identifier=None, log=None) -> dict:
    """Read the sources again (or the one named) and take in the skills that are new:
    {updated: {id: [new names]}}."""
    log = log or (lambda message: None)
    rows = _kept(life.identity)
    if identifier and not any(row["id"] == identifier for row in rows):
        raise Problem(f"no skill source {identifier!r}", "harness skills sources lists them", code="no_source")
    updated = {}
    for row in rows:
        if identifier in (None, row["id"]):
            updated[row["id"]] = _read_in(life, row, log)[0]
    save(life.identity.directory / FILE, rows)
    return {"updated": updated}


def remove(life, identifier, keep=False) -> dict:
    """Forget a source. The skills it brought are removed with it unless `keep`."""
    rows = _kept(life.identity)
    row = next((row for row in rows if row["id"] == identifier), None)
    if row is None:
        raise Problem(f"no skill source {identifier!r}", "harness skills sources lists them", code="no_source")
    removed = []
    if not keep:
        for name in row.get("skills", []):
            origin = read(life.learning.skills_root / name / "origin.json", {}, recover=True)
            if origin.get("skill_source") == identifier:
                life.learning.delete(name)
                removed.append(name)
    save(life.identity.directory / FILE, [other for other in rows if other["id"] != identifier])
    return {"removed": identifier, "skills_removed": removed, "skills_kept": [] if not keep else row.get("skills", [])}


def listing(life) -> dict:
    """{sources: [{id, from, kind, added, checked, skills: [{name, evidence, there}]}],
    shared: [{name, package, entries, read_only}]}: the sources added to this identity, and
    the shared libraries."""
    from harness.runtime.learning.learner import libraries

    have = {skill["name"]: skill for skill in life.learning.skills()}
    rows = []
    for row in _kept(life.identity):
        rows.append({"id": row["id"], "from": row["from"], "kind": row.get("kind"), "added": row.get("added"),
                     "checked": row.get("checked"),
                     "skills": [{"name": name, "evidence": (have.get(name) or {}).get("evidence"),
                                 "there": name in have} for name in row.get("skills", [])]})
    try:
        shared = [{"name": row.get("name"), "package": row.get("package") or "", "entries": row.get("entries"),
                   "folder": row.get("directory"), "read_only": True} for row in libraries()]
    except (OSError, ValueError):
        shared = []
    return {"sources": rows, "shared": shared}


def skill_sources(server, body):
    """GET: the identity's skill sources and the shared libraries. POST {action: add | remove |
    test | update, from | id, keep}: the sources after it, and `result`."""
    from .host import _life, _one

    life = _life(server, body)
    action = _one(body.get("action"))
    result = None
    if action == "add":
        result = add(life, body.get("from"))
    elif action == "remove":
        result = remove(life, body.get("id"), keep=bool(body.get("keep")))
    elif action == "test":
        result = test(life, body.get("id") or body.get("from"))
    elif action == "update":
        result = update(life, body.get("id"))
    elif action:
        raise Problem(f"no action {action!r} for skill sources", "the actions are add, remove, test and update",
                      code="no_action")
    return {"identity": life.identity.id, **listing(life), **({"result": result} if result is not None else {})}
