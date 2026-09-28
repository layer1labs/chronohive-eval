<!-- © 2026 Layer1Labs Silicon Inc. All rights reserved. -->
<!-- CONFIDENTIAL — ChronoHive Evaluation Package. Licensed solely for -->
<!-- evaluation under the ChronoHive Terms of Confidentiality (TOC.md) and -->
<!-- the ChronoHive Evaluation License (LICENSE). Do not distribute. -->

# toolchain/

Pinned, self-contained build tools for the LF evaluation workloads.
Everything an evaluator needs to validate and compile `lf/*.lf` lives
here or is fetched here by `scripts/fetch-lfc.sh`.

| File | What |
|------|------|
| `lf-cli-0.13.0-Linux-x86_64/` | Pinned `lfc` v0.13.0 (validation gate). Created by `scripts/fetch-lfc.sh`; gitignored. Never hand-install — the fetch script verifies the SHA-256. |
| `chronoc-linux-x86_64` | Pinned `chronoc` v0.1.0 (Rust, LF subset → `.chb` blob), Linux x86_64. Vendored. |

## chronoc provenance

- Version: `0.1.0` (`chronoc --version`)
- SHA-256: `502ecdf29160eb805e90b4775421675ae842876c14ad1ba09da6814708aaa65e`
- Built from: the ChronoHive repository, `toolchain/chronoc/`, release profile
  (`cargo build --release --locked`), Rust 1.89.0.
- Linked against system libc/libgcc only; runs on any modern Linux x86_64.

To rebuild from source (e.g. for another platform), clone the ChronoHive
repository and run `cargo build --release --locked` in `toolchain/chronoc/`,
then point `scripts/compile_lf.sh` at it with `CHRONOC=<path>`.

Bumping either pin requires re-validating every `.lf` source and
recompiling every blob — blobs carry `lfc`/`chronoc` provenance so
staleness is detectable.
