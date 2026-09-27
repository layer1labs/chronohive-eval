#!/usr/bin/env bash
# compile_lf.sh — compile an LF workload to a ChronoHive .chb blob.
#
# Needs: the pinned lfc v0.13.0 and a chronoc build. If either is missing,
# prints what to install instead of failing cryptically. Compiling is
# optional for evaluation — the API and worked example need neither.
#
# Usage: scripts/compile_lf.sh <source.lf> -o <out.chb> [chronoc args...]
set -euo pipefail

SRC="${1:?usage: compile_lf.sh <source.lf> -o <out.chb> [chronoc args...]}"
shift

# Locate chronoc: env override, then the ChronoHive repo checkout, then PATH.
CHRONOC="${CHRONOC:-}"
if [ -z "$CHRONOC" ]; then
  for c in "$HOME/workspace/chronohive/toolchain/chronoc/target/release/chronoc" \
           "$(command -v chronoc 2>/dev/null)"; do
    if [ -n "$c" ] && [ -x "$c" ]; then CHRONOC="$c"; break; fi
  done
fi
# Locate the pinned lfc: env override, then the canonical install path.
LFC="${LFC:-$HOME/workspace/lf-toolchain/lf-cli-0.13.0-Linux-x86_64/bin/lfc}"

missing=0
[ -n "$CHRONOC" ] || { echo "missing: chronoc (set CHRONOC= or build the ChronoHive repo: cargo build --release --manifest-path toolchain/chronoc/Cargo.toml)"; missing=1; }
[ -x "$LFC" ] || { echo "missing: pinned lfc v0.13.0 at $LFC (set LFC= to your lfc 0.13.0 binary)"; missing=1; }
if [ "$missing" -ne 0 ]; then
  echo
  echo "Full one-shot setup lives in the ChronoHive repo: scripts/setup-ide.sh"
  echo "(installs the LF IDE extension, Java, Rust, and verifies the pinned lfc)."
  exit 2
fi

export JAVA_HOME="${JAVA_HOME:-$HOME/workspace/java/jdk-21.0.12.1+1-jre}"
exec "$CHRONOC" compile "$SRC" --lfc "$LFC" "$@"
