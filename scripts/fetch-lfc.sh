#!/usr/bin/env bash
# fetch-lfc.sh — download the pinned lfc and verify its SHA-256.
#
# Idempotent: skips the download when the pinned lfc is already present
# and its directory verifies. Installs into <repo>/toolchain/.
#
# Usage: scripts/fetch-lfc.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLCHAIN_DIR="$REPO_ROOT/toolchain"

LFC_VERSION="0.13.0"
LFC_URL="https://github.com/lf-lang/lingua-franca/releases/download/v${LFC_VERSION}/lf-cli-${LFC_VERSION}-Linux-x86_64.tar.gz"
# Pinned hash (matches ~/workspace/lf-toolchain/pin.env and the
# chronohive eval-demo Dockerfile).
LFC_SHA256="175784319935e388a5ebe44f33dc4e3367eed9f24d071c82af8b50afe013a1c2"
LFC_DIR="$TOOLCHAIN_DIR/lf-cli-${LFC_VERSION}-Linux-x86_64"
LFC_BIN="$LFC_DIR/bin/lfc"

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
    echo "fetch-lfc.sh: only Linux x86_64 is pinned." >&2
    echo "On other platforms, install lfc v${LFC_VERSION} manually and set" >&2
    echo "LFC=<path-to-lfc-binary> when calling scripts/compile_lf.sh." >&2
    exit 2
fi

if [ -x "$LFC_BIN" ]; then
    echo "lfc v${LFC_VERSION} already present: $LFC_BIN"
    exit 0
fi

mkdir -p "$TOOLCHAIN_DIR"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "downloading lfc v${LFC_VERSION} ..."
curl -fsSL -o "$tmp/lf-cli.tar.gz" "$LFC_URL"

echo "verifying SHA-256 ..."
echo "${LFC_SHA256}  $tmp/lf-cli.tar.gz" | sha256sum -c - \
    || { echo "fetch-lfc.sh: SHA-256 MISMATCH — refusing to unpack" >&2; exit 1; }

tar -xzf "$tmp/lf-cli.tar.gz" -C "$TOOLCHAIN_DIR"
if [ ! -x "$LFC_BIN" ]; then
    echo "fetch-lfc.sh: unpacked but $LFC_BIN not found/executable" >&2
    exit 1
fi
echo "lfc v${LFC_VERSION} ready: $LFC_BIN"
