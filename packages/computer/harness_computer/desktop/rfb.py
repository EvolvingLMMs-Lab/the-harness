"""A client of the remote framebuffer protocol (RFB, RFC 6143: what VNC speaks), for the
screen of a display workspace's virtual machine (desktop/vm.py): its picture, and its
own pointer and keyboard, never the user's.

The machine's screen is served by the hypervisor (QEMU's VNC server, on this computer's
loopback with a password of the workspace's own) or by the guest (macOS Screen Sharing
in a Virtualization.framework machine, Apple's authentication with the guest's user).
Security types: None (1), VNC authentication (2, DES) and Apple Remote Desktop (30,
Diffie-Hellman and AES-128); the ciphers are written here, so this is standard library
only (pictures need Pillow).

    client = Client("127.0.0.1", 5901, password="secret12").connect()
    client.size                         (1280, 800)
    client.picture()                    a PIL RGB image of the whole screen
    client.click(100, 200, "left", 1)
    client.keys(["ctrl", "l"]); client.type("hello")
    client.close()

Pointer events are absolute: a QEMU machine needs a tablet (usb-tablet) for them to land
where they say. Keys are X keysyms (inject.py KEYSYMS); characters go as their Latin-1 or
Unicode keysyms.
"""

import hashlib
import os
import socket
import struct
import threading
import time

from .inject import char_keysym, keysym

# Security types.
NONE, VNC_AUTH, ARD = 1, 2, 30
# Encodings: raw pixels, a rectangle copied from elsewhere on the screen, and the
# pseudo-encoding that announces a new screen size.
RAW, COPY_RECT, DESKTOP_SIZE = 0, 1, -223
CONNECT_SECONDS = 10.0
READ_SECONDS = 20.0
# Pointer buttons as bits of the button mask: left, middle, right; the wheel's up, down,
# left and right are buttons 4 to 7, pressed and released.
BUTTONS = {"left": 1, "middle": 2, "right": 4}
WHEEL = {"up": 8, "down": 16, "left": 32, "right": 64}


class RFBError(RuntimeError):
    """The server refused, or spoke something this client does not."""


class Client:
    """One connection to an RFB server (see the module's text). Thread-safe: one request at
    a time."""

    def __init__(self, host: str, port: int, password: str | None = None, user: str | None = None,
                 shared: bool = True, timeout: float = READ_SECONDS):
        self.host, self.port = host, int(port)
        self._password, self._user = password, user
        self._shared = bool(shared)
        self._timeout = float(timeout)
        self._socket = None
        self._lock = threading.RLock()
        self.size = (0, 0)
        self.name = ""
        self.security = None
        self._frame = None
        self._buttons = 0
        self._pointer = (0, 0)

    # -- connection --------------------------------------------------------------------

    def connect(self, timeout: float = CONNECT_SECONDS) -> "Client":
        with self._lock:
            self._socket = socket.create_connection((self.host, self.port), timeout=timeout)
            self._socket.settimeout(self._timeout)
            self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                self._handshake()
            except BaseException:
                self.close()
                raise
        return self

    def close(self) -> None:
        with self._lock:
            connection, self._socket = self._socket, None
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def _handshake(self) -> None:
        banner = self._read(12)
        if not banner.startswith(b"RFB "):
            raise RFBError(f"not an RFB server: {banner!r}")
        major, minor = int(banner[4:7]), int(banner[8:11])
        # 3.3 or 3.7 as offered; anything newer (Apple's 3.889 too) as 3.8.
        version = (3, 8) if (major, minor) >= (3, 8) else (3, minor if minor in (3, 7) else 3)
        self._send(b"RFB %03d.%03d\n" % version)
        if version == (3, 3):
            offered = [struct.unpack(">I", self._read(4))[0]]
            if offered == [0]:
                raise RFBError(f"the server refused the connection: {self._reason()}")
        else:
            count = self._read(1)[0]
            if not count:
                raise RFBError(f"the server refused the connection: {self._reason()}")
            offered = list(self._read(count))
        chosen = self._choose(offered)
        if version != (3, 3):
            self._send(bytes([chosen]))
        self.security = chosen
        if chosen == VNC_AUTH:
            challenge = self._read(16)
            self._send(vnc_response(self._password or "", challenge))
        elif chosen == ARD:
            self._ard()
        if chosen != NONE or version == (3, 8):
            result = struct.unpack(">I", self._read(4))[0]
            if result:
                reason = self._reason() if version == (3, 8) else ""
                raise RFBError("the server refused the password" + (f": {reason}" if reason else ""))
        self._send(bytes([1 if self._shared else 0]))
        width, height = struct.unpack(">HH", self._read(4))
        self._read(16)
        self.name = self._read(struct.unpack(">I", self._read(4))[0]).decode("utf-8", "replace")
        self.size = (width, height)
        self._frame = bytearray(width * height * 4)
        # 32 bits a pixel, little-endian blue, green, red, unused: Pillow's "BGRX".
        self._send(struct.pack(">B3xBBBBHHHBBB3x", 0, 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
        self._encodings()

    def _encodings(self) -> None:
        """SetEncodings: raw pixels, copied rectangles, new screen sizes. QEMU also decides
        on it whether the client's points are absolute (a tablet the guest drives) or
        relative, and keeps that until the next one: sent again before pointer input, it
        follows the guest's tablet coming up after the client connected."""
        encodings = (RAW, COPY_RECT, DESKTOP_SIZE)
        self._send(struct.pack(">BxH", 2, len(encodings)) + b"".join(struct.pack(">i", e) for e in encodings))

    def _choose(self, offered) -> int:
        wanted = [ARD] if self._user else []
        wanted += [VNC_AUTH] if self._password else []
        wanted += [NONE]
        for kind in wanted:
            if kind in offered:
                return kind
        raise RFBError(f"no security type in common: the server offers {offered}, this client has "
                       f"{wanted} with the credentials it was given")

    def _ard(self) -> None:
        """Apple Remote Desktop authentication: Diffie-Hellman, then the user and password
        (64 bytes each, NUL-ended, random after) under AES-128 keyed by the MD5 of the
        shared secret."""
        generator, length = struct.unpack(">HH", self._read(4))
        prime = int.from_bytes(self._read(length), "big")
        theirs = int.from_bytes(self._read(length), "big")
        private = int.from_bytes(os.urandom(length), "big") % (prime - 2) + 1
        mine = pow(generator, private, prime)
        secret = pow(theirs, private, prime).to_bytes(length, "big")
        key = hashlib.md5(secret).digest()
        credentials = b""
        for value in (self._user or "", self._password or ""):
            data = value.encode("utf-8")[:63] + b"\0"
            credentials += data + os.urandom(64 - len(data))
        self._send(aes128_ecb(key, credentials) + mine.to_bytes(length, "big"))

    def _reason(self) -> str:
        try:
            return self._read(struct.unpack(">I", self._read(4))[0]).decode("utf-8", "replace")
        except (OSError, RFBError):
            return ""

    # -- the screen ----------------------------------------------------------------------

    def refresh(self, incremental: bool = False) -> None:
        """Ask for the screen and take in the update that answers."""
        with self._lock:
            for _ in range(4):
                size = self.size
                self._send(struct.pack(">BBHHHH", 3, 1 if incremental else 0, 0, 0, *size))
                while not self._message():
                    pass
                if self.size == size:
                    return
                # The screen changed size: its new picture comes with the next update.
                incremental = False

    def picture(self):
        """The whole screen, as a PIL RGB image."""
        from PIL import Image

        with self._lock:
            self.refresh()
            width, height = self.size
            return Image.frombuffer("RGB", (width, height), bytes(self._frame), "raw", "BGRX", 0, 1)

    def _message(self) -> bool:
        """Read one server message; True when it was a screen update."""
        kind = self._read(1)[0]
        if kind == 0:
            count = struct.unpack(">xH", self._read(3))[0]
            for _ in range(count):
                x, y, width, height, encoding = struct.unpack(">HHHHi", self._read(12))
                if encoding == RAW:
                    self._paint(x, y, width, height, self._read(width * height * 4))
                elif encoding == COPY_RECT:
                    source = struct.unpack(">HH", self._read(4))
                    self._copy(source, x, y, width, height)
                elif encoding == DESKTOP_SIZE:
                    self.size = (width, height)
                    self._frame = bytearray(width * height * 4)
                else:
                    raise RFBError(f"the server sent encoding {encoding}, which was not asked for")
            return True
        if kind == 1:
            count = struct.unpack(">xHH", self._read(5))[1]
            self._read(count * 6)
        elif kind == 2:
            pass
        elif kind == 3:
            self._read(3)
            self._read(struct.unpack(">I", self._read(4))[0])
        else:
            raise RFBError(f"unknown server message {kind}")
        return False

    def _paint(self, x, y, width, height, pixels) -> None:
        stride, row = self.size[0] * 4, width * 4
        for line in range(height):
            start = (y + line) * stride + x * 4
            self._frame[start:start + row] = pixels[line * row:(line + 1) * row]

    def _copy(self, source, x, y, width, height) -> None:
        stride, row = self.size[0] * 4, width * 4
        lines = [bytes(self._frame[(source[1] + line) * stride + source[0] * 4:][:row]) for line in range(height)]
        for line, data in enumerate(lines):
            start = (y + line) * stride + x * 4
            self._frame[start:start + row] = data

    # -- input ---------------------------------------------------------------------------

    def move(self, x, y) -> None:
        with self._lock:
            self._encodings()
            self._pointer_event(self._buttons, x, y)

    def click(self, x, y, button="left", count=1) -> None:
        bit = BUTTONS[button]
        with self._lock:
            self._encodings()
            self._pointer_event(self._buttons, x, y)
            for _ in range(int(count)):
                self._pointer_event(self._buttons | bit, x, y)
                time.sleep(0.02)
                self._pointer_event(self._buttons & ~bit, x, y)
                time.sleep(0.04)

    def drag(self, x, y, to_x, to_y, seconds=0.4, button="left") -> None:
        bit = BUTTONS[button]
        steps = max(2, int(float(seconds) / 0.02))
        with self._lock:
            self._encodings()
            self._pointer_event(self._buttons, x, y)
            self._pointer_event(self._buttons | bit, x, y)
            for step in range(1, steps + 1):
                time.sleep(float(seconds) / steps)
                self._pointer_event(self._buttons | bit, x + (to_x - x) * step / steps, y + (to_y - y) * step / steps)
            self._pointer_event(self._buttons & ~bit, to_x, to_y)

    def scroll(self, direction, amount=1, x=None, y=None) -> None:
        bit = WHEEL[direction]
        with self._lock:
            self._encodings()
            if x is not None:
                self._pointer_event(self._buttons, x, y)
            px, py = self._pointer
            for _ in range(max(1, int(amount))):
                self._pointer_event(self._buttons | bit, px, py)
                self._pointer_event(self._buttons, px, py)
                time.sleep(0.01)

    def keys(self, names) -> None:
        """Press the keys together, release them in reverse."""
        codes = [keysym(name) for name in names]
        with self._lock:
            for code in codes:
                self._key_event(True, code)
            time.sleep(0.03)
            for code in reversed(codes):
                self._key_event(False, code)

    def type(self, text) -> None:
        """Type the text a character at a time."""
        with self._lock:
            for char in str(text):
                code = char_keysym(char)
                self._key_event(True, code)
                self._key_event(False, code)
                time.sleep(0.005)

    @property
    def pointer(self) -> tuple[int, int]:
        return self._pointer

    def _pointer_event(self, buttons, x, y) -> None:
        width, height = self.size
        x = min(max(int(round(x)), 0), max(width - 1, 0))
        y = min(max(int(round(y)), 0), max(height - 1, 0))
        with self._lock:
            self._send(struct.pack(">BBHH", 5, buttons & 0xFF, x, y))
            # The wheel's buttons are pressed and released at once; the others stay held.
            self._buttons = buttons & 7
            self._pointer = (x, y)

    def _key_event(self, down, code) -> None:
        self._send(struct.pack(">BBxxI", 4, 1 if down else 0, code))

    # -- bytes ---------------------------------------------------------------------------

    def _send(self, data: bytes) -> None:
        if self._socket is None:
            raise RFBError("not connected")
        self._socket.sendall(data)

    def _read(self, count: int) -> bytes:
        if self._socket is None:
            raise RFBError("not connected")
        data = bytearray()
        while len(data) < count:
            chunk = self._socket.recv(min(count - len(data), 1 << 20))
            if not chunk:
                raise RFBError("the server closed the connection")
            data += chunk
        return bytes(data)


# -- VNC authentication: DES ---------------------------------------------------------------

def vnc_response(password: str, challenge: bytes) -> bytes:
    """The answer to a VNC challenge: each 8-byte half DES-encrypted with the password (its
    first 8 bytes, NUL-padded) as the key, every key byte's bits reversed."""
    key = password.encode("latin-1", "replace")[:8].ljust(8, b"\0")
    key = bytes(int(f"{byte:08b}"[::-1], 2) for byte in key)
    return des_encrypt(key, challenge[:8]) + des_encrypt(key, challenge[8:16])


_IP = (58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4, 62, 54, 46, 38, 30, 22, 14, 6, 64, 56, 48, 40,
       32, 24, 16, 8, 57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3, 61, 53, 45, 37, 29, 21, 13, 5, 63,
       55, 47, 39, 31, 23, 15, 7)
_FP = (40, 8, 48, 16, 56, 24, 64, 32, 39, 7, 47, 15, 55, 23, 63, 31, 38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13,
       53, 21, 61, 29, 36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27, 34, 2, 42, 10, 50, 18, 58, 26,
       33, 1, 41, 9, 49, 17, 57, 25)
_E = (32, 1, 2, 3, 4, 5, 4, 5, 6, 7, 8, 9, 8, 9, 10, 11, 12, 13, 12, 13, 14, 15, 16, 17, 16, 17, 18, 19, 20, 21, 20,
      21, 22, 23, 24, 25, 24, 25, 26, 27, 28, 29, 28, 29, 30, 31, 32, 1)
_P = (16, 7, 20, 21, 29, 12, 28, 17, 1, 15, 23, 26, 5, 18, 31, 10, 2, 8, 24, 14, 32, 27, 3, 9, 19, 13, 30, 6, 22, 11,
      4, 25)
_PC1 = (57, 49, 41, 33, 25, 17, 9, 1, 58, 50, 42, 34, 26, 18, 10, 2, 59, 51, 43, 35, 27, 19, 11, 3, 60, 52, 44, 36,
        63, 55, 47, 39, 31, 23, 15, 7, 62, 54, 46, 38, 30, 22, 14, 6, 61, 53, 45, 37, 29, 21, 13, 5, 28, 20, 12, 4)
_PC2 = (14, 17, 11, 24, 1, 5, 3, 28, 15, 6, 21, 10, 23, 19, 12, 4, 26, 8, 16, 7, 27, 20, 13, 2, 41, 52, 31, 37, 47,
        55, 30, 40, 51, 45, 33, 48, 44, 49, 39, 56, 34, 53, 46, 42, 50, 36, 29, 32)
_SHIFTS = (1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1)
_S = (
    (14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7, 0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8,
     4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0, 15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13),
    (15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10, 3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5,
     0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15, 13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9),
    (10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8, 13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1,
     13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7, 1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12),
    (7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15, 13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9,
     10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4, 3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14),
    (2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9, 14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6,
     4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14, 11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3),
    (12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11, 10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8,
     9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6, 4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13),
    (4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1, 13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6,
     1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2, 6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12),
    (13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7, 1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2,
     7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8, 2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11))


def _bits(data: bytes) -> list[int]:
    return [(byte >> (7 - i)) & 1 for byte in data for i in range(8)]


def _permute(bits, table) -> list[int]:
    return [bits[i - 1] for i in table]


def des_encrypt(key: bytes, block: bytes) -> bytes:
    """One 8-byte block under single DES (FIPS 46-3), encryption only."""
    keys = _permute(_bits(key), _PC1)
    left_key, right_key = keys[:28], keys[28:]
    rounds = []
    for shift in _SHIFTS:
        left_key, right_key = left_key[shift:] + left_key[:shift], right_key[shift:] + right_key[:shift]
        rounds.append(_permute(left_key + right_key, _PC2))
    bits = _permute(_bits(block), _IP)
    left, right = bits[:32], bits[32:]
    for subkey in rounds:
        mixed = [a ^ b for a, b in zip(_permute(right, _E), subkey)]
        out = []
        for box in range(8):
            six = mixed[box * 6:box * 6 + 6]
            value = _S[box][(six[0] << 5 | six[5] << 4) | (six[1] << 3 | six[2] << 2 | six[3] << 1 | six[4])]
            out += [(value >> (3 - i)) & 1 for i in range(4)]
        left, right = right, [a ^ b for a, b in zip(left, _permute(out, _P))]
    bits = _permute(right + left, _FP)
    return bytes(int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, 64, 8))


# -- Apple Remote Desktop authentication: AES-128 ------------------------------------------

def _aes_tables():
    sbox = [0] * 256
    p = q = 1
    while True:
        # p runs over the multiplicative group (times 3), q over the inverses (divided by 3).
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        rotated = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        sbox[p] = (rotated ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


_SBOX = _aes_tables()


def _xtime(value: int) -> int:
    value <<= 1
    return (value ^ 0x1B) & 0xFF if value & 0x100 else value


def _aes_keys(key: bytes) -> list[list[int]]:
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        word = list(words[i - 1])
        if i % 4 == 0:
            word = [_SBOX[b] for b in word[1:] + word[:1]]
            word[0] ^= rcon
            rcon = _xtime(rcon)
        words.append([a ^ b for a, b in zip(words[i - 4], word)])
    return [sum(words[r * 4:r * 4 + 4], []) for r in range(11)]


def aes128_encrypt_block(keys, block: bytes) -> bytes:
    state = [b ^ k for b, k in zip(block, keys[0])]
    for round_number in range(1, 11):
        state = [_SBOX[b] for b in state]
        # Rows shift left by their index; the state is column-major (byte i: row i % 4).
        state = [state[(i + 4 * (i % 4)) % 16] for i in range(16)]
        if round_number < 10:
            mixed = []
            for c in range(4):
                a = state[c * 4:c * 4 + 4]
                total = a[0] ^ a[1] ^ a[2] ^ a[3]
                mixed += [a[i] ^ total ^ _xtime(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
            state = mixed
        state = [b ^ k for b, k in zip(state, keys[round_number])]
    return bytes(state)


def aes128_ecb(key: bytes, data: bytes) -> bytes:
    """`data` (a multiple of 16 bytes) under AES-128 in ECB mode (FIPS 197), encryption only."""
    keys = _aes_keys(key)
    return b"".join(aes128_encrypt_block(keys, data[i:i + 16]) for i in range(0, len(data), 16))
