#!/usr/bin/env python3
# © 2026 Layer1Labs Silicon Inc. All rights reserved.
# CONFIDENTIAL — ChronoHive Evaluation Package. Licensed solely for
# evaluation under the ChronoHive Terms of Confidentiality (TOC.md) and
# the ChronoHive Evaluation License (LICENSE). Do not distribute.
"""chronohive-eval repository gate. Fails loudly on any regression.

  1. Byte-compile every Python file in the repo.
  2. Ed25519: reproduce the RFC 8032 test vectors byte-identically,
     plus round-trip and tamper-rejection checks.
  3. Forbidden-name sweep: the package is vendor-neutral and never
     names internal programs. The forbidden names are assembled from
     character codes so they never appear as literals in this file.
  4. Header sweep: every shipped source, script, and customer-facing
     document carries the proprietary/confidential banner.
  5. Compile client --check: complete LF project file map, pinned lfc
     validation gate, request-schema check, reference-blob verification.
  6. Negative path-validation tests for the compile client.
  7. Tracked-artifact rejection: no build outputs, key material, or
     removed server snapshots in git.
  8. Secret-hygiene check: no secret-like artifacts on disk (contents
     are never printed).

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
sys.path.insert(0, os.path.join(REPO_ROOT, "clients"))

# Forbidden names, assembled from character codes so the literals never
# appear in any public file (including this one).
_FORBIDDEN = [
    "".join(chr(c) for c in (100, 100, 110)),
    "".join(chr(c) for c in (114, 99, 112, 104)),
]
BANNED_PATTERNS = [
    r"\b" + re.escape(name) + r"\b" for name in _FORBIDDEN
] + [
    r"\bTODO\b",
    r"\bFIXME\b",
    r"\bHACK\b",
    r"\bXXX\b",
    r"do not (merge|ship|publish|distribute)[^.]{0,60}(yet|todo)",
]
# Files the sweep reads (text sources shipped in the package).
SWEEP_EXTENSIONS = {".py", ".md", ".sh", ".lf", ".json", ".yml", ".yaml",
                    ""}  # "" covers extensionless files like Dockerfile
# ".specify" is spec-kit/AEE tooling scaffolding (spec 001 backfill,
# 2026-10-08): third-party tool content, not shipped package sources, so
# the branding/header sweeps do not apply to it. Same for the spec-kit
# generated agent skills under .github/skills (SWEEP_SKIP_PREFIXES).
# Our own specs/ tree is NOT skipped — it is package content and must
# pass both sweeps.
SWEEP_SKIP_DIRS = {".git", "__pycache__", ".vscode", ".specify"}
SWEEP_SKIP_PREFIXES = {os.path.join(".github", "skills")}
# This script itself is skipped: it assembles the forbidden patterns it
# enforces (the assembly is the enforcement mechanism, not a violation).
SWEEP_SKIP_FILES = {"rfc8032_test_vectors.json", "check.py"}

# Proprietary/confidential banner markers. Every shipped text source in
# these extensions must contain one of them.
HEADER_MARKERS = (
    "© 2026 Layer1Labs Silicon Inc.",
    "Layer1Labs Silicon Inc. All rights reserved",
)
HEADER_EXTENSIONS = {".py", ".sh", ".lf", ".yml", ".yaml"}
HEADER_FILES = {"Dockerfile"}  # extensionless files that need the banner
# Customer-facing markdown that must carry the banner.
HEADER_MD_FILES = {
    "README.md", "LICENSE", "NOTICE", "TOC.md",
    "docs/API.md", "docs/LF_TOOLCHAIN.md", "docs/EVALUATION.md",
    "docs/ARCHITECTURE.md",
    "lf/README.md", "toolchain/README.md",
}

# Server-side / snapshot artifacts removed from the public package. None
# may reappear in the tree or in git.
REMOVED_ARTIFACTS = (
    "docker-compose.yml",
    "service/Dockerfile",
    "service/chronohive_api.py",
    "service/entrypoint.sh",
    "src/chronohive/__init__.py",
    "src/chronohive/io_adapters.py",
    "src/chronohive/runtime.py",
    "scripts/demo_admission.py",
    "tools/gen_key.py",
)

# Never tracked, never left on disk.
SECRET_LIKE_NAMES = (
    "toc_signing.key",
    "toc_acceptance.json",
    ".env",
)


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


def _iter_sweep_files():
    for root, dirs, names in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in SWEEP_SKIP_DIRS]
        rel_root = os.path.relpath(root, REPO_ROOT)
        if rel_root in SWEEP_SKIP_PREFIXES or any(
                rel_root.startswith(p + os.sep)
                for p in SWEEP_SKIP_PREFIXES):
            dirs[:] = []
            continue
        for name in sorted(names):
            if name in SWEEP_SKIP_FILES or name.endswith(".cspec.reference"):
                continue
            _stem, ext = os.path.splitext(name)
            if ext not in SWEEP_EXTENSIONS:
                continue
            yield os.path.join(root, name)


def check_branding() -> None:
    step("forbidden-name sweep")
    patterns = [(re.compile(p, re.IGNORECASE), f"pattern#{i}")
                for i, p in enumerate(BANNED_PATTERNS)]
    violations: list[str] = []
    for path in _iter_sweep_files():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except UnicodeDecodeError:
            continue
        for rx, label in patterns:
            for match in rx.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                rel = os.path.relpath(path, REPO_ROOT)
                violations.append(f"{rel}:{line}: {label}")
    if violations:
        raise RuntimeError("forbidden-name sweep found banned content:\n  " +
                           "\n  ".join(violations))
    print("forbidden-name sweep clean")


def check_headers() -> None:
    step("header sweep")
    missing: list[str] = []
    for path in _iter_sweep_files():
        rel = os.path.relpath(path, REPO_ROOT)
        _stem, ext = os.path.splitext(os.path.basename(path))
        name = os.path.basename(path)
        needs = (ext in HEADER_EXTENSIONS or name in HEADER_FILES
                 or rel in HEADER_MD_FILES)
        if not needs:
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                head = fh.read(4096)
        except UnicodeDecodeError:
            continue
        if not any(marker in head for marker in HEADER_MARKERS):
            missing.append(rel)
    if missing:
        raise RuntimeError("files missing the proprietary/confidential "
                           "banner:\n  " + "\n  ".join(missing))
    print("proprietary/confidential banners present")


def check_compile_client() -> None:
    step("compile client --check")
    proc = subprocess.run(
        [sys.executable, "clients/compile_client.py", "--check"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
    print(proc.stdout)
    if proc.returncode != 0:
        raise RuntimeError("compile client --check failed:\n" +
                           proc.stderr[-3000:])


def check_negative_paths() -> None:
    step("compile client negative path validation")
    import compile_client
    bad = [
        "", "/abs/path.lf", "~/home.lf", "../escape.lf", "a/../../b.lf",
        "back\\slash.lf", "noext", "prog.txt", "sub/../other.lf",
        "x" * 300 + ".lf",
    ]
    for path in bad:
        err = compile_client.project_path_error(path)
        assert err, f"path {path!r} was accepted but must be rejected"
    good = ["main.lf", "sub/dir.lf", "a-b_c.lf"]
    for path in good:
        err = compile_client.project_path_error(path)
        assert err is None, f"path {path!r} rejected: {err}"
    print(f"{len(bad)} hostile paths rejected, {len(good)} valid paths kept")


def _git_tracked() -> set[str]:
    proc = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        return set()
    return set(proc.stdout.splitlines())


def check_tracked_artifacts() -> None:
    step("tracked-artifact rejection")
    tracked = _git_tracked()
    bad: list[str] = []
    for path in tracked:
        base = os.path.basename(path)
        if ("__pycache__" in path or path.endswith(".pyc")
                or base in SECRET_LIKE_NAMES):
            bad.append(path)
    for removed in REMOVED_ARTIFACTS:
        if removed in tracked:
            bad.append(removed)
        if os.path.exists(os.path.join(REPO_ROOT, removed)):
            bad.append(removed + " (on disk)")
    if bad:
        raise RuntimeError("forbidden artifacts present:\n  " +
                           "\n  ".join(sorted(bad)))
    print("no build outputs, key material, or removed snapshots tracked")


def check_secret_hygiene() -> None:
    step("secret hygiene")
    found: list[str] = []
    for root, _dirs, names in os.walk(REPO_ROOT):
        if ".git" in root.split(os.sep):
            continue
        for name in names:
            if name in SECRET_LIKE_NAMES:
                found.append(os.path.relpath(
                    os.path.join(root, name), REPO_ROOT))
    if found:
        # Names only — contents are never read or printed.
        raise RuntimeError("secret-like artifacts on disk:\n  " +
                           "\n  ".join(sorted(found)))
    print("no secret-like artifacts on disk")


def main() -> None:
    check_compile()
    check_ed25519()
    check_branding()
    check_headers()
    check_compile_client()
    check_negative_paths()
    check_tracked_artifacts()
    check_secret_hygiene()
    print("\n\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
