"""TOC acceptance token: the canonical message format shared by the
signing tool (tools/sign_toc.py) and the API server.

Both sides MUST build/verify through these functions. Never reimplement
the format inline: a mismatch silently breaks acceptance verification.

An acceptance token is a JSON object:

    {
      "protocol":      "CHRONOHIVE-TOC-ACCEPT/v1",
      "toc_sha256":    "<hex sha256 of the exact TOC.md bytes the signer read>",
      "key_id":        "<API key id the acceptance is bound to>",
      "signer_name":   "<legal name of the person executing the TOC>",
      "organization":  "<company / institution>",
      "email":         "<contact email>",
      "timestamp":     <unix time of signing>,
      "public_key":    "<hex ed25519 public key>",
      "signature":     "<hex ed25519 signature over the canonical message>"
    }

The signature covers the canonical message below, which binds the TOC
hash, the API key id, and the signer's identity together: the token
cannot be transplanted onto a different TOC text or a different key.
"""

from __future__ import annotations

import ed25519
import time

PROTOCOL = "CHRONOHIVE-TOC-ACCEPT/v1"

# Timestamp bounds enforced by verify_token. The signing timestamp is
# client-supplied, so the server bounds it: tokens dated more than this
# far in the future are rejected (10 minutes of clock skew is tolerated),
# and timestamps before 2020-01-01 are rejected as implausible. The
# authoritative execution time is the server's own accepted_at, recorded
# at accept time — never the client's timestamp.
_MAX_FUTURE_SKEW_S = 600
_MIN_TIMESTAMP = 1577836800  # 2020-01-01T00:00:00Z

_REQUIRED_FIELDS = ("protocol", "toc_sha256", "key_id", "signer_name",
                    "organization", "email", "timestamp", "public_key",
                    "signature")


def canonical_message(toc_sha256: str, key_id: str, signer_name: str,
                      organization: str, email: str, timestamp: int) -> bytes:
    fields = [PROTOCOL, toc_sha256, key_id, signer_name, organization,
              email, str(timestamp)]
    names = ["protocol"] + list(_REQUIRED_FIELDS[1:7])
    for name, value in zip(names, fields):
        if not value or "\n" in value or "\r" in value:
            raise ValueError(f"invalid or empty field: {name}")
    return ("\n".join(fields) + "\n").encode("utf-8")


def build_token(*, toc_sha256: str, key_id: str, signer_name: str,
                organization: str, email: str, timestamp: int,
                secret_key: bytes) -> dict:
    """Build and sign an acceptance token with a 32-byte ed25519 secret key."""
    msg = canonical_message(toc_sha256, key_id, signer_name,
                            organization, email, timestamp)
    sig = ed25519.sign(secret_key, msg)
    return {
        "protocol": PROTOCOL,
        "toc_sha256": toc_sha256,
        "key_id": key_id,
        "signer_name": signer_name,
        "organization": organization,
        "email": email,
        "timestamp": int(timestamp),
        "public_key": ed25519.publickey(secret_key).hex(),
        "signature": sig.hex(),
    }


def verify_token(token: dict, expected_toc_sha256: str,
                 expected_key_id: str) -> tuple[bool, str]:
    """Verify an acceptance token. Returns (ok, reason)."""
    if not isinstance(token, dict):
        return False, "token must be a JSON object"
    for field in _REQUIRED_FIELDS:
        if field not in token:
            return False, f"missing field: {field}"
    if token.get("protocol") != PROTOCOL:
        return False, "unknown protocol"
    if token["toc_sha256"] != expected_toc_sha256:
        return False, ("toc_sha256 does not match the server's TOC text; "
                       "fetch GET /v1/toc and sign that exact text")
    if token["key_id"] != expected_key_id:
        return False, "token key_id does not match the authenticated API key"
    try:
        ts = int(token["timestamp"])
    except (ValueError, TypeError):
        return False, "malformed timestamp"
    now = int(time.time())
    if ts > now + _MAX_FUTURE_SKEW_S:
        return False, "timestamp is in the future"
    if ts < _MIN_TIMESTAMP:
        return False, "timestamp is implausibly old"
    try:
        msg = canonical_message(token["toc_sha256"], token["key_id"],
                                token["signer_name"], token["organization"],
                                token["email"], ts)
        pk = bytes.fromhex(token["public_key"])
        sig = bytes.fromhex(token["signature"])
    except (ValueError, TypeError) as exc:
        return False, f"malformed token fields: {exc}"
    if not ed25519.verify(pk, msg, sig):
        return False, "signature verification failed"
    return True, "ok"
