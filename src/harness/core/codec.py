"""Codecs shared by benchmark workers: episode cursors, outcome tokens, action bounds, data
URLs.

Importable without a simulator, torch or a GPU (image_data_url imports NumPy, and
OpenCV or Pillow, when it is called).
"""

import base64
import math
import secrets
import struct
import zlib


class EpisodeCursor:
    """Reject a repeated motion without guessing whether the simulator applied it."""

    def __init__(self):
        self.episode_id = None
        self.step = None

    def start(self, episode_id: str, step: int = 0) -> None:
        self.episode_id = episode_id
        self.step = step

    def check(self, episode_id: str, step: int) -> None:
        if self.episode_id is None or (episode_id, step) != (self.episode_id, self.step):
            raise ValueError("Stale or missing observation; action was not executed")

    def advance(self) -> int:
        self.step += 1
        return self.step

    def invalidate(self) -> None:
        self.episode_id = None
        self.step = None


class OutcomeToken:
    """The token that reads an episode's outcome (claim_outcome, outcome): one per episode,
    claimed once by the harness after the loop, never by a program. A second claim, an
    outcome asked before the claim and a wrong token raise PermissionError; the token is
    compared in constant time. A new episode gets a new OutcomeToken."""

    def __init__(self):
        self._token = None

    def claim(self) -> str:
        if self._token is not None:
            raise PermissionError("The outcome token for this episode was already claimed")
        self._token = secrets.token_hex(16)
        return self._token

    def check(self, token) -> None:
        if self._token is None or not isinstance(token, str) or not secrets.compare_digest(token, self._token):
            raise PermissionError("Invalid outcome token")



def finite_bounds(low, high):
    bounds = []
    for start, stop in zip(low, high, strict=True):
        lower, upper = float(start), float(stop)
        if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
            raise ValueError("Action bounds must be finite and ordered")
        bounds.append((lower, upper))
    return bounds



def validate_vector(values, bounds, label="position"):
    """A list of finite values within its per-component bounds."""
    if not isinstance(values, list) or len(values) != len(bounds):
        raise ValueError(f"{label} must contain {len(bounds)} finite numbers")
    command = []
    for value, (lower, upper) in zip(values, bounds, strict=True):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{label} values must be finite numbers")
        number = float(value)
        if number < lower or number > upper:
            raise ValueError(f"{label} value {number} is outside [{lower}, {upper}]")
        command.append(number)
    return command



def fit_into(inner, outer):
    """Where a picture of size `inner` (width, height) sits in one of size `outer`: (left,
    top, width, height), as large as it fits, centred (a monitor of another shape in a
    screenshot, a recorded screen in a replay's frame)."""
    scale = min(outer[0] / inner[0], outer[1] / inner[1])
    width, height = max(1, round(inner[0] * scale)), max(1, round(inner[1] * scale))
    return (outer[0] - width) // 2, (outer[1] - height) // 2, width, height


def data_url(payload, mime="image/png"):
    if not payload:
        raise ValueError("Image payload is empty")
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def image_data_url(array, fmt="jpeg", quality=95):
    """An HxWx3 RGB (or HxW grayscale) array as a data URL of a `fmt` (jpeg or png) image,
    JPEG at `quality`: OpenCV encodes it, or Pillow where OpenCV is not installed (an
    environment may have Pillow and NumPy only)."""
    import numpy as np

    array = np.asarray(array)
    if not (array.ndim == 2 or (array.ndim == 3 and array.shape[-1] == 3)):
        raise ValueError("images must be HxWx3 RGB (or HxW grayscale) arrays")
    fmt = {"jpg": "jpeg"}.get(fmt.lower(), fmt.lower())
    if fmt not in ("jpeg", "png"):
        raise ValueError(f"image format {fmt!r}: jpeg or png")
    array = array.astype(np.uint8)
    try:
        import cv2
    except ImportError:
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.fromarray(array, "RGB" if array.ndim == 3 else "L").save(
            buffer, format=fmt.upper(), **({"quality": quality} if fmt == "jpeg" else {}))
        return data_url(buffer.getvalue(), f"image/{fmt}")
    ok, encoded = cv2.imencode(".jpg" if fmt == "jpeg" else ".png",
                               cv2.cvtColor(array, cv2.COLOR_RGB2BGR) if array.ndim == 3 else array,
                               [cv2.IMWRITE_JPEG_QUALITY, int(quality)] if fmt == "jpeg" else [])
    if not ok:
        raise ValueError("Could not encode the image")
    return data_url(encoded.tobytes(), f"image/{fmt}")


def decode_data_url(url) -> bytes:
    """The bytes a base64 data URL (data:<type>;base64,<payload>) carries."""
    header, comma, payload = str(url).partition(",")
    if not (header.startswith("data:") and header.endswith(";base64") and comma):
        raise ValueError("not a base64 data URL")
    return base64.b64decode(payload, validate=True)


def encode_png(width, height, rgb):
    """Encode tightly packed RGB bytes as a PNG."""
    if width < 1 or height < 1:
        raise ValueError("Image dimensions must be positive")
    expected = width * height * 3
    if len(rgb) != expected:
        raise ValueError("RGB byte count does not match the image size")
    raw = b"".join(
        b"\x00" + rgb[row * width * 3:(row + 1) * width * 3]
        for row in range(height)
    )

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

