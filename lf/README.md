# LF project — ChronoHive evaluation workload

> © 2026 Layer1Labs Silicon Inc. All rights reserved.
> **CONFIDENTIAL — PROPRIETARY.** Licensed solely for evaluation under
> the ChronoHive Terms of Confidentiality (`../TOC.md`) and the
> ChronoHive Evaluation License (`../LICENSE`). **Do not distribute.**

This directory is a complete, self-contained Lingua Franca project: the
reference workload evaluators compile to a ChronoHive `.cspec` specification.

## Layout

| Path | Purpose |
|---|---|
| `IoCoordinator.lf` | The workload: a timed training loop (`Trainer`) driving periodic checkpoints (`CheckpointIO`) and read-ahead (`PrefetchIO`) |
| `IoCoordinator.cspec.reference` | The known-good compiled specification for this exact source, for offline verification (see below) |
| `.vscode/` | Editor configuration for LF authoring |

## The workload

`IoCoordinator.lf` models storage I/O coordination around a training
loop: the `Trainer` reactor issues periodic checkpoint writes and
prefetch reads; `CheckpointIO` and `PrefetchIO` arbitrate them against a
declared `storage_bw` capacity. The main reactor takes a `steps`
parameter (default 200).

Source integrity (the compiler embeds this hash in every specification it emits):

```
sha256sum lf/IoCoordinator.lf
# 722970549e19eada4f955c5a519b8bf2c151dab400633c8e8e77c4aaa08f4a16
```

## Compiling

The canonical path is the compile client at the repo root:

```sh
# against the hosted compile API (needs a TOC-executed key with a compile license)
python3 clients/compile_client.py --api-url https://api.layer1labs.ai \
    --api-key "$CHRONOHIVE_API_KEY" --capacity storage_bw=100 -o /tmp/io.cspec

# fully local (pinned lfc + chronoc on PATH or via LFC/CHRONOC/JAVA_HOME)
python3 clients/compile_client.py --local --capacity storage_bw=100 -o /tmp/io.cspec

# offline self-check: validates the project map, the pinned lfc gate,
# and the checked-in reference specification — no network, no chronoc
# (pinned lfc + a JRE are still required)
python3 clients/compile_client.py --check
```

Compiling is optional for evaluation — the admission API needs neither
`lfc` nor `chronoc`. This project exists for evaluators who want to
define their own LF workloads and compile them to the `.cspec` artifact
the ChronoHive engine executes.

## Toolchain pins

| Component | Pin | Role |
|---|---|---|
| `lfc` | v0.13.0 | The sole authority on valid LF — every compile must pass its validation gate (`lfc -n -q`) |
| `chronoc` | v0.1.0-alpha.1 | Lowers `lfc`-accepted sources in the documented subset to `.cspec` v1 (`CSP1` magic, CRC-32 trailer) |
| LF IDE extension | `lf-lang.vscode-lingua-franca` | Authoring with validation as you type (advisory only) |

`chronoc` performs no LF language validation of its own: `lfc` is the
frontend, `chronoc` replaces `lfc`'s code generator with specification lowering.
No generated LF code runs anywhere in this path — there is no LF runtime
in the execution path. Blobs carry `lfc`/`chronoc` provenance, so
staleness is detectable.

Bumping the `lfc` pin requires re-validating every `.lf` source and
recompiling every specification.

## Reference-specification verification

`IoCoordinator.cspec.reference` (3,308 bytes) is the exact output of the
pinned toolchain for the checked-in source (`steps=200`,
`storage_bw=100`). Verify it any time without the toolchain:

```sh
python3 clients/compile_client.py --check
```

which checks the `CSP1` magic, version, CRC-32 trailer, string table,
capacities, operation and schedule counts, bindings, the embedded LF
source SHA-256, `lfc`/`chronoc` provenance, and the target step count.
