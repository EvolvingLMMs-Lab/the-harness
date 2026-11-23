"""Ask a game server what it is (the game's own server list ping): its version, before the
body joins it. Standard library only; nothing is logged in."""

import json
import re
import socket
import struct


def _varint(value: int) -> bytes:
    value &= 0xFFFFFFFF
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _read_varint(read) -> int:
    value = 0
    for shift in range(0, 35, 7):
        byte = read(1)[0]
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value
    raise ValueError("the server's answer is not the game's")


def _packet(*parts: bytes) -> bytes:
    body = b"".join(parts)
    return _varint(len(body)) + body


def status(host: str, port: int, timeout: float = 5.0) -> dict | None:
    """What the server at host:port says of itself ({"version": {"name", "protocol"}, ...}),
    or None when nothing answers there as a game server does."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            name = host.encode("utf-8")
            # A handshake that asks for the status (protocol -1: the client does not say its own).
            sock.sendall(_packet(_varint(0), _varint(-1), _varint(len(name)), name, struct.pack(">H", int(port)), _varint(1)))
            sock.sendall(_packet(_varint(0)))
            stream = sock.makefile("rb")

            def read(count):
                got = stream.read(count)
                if len(got) != count:
                    raise ValueError("the server closed the connection")
                return got

            _read_varint(read)                 # the packet's length
            if _read_varint(read) != 0:
                return None
            return json.loads(read(_read_varint(read)).decode("utf-8", "replace"))
    except (OSError, ValueError, IndexError):
        return None


def game_version(answer: dict | None) -> str | None:
    """The version of the game in a status answer ("1.16.1" out of "1.16.1" or "Paper 1.20.4"),
    or None where it names none."""
    name = str(((answer or {}).get("version") or {}).get("name") or "")
    found = re.search(r"\d+\.\d+(?:\.\d+)?", name)
    return found.group(0) if found else None
