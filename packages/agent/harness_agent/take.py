"""Taking an identity with you: sharing it, adopting one, backing it up, moving it, and
bringing one over from OpenClaw or Hermes.

Sharing (harness agent share ID --to PLACE) writes a package and sends it the way `harness
share` sends a library (harness.packages.libraries.send: a GitHub repository, private when it
is created, another git remote, an archive in a folder or on a computer reached by scp):

    <name>/
      package.toml            [package] name, version, summary; [provides] identity = ["<name>"]
      identity/<name>/        IDENTITY.md, SOUL.md, avatar.png, reactions.json (no built-in
                              nodes, no counts), skills/<skill>/ (SKILL.md, program.py, test.py)
                              and, with --with-memory, USER.md, MEMORY.md and memory/
      README.md               what it is and the line that adopts it

The private key and credentials never go (agents/.keys/, channels/, places.json, the model
keys); nor do conversations, the calendar, spending or the learning library's records.
Before anything is sent the owner sees every text that becomes public; places of this
computer become names (the home folder becomes ~) and the groups its reactions name
become placeholders (<group>). A credential found in what would go stops the share.
--card writes a Character Card V3 (PNG or JSON) with only the name and the persona.

Adopting (harness agent adopt SOURCE: such a package by its link, folder or archive, or a
character card) makes a new identity: a new id, a new key pair and adopted.json saying where
it came from. Someone else's skills are unknown programs: each goes back to "proposed" and
its program waits (program.proposed.py) until its own test passes here (test_adopted,
harness agent adopt --test). Reactions come disabled; the owner enables them one by one.

Backup (harness agent backup ID) is the whole identity folder, its private key, its memory
and its channel credentials (channels/, places.json), and with --with-keys the model keys,
encrypted with a passphrase. The core and this package use the standard library only, which
has no authenticated cipher, so a backup uses a well-known construction from its primitives:
scrypt (hashlib.scrypt; PBKDF2-HMAC-SHA256 where OpenSSL lacks it) derives 64 bytes from the
passphrase and a random salt, the first half keys HMAC-SHA256 in counter mode as the
keystream (HMAC as a pseudorandom function, a fresh random nonce each backup) and the second
half keys an HMAC-SHA256 tag over the header and the ciphertext (encrypt-then-MAC). The tag
is checked before anything is decrypted, so a wrong passphrase or a changed file is refused
as a whole. Restoring asks for the passphrase and says which channels to log in to again.

Moving: restore on the new computer and log in to its channels there (many channels allow an
account online in one place, so the old computer's connection drops), then retire it on the
old one (harness agent retire ID): retired.json in its folder stops its life here, and
opening it here afterwards says it has moved.

Bringing one over (harness agent import openclaw|hermes): persona, memory and skills of an
OpenClaw workspace or a Hermes profile, never its channel tokens or keys (so one token is
never used by two agents at once); afterwards it suggests stopping the original agent."""
import base64
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import time

from harness.sdk import Problem
from harness.sdk import atomic_write, data
from . import cards, state
from .state import Identity, IdentityError, read, save

# What a share leaves out, as the preview says it.
LEFT_OUT = ("private key", "channel credentials (channels/, places.json)", "model keys", "conversations",
            "calendar", "spending", "learning records")
# Fields of a reaction that name a group or a chat of a channel: they become placeholders.
GROUP_FIELDS = ("group", "group_id", "group_name", "chat", "thing", "channel_group")
# Fields of a reaction that hold a folder of this computer: shared as its last name.
FOLDER_FIELDS = ("folder", "directory", "path", "cwd", "run")
# What of an identity's folder a backup leaves out: what only its running process uses.
NOT_BACKED_UP = (".life.lock", ".identity.lock", ".memory.lock", "life.json", "__pycache__")
BACKUP_MAGIC = b"HARNESS-AGENT-BACKUP\n"
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
PBKDF2_ROUNDS = 600_000


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _id_of(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(text)).strip("-_")[:48] or "agent"


def _free_id(wanted: str, root=None) -> str:
    base = _id_of(wanted)
    if not re.match(r"[A-Za-z0-9]", base):
        base = "agent-" + base
    found, chosen, number = set(state.identities(root)), base, 2
    while chosen in found or (state.agents_root(root) / chosen).exists():
        chosen, number = f"{base}-{number}", number + 1
    return chosen


# -- what goes ---------------------------------------------------------------------------


def _places():
    from harness.packages.libraries import _places as places

    return places()


def _secrets(identity) -> list:
    """Values that must never leave in a share: the private key, the model keys, channel
    tokens and anything a channel's configuration keeps under a secret-looking name."""
    found = []
    key = read(identity.root / ".keys" / f"{identity.id}.json", None)
    if key and key.get("seed"):
        found.append(key["seed"])
        found.append(base64.b64decode(key["seed"]).hex())
    try:
        from harness.sdk import Credentials

        found += [value for value in Credentials(data())._kept().values() if len(value) >= 8]
    except Exception:
        pass
    for name, value in os.environ.items():
        if re.search(r"TOKEN|SECRET|PASSWORD|API_KEY", name) and len(value) >= 8:
            found.append(value)

    def walk(value, key=""):
        if isinstance(value, dict):
            for name, item in value.items():
                walk(item, str(name))
        elif isinstance(value, list):
            for item in value:
                walk(item, key)
        elif isinstance(value, str) and re.search(r"token|secret|password|key|cookie", key, re.I) and len(value) >= 8:
            found.append(value)

    for path in sorted((identity.directory / "channels").rglob("*.json")) if (identity.directory / "channels").is_dir() else ():
        try:
            walk(json.loads(_text(path)))
        except ValueError:
            pass
    walk(read(identity.directory / "places.json", []))
    return sorted(set(found), key=len, reverse=True)


def _known_groups(identity) -> list:
    """Names and numbers of the groups and channel chats this identity is in."""
    found = set()
    channels = identity.directory / "channels"
    for path in sorted(channels.rglob("*.json")) if channels.is_dir() else ():
        try:
            found |= {str(group) for group in (json.loads(_text(path)).get("groups") or {})}
        except (ValueError, AttributeError):
            pass
    for path in (identity.directory / "sessions").glob("*/meta.json") if (identity.directory / "sessions").is_dir() else ():
        meta = read(path, {})
        if meta.get("kind") == "place" and meta.get("thing"):
            thing = str(meta["thing"])
            found.add(thing)
            found.add(thing.split(":", 1)[-1])
            if meta.get("title"):
                found.add(str(meta["title"]))
    return sorted((name for name in found if len(name) >= 2), key=len, reverse=True)


def _placeholders(value, names: dict, known: list, key=None):
    """`value` with every group a reaction names as a placeholder (<group>, <group 2>...)."""
    def placeholder(text):
        text = str(text)
        if text.startswith("<") or text in ("main", "*"):
            return text
        kind, _, rest = text.partition(":")
        if rest and kind in ("group", "private"):
            return f"{kind}:{placeholder(rest)}" if kind == "group" else "private:<person>"
        if text not in names:
            names[text] = "<group>" if not names else f"<group {len(names) + 1}>"
        return names[text]

    if isinstance(value, dict):
        return {name: _placeholders(item, names, known, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_placeholders(item, names, known, key) for item in value]
    if key in GROUP_FIELDS and isinstance(value, (str, int)) and not isinstance(value, bool):
        return placeholder(value)
    if isinstance(value, str):
        for name in known:
            if name in value:
                value = value.replace(name, placeholder(name))
    return value


def _scrubbed(value, places, key=None):
    """`value` without this computer's places: a folder field becomes its last name, the
    home folder inside any text ~ (as harness share does)."""
    from harness.packages.libraries import _scrub

    if isinstance(value, dict):
        return {name: _scrubbed(item, places, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_scrubbed(item, places, key) for item in value]
    if isinstance(value, str) and key in FOLDER_FIELDS and (os.path.isabs(value) or re.match(r"^[A-Za-z]:[\\/]", value)):
        return re.split(r"[\\/]", value.rstrip("\\/"))[-1]
    return _scrub(value, places, key)


def skills_of(identity) -> dict:
    """Its skills as they travel: {name: {file: bytes}}, the SKILL.md folders (skills/<name>/)
    with the current program and test of a learned one from its learning library; archived,
    failed and waiting ones stay."""
    from harness.runtime.learning.library import Library
    from .learning import skill_md

    found = {}
    root = identity.directory / "skills"
    for folder in sorted(root.iterdir()) if root.is_dir() else ():
        if not (folder / "SKILL.md").is_file():
            continue
        files = {}
        for path in sorted(folder.rglob("*")):
            relative = path.relative_to(folder).as_posix()
            if path.is_file() and relative not in ("origin.json", "program.proposed.py") and "__pycache__" not in relative:
                files[relative] = path.read_bytes()
        found[folder.name] = files
    library = identity.library
    if (library / "skills").is_dir():
        index = Library(library).index()
        for path in sorted((library / "skills").glob("*.py")):
            row = index.get(f"skills/{path.name}") or {}
            if row.get("forgotten") or row.get("removed") or row.get("evidence") == "failed":
                continue
            files = found.setdefault(path.stem, {})
            files["program.py"] = path.read_bytes()
            test = library / "tests" / path.name
            if test.is_file():
                files["test.py"] = test.read_bytes()
            if "SKILL.md" not in files:
                files["SKILL.md"] = skill_md(path.stem, row.get("summary") or path.stem, "").encode("utf-8")
    return found


def collect(identity, *, with_memory=False) -> dict:
    """What a share of `identity` holds: {"files": {path in identity/<name>/: bytes},
    "replaced": {group: placeholder}, "skills", "reactions", "memory": bool}. Local places
    become names and groups placeholders; a credential among it raises ValueError."""
    places = _places()
    files = {}

    def text(relative, value):
        for place in places:
            value = value.replace(place, "~")
        files[relative] = value.encode("utf-8")

    for name in ("IDENTITY.md", "SOUL.md") + (("USER.md", "MEMORY.md") if with_memory else ()):
        path = identity.directory / name
        if path.is_file():
            text(name, _text(path))
    if (identity.directory / "avatar.png").is_file():
        files["avatar.png"] = (identity.directory / "avatar.png").read_bytes()
    if with_memory and (identity.directory / "memory").is_dir():
        for path in sorted((identity.directory / "memory").glob("*.md")):
            text(f"memory/{path.name}", _text(path))
    skills = skills_of(identity)
    for name, parts in skills.items():
        for relative, raw in parts.items():
            try:
                text(f"skills/{name}/{relative}", raw.decode("utf-8"))
            except UnicodeDecodeError:
                files[f"skills/{name}/{relative}"] = raw
    nodes = [node for node in (read(identity.directory / "reactions.json", {}) or {}).get("nodes", [])
             if node.get("source") != "builtin"]
    replaced = {}
    known = _known_groups(identity)
    shared = [_placeholders(_scrubbed({key: node.get(key) for key in ("name", "about", "when", "do", "under", "source")
                                       if key in node}, places), replaced, known)
              for node in nodes]
    if shared:
        from .reactions import FORMAT as TREE_FORMAT
        text("reactions.json", json.dumps({"format": TREE_FORMAT, "nodes": shared}, ensure_ascii=False, indent=2) + "\n")
    secrets = _secrets(identity)
    for relative, raw in files.items():
        for secret in secrets:
            if secret.encode("utf-8") in raw:
                raise ValueError(f"{relative} holds a credential of this computer: take it out before sharing")
    return {"files": files, "replaced": replaced, "skills": sorted(skills), "reactions": [n["name"] for n in shared],
            "memory": with_memory}


def preview_of(name, found) -> dict:
    """Every piece of text that becomes public ({file, text}), the other files by name, and
    what stays here."""
    texts, other = [], []
    for relative, raw in sorted(found["files"].items()):
        try:
            texts.append({"file": f"identity/{name}/{relative}", "text": raw.decode("utf-8")})
        except UnicodeDecodeError:
            other.append(f"identity/{name}/{relative}")
    return {"texts": texts, "other_files": other, "skills": found["skills"], "reactions": found["reactions"],
            "replaced": {placeholder: "a group" for placeholder in found["replaced"].values()},
            "left_out": (() if found["memory"] else ("memory", "USER.md")) + LEFT_OUT}


def write_package(identity, folder, *, name, version, found, source) -> dict:
    """The package of `found` (collect()) in `folder`: package.toml, identity/<name>/ and a README."""
    from harness.config import dumps
    from harness.packages.manifest import load

    folder = Path(folder)
    target = folder / "identity" / name
    shutil.rmtree(target, ignore_errors=True)
    for relative, raw in found["files"].items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    def count(number, word):
        return f"{number} {word}" + ("" if number == 1 else "s")

    summary = (f"An agent identity, {identity.name}: persona, {count(len(found['skills']), 'skill')}, "
               f"{count(len(found['reactions']), 'reaction')}")
    (folder / "package.toml").write_text(dumps({"package": {"name": name, "version": version, "summary": summary},
                                                "provides": {"identity": [name]}}), encoding="utf-8", newline="\n")
    adopt = f"harness agent adopt {source}"
    readme = folder / "README.md"
    if not readme.is_file() or "<!-- written by harness agent share -->" in _text(readme):
        readme.write_text("\n".join([
            "<!-- written by harness agent share -->", f"# {identity.name}", "", summary + ".", "",
            "An identity of a [The Harness](https://harness.lmms-lab.com) agent. Adopting it gives you a new identity "
            "with its own key: its skills start as proposed and run only after their own tests pass on your "
            "computer, and its reactions start disabled.", "", "```sh", adopt, "```", ""]), encoding="utf-8",
            newline="\n")
    load(folder)
    return {"summary": summary, "install": adopt}


def share(identity, where, *, name=None, version=None, with_memory=False, public=False, url="", confirm=None,
          log=print) -> dict:
    """Send `identity` as a package to `where` (as harness share sends a library), after
    `confirm(preview)` said yes; a GitHub repository it creates is private unless `public`.
    Without confirm, or when it says no, nothing is sent ({"needs_consent": True, ...})."""
    from harness.packages.libraries import package_name, send

    name = package_name(name or identity.id)
    found = collect(identity, with_memory=with_memory)

    def write(folder, version, source):
        written = write_package(identity, folder, name=name, version=version, found=found, source=source)
        return {"identity": identity.id, **preview_of(name, found), **written}

    return send(where, name, write, version=version, private=not public, url=url, confirm=confirm, log=log)


def share_card(identity, path, *, confirm=None) -> dict:
    """A Character Card V3 at `path` (.png: inside its avatar; .json) with only its name and
    persona, after `confirm(preview)`."""
    soul = _text(identity.directory / "SOUL.md") if (identity.directory / "SOUL.md").is_file() else ""
    for place in _places():
        soul = soul.replace(place, "~")
    persona = cards.persona(soul)
    preview = {"identity": identity.id, "destination": str(path),
               "texts": [{"file": "name", "text": identity.name},
                         *({"file": key, "text": value} for key, value in persona.items() if value)],
               "other_files": ["avatar.png"] if str(path).lower().endswith(".png") else [],
               "left_out": ("skills", "reactions", "memory", "USER.md") + LEFT_OUT}
    for secret in _secrets(identity):
        if any(secret in row["text"] for row in preview["texts"]):
            raise ValueError("the persona holds a credential of this computer: take it out before sharing")
    if confirm is None or not confirm(preview):
        return {**preview, "needs_consent": True}
    written = cards.write(path, name=identity.name, soul_text=soul, avatar=identity.directory / "avatar.png")
    return {**preview, "sent": str(Path(written).resolve())}


# -- adopting ----------------------------------------------------------------------------


def _is_card(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in (".png", ".json"):
        return False
    try:
        cards.read(path)
        return True
    except (ValueError, KeyError):
        return False


def _identity_folder(folder: Path) -> Path:
    """The identity a fetched package or folder holds."""
    folder = Path(folder)
    if (folder / "IDENTITY.md").is_file() or (folder / "SOUL.md").is_file():
        return folder
    found = sorted(path.parent for path in folder.glob("identity/*/IDENTITY.md"))
    if not found:
        found = sorted(path.parent for path in folder.glob("*/identity/*/IDENTITY.md"))
    if len(found) != 1:
        raise ValueError("no identity there: a package of harness agent share (identity/<name>/), an identity "
                         "folder, or a character card")
    return found[0]


def adopt(source, *, id=None, root=None, log=print) -> dict:
    """A new identity from someone else's: a package of harness agent share (its link,
    folder or archive) or a character card. It gets a new id, a new key pair and
    adopted.json (where it came from); its skills are proposed with their programs waiting
    for their own tests, its reactions disabled, the other owner's USER.md left behind."""
    from harness.packages import sources
    from .reactions import Tree

    text = str(source).strip()
    local = Path(os.path.expanduser(text))
    note = {"from": text, "time": time.time()}
    if _is_card(local):
        card = cards.read(local)
        identity = state.create(_free_id(id or card["name"], root), card=local, root=root)
        note.update(kind="character card", name=card["name"])
        save(identity.directory / "adopted.json", note)
        return {"identity": identity.id, "name": identity.name, "fingerprint": identity.fingerprint, "skills": [],
                "reactions": [], "from": text}
    github = re.match(r"^github:([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?(?:#(.*))?$", text)
    spec = f"git:github.com/{github.group(1)}/{github.group(2)}" + (f"#{github.group(3)}" if github.group(3) else "") \
        if github else text
    with tempfile.TemporaryDirectory(prefix="harness-adopt-") as temporary:
        found, origin = sources.fetch(sources.parse(spec), Path(temporary), log=log)
        folder = _identity_folder(found)
        package = {}
        for candidate in (folder.parent.parent, found):
            if (candidate / "package.toml").is_file():
                try:
                    from harness.packages.manifest import load

                    loaded = load(candidate)
                    package = {"package": loaded.name, "version": loaded.version}
                except ValueError:
                    pass
                break
        identity = state.create(_free_id(id or folder.name, root), root=root)
        for name in ("IDENTITY.md", "SOUL.md", "avatar.png"):
            if (folder / name).is_file():
                shutil.copyfile(folder / name, identity.directory / name)
        memory = 0
        if (folder / "memory").is_dir():
            for path in sorted((folder / "memory").glob("*.md")):
                shutil.copyfile(path, identity.directory / "memory" / path.name)
                memory += 1
            identity._index(identity._entries())
        skills = []
        for skill in sorted((folder / "skills").iterdir()) if (folder / "skills").is_dir() else ():
            if not (skill / "SKILL.md").is_file():
                continue
            name = re.sub(r"[^a-z0-9_]+", "_", skill.name.lower()).strip("_")[:60] or "skill"
            target = identity.directory / "skills" / name
            shutil.copytree(skill, target, dirs_exist_ok=True)
            (target / "origin.json").unlink(missing_ok=True)
            waits = (target / "program.py").is_file()
            if waits:
                os.replace(target / "program.py", target / "program.proposed.py")
            save(target / "origin.json", {"source": "adopted", "from": text, "time": time.time(), "evidence": "proposed",
                                          **({"waits": "its own test here (harness agent adopt --test)"} if waits else {})})
            skills.append(name)
        tree, reactions, skipped = Tree(identity), [], []
        nodes = [node for node in (read(folder / "reactions.json", {}) or {}).get("nodes", [])
                 if isinstance(node, dict) and node.get("source") != "builtin"]
        for _ in range(len(nodes) + 1):  # a node after the node it hangs under
            waiting = []
            for node in nodes:
                if node.get("under") is not None and tree.node(node["under"]) is None and \
                        any(other.get("name") == node["under"] for other in nodes):
                    waiting.append(node)
                    continue
                try:
                    tree.add(str(node.get("name") or ""), node.get("when"), node.get("do"), under=node.get("under"),
                             about=str(node.get("about") or ""),
                             source="owner" if node.get("source") == "owner" else "learned", evidence="proposed",
                             origin={"adopted": text})
                    tree.enable(node["name"], False)
                    reactions.append(node["name"])
                except (ValueError, TypeError, KeyError) as error:
                    skipped.append({"reaction": node.get("name"), "why": str(error)})
            if len(waiting) == len(nodes):
                skipped += [{"reaction": node.get("name"), "why": "the node it hangs under is not there"}
                            for node in waiting]
                break
            nodes = waiting
            if not nodes:
                break
        note.update(kind="package", origin=origin, **package, skills=skills, reactions=reactions,
                    **({"memory_entries": memory} if memory else {}), **({"skipped": skipped} if skipped else {}))
        save(identity.directory / "adopted.json", note)
    return {"identity": identity.id, "name": identity.name, "fingerprint": identity.fingerprint, "skills": skills,
            "reactions": reactions, "skipped": skipped, "from": text}


def test_adopted(identity, names=None) -> list:
    """Run the own test of each adopted skill whose program waits (or of `names`): passed,
    its program is used and it is "own test passed"; failed or without a test, it stays
    proposed and its program is not used."""
    from harness.runtime.learning.learner import Learner, candidate
    from .learning import parse_skill_md, run_test

    results = []
    root = identity.directory / "skills"
    for folder in sorted(root.iterdir()) if root.is_dir() else ():
        program = folder / "program.proposed.py"
        if not program.is_file() or (names and folder.name not in names):
            continue
        origin = read(folder / "origin.json", {}, recover=True)
        if not (folder / "test.py").is_file():
            results.append({"skill": folder.name, "ok": False, "evidence": "proposed", "why": "it has no test"})
            continue
        code, test = _text(program), _text(folder / "test.py")
        ran = run_test(code, test)
        if not ran["ok"]:
            save(folder / "origin.json", {**origin, "tested": time.time(), "test": "failed"})
            results.append({"skill": folder.name, "ok": False, "evidence": "proposed", "output": ran["output"][-500:]})
            continue
        os.replace(program, folder / "program.py")
        try:
            summary = parse_skill_md(_text(folder / "SKILL.md"))["description"]
            item = candidate("skill", folder.name, code, test, summary=summary[:300], source="passive", origin="hand")
            Learner(identity.library, {"path": str(identity.library), "learn": "on"}, create=True).admit(
                item, "provisional", test_run={"ok": True, "method": "own_test", "output": ran["output"][-500:]},
                why="adopted; its own test passed here")
        except ValueError:
            pass  # a program the learning library does not take: used from its folder
        save(folder / "origin.json", {**{k: v for k, v in origin.items() if k != "waits"}, "evidence": "own_test",
                                      "tested": time.time(), "test": "passed"})
        results.append({"skill": folder.name, "ok": True, "evidence": "own_test"})
    return results


# -- backup and moving -------------------------------------------------------------------


def _derive(passphrase: str, header: dict) -> tuple[bytes, bytes]:
    salt = base64.b64decode(header["salt"])
    secret = str(passphrase).encode("utf-8")
    if header["kdf"] == "scrypt":
        raw = hashlib.scrypt(secret, salt=salt, n=header["n"], r=header["r"], p=header["p"], dklen=64,
                             maxmem=256 * 1024 * 1024)
    elif header["kdf"] == "pbkdf2-sha256":
        raw = hashlib.pbkdf2_hmac("sha256", secret, salt, header["rounds"], dklen=64)
    else:
        raise ValueError(f"a backup of an unknown kind ({header['kdf']})")
    return raw[:32], raw[32:]


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    base = hmac.new(key, digestmod=hashlib.sha256)
    blocks = []
    for counter in range((length + 31) // 32):
        block = base.copy()
        block.update(nonce + counter.to_bytes(8, "big"))
        blocks.append(block.digest())
    return b"".join(blocks)[:length]


def _xor(data: bytes, stream: bytes) -> bytes:
    if not data:
        return b""
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")


def encrypt(plain: bytes, passphrase: str, info: dict | None = None) -> bytes:
    """`plain` sealed with `passphrase` (see the module: scrypt, HMAC-SHA256 keystream and tag)."""
    if not passphrase:
        raise ValueError("a backup needs a passphrase")
    header = {"format": 1, "cipher": "hmac-sha256-ctr+hmac-sha256", "salt": base64.b64encode(os.urandom(16)).decode(),
              "nonce": base64.b64encode(os.urandom(16)).decode(), **(info or {})}
    if hasattr(hashlib, "scrypt"):
        header.update(kdf="scrypt", **SCRYPT)
    else:
        header.update(kdf="pbkdf2-sha256", rounds=PBKDF2_ROUNDS)
    key, mac = _derive(passphrase, header)
    head = json.dumps(header, sort_keys=True).encode("utf-8")
    sealed = _xor(plain, _keystream(key, base64.b64decode(header["nonce"]), len(plain)))
    tag = hmac.new(mac, BACKUP_MAGIC + head + b"\n" + sealed, hashlib.sha256).digest()
    return BACKUP_MAGIC + head + b"\n" + sealed + tag


def header_of(blob: bytes) -> dict:
    if not blob.startswith(BACKUP_MAGIC):
        raise ValueError("not a backup of harness agent backup")
    head, _, _ = blob[len(BACKUP_MAGIC):].partition(b"\n")
    return json.loads(head.decode("utf-8"))


def decrypt(blob: bytes, passphrase: str) -> bytes:
    """What encrypt() sealed; ValueError for a wrong passphrase or a changed file."""
    header = header_of(blob)
    head, _, rest = blob[len(BACKUP_MAGIC):].partition(b"\n")
    if len(rest) < 32:
        raise ValueError("the backup is cut short")
    sealed, tag = rest[:-32], rest[-32:]
    key, mac = _derive(passphrase, header)
    expected = hmac.new(mac, BACKUP_MAGIC + head + b"\n" + sealed, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("the passphrase is wrong, or the backup was changed")
    return _xor(sealed, _keystream(key, base64.b64decode(header["nonce"]), len(sealed)))


def _model_keys() -> dict:
    try:
        from harness.sdk import Credentials

        return dict(Credentials(data())._kept())
    except Exception:
        return {}


def backup(identity, path, passphrase, *, with_keys=False) -> dict:
    """A full backup of `identity` at `path`, encrypted with `passphrase`: its folder (persona,
    memory, conversations, library, reactions, calendar, spending, channel credentials), its
    private key, and with `with_keys` the model keys."""
    raw = io.BytesIO()
    included = {"identity": identity.id, "name": identity.name, "created": time.time(), "model_keys": bool(with_keys)}
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        def add(name, payload):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(payload), int(time.time()), 0o600
            tar.addfile(info, io.BytesIO(payload))

        count = 0
        for current, folders, names in os.walk(identity.directory):
            folders[:] = sorted(name for name in folders if name not in NOT_BACKED_UP)
            for name in sorted(names):
                if name in NOT_BACKED_UP or name.endswith(".tmp"):
                    continue
                file = Path(current) / name
                add("identity/" + file.relative_to(identity.directory).as_posix(), file.read_bytes())
                count += 1
        key = identity.root / ".keys" / f"{identity.id}.json"
        if key.is_file():
            add("key.json", key.read_bytes())
        if with_keys:
            add("model-keys.json", json.dumps(_model_keys()).encode("utf-8"))
        add("backup.json", json.dumps({**included, "files": count, "key": key.is_file()}).encode("utf-8"))
    blob = encrypt(raw.getvalue(), passphrase, {"identity": identity.id})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, blob, private=True)
    return {"backup": str(path.resolve()), "identity": identity.id, "bytes": len(blob), "model_keys": bool(with_keys),
            "channels": _channels(identity.directory)}


def _channels(directory) -> list:
    """The channels whose login a restore asks for again: its connected spaces."""
    return [str(row.get("title") or row.get("id")) for row in read(Path(directory) / "places.json", [])
            if isinstance(row, dict) and row.get("kind") == "space"]


def restore(path, passphrase, *, replace=False, root=None) -> dict:
    """Restore a backup here: the identity (same id, same key), and the model keys it holds.
    An identity of that id here is refused unless it was retired here or `replace`; the one
    that was here is kept beside it (agents/.<id>.before-restore-<time>)."""
    blob = Path(path).read_bytes()
    plain = decrypt(blob, passphrase)
    agents = state.agents_root(root)
    with tempfile.TemporaryDirectory(prefix="harness-restore-") as temporary:
        temporary = Path(temporary).resolve()
        with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tar:
            for member in tar.getmembers():
                target = (temporary / member.name).resolve()
                if not member.isfile() or temporary not in target.parents:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(member).read())
        about = json.loads((temporary / "backup.json").read_text(encoding="utf-8"))
        name = state.identifier(about["identity"])
        destination = agents / name
        if destination.exists():
            if not (replace or (destination / state.RETIRED).exists()):
                raise IdentityError(f"identity {name} is here already: give --replace to restore over it (the one here "
                                    "is kept aside)")
            os.replace(destination, agents / f".{name}.before-restore-{int(time.time())}")
        agents.mkdir(parents=True, exist_ok=True)
        shutil.copytree(temporary / "identity", destination)
        for leftover in (state.RETIRED, "life.json"):
            (destination / leftover).unlink(missing_ok=True)
        if (temporary / "key.json").is_file():
            (agents / ".keys").mkdir(parents=True, exist_ok=True)
            save(agents / ".keys" / f"{name}.json", json.loads((temporary / "key.json").read_text(encoding="utf-8")))
        keys = []
        if (temporary / "model-keys.json").is_file():
            from harness.sdk import Credentials

            credentials = Credentials(data())
            have = credentials._kept()
            for key, value in json.loads((temporary / "model-keys.json").read_text(encoding="utf-8")).items():
                if not have.get(key):
                    credentials.keep(key, value)
                    keys.append(key)
    identity = Identity(name, root=root, create=False)
    return {"identity": identity.id, "name": identity.name, "fingerprint": identity.fingerprint,
            "channels": _channels(identity.directory), "model_keys": keys}


def refusal(error) -> Problem:
    """Why a backup was not restored, with what to do: what restore() and decrypt() raise,
    in a frontend's words."""
    text = str(error)
    if isinstance(error, IdentityError):
        return Problem(text.split(":")[0], "restore over it (replace): the one here is kept aside, not deleted",
                       code="identity_exists")
    if "passphrase" in text:
        return Problem(text, "type the passphrase the backup was made with; a file that was changed cannot be "
                       "restored", code="backup_passphrase")
    return Problem(text, "choose a file that harness agent backup made (ID.harness-backup)", code="not_backup")


def retire(identity) -> dict:
    """Stop `identity` on this computer after it moved: retired.json in its folder (the
    resident service no longer starts it, and opening it says it has moved); a host running
    its life here is asked to pause it."""
    save(identity.directory / state.RETIRED, {"time": time.time(), "why": "moved to another computer"})
    state.release(identity)
    paused = False
    try:
        from harness.host import _reachable, read_address
        from harness.host.client import _call

        host = _reachable(read_address())
        if host is not None:
            _call(host.url, host.token, "/api/agent/pause", {"identity": identity.id}, 10.0)
            paused = True
    except Exception:
        paused = False
    return {"retired": identity.id, "name": identity.name, "paused_in_host": paused}


# -- bringing one over from OpenClaw or Hermes ------------------------------------------


def home_of(kind) -> Path:
    """Where OpenClaw keeps its workspace and Hermes its profile, as their documentation says
    (OPENCLAW_WORKSPACE_DIR, ~/.openclaw/workspace; HERMES_HOME, ~/.hermes)."""
    if kind == "openclaw":
        if os.environ.get("OPENCLAW_WORKSPACE_DIR"):
            return Path(os.environ["OPENCLAW_WORKSPACE_DIR"]).expanduser()
        profile = os.environ.get("OPENCLAW_PROFILE")
        return Path.home() / (f".openclaw-{profile}" if profile and profile != "default" else ".openclaw") / "workspace"
    if kind == "hermes":
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()
    raise ValueError("bring an agent over from openclaw or hermes")


def found_elsewhere() -> list:
    """The OpenClaw and Hermes agents on this computer, for onboarding's "bring it over"."""
    found = []
    for kind in ("openclaw", "hermes"):
        folder = home_of(kind)
        if (folder / "SOUL.md").is_file() or (folder / "memories").is_dir() or (folder / "IDENTITY.md").is_file():
            found.append({"kind": kind, "folder": str(folder)})
    return found


def _strip(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return re.sub(r"^\s*# [^\n]*\n", "", text.strip() + "\n", count=1).strip()


def _pieces(text: str) -> list:
    """Memory text as entries: Hermes separates entries with a line of §; otherwise each
    paragraph or top-level bullet is one; each at most state.ENTRY_CHARS."""
    text = _strip(text)
    if re.search(r"(?m)^\s*§\s*$", text):
        parts = re.split(r"(?m)^\s*§\s*$", text)
    else:
        parts = re.split(r"\n\s*\n|\n(?=[-*] )", text)
    out = []
    for part in (p.strip() for p in parts):
        while part:
            out.append(part[:state.ENTRY_CHARS])
            part = part[state.ENTRY_CHARS:].strip()
    return [part for part in out if not re.fullmatch(r"#+ [^\n]*", part)]  # a heading alone is no entry


def import_from(kind, folder=None, *, id=None, root=None) -> dict:
    """A new identity from an OpenClaw workspace or a Hermes profile (`folder`, else where it
    keeps it): persona (SOUL.md, IDENTITY.md's name; OpenClaw's AGENTS.md as instructions),
    USER.md, memory (MEMORY.md and OpenClaw's memory/ days, Hermes's memories/) and skills
    (SKILL.md folders, as proposed). Never its configuration, .env, auth.json, credentials/ or
    platform state: no channel token or key comes along."""
    folder = Path(folder).expanduser() if folder else home_of(kind)
    if not folder.is_dir():
        raise ValueError(f"no {kind} agent at {folder}")
    if kind == "openclaw":
        soul_path, user_path, memory_path = folder / "SOUL.md", folder / "USER.md", folder / "MEMORY.md"
        days = sorted((folder / "memory").glob("*.md")) if (folder / "memory").is_dir() else []
        skills = sorted(path.parent for path in folder.glob("skills/*/SKILL.md"))
        display = state.display_name(folder) if (folder / "IDENTITY.md").is_file() else None
        display = None if display == folder.name else display
        extra = _strip(_text(folder / "AGENTS.md")) if (folder / "AGENTS.md").is_file() else ""
    elif kind == "hermes":
        soul_path, user_path = folder / "SOUL.md", folder / "memories" / "USER.md"
        memory_path, days = folder / "memories" / "MEMORY.md", []
        skills = sorted(path.parent for path in folder.glob("skills/**/SKILL.md"))
        display, extra = None, ""
        if (folder / "profile.yaml").is_file():
            found = re.search(r"(?m)^display_name:\s*[\"']?(.+?)[\"']?\s*$", _text(folder / "profile.yaml"))
            display = found.group(1) if found else None
    else:
        raise ValueError("bring an agent over from openclaw or hermes")
    wanted = id or display or (folder.parent.name if kind == "openclaw" and folder.name == "workspace" else folder.name)
    identity = state.create(_free_id(wanted.lstrip("."), root), display=display, root=root)
    soul = _strip(_text(soul_path)) if soul_path.is_file() else ""
    if extra:
        soul = (soul + "\n\n" if soul else "") + "## Instructions (from AGENTS.md)\n\n" + extra
    if soul:
        atomic_write(identity.directory / "SOUL.md", state.TEMPLATES["SOUL.md"] + "\n" + soul + "\n")
    if user_path.is_file() and _strip(_text(user_path)):
        atomic_write(identity.directory / "USER.md", state.TEMPLATES["USER.md"] + "\n" + _strip(_text(user_path)) + "\n")
    if kind == "openclaw" and (folder / "IDENTITY.md").is_file():
        name = identity.name
        atomic_write(identity.directory / "IDENTITY.md", _text(folder / "IDENTITY.md"))
        if state.display_name(identity.directory) == identity.id and name != identity.id:
            identity.rename(name)
    entries, full = [], 0
    sources = ([(memory_path, "MEMORY.md")] if memory_path.is_file() else []) + [(day, f"memory/{day.name}") for day in days]
    for path, label in sources:
        pieces = _pieces(_text(path))
        for number, piece in enumerate(pieces, 1):
            key = f"{kind} {label}" + (f" #{number}" if len(pieces) > 1 else "")
            try:
                identity.remember(key[:160], piece, source=f"import:{kind}", expected=identity.memory()["revision"])
                entries.append(key)
            except ValueError:
                full += 1
    brought = []
    for skill in skills:
        name = re.sub(r"[^a-z0-9_]+", "_", skill.name.lower()).strip("_")[:60] or "skill"
        target = identity.directory / "skills" / name
        if target.exists():
            continue
        shutil.copytree(skill, target, ignore=shutil.ignore_patterns(".env", "*.key", "auth.json", "__pycache__"))
        waits = (target / "program.py").is_file()
        if waits:
            os.replace(target / "program.py", target / "program.proposed.py")
        save(target / "origin.json", {"source": f"import:{kind}", "from": str(skill.relative_to(folder)),
                                      "time": time.time(), "evidence": "proposed"})
        brought.append(name)
    save(identity.directory / "adopted.json", {"kind": kind, "from": str(folder), "time": time.time(),
                                               "memory_entries": len(entries), "skills": brought})
    stop = {"openclaw": "openclaw gateway stop", "hermes": "hermes gateway stop"}[kind]
    return {"identity": identity.id, "name": identity.name, "memory_entries": len(entries),
            **({"memory_not_brought": full} if full else {}), "skills": brought,
            "not_brought": ["channel tokens", "keys", "configuration"],
            "suggest": f"stop the original agent ({stop}) so one channel token is not used by two agents; then connect "
                       f"its channels to {identity.id} here"}
