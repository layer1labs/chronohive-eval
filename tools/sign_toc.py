#!/usr/bin/env python3
# © 2026 Layer1Labs Silicon Inc. All rights reserved.
# CONFIDENTIAL — ChronoHive Evaluation Package. Licensed solely for
# evaluation under the ChronoHive Terms of Confidentiality (TOC.md) and
# the ChronoHive Evaluation License (LICENSE). Do not distribute.
"""Sign the ChronoHive Terms of Confidentiality (TOC).

Executing the TOC is required before the eval API serves any request:
the API verifies your signature and only then activates your API key.

Flow:
  1. Read the canonical TOC text (local TOC.md, or fetched from the
     API's GET /v1/toc so you sign exactly what the server enforces).
  2. Generate an ed25519 signing key (or reuse --privkey).
  3. Sign the TOC hash bound to your API key id and identity.
  4. Optionally submit the acceptance token to POST /v1/toc/accept.

Usage:
  python3 tools/sign_toc.py --toc TOC.md --key-id eval-01 \\
      --name "Jane Doe" --org "Example Corp" --email jane@example.com
  python3 tools/sign_toc.py --api-url https://api.layer1labs.ai --api-key KEY \\
      --key-id eval-01 --submit   # prompts for identity, submits

The private key is written with mode 600. Keep it: it is your proof of
execution. The acceptance token itself contains no secrets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ed25519
import toc_common

# The eval API sits behind Cloudflare, which blocks Python's default
# urllib User-Agent (HTTP 1010). Identify as the eval client instead.
USER_AGENT = "ChronoHive-Eval-Client/0.1.0"


def read_toc_text(*, toc_path: str | None, api_url: str | None) -> tuple[bytes, str]:
    """Return (toc_bytes, toc_sha256) from a file or the API."""
    if api_url:
        url = api_url.rstrip("/") + "/v1/toc"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
        text = payload["toc_text"]
        data = text.encode("utf-8")
        sha = payload["toc_sha256"]
        if hashlib.sha256(data).hexdigest() != sha:
            raise RuntimeError("server TOC text does not match its sha256")
        return data, sha
    if not toc_path:
        raise RuntimeError("need --toc or --api-url")
    with open(toc_path, "rb") as fh:
        data = fh.read()
    return data, hashlib.sha256(data).hexdigest()


def load_or_create_privkey(path: str | None) -> tuple[bytes, str | None]:
    if path and os.path.exists(path):
        with open(path, "rb") as fh:
            sk = fh.read().strip()
        if len(sk) != 32:
            raise RuntimeError(f"{path}: not a 32-byte ed25519 secret key")
        return sk, path
    sk, _pk = ed25519.generate_keypair()
    return sk, None


def save_privkey(sk: bytes, path: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(sk)


def build_acceptance(*, toc_sha256: str, key_id: str, signer_name: str,
                     organization: str, email: str,
                     secret_key: bytes) -> dict:
    return toc_common.build_token(
        toc_sha256=toc_sha256, key_id=key_id, signer_name=signer_name,
        organization=organization, email=email,
        timestamp=int(time.time()), secret_key=secret_key)


def submit_acceptance(api_url: str, api_key: str, token: dict) -> dict:
    req = urllib.request.Request(
        api_url.rstrip("/") + "/v1/toc/accept",
        data=json.dumps(token).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api_key,
                 "User-Agent": USER_AGENT},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return {"status": resp.status, "body": json.load(resp)}


def _prompt(text: str) -> str:
    value = input(text + ": ").strip()
    if not value:
        raise RuntimeError(f"{text} is required")
    return value


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--toc", help="path to the canonical TOC.md")
    src.add_argument("--api-url", help="API base URL (fetches canonical TOC)")
    ap.add_argument("--key-id", required=True, help="your API key id")
    ap.add_argument("--name", help="legal name of the signer")
    ap.add_argument("--org", help="company / institution")
    ap.add_argument("--email", help="contact email")
    ap.add_argument("--privkey",
                    help="existing 32-byte ed25519 private key file "
                         "(generated if omitted)")
    ap.add_argument("--save-privkey", default="toc_signing.key",
                    help="where to write a fresh private key")
    ap.add_argument("--out", default="toc_acceptance.json",
                    help="where to write the acceptance token")
    ap.add_argument("--api-key", help="API key (required with --submit)")
    ap.add_argument("--submit", action="store_true",
                    help="POST the token to /v1/toc/accept immediately")
    args = ap.parse_args()

    toc_bytes, toc_sha256 = read_toc_text(toc_path=args.toc,
                                          api_url=args.api_url)
    print(f"TOC: {len(toc_bytes)} bytes, sha256={toc_sha256}")

    name = args.name or _prompt("Legal name")
    org = args.org or _prompt("Organization")
    email = args.email or _prompt("Email")

    sk, reused = load_or_create_privkey(args.privkey)
    if reused:
        print(f"reusing signing key from {reused}")
    else:
        save_privkey(sk, args.save_privkey)
        print(f"new signing key written to {args.save_privkey} (mode 600)")

    token = build_acceptance(toc_sha256=toc_sha256, key_id=args.key_id,
                             signer_name=name, organization=org, email=email,
                             secret_key=sk)
    ok, reason = toc_common.verify_token(token, toc_sha256, args.key_id)
    if not ok:  # self-check before handing it out
        raise RuntimeError(f"self-verification failed: {reason}")

    with open(args.out, "w") as fh:
        json.dump(token, fh, indent=2)
        fh.write("\n")
    print(f"acceptance token written to {args.out}")
    print(f"public key: {token['public_key']}")

    if args.submit:
        if not args.api_url or not args.api_key:
            raise RuntimeError("--submit needs --api-url and --api-key")
        result = submit_acceptance(args.api_url, args.api_key, token)
        print(f"server response: {result['status']}")
        print(json.dumps(result["body"], indent=2))


if __name__ == "__main__":
    main()
