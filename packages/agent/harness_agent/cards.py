"""Character cards (Character Card V3, and V2 and V1 before it): a persona shared as JSON or
inside a PNG. The name goes into IDENTITY.md; description, personality and system_prompt
into SOUL.md; a PNG card is kept as the avatar; every other field is ignored."""
import base64
import json
from pathlib import Path
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


def soul(card: dict) -> str:
    """SOUL.md's text from a card."""
    parts = [(title, card.get(key)) for title, key in (("Description", "description"), ("Personality", "personality"),
                                                       ("System prompt", "system_prompt"))]
    return "\n\n".join(f"## {title}\n\n{text}" for title, text in parts if text)
