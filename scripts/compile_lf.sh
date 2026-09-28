#!/usr/bin/env bash
# © 2026 Layer1Labs Silicon Inc. All rights reserved.
# CONFIDENTIAL — ChronoHive Evaluation Package. Licensed solely for
# evaluation under the ChronoHive Terms of Confidentiality (TOC.md) and
# the ChronoHive Evaluation License (LICENSE). Do not distribute.
#
# compile_lf.sh — compile an LF workload to a ChronoHive .chb blob.
#
# Portable: resolves the pinned lfc and chronoc from this repo's
# toolchain/ directory (fetching lfc on first use), and locates a JVM
# for lfc. Compiling is optional for evaluation — the API and worked
# example need neither.
#
# Usage: scripts/compile_lf.sh <source.lf> -o <out.chb> [chronoc args...]
#
# Env overrides:
#   CHRONOC=<path>   chronoc binary (default: toolchain/chronoc-linux-x86_64)
#   LFC=<path>       lfc binary (default: toolchain's pinned v0.13.0)
#   JAVA_HOME=<path> JVM for lfc (default: auto-detected from PATH)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLCHAIN_DIR="$REPO_ROOT/toolchain"

SRC="${1:?usage: compile_lf.sh <source.lf> -o <out.chb> [chronoc args...]}"
shift

# --- chronoc: env override, then the repo-vendored binary, then PATH. ---
CHRONOC="${CHRONOC:-}"
if [ -z "$CHRONOC" ]; then
    for c in "$TOOLCHAIN_DIR/chronoc-linux-x86_64" \
             "$(command -v chronoc 2>/dev/null || true)"; do
        if [ -n "$c" ] && [ -x "$c" ]; then CHRONOC="$c"; break; fi
    done
fi

# --- lfc: env override, then the repo-pinned install (fetch if absent). ---
LFC="${LFC:-$TOOLCHAIN_DIR/lf-cli-0.13.0-Linux-x86_64/bin/lfc}"
if [ ! -x "$LFC" ]; then
    echo "pinned lfc not found — fetching (one-time download) ..."
    "$REPO_ROOT/scripts/fetch-lfc.sh"
fi

missing=0
[ -n "$CHRONOC" ] || { echo "missing: chronoc (vendored binary not found; set CHRONOC=<path> or rebuild from the ChronoHive repo — see toolchain/README.md)"; missing=1; }
[ -x "$LFC" ] || { echo "missing: pinned lfc v0.13.0 (set LFC=<path-to-lfc-0.13.0>)"; missing=1; }
if [ "$missing" -ne 0 ]; then exit 2; fi

# --- JVM for lfc (and chronoc's validation gate): JAVA_HOME wins,
# --- otherwise derive it from java on PATH. chronoc falls back to a
# --- build-time default path when JAVA_HOME is unset, so always set it.
if [ -z "${JAVA_HOME:-}" ]; then
    if command -v java >/dev/null 2>&1; then
        JAVA_BIN="$(readlink -f "$(command -v java)")"
        export JAVA_HOME="$(dirname "$(dirname "$JAVA_BIN")")"
    else
        echo "missing: a JVM (Java 17+) for lfc." >&2
        echo "Install a headless JRE (e.g. 'apt install default-jre-headless')" >&2
        echo "or set JAVA_HOME=<path-to-jre>." >&2
        exit 2
    fi
fi

echo "chronoc: $CHRONOC"
echo "lfc:     $LFC"
echo "java:    $JAVA_HOME"

# chronoc's lfc validation gate is sensitive to source paths that are not
# simple relative paths under the working directory, so stage the project
# through a temp dir and compile with a relative path — the same shape the
# compile API uses server-side. A relative -o output path is resolved
# against the caller's cwd before staging.
STAGE="$(mktemp -d -t ch-lf-compile-XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -o)
      ARGS+=("-o")
      case "${2:?missing value for -o}" in
        /*) ARGS+=("$2") ;;
        *)  ARGS+=("$PWD/$2") ;;
      esac
      shift 2
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done
SRC_DIR="$(cd "$(dirname "$SRC")" && pwd)"
cp -r "$SRC_DIR"/. "$STAGE"/
ENTRYPOINT="$(basename "$SRC")"

(
  cd "$STAGE"
  exec "$CHRONOC" compile "$ENTRYPOINT" --lfc "$LFC" "${ARGS[@]}"
)
