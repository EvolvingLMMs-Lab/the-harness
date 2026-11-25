"""An identity's key pair: Ed25519 (RFC 8032) in the standard library, so the core and this
package need nothing compiled. An environment that speaks the Agent Space Protocol asks a
participant to sign as its identity; the private key never leaves this computer except in
an encrypted backup. Signing is slow in pure Python (milliseconds), which is fine for the
few signatures a connection needs."""
import base64
import hashlib
import os

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _recover_x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x * x - x2) % _P:
        return None
    if x & 1 != sign:
        x = _P - x
    return x


_GY = 4 * pow(5, _P - 2, _P) % _P
_G = (_recover_x(_GY, 0), _GY, 1, _recover_x(_GY, 0) * _GY % _P)


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    a_ = (y1 - x1) * (y2 - x2) % _P
    b_ = (y1 + x1) * (y2 + x2) % _P
    c = 2 * t1 * t2 * _D % _P
    d = 2 * z1 * z2 % _P
    e, f, g, h = b_ - a_, d - c, d + c, b_ + a_
    return e * f % _P, g * h % _P, f * g % _P, e * h % _P


def _mul(scalar, point):
    result = (0, 1, 1, 0)
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _equal(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _encode(point):
    zinv = pow(point[2], _P - 2, _P)
    x, y = point[0] * zinv % _P, point[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decode(data):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _hint(data):
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def _secret(seed):
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return scalar, digest[32:]


def public_key(seed: bytes) -> bytes:
    """The 32-byte public key of a 32-byte private seed."""
    return _encode(_mul(_secret(seed)[0], _G))


def sign(seed: bytes, message: bytes) -> bytes:
    """The 64-byte signature of `message` under the seed's key."""
    scalar, prefix = _secret(seed)
    public = _encode(_mul(scalar, _G))
    r = _hint(prefix + message) % _L
    big_r = _encode(_mul(r, _G))
    s = (r + _hint(big_r + public + message) * scalar) % _L
    return big_r + int.to_bytes(s, 32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """Whether `signature` is the key's signature of `message`."""
    if len(signature) != 64:
        return False
    point, big_r = _decode(public), _decode(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if point is None or big_r is None or s >= _L:
        return False
    h = _hint(signature[:32] + public + message) % _L
    return _equal(_mul(s, _G), _add(big_r, _mul(h, point)))


def generate() -> tuple[bytes, bytes]:
    """A new (seed, public key)."""
    seed = os.urandom(32)
    return seed, public_key(seed)


def fingerprint(public: bytes) -> str:
    """How a person compares two keys: SHA256 of the public key, as ssh-keygen -l shows it."""
    return "SHA256:" + base64.b64encode(hashlib.sha256(public).digest()).decode().rstrip("=")
