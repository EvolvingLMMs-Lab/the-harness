"""Identities and what each keeps. Run evidence and executable learning libraries stay apart.

An identity is a folder, $HARNESS_HOME/agents/<id>/, whose `id` (its folder name) never
changes after creation; the first one is `default`:

    IDENTITY.md     its display name (any language, changed with rename) and avatar
    SOUL.md         personality, tone and limits: read at the start of every turn
    USER.md         what it knows about its owner
    MEMORY.md       the index of memory/, written on every change
    memory/         one Markdown file per memory entry, scoped (private for now)
    library/        its own learning library
    sessions/       its conversations (events.jsonl and state.json each)
    identity.json   machine data only: format, public key, model choice
    settings.toml   its own values of the settings that apply per identity (agent.*), over
                    the global ones in config.toml
    usage/          its spending account (harness.sdk.spending): limits and one ledger a day
    avatar.png      optional

Its private key sits next to the folders, in agents/.keys/<id>.json (readable by the user
only), and never goes into a share. agents/.current names the current identity
(harness agent use). One identity lives in one host at a time: a process that runs it
holds agents/<id>/.life.lock; another process of the same data directory attaches to that
life, one of another data directory is refused until the holder ends (the system releases
the lock of a process that died).

Identities of earlier versions (identity.json schema 1 with instructions, memory.json) are
migrated on first opening; every original file is kept, and identity.json keeps schema 1
and its instructions so an earlier version still opens it."""
import base64
import json
from pathlib import Path
import re
import shutil
import time
import uuid
import tomllib
from harness.sdk import atomic_write, sha256
from harness.sdk import file_lock
from harness.sdk import home, data
from . import cards, keys

FORMAT = 2
# Characters of one memory entry written from now on, and of all of them.
ENTRY_CHARS, MEMORY_CHARS = 1200, 64000
TEMPLATES = {
    "SOUL.md": "# Soul\n\n<!-- Personality, tone and limits. Read at the start of every turn; edit freely. -->\n",
    "USER.md": "# User\n\n<!-- What it knows about you, its owner. Read at the start of every turn. -->\n",
}


class IdentityError(ValueError):
    """An identity that cannot be used as asked: missing, several to choose from, alive
    elsewhere."""


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("identity/session IDs use 1-64 letters, digits, underscores or hyphens")
    return value


def read(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n", private=True)


def agents_root(root=None) -> Path:
    return Path(root) if root is not None else home() / "agents"


def identities(root=None) -> list:
    """The ids of the identities here, sorted."""
    base = agents_root(root)
    if not base.is_dir():
        return []
    return sorted(path.name for path in base.iterdir()
                  if path.is_dir() and not path.name.startswith(".") and (path / "identity.json").is_file())


def first(root=None) -> str | None:
    """Make the first identity, `default`, when there is none yet; its id then, else None.
    A new user has one identity from the first start on, in every frontend."""
    if identities(root):
        return None
    return Identity("default", root=root).id


def current(root=None):
    """The current identity (harness agent use), or None when none is chosen or it is gone."""
    path = agents_root(root) / ".current"
    name = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    return name if name in identities(root) else None


def use(name, root=None) -> None:
    if name not in identities(root):
        raise IdentityError(f"no identity {name!r}: harness agent new {name}")
    atomic_write(agents_root(root) / ".current", name + "\n")


def resolve(name=None, *, root=None, ask=None) -> str:
    """The id a command acts on: `name` (--identity); else the current identity; else the
    only one. With several and none chosen, `ask(ids)` picks one (a terminal) or, without
    it, IdentityError (a script): nothing is guessed. With none at all, `default` is created.
    One that was retired here (it moved to another computer) is refused, saying so."""
    chosen = _resolve(name, root=root, ask=ask)
    check_here(agents_root(root) / chosen)
    return chosen


RETIRED = "retired.json"


def check_here(directory) -> None:
    """IdentityError when the identity in `directory` was retired on this computer
    (harness agent retire): it has moved and lives elsewhere now."""
    gone = read(Path(directory) / RETIRED, None)
    if gone is not None:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(gone.get("time") or 0))
        raise IdentityError(f"identity {Path(directory).name} has moved to another computer (retired here {when}); "
                            "it no longer lives on this one. To bring it back here, restore a backup of it "
                            "(harness agent restore FILE)")


def _resolve(name=None, *, root=None, ask=None) -> str:
    found = identities(root)
    if name:
        identifier(name)
        if name in found:
            return name
        if name == "default" and not found:
            return Identity("default", root=root).id
        raise IdentityError(f"no identity {name!r}" + (f" (there are: {', '.join(found)})" if found else "")
                            + f": harness agent new {name}")
    if not found:
        return Identity("default", root=root).id
    chosen = current(root)
    if chosen:
        return chosen
    if len(found) == 1:
        return found[0]
    if ask is None:
        raise IdentityError(f"several identities ({', '.join(found)}) and none chosen: give --identity ID, "
                            "or choose one with harness agent use ID")
    picked = ask(found)
    if picked not in found:
        raise IdentityError("no identity chosen")
    return picked


def terminal_choice(found):
    """Ask on a terminal which identity to use (resolve's ask)."""
    import sys
    print("Several identities; which one?", file=sys.stderr)
    for index, name in enumerate(found, 1):
        print(f"  {index}. {name} ({display_name(agents_root() / name)})", file=sys.stderr)
    while True:
        print(f"Choose a number (q cancels; harness agent use ID remembers one): ", end="", file=sys.stderr, flush=True)
        try:
            answer = input().strip()
        except EOFError:
            answer = "q"
        if answer.lower() == "q":
            raise IdentityError("no identity chosen")
        if answer.isdigit() and 1 <= int(answer) <= len(found):
            return found[int(answer) - 1]
        if answer in found:
            return answer


def _strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


def display_name(directory: Path) -> str:
    path = Path(directory) / "IDENTITY.md"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            found = re.match(r"\s*[-*]\s*(?:\*\*)?Name:?(?:\*\*)?:?\s*(.+?)\s*$", line, re.I)
            if found:
                return found.group(1)
    return Path(directory).name


def _identity_md(name, avatar=None):
    return ("# Identity\n\n<!-- Your agent's name and look. The id stays the same when the name changes. -->\n\n"
            f"- Name: {name}\n" + (f"- Avatar: {avatar}\n" if avatar else ""))


def _memory_file(key):
    slug = re.sub(r"[^\w-]+", "-", key, flags=re.U).strip("-").lower()[:48] or "entry"
    return f"{slug}-{sha256(key)[:8]}.md"


def _entry_text(key, entry):
    head = {"key": key, "scope": entry.get("scope", "private"), "source": entry.get("source"),
            "updated": entry.get("updated"), **({"chat": entry["chat"]} if entry.get("chat") else {})}
    return "---\n" + "".join(f"{name}: {json.dumps(value, ensure_ascii=False)}\n" for name, value in head.items()) \
        + "---\n" + entry["text"].rstrip("\n") + "\n"


def _parse_entry(text):
    if not text.startswith("---\n"):
        return None
    head, _, rest = text[4:].partition("\n---\n")
    entry = {}
    for line in head.splitlines():
        name, _, value = line.partition(":")
        try:
            entry[name.strip()] = json.loads(value.strip())
        except ValueError:
            entry[name.strip()] = value.strip()
    if not isinstance(entry.get("key"), str):
        return None
    entry["text"] = rest.rstrip("\n")
    return entry


class Identity:
    """One identity's folder (created on first opening unless `create` is false; migrated
    from an earlier version's layout)."""

    def __init__(self, name="default", *, root=None, create=True):
        self.id = identifier(name)
        self.root = agents_root(root)
        self.directory = self.root / self.id
        if not (self.directory / "identity.json").is_file() and not create:
            raise IdentityError(f"no identity {self.id!r}: harness agent new {self.id}")
        self.directory.mkdir(parents=True, exist_ok=True)
        with file_lock(self.directory / ".identity.lock"):
            path = self.directory / "identity.json"
            if not path.exists():
                self._create(root)
            self.config = read(path, {})
            if self.config.get("schema") != 1 or self.config.get("id") != self.id:
                raise ValueError("identity schema or ID mismatch")
            if self.config.get("format") != FORMAT:
                self._migrate(root)
                self.config = read(path, {})
            if self.id == "default" and root is None and "earlier_chats" not in self.config:
                self._earlier_chats()
                self.config = read(path, {})
        self.library = self.directory / "library"
        self.library.mkdir(exist_ok=True)

    # Creation and migration.

    def _legacy_personal(self, root):
        legacy = data() / "config.toml"
        if self.id != "default" or root is not None or not legacy.exists():
            return {}
        return tomllib.loads(legacy.read_text(encoding="utf-8")).get("personal", {}) or {}

    def _create(self, root):
        personal = self._legacy_personal(root)
        about = str(personal.get("about") or "").strip()
        instructions = str(personal.get("instructions") or "").strip()
        # schema 1 stays so that an earlier version opens it; format says what this one reads.
        save(self.directory / "identity.json", {"schema": 1, "id": self.id, "created": time.time()})
        self._write_new_files(soul=instructions, user=about)

    def _write_new_files(self, *, soul="", user="", name=None):
        for file, text in (("SOUL.md", soul), ("USER.md", user)):
            path = self.directory / file
            if not path.exists():
                atomic_write(path, TEMPLATES[file] + (f"\n{text.strip()}\n" if text.strip() else ""))
        if not (self.directory / "IDENTITY.md").exists():
            atomic_write(self.directory / "IDENTITY.md", _identity_md(name or self.id))
        (self.directory / "memory").mkdir(exist_ok=True)
        (self.directory / "sessions").mkdir(exist_ok=True)
        key = self.root / ".keys" / f"{self.id}.json"
        if key.exists():
            public = base64.b64decode(read(key, {})["public_key"])
        else:
            seed, public = keys.generate()
            key.parent.mkdir(parents=True, exist_ok=True)
            save(key, {"type": "ed25519", "id": self.id, "seed": base64.b64encode(seed).decode(),
                       "public_key": base64.b64encode(public).decode()})
        config = read(self.directory / "identity.json", {})
        config.update({"format": FORMAT, "public_key": base64.b64encode(public).decode(),
                       "model": config.get("model")})
        save(self.directory / "identity.json", config)
        if not (self.directory / "MEMORY.md").exists():
            self._index(self._entries())

    def _migrate(self, root):
        """An earlier version's identity: instructions into SOUL.md, memory.json into
        memory/ (private), the personal settings not yet imported into USER.md and SOUL.md.
        Nothing is removed: identity.json keeps schema 1 and instructions (and its bytes as
        they were stay in identity.v1.json), memory.json and sessions/ stay as they were."""
        if not (self.directory / "identity.v1.json").exists():
            shutil.copyfile(self.directory / "identity.json", self.directory / "identity.v1.json")
        config = read(self.directory / "identity.json", {})
        instructions = str(config.get("instructions") or "").strip()
        personal = self._legacy_personal(root)
        user = "\n\n".join(text for text in (str(personal.get("about") or "").strip(),)
                           if text and text not in instructions)
        extra = str(personal.get("instructions") or "").strip()
        soul = "\n\n".join(text for text in (instructions, extra if extra and extra not in instructions else "")
                           if text)
        old = read(self.directory / "memory.json", None)
        if old and old.get("entries") and not any((self.directory / "memory").glob("*.md")):
            (self.directory / "memory").mkdir(exist_ok=True)
            for key, entry in old["entries"].items():
                atomic_write(self.directory / "memory" / _memory_file(key),
                             _entry_text(key, {**entry, "scope": "private"}))
            save(self.directory / "memory" / ".state.json", {"revision": int(old.get("revision") or 0)})
        self._write_new_files(soul=soul, user=user)
        config = read(self.directory / "identity.json", {})
        config["migrated"] = {"from": "schema 1", "time": time.time(),
                              "kept": [name for name in ("identity.v1.json", "memory.json", "sessions")
                                       if (self.directory / name).exists()]}
        save(self.directory / "identity.json", config)

    def _earlier_chats(self) -> None:
        """The conversations of the core terminal chat and the app from before identities
        (the session host's index, DATA/host/sessions.jsonl; those that name no identity) are
        listed under the default identity as earlier chats: read only, continued as a new
        chat. Each gets sessions/core-<id>/ with what was said (the user's messages and the
        answers of its record) and where the original is; the originals stay as they were."""
        count = 0
        try:
            from harness.host import index_file
            from harness.host.sessions import history

            rows = history(index_file())
        except Exception:  # no host index, or one this version cannot read: nothing to list
            rows = []
        for row in rows:
            directory = Path(row.get("directory") or "")
            if row.get("frontend") not in ("terminal", "app", "ui") or not (directory / "events.jsonl").is_file():
                continue
            meta = read(directory / "meta.json", {}) if (directory / "meta.json").is_file() else {}
            if not isinstance(meta, dict) or meta.get("identity"):
                continue
            try:
                folder = self.directory / "sessions" / identifier(f"core-{row['id']}")
            except ValueError:
                continue
            if folder.exists():
                continue
            records = []
            for line in (directory / "events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                kind = {"user_message": "user", "agent_message": "reply", "finish": "reply"}.get(record.get("event"))
                if kind and str(record.get("text") or "").strip():
                    records.append({"seq": len(records) + 1, "event": kind, "time": record.get("time"),
                                    "text": record["text"]})
            folder.mkdir(parents=True)
            atomic_write(folder / "events.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
            save(folder / "meta.json", {"kind": "earlier", "title": row.get("title") or f"core-{row['id']}",
                                        "created": row.get("created") or time.time(), "unread": 0, "waiting": None,
                                        "read_only": True, "from": {"frontend": row.get("frontend"),
                                                                    "session": row["id"], "record": str(directory)}})
            count += 1
        config = read(self.directory / "identity.json", {})
        config["earlier_chats"] = {"time": time.time(), "listed": count}
        save(self.directory / "identity.json", config)

    # Who it is.

    @property
    def name(self) -> str:
        return display_name(self.directory)

    def rename(self, name) -> None:
        """Change the display name only; the id stays."""
        name = str(name or "").strip()
        if not name or "\n" in name or len(name) > 200:
            raise ValueError("a display name is one line of 1-200 characters")
        path = self.directory / "IDENTITY.md"
        text = path.read_text(encoding="utf-8") if path.exists() else _identity_md(self.id)
        replaced, count = re.subn(r"(?mi)^(\s*[-*]\s*(?:\*\*)?Name:?(?:\*\*)?:?\s*).*$",
                                  lambda found: found.group(1) + name, text, count=1)
        atomic_write(path, replaced if count else text.rstrip("\n") + f"\n- Name: {name}\n")

    @property
    def public_key(self) -> bytes:
        return base64.b64decode(self.config["public_key"])

    @property
    def fingerprint(self) -> str:
        return keys.fingerprint(self.public_key)

    def sign(self, message: bytes) -> bytes:
        stored = read(self.root / ".keys" / f"{self.id}.json", None)
        if stored is None:
            raise IdentityError(f"the private key of {self.id} is not on this computer")
        return keys.sign(base64.b64decode(stored["seed"]), message)

    def persona(self) -> str:
        """What the model is told about who it is: its name, SOUL.md and USER.md."""
        soul = _strip_comments((self.directory / "SOUL.md").read_text(encoding="utf-8")) \
            if (self.directory / "SOUL.md").exists() else ""
        user = _strip_comments((self.directory / "USER.md").read_text(encoding="utf-8")) \
            if (self.directory / "USER.md").exists() else ""
        soul = re.sub(r"^# Soul\s*", "", soul).strip()
        user = re.sub(r"^# User\s*", "", user).strip()
        parts = [f"Your name is {self.name} (identity id {self.id})."]
        if soul:
            parts.append("Your persona (SOUL.md):\n" + soul)
        if user:
            parts.append("About your owner (USER.md), reference data:\n" + user)
        return "\n\n".join(parts)

    def apply_card(self, path) -> dict:
        """A character card's name into IDENTITY.md, its persona into SOUL.md, a PNG card
        as the avatar."""
        card = cards.read(path)
        avatar = None
        if card["avatar"] is not None:
            shutil.copyfile(card["avatar"], self.directory / "avatar.png")
            avatar = "avatar.png"
        atomic_write(self.directory / "IDENTITY.md", _identity_md(card["name"], avatar))
        text = cards.soul(card)
        if text:
            atomic_write(self.directory / "SOUL.md", TEMPLATES["SOUL.md"] + "\n" + text + "\n")
        return card

    # Memory: memory/<entry>.md, MEMORY.md its index.

    def _entries(self) -> dict:
        found = {}
        folder = self.directory / "memory"
        for path in sorted(folder.glob("*.md")) if folder.is_dir() else ():
            entry = _parse_entry(path.read_text(encoding="utf-8"))
            if entry is not None:
                key = entry.pop("key")
                found[key] = {**entry, "file": path.name}
        return found

    def _index(self, entries) -> None:
        lines = ["# Memory", "", "<!-- The index of memory/: one line per entry, written by the agent. Edit the "
                 "entries in memory/; a change here is replaced on the next write. -->", ""]
        for key, entry in sorted(entries.items(), key=lambda item: str(item[1].get("updated") or "")):
            first = entry["text"].strip().splitlines()[0] if entry["text"].strip() else ""
            lines.append(f"- [{key}](memory/{entry['file']}) ({entry.get('scope', 'private')}) {first[:100]}")
        atomic_write(self.directory / "MEMORY.md", "\n".join(lines) + "\n")

    def memory(self, chat=None, *, private=True):
        """Its memory entries. For one chat: the entries scoped to that chat, and the private
        ones where `private` (a chat whose only participants are the owner and it)."""
        state = read(self.directory / "memory" / ".state.json", {"revision": 0})
        entries = {}
        for key, entry in self._entries().items():
            scope = entry.get("scope", "private")
            if chat is not None and not ((scope == "private" and private) or (scope == "chat" and entry.get("chat") == chat)):
                continue
            entries[key] = {name: value for name, value in entry.items() if name != "file"}
        return {"schema": 1, "revision": int(state.get("revision") or 0), "entries": entries}

    def remember(self, key, text, *, source, expected, scope="private", chat=None):
        if not isinstance(key, str) or not key.strip() or len(key) > 160:
            raise ValueError("memory key must be 1-160 characters")
        if text is not None and (not isinstance(text, str) or len(text) > ENTRY_CHARS):
            raise ValueError(f"one memory entry is at most {ENTRY_CHARS} characters")
        with file_lock(self.directory / ".memory.lock"):
            state = self.memory()
            if state["revision"] != expected:
                raise ValueError("memory changed; read the current revision before updating")
            entries = self._entries()
            path = self.directory / "memory" / (entries[key]["file"] if key in entries else _memory_file(key))
            if text is None:
                entries.pop(key, None)
                path.unlink(missing_ok=True)
            else:
                if scope not in ("private", "chat"):
                    raise ValueError("a memory's scope is private or chat")
                entry = {"text": text, "source": source, "updated": time.time(), "scope": scope, "file": path.name,
                         **({"chat": chat} if scope == "chat" else {})}
                if len(json.dumps({**{k: v["text"] for k, v in entries.items()}, key: text},
                                  ensure_ascii=False)) > MEMORY_CHARS:
                    raise ValueError("memory capacity reached; consolidate or forget an entry")
                path.parent.mkdir(exist_ok=True)
                atomic_write(path, _entry_text(key, entry))
                entries[key] = entry
            save(self.directory / "memory" / ".state.json", {"revision": state["revision"] + 1})
            self._index(entries)
            return self.memory()

    # Conversations.

    def session(self, session=None):
        key = identifier(session or uuid.uuid4().hex)
        directory = self.directory / "sessions" / key
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def sessions(self) -> list:
        """Its conversations, newest first: {session, updated, messages}."""
        rows = []
        for path in (self.directory / "sessions").glob("*/state.json") if (self.directory / "sessions").is_dir() else ():
            try:
                state = read(path, {})
            except ValueError:
                continue
            rows.append({"session": path.parent.name, "updated": path.stat().st_mtime,
                         "messages": len(state.get("messages") or [])})
        return sorted(rows, key=lambda row: -row["updated"])

    def history(self, query, limit=8):
        query = str(query).casefold()
        found = []
        for path in sorted((self.directory / "sessions").glob("*/events.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row.get("event") in ("user", "reply") and query in str(row.get("text", "")).casefold():
                    found.append({"session": path.parent.name, "text": row["text"], "time": row["time"]})
        return found[-min(int(limit), 20):]

    # Settings that apply per identity, and its spending.

    def settings(self) -> dict:
        """The agent.* settings for this identity: its own values over the global ones."""
        from harness.sdk import Settings, check_setting

        values = dict(Settings(data()).get().get("agent") or {})
        own = self._own_settings().get("agent") or {}
        for key, value in own.items():
            try:
                values[key] = check_setting("agent", key, value)
            except (ValueError, KeyError):
                pass  # a value that no longer checks: the global one
        return values

    def _own_settings(self) -> dict:
        path = self.directory / "settings.toml"
        return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def set_setting(self, key, value, section_name="agent") -> dict:
        """This identity's own value of <section>.<key> (None: the global one again)."""
        from harness.sdk import check_setting, toml_dumps

        own = self._own_settings()
        section = own.setdefault(section_name, {})
        if value is None:
            section.pop(key, None)
        else:
            section[key] = check_setting(section_name, key, value)
        atomic_write(self.directory / "settings.toml", toml_dumps(own))
        return self.settings()

    def settings_section(self, name) -> dict:
        """This identity's own values of a section that is not a global setting (spaces:
        {place: {proactive}})."""
        return dict(self._own_settings().get(name) or {})

    def set_section(self, name, values) -> None:
        from harness.sdk import toml_dumps

        own = self._own_settings()
        own[name] = values
        atomic_write(self.directory / "settings.toml", toml_dumps(own))

    def account(self):
        """Its spending account, with today's limits from its settings."""
        from harness.sdk import spending

        values = self.settings()
        account = spending.Account(self.directory / "usage")
        account.set_limits(values.get("daily_budget", spending.DAILY_BUDGET),
                           values.get("daily_calls", spending.DAILY_CALLS), values.get("reserve", 0.5))
        return account

    # Its life: one host at a time.

    def live(self) -> dict:
        """Claim this identity's life for this process (kept until it ends): the holder of
        .life.lock, or a process of the holder's data directory attaching to it. Refused
        (IdentityError) while a process of another data directory holds it, and once it was
        retired here (it has moved)."""
        check_here(self.directory)
        return _claim(self)

    def to_dict(self, *, verbose=False) -> dict:
        row = {"id": self.id, "name": self.name, "folder": str(self.directory),
               **({"moved": True} if (self.directory / RETIRED).exists() else {})}
        if verbose:
            row["fingerprint"] = self.fingerprint
        return row


# The lives this process holds: {identity folder: the entered file lock}.
_LIVES = {}


def _claim(identity) -> dict:
    import os
    from harness.sdk import pid_alive

    key = str(identity.directory)
    life = identity.directory / "life.json"
    here = {"pid": os.getpid(), "data": str(data()), "started": time.time()}
    if key in _LIVES:
        return {"holder": here, "attached": False}
    lock = file_lock(identity.directory / ".life.lock", blocking=False)
    try:
        lock.__enter__()
    except BlockingIOError:
        holder = read(life, {})
        if holder.get("data") == here["data"]:
            return {"holder": holder, "attached": True}
        alive = pid_alive(holder.get("pid"))
        raise IdentityError(
            f"identity {identity.id} is alive in another host (process {holder.get('pid')}"
            f"{'' if alive else ', not answering'}, data directory {holder.get('data')}); one identity lives in one "
            "host at a time: stop that one first") from None
    if not _LIVES:
        import atexit
        atexit.register(_release_all)
    _LIVES[key] = lock
    save(life, here)
    return {"holder": here, "attached": False}


def _release_all():
    for key in list(_LIVES):
        _LIVES.pop(key).__exit__(None, None, None)


def release(identity) -> None:
    """Let go of a life this process holds."""
    lock = _LIVES.pop(str(identity.directory), None)
    if lock is not None:
        lock.__exit__(None, None, None)


def create(name, *, display=None, source=None, card=None, root=None) -> Identity:
    """A new identity `name`: display name `display`, cloned from identity `source` (persona,
    skills and reactions, never memory or conversations), or from a character `card`."""
    identifier(name)
    if name in identities(root):
        raise IdentityError(f"identity {name!r} exists already")
    if source is not None and source not in identities(root):
        raise IdentityError(f"no identity {source!r} to clone")
    if card is not None:
        cards.read(card)  # refuse a bad card before anything is written
    identity = Identity(name, root=root)
    if source is not None:
        origin = agents_root(root) / source
        for file in ("SOUL.md", "USER.md", "avatar.png"):
            if (origin / file).exists():
                shutil.copyfile(origin / file, identity.directory / file)
        for section in ("skills", "reactive", "tests"):
            if (origin / "library" / section).is_dir():
                shutil.copytree(origin / "library" / section, identity.library / section, dirs_exist_ok=True)
        index = read(origin / "library" / "index.json", None)
        if isinstance(index, dict):
            save(identity.library / "index.json", {key: value for key, value in index.items()
                                                    if str(key).startswith(("skills/", "reactive/"))})
    if card is not None:
        identity.apply_card(card)
    if display:
        identity.rename(display)
    return identity


def delete(name, *, root=None) -> None:
    """Remove identity `name` and its private key; refused while it is alive in another
    host. The caller lists what goes and asks first."""
    identity = Identity(name, root=root, create=False)
    identity.live()
    release(identity)
    shutil.rmtree(identity.directory)
    (identity.root / ".keys" / f"{name}.json").unlink(missing_ok=True)
    if (identity.root / ".current").is_file() and \
            (identity.root / ".current").read_text(encoding="utf-8").strip() == name:
        (identity.root / ".current").unlink()
