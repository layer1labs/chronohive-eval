# © 2026 Layer1Labs Silicon Inc. All rights reserved.
# CONFIDENTIAL — ChronoHive Evaluation Package. Licensed solely for
# evaluation under the ChronoHive Terms of Confidentiality (TOC.md) and
# the ChronoHive Evaluation License (LICENSE). Do not distribute.
"""Pure-Python Ed25519 digital signatures (RFC 8032).

Dependency-free on purpose: the TOC acceptance flow must work for any
evaluator and inside the API container with nothing to install.
Validated by cross-checking signatures against an independent
implementation (see scripts/check.py). Do not hand-modify the arithmetic.
"""

from __future__ import annotations

import hashlib
import secrets

# Field and group parameters (RFC 8032 section 5.1).
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _xrecover(y: int) -> int:
    """Recover the x-coordinate for a curve point with the given y."""
    xx = (y * y - 1) * _inv(_D * y * y + 1) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _SQRT_M1) % _P
    if x & 1:
        x = _P - x
    return x


# Extended twisted-Edwards coordinates (X, Y, Z, T); affine x = X/Z, y = Y/Z.
_IDENTITY = (0, 1, 1, 0)


def _edwards_add(p: tuple, q: tuple) -> tuple:
    (x1, y1, z1, t1) = p
    (x2, y2, z2, t2) = q
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = t1 * (2 * _D % _P) * t2 % _P
    d = z1 * 2 * z2 % _P
    e = (b - a) % _P
    f = (d - c) % _P
    g = (d + c) % _P
    h = (b + a) % _P
    return ((e * f) % _P, (g * h) % _P, (f * g) % _P, (e * h) % _P)


def _to_affine(p: tuple) -> tuple:
    x, y, z, _ = p
    zi = _inv(z)
    return ((x * zi) % _P, (y * zi) % _P)


def _eq(p: tuple, q: tuple) -> bool:
    return _to_affine(p) == _to_affine(q)


def _scalarmult(p: tuple, e: int) -> tuple:
    # Binary double-and-add. Not constant-time; signing here is an
    # interactive, low-frequency operation, not an oracle-exposed one.
    q = _IDENTITY
    while e > 0:
        if e & 1:
            q = _edwards_add(q, p)
        p = _edwards_add(p, p)
        e >>= 1
    return q


# Base point: y = 4/5 (RFC 8032 section 5.1).
_BASE_Y = (4 * _inv(5)) % _P
_BASE_X = _xrecover(_BASE_Y)
_BASE = (_BASE_X, _BASE_Y, 1, (_BASE_X * _BASE_Y) % _P)


def _encodepoint(p: tuple) -> bytes:
    x, y = _to_affine(p)
    return ((y | ((x & 1) << 255))).to_bytes(32, "little")


def _decodepoint(s: bytes) -> tuple:
    if len(s) != 32:
        raise ValueError("point must be 32 bytes")
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    sign = (s[31] >> 7) & 1
    if y >= _P:
        raise ValueError("y out of range")
    x = _xrecover(y)
    if (x & 1) != sign:
        x = _P - x
    # On-curve check: -x^2 + y^2 = 1 + d*x^2*y^2.
    if ((-x * x + y * y - 1 - _D * x * x * y * y) % _P) != 0:
        raise ValueError("point not on curve")
    return (x, y, 1, (x * y) % _P)


def _encodeint(x: int) -> bytes:
    return x.to_bytes(32, "little")


def _decodeint(s: bytes) -> int:
    return int.from_bytes(s, "little")


def _hint(data: bytes) -> int:
    return _decodeint(hashlib.sha512(data).digest())


def _clamp(h: bytes) -> int:
    a = bytearray(h)
    a[0] &= 248
    a[31] &= 63
    a[31] |= 64
    return _decodeint(bytes(a))


def generate_keypair() -> tuple[bytes, bytes]:
    """Return (secret_key, public_key), 32 bytes each."""
    sk = secrets.token_bytes(32)
    return sk, publickey(sk)


def publickey(secret_key: bytes) -> bytes:
    """Derive the 32-byte public key from a 32-byte secret key."""
    if len(secret_key) != 32:
        raise ValueError("secret key must be 32 bytes")
    a = _clamp(hashlib.sha512(secret_key).digest()[:32])
    return _encodepoint(_scalarmult(_BASE, a))


def sign(secret_key: bytes, message: bytes) -> bytes:
    """Sign a message; returns the 64-byte signature."""
    if len(secret_key) != 32:
        raise ValueError("secret key must be 32 bytes")
    h = hashlib.sha512(secret_key).digest()
    a = _clamp(h[:32])
    pk = _encodepoint(_scalarmult(_BASE, a))
    r = _hint(h[32:] + message) % _L
    big_r = _encodepoint(_scalarmult(_BASE, r))
    s = (_hint(big_r + pk + message) * a + r) % _L
    return big_r + _encodeint(s)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify a signature. Returns True/False, never raises."""
    try:
        if len(public_key) != 32 or len(signature) != 64:
            return False
        a_point = _decodepoint(public_key)
        # Reject small-order public keys.
        if not _eq(_scalarmult(a_point, _L), _IDENTITY):
            return False
        big_r = _decodepoint(signature[:32])
        s = _decodeint(signature[32:])
        if s >= _L:
            return False
        h = _hint(signature[:32] + public_key + message)
        lhs = _scalarmult(_BASE, s)
        rhs = _edwards_add(big_r, _scalarmult(a_point, h))
        return _eq(lhs, rhs)
    except (ValueError, AssertionError):
        return False
