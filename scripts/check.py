#!/usr/bin/env python3
# © 2026 Layer1Labs Silicon Inc. All rights reserved.
# CONFIDENTIAL — ChronoHive Evaluation Package. Licensed solely for
# evaluation under the ChronoHive Terms of Confidentiality (TOC.md) and
# the ChronoHive Evaluation License (LICENSE). Do not distribute.
"""chronohive-eval repository gate. Fails loudly on any regression.

  1. Byte-compile every Python file in the repo.
  2. Ed25519: reproduce the RFC 8032 test vectors byte-identically,
     plus round-trip and tamper-rejection checks.
  3. Branding sweep: no vendor mentions, no RCPH, no TODO/FIXME/HACK
     markers, no internal engineering notes on public surfaces.
  4. Compile client --check: complete LF project file map, pinned lfc
     validation gate, request-schema check, reference-blob verification.

Needs the pinned lfc on PATH or $LFC (a JRE for lfc via $JAVA_HOME);
CI installs it (see .github/workflows/ci.yml).

Usage: python3 scripts/check.py
"""

from __future__ import annotations

import compileall
import json
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

# Vendor-neutrality + public-surface hygiene. (?i) applied per pattern.
BANNED_PATTERNS = [
    r"\bddn\b",            # vendor name — the package is vendor-neutral
    r"\brcph\b",           # never public
    r"\bTODO\b",
    r"\bFIXME\b",
    r"\bHACK\b",
    r"\bXXX\b",
    r"do not (merge|ship|publish|distribute)[^.]{0,60}(yet|todo)",
]
# Files the sweep reads (text sources shipped in the package).
SWEEP_EXTENSIONS = {".py", ".md", ".sh", ".lf", ".json", ".yml", ".yaml",
                    ""}  # "" covers extensionless files like Dockerfile
SWEEP_SKIP_DIRS = {".git", "__pycache__", ".vscode"}
# This script itself is skipped: it literally defines the banned patterns
# it enforces (the definitions are the enforcement mechanism, not violations).
SWEEP_SKIP_FILES = {"rfc8032_test_vectors.json", "check.py"}


def step(name: str) -> None:
    print(f"\n=== {name} ===", flush=True)


def check_compile() -> None:
    step("compile")
    ok = compileall.compile_dir(REPO_ROOT, quiet=1, force=True,
                                rx=re.compile(r"/\.git/"))
    if not ok:
        raise RuntimeError("compile failed")


def check_ed25519() -> None:
    step("ed25519 RFC 8032 vectors")
    import ed25519
    vectors = json.load(open(os.path.join(
        REPO_ROOT, "tools", "rfc8032_test_vectors.json")))
    assert len(vectors) >= 3, "need at least 3 RFC vectors"
    for v in vectors:
        skb, msgb = bytes.fromhex(v["sk"]), bytes.fromhex(v["msg"])
        pkb, sigb = bytes.fromhex(v["pk"]), bytes.fromhex(v["sig"])
        assert ed25519.publickey(skb) == pkb, f"TEST {v['n']}: pubkey"
        assert ed25519.sign(skb, msgb) == sigb, f"TEST {v['n']}: signature"
        assert ed25519.verify(pkb, msgb, sigb), f"TEST {v['n']}: verify"
        bad = bytearray(sigb)
        bad[0] ^= 1
        assert not ed25519.verify(pkb, msgb, bytes(bad)), "tamper accepted"
    for msg in (b"", b"hello", os.urandom(500)):
        sk, pk = ed25519.generate_keypair()
        sig = ed25519.sign(sk, msg)
        assert ed25519.verify(pk, msg, sig)
    print(f"{len(vectors)} RFC vectors byte-identical; "
          "round-trip + tamper rejection OK")


def check_branding() -> None:
    step("branding sweep")
    patterns = [(re.compile(p, re.IGNORECASE), p) for p in BANNED_PATTERNS]
    violations: list[str] = []
    for root, dirs, names in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in SWEEP_SKIP_DIRS]
        for name in sorted(names):
            if name in SWEEP_SKIP_FILES or name.endswith(".chb.reference"):
                continue
            _stem, ext = os.path.splitext(name)
            if ext not in SWEEP_EXTENSIONS:
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except UnicodeDecodeError:
                continue
            for rx, pattern in patterns:
                for match in rx.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    rel = os.path.relpath(path, REPO_ROOT)
                    violations.append(f"{rel}:{line}: /{pattern}/")
    if violations:
        raise RuntimeError("branding sweep found banned content:\n  " +
                           "\n  ".join(violations))
    print("no vendor mentions, no RCPH, no TODO/FIXME/HACK markers")


def check_compile_client() -> None:
    step("compile client --check")
    proc = subprocess.run(
        [sys.executable, "clients/compile_client.py", "--check"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
    print(proc.stdout)
    if proc.returncode != 0:
        raise RuntimeError("compile client --check failed:\n" +
                           proc.stderr[-3000:])


def main() -> None:
    check_compile()
    check_ed25519()
    check_branding()
    check_compile_client()
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
