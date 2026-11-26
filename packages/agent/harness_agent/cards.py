"""Character cards (Character Card V3, and V2 and V1 before it): a persona shared as JSON or
inside a PNG. The name goes into IDENTITY.md; description, personality and system_prompt
into SOUL.md; a PNG card is kept as the avatar; every other field is ignored.

write() makes a V3 card of an identity's name and persona only (nothing else of it goes): as
JSON, or inside its avatar PNG (a `ccv3` tEXt chunk, and a `chara` one with the same card
for readers of V2)."""
import base64
import json
from pathlib import Path
import re
import struct
import zlib

PNG = b"\x89PNG\r\n\x1a\n"
# The tEXt keywords that hold a card, newest first.
KEYWORDS = ("ccv3", "chara")


def _png_text(data: bytes) -> dict:
    """{keyword: text} of the PNG's tEXt, zTXt and iTXt chunks."""
    found, at = {}, len(PNG)
    while at + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        content = data[at + 8:at + 8 + length]
        at += 12 + length
        if kind == b"tEXt":
            keyword, _, text = content.partition(b"\0")
            found[keyword.decode("latin-1")] = text.decode("latin-1")
        elif kind == b"zTXt":
            keyword, _, rest = content.partition(b"\0")
            found[keyword.decode("latin-1")] = zlib.decompress(rest[1:]).decode("latin-1")
        elif kind == b"iTXt":
            keyword, _, rest = content.partition(b"\0")
            compressed, rest = rest[0], rest[2:]
            _, _, rest = rest.partition(b"\0")  # language
            _, _, text = rest.partition(b"\0")  # translated keyword
            found[keyword.decode("latin-1")] = (zlib.decompress(text) if compressed else text).decode("utf-8")
        elif kind == b"IEND":
            break
    return found


def read(path) -> dict:
    """The card at `path` (.json, or a .png with the card inside) as {name, description,
    personality, system_prompt, avatar}: avatar is the PNG's path, or None."""
    path = Path(path)
    data = path.read_bytes()
    avatar = None
    if data.startswith(PNG):
        texts = _png_text(data)
        encoded = next((texts[key] for key in KEYWORDS if key in texts), None)
        if encoded is None:
            raise ValueError(f"{path.name} is a PNG without a character card inside")
        raw = json.loads(base64.b64decode(encoded).decode("utf-8"))
        avatar = path
    else:
        raw = json.loads(data.decode("utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("a character card is a JSON object")
    card = raw.get("data") if isinstance(raw.get("data"), dict) else raw  # V2/V3 keep it under data
    name = str(card.get("name") or "").strip()
    if not name:
        raise ValueError("the character card has no name")
    return {"name": name[:200], **{key: str(card.get(key) or "").strip()
                                   for key in ("description", "personality", "system_prompt")},
            "avatar": avatar}


def _chunk(kind: bytes, content: bytes) -> bytes:
    return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xffffffff)


def persona(soul_text: str) -> dict:
    """{description, personality, system_prompt} of SOUL.md's text: the sections soul() writes
    when it has them, else the whole text as the description."""
    text = re.sub(r"<!--.*?-->", "", soul_text, flags=re.S)
    text = re.sub(r"^\s*# Soul\s*", "", text).strip()
    found = {"description": "", "personality": "", "system_prompt": ""}
    parts = re.split(r"(?m)^## (Description|Personality|System prompt)\s*$", text)
    if len(parts) > 1 and not parts[0].strip():
        for title, body in zip(parts[1::2], parts[2::2]):
            found[title.lower().replace(" ", "_")] = body.strip()
    else:
        found["description"] = text
    return found


def write(path, *, name: str, soul_text: str = "", avatar=None) -> Path:
    """A Character Card V3 at `path`: a .png (the avatar with the card inside; `avatar` is
    needed) or .json, holding only the name and the persona of SOUL.md."""
    path = Path(path)
    card = {"spec": "chara_card_v3", "spec_version": "3.0",
            "data": {"name": name, **persona(soul_text), "scenario": "", "first_mes": "", "mes_example": "",
                     "creator_notes": "", "post_history_instructions": "", "alternate_greetings": [],
                     "group_only_greetings": [], "tags": [], "creator": "", "character_version": "",
                     "extensions": {}}}
    encoded = json.dumps(card, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() != ".png":
        path.write_text(encoded + "\n", encoding="utf-8", newline="\n")
        return path
    if avatar is None or not Path(avatar).is_file():
        raise ValueError("a PNG card is the avatar with the card inside, and this identity has no avatar.png: "
                         "export a .json card instead")
    data = Path(avatar).read_bytes()
    if not data.startswith(PNG):
        raise ValueError("the avatar is not a PNG")
    # The avatar's chunks without a card it carried; the card's before IEND.
    chunks, at = [], len(PNG)
    while at + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        raw = data[at:at + 12 + length]
        at += 12 + length
        if kind == b"IEND":
            break
        if kind in (b"tEXt", b"zTXt", b"iTXt") and raw[8:].split(b"\0", 1)[0].decode("latin-1") in KEYWORDS:
            continue
        chunks.append(raw)
    value = base64.b64encode(encoded.encode("utf-8"))
    chunks += [_chunk(b"tEXt", b"ccv3\0" + value), _chunk(b"tEXt", b"chara\0" + value), _chunk(b"IEND", b"")]
    path.write_bytes(PNG + b"".join(chunks))
    return path


def soul(card: dict) -> str:
    """SOUL.md's text from a card."""
    parts = [(title, card.get(key)) for title, key in (("Description", "description"), ("Personality", "personality"),
                                                       ("System prompt", "system_prompt"))]
    return "\n\n".join(f"## {title}\n\n{text}" for title, text in parts if text)
