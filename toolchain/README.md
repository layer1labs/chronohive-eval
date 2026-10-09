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
| `chronoc-linux-x86_64` | Pinned `chronoc` v0.1.0-alpha.1 (Rust, LF subset → `.cspec` constraint specification), Linux x86_64. Vendored. |

## chronoc provenance

- Version: `0.1.0-alpha.1` (`chronoc --version`)
- SHA-256: `ab12076b76c095438b43b56ff71dc38db783c5fc988ce61b8caf396db89281e1`
- Built from: the `layer1labs/chronohive-toolchain` repository, `chronoc/`,
  release profile (`cargo build --release --locked`). Re-vendored 2026-10-08
  for the Constraint Specification rename (`.cspec`, magic `CSP1`); the previous
  pin was a pre-rename `0.1.0` build emitting `.chb`/`CHB1`.
- Linked against system libc/libgcc only; runs on any modern Linux x86_64.

To rebuild from source (e.g. for another platform), clone the ChronoHive
repository and run `cargo build --release --locked` in `toolchain/chronoc/`,
then point `scripts/compile_lf.sh` at it with `CHRONOC=<path>`.

Bumping either pin requires re-validating every `.lf` source and
recompiling every specification — specifications carry `lfc`/`chronoc`
provenance so staleness is detectable.
