# ChronoHive Evaluation Package

© 2026 Layer1Labs Silicon Inc. All rights reserved. CONFIDENTIAL — do not distribute.

Evaluate ChronoHive's storage-admission capability: the eval API serves
**real admission decisions from the ChronoHive Runtime kernel** against
a **simulated** storage backend, contention model, and storage API surface.
Evaluation numbers are simulation outcomes, not hardware measurements.

## Quickstart (self-hosted, ~2 minutes)

```bash
docker compose up --build
```

On first boot the container generates an eval API key and prints it to
its logs — it is shown once:

```bash
docker compose logs api | grep "RAW API KEY" -A 2
```

Then run the worked example end to end (it executes the TOC, runs a
scenario, makes live kernel decisions, and fetches the result back):

```bash
python3 examples/eval_walkthrough.py --api-url http://localhost:8080 \
    --api-key <the-key> --key-id eval-local-01 \
    --name "Your Name" --org "Your Company" --email you@company.com
```

Or open the eval console at http://localhost:8080.

## The one rule: execute the TOC first

Every eval endpoint stays locked (`403 toc_acceptance_required`) until
your API key has a verified Terms of Confidentiality acceptance on
file. The flow:

1. Read the canonical TOC: `GET /v1/toc` (or `TOC.md` in this repo —
   both carry the same pinned hash).
2. Sign it: `python3 tools/sign_toc.py --api-url <server> --key-id <id> --submit`
   (prompts for name/org/email; writes your ed25519 signing key and the
   acceptance token).
3. The server verifies your ed25519 signature against the pinned TOC
   hash and activates your key. Per TOC §5, a verified signature
   constitutes execution with the same force as a handwritten signature.

No dependencies are needed for any of this — signing, verification,
the API, and the example are all pure-Python stdlib.

## What's in this repo

| Path | What |
|------|------|
| `TOC.md` | Terms of Confidentiality (DRAFT — pending counsel review) |
| `LICENSE` | ChronoHive Evaluation License (DRAFT — pending counsel review) |
| `docs/API.md` | Complete API reference — every endpoint, schema, error, quota |
| `examples/eval_walkthrough.py` | Real end-to-end example: TOC → scenario → live decisions → fetch |
| `service/` | The eval API (`chronohive_api.py`) + Dockerfile + entrypoint |
| `src/chronohive/` | Pinned snapshot of the ChronoHive Runtime kernel (admission logic) |
| `scripts/demo_admission.py` | Pinned snapshot of the deterministic eval demo |
| `tools/` | `sign_toc.py` (TOC signing), `gen_key.py` (API key minting), `ed25519.py` + `toc_common.py` (vendored crypto) |
| `docker-compose.yml` | One-command local deployment |
| `lf/` | Lingua Franca workload sources (canonical: `IoCoordinator.lf`) |
| `toolchain/` | Pinned LF toolchain: vendored `chronoc` v0.1.0 + `lfc` v0.13.0 fetch (SHA-256 verified) |
| `docs/LF_TOOLCHAIN.md` | Optional LF toolchain: IDE → pinned `lfc` → `chronoc` → `.chb` blob |
| `scripts/compile_lf.sh` | Optional LF→blob compile helper (self-contained; needs only a JVM) |
| `scripts/demo-lf.sh` | Guided LF tour: source → validate → compile → blob provenance |
| `scripts/fetch-lfc.sh` | One-time pinned-`lfc` download with hash verification |

`src/chronohive/*` and `scripts/demo_admission.py` are pinned,
read-only snapshots vendored from the private ChronoHive repository —
do not edit them here; changes flow from upstream.

## Lingua Franca workloads (optional)

Workloads can be authored as Lingua Franca programs (`lf/IoCoordinator.lf`,
SHA-256 pinned in `docs/LF_TOOLCHAIN.md`) and compiled to the binary blob
the engine executes, via the pinned `lfc` validation gate and the
`chronoc` compiler. Run the guided tour:

```sh
scripts/demo-lf.sh
```

or compile directly (self-contained — needs only a JVM for `lfc`):

```sh
scripts/compile_lf.sh lf/IoCoordinator.lf -o io.chb
```

Full authoring setup (IDE extension, Java, Rust) is documented in
`docs/LF_TOOLCHAIN.md`. Evaluation itself needs neither — the API, the
worked example, and the scenarios all run on stdlib Python plus Docker.

## Suggested evaluation protocol

1. Run `examples/eval_walkthrough.py` to confirm the full loop works.
2. Sweep `POST /v1/scenarios` across jobs (4–32), checkpoint sizes
   (50–1000 GB), and `incast_alpha` (0–1); record stall reduction and
   the pass/fail verdict per seed. Seeds are deterministic — reruns
   reproduce exactly.
3. Drive `POST /v1/admission/decide` with your own request mixes
   (deadlined checkpoints vs. best-effort prefetches) and observe
   grant/refuse/QoS behavior per window.
4. Compare against your baseline: the scenario result always includes
   the no-admission baseline for the same seed.

## Hosted evaluation

If Layer1Labs issued you a hosted API key (`https://api.layer1labs.ai`),
the same flow applies: execute the TOC against the hosted URL with
your issued key id, then evaluate. Your key carries its own quotas and
expiry.

## Notices

- DRAFT legal documents: `TOC.md` and `LICENSE` are templates pending
  counsel review. Do not treat them as final legal instruments.
- Known limitations: scenario results and quota counters reset on
  server restart; API keys load at startup only; `/` and `/v1/health`
  are unauthenticated.
