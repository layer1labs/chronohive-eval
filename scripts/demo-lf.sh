#!/usr/bin/env bash
# © 2026 Layer1Labs Silicon Inc. All rights reserved.
# CONFIDENTIAL — ChronoHive Evaluation Package. Licensed solely for
# evaluation under the ChronoHive Terms of Confidentiality (TOC.md) and
# the ChronoHive Evaluation License (LICENSE). Do not distribute.
# demo-lf.sh — guided tour of the Lingua Franca evaluation workload.
#
# Walks through the full chain an evaluator can inspect:
#   1. the LF source (lf/IoCoordinator.lf)
#   2. validation by the pinned real lfc v0.13.0 (the authoritative gate)
#   3. lowering by chronoc v0.1.0 to a .chb blob
#   4. blob provenance (hashes, pins, shape)
#   5. how the workload reaches the eval API
#
# Needs: a JVM (Java 17+) for lfc; internet on first run to fetch the
# pinned lfc (hash-verified). Everything else is vendored.
#
# Usage: scripts/demo-lf.sh [--out <blob-path>]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LF_SRC="$REPO_ROOT/lf/IoCoordinator.lf"
OUT="${2:-/tmp/IoCoordinator.chb}"
if [ "${1:-}" = "--out" ] && [ -n "${2:-}" ]; then OUT="$2"; fi

say() { printf '\n=== %s ===\n' "$1"; }

say "1. The LF source: lf/IoCoordinator.lf"
echo "A timed training loop (Trainer) drives storage I/O through two"
echo "single-purpose reactors: CheckpointIO (periodic checkpoints) and"
echo "PrefetchIO (read-ahead)."
echo
sed -n '1,20p' "$LF_SRC"
echo "    ..."
echo
echo "source SHA-256: $(sha256sum "$LF_SRC" | cut -d' ' -f1)"

say "2-3. Validate (pinned lfc) + compile (chronoc) to a .chb blob"
"$REPO_ROOT/scripts/compile_lf.sh" "$LF_SRC" -o "$OUT" \
    --param steps=200 --capacity storage_bw=100

say "4. Blob provenance"
ls -l "$OUT"
echo "blob SHA-256:   $(sha256sum "$OUT" | cut -d' ' -f1)"
echo "magic bytes:    $(head -c 4 "$OUT")"
echo "The blob embeds the source SHA-256 and the lfc/chronoc versions that"
echo "produced it, so staleness is detectable."

say "5. How the workload reaches the eval API"
echo "The workload's shapes (train steps, checkpoint MB, prefetch depth)"
echo "parameterize API scenarios: jobs, ckpt_gb, prefetch_gb, ... — see"
echo "examples/eval_walkthrough.py (self-hosted: docker compose up --build)."
echo
echo "Done. Re-run any step individually with scripts/compile_lf.sh."
