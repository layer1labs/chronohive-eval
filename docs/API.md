# ChronoHive Admission API — Reference

© 2026 Layer1Labs Silicon Inc. All rights reserved. CONFIDENTIAL.

This is the complete reference for the ChronoHive evaluation API. It
covers the hosted endpoint and self-hosted deployments alike.

**Honesty appendix (applies to every endpoint):** the storage backend,
the incast contention model, and the DDN API surface are **simulated**;
every grant/refuse decision is produced by the **real ChronoHive
Runtime kernel**. All numbers are simulation outcomes, not DDN hardware
measurements. Every response carries `"simulated_backend": true`.

## Base URLs

| Deployment  | Base URL                      |
|-------------|-------------------------------|
| Hosted eval | `https://api.layer1labs.ai`   |
| Self-hosted | `http://localhost:8080` (docker compose default) |

All paths below are relative to the base URL.

## Authentication

Every endpoint except `GET /v1/health`, `GET /v1/toc`, and `GET /`
requires an API key:

```
Authorization: Bearer <raw-key>
```

Keys are issued by the operator (or minted locally with
`tools/gen_key.py`), have an expiry date, and are stored server-side as
salted hashes — the server never sees your key except in the
Authorization header.

| Failure | Status | Meaning |
|---------|--------|---------|
| Missing/malformed header | 401 | No `Bearer` credentials sent |
| Unknown or expired key | 401 | Key not recognized or past `expires_at` |

## Executing the TOC (required before use)

Eval endpoints stay locked until your API key has a verified Terms of
Confidentiality acceptance on file. Without it you get:

```json
{
  "error": "toc_acceptance_required",
  "message": "This API key has not executed the Terms of Confidentiality...",
  "toc_sha256": "<pinned hash>",
  "accept_endpoint": "/v1/toc/accept",
  "toc_endpoint": "/v1/toc"
}
```

**Step 1 — read the canonical TOC.** Fetch it from the server so you
sign exactly the text it enforces:

```
curl https://api.layer1labs.ai/v1/toc
```

**Step 2 — sign it.** The signing tool generates an ed25519 keypair
(pure Python, no dependencies), binds the TOC hash to your key id and
identity, and produces an acceptance token:

```
python3 tools/sign_toc.py --api-url https://api.layer1labs.ai \
    --key-id <your-key-id> \
    --name "Jane Doe" --org "Example Corp" --email jane@example.com
```

This writes `toc_signing.key` (mode 600 — your proof of execution, keep
it) and `toc_acceptance.json`.

**Step 3 — submit the token:**

```
curl -X POST https://api.layer1labs.ai/v1/toc/accept \
  -H "Authorization: Bearer <raw-key>" \
  -H "Content-Type: application/json" \
  -d @toc_acceptance.json
```

Or do all three steps at once with `--submit`:

```
python3 tools/sign_toc.py --api-url https://api.layer1labs.ai \
    --api-key <raw-key> --key-id <your-key-id> --submit
```

A `200 {"accepted": true, ...}` means your key is activated. Per TOC
§5, a signature verified against the pinned TOC hash constitutes
execution of the TOC with the same force as a handwritten signature.

## Endpoints

### GET /v1/health

Liveness probe. Unauthenticated.

```
curl https://api.layer1labs.ai/v1/health
```

```json
{
  "status": "ok",
  "version": "1.1.0",
  "toc_sha256": "<pinned TOC hash>",
  "simulated_backend": true
}
```

### GET /v1/toc

The canonical Terms of Confidentiality text and its SHA-256 digest.
Unauthenticated. Sign exactly this text.

Response:

```json
{
  "toc_sha256": "<hex>",
  "toc_text": "<full TOC.md text>",
  "accept_endpoint": "/v1/toc/accept",
  "simulated_backend": true
}
```

### POST /v1/toc/accept

Submit a signed acceptance token (see "Executing the TOC").
Authenticated — the token's `key_id` must match the calling key.

Request body: the acceptance token object:

```json
{
  "protocol": "CHRONOHIVE-TOC-ACCEPT/v1",
  "toc_sha256": "<hex>",
  "key_id": "<your-key-id>",
  "signer_name": "Jane Doe",
  "organization": "Example Corp",
  "email": "jane@example.com",
  "timestamp": 1790000000,
  "public_key": "<hex ed25519 public key>",
  "signature": "<hex ed25519 signature>"
}
```

Success (`200`):

```json
{
  "accepted": true,
  "key_id": "<your-key-id>",
  "toc_sha256": "<hex>",
  "signer": "Jane Doe",
  "organization": "Example Corp",
  "accepted_at": 1790000000,
  "simulated_backend": true
}
```

Failures: `401` (bad key), `403 {"error": "toc_acceptance_rejected",
"reason": "..."}` — hash mismatch, key_id mismatch, bad signature,
timestamp in the future (beyond 10 minutes of clock skew), or implausibly
old timestamp (before 2020-01-01).

The server persists each acceptance as `key_id -> {"token": <the signed
token>, "accepted_at": <server unix time>}`. `accepted_at` is the server's
own clock at accept time — the authoritative execution record — never the
client-supplied token timestamp. The acceptance survives restarts.

### POST /v1/scenarios

Run the deterministic checkpoint/prefetch admission simulation.
Authenticated + TOC required. Quota: `quota_scenarios_per_day` per key
(default 50/day).

Request:

```json
{
  "jobs": 8,
  "ckpt_gb": 200.0,
  "prefetch_gb": 150.0,
  "incast_alpha": 0.2,
  "seeds": [7, 21],
  "miss_penalty_s": 60.0
}
```

| Field | Type | Default | Bounds | Meaning |
|-------|------|---------|--------|---------|
| jobs | int | 8 | 1–64 | Simulated training jobs |
| ckpt_gb | float | 200.0 | 1–10000 | Checkpoint size per job (GB) |
| prefetch_gb | float | 150.0 | 1–10000 | Prefetch size per job (GB) |
| incast_alpha | float | 0.2 | 0–1 | Contention severity |
| seeds | int[] | [7] | 1–10 seeds | Deterministic seeds; same seed ⇒ same result |
| miss_penalty_s | float | 60.0 | 0–3600 | GPU stall seconds per checkpoint miss |

Response (`200`): a `scenario_id` plus the full result. Per seed, the
result compares **baseline** (no admission control) against
**admission** (every transfer arbitrated by the kernel):

```json
{
  "scenario_id": "a3f9c1...",
  "simulated_backend": true,
  "result": {
    "simulated_backend": true,
    "honesty": "Storage backend, contention model, ...",
    "params": { "jobs": 8, "ckpt_gb": 200.0, "...": "..." },
    "seeds": [
      {
        "seed": 7,
        "baseline":  { "gpu_stall_s": 1234.0, "ckpt_misses": 5,
                       "makespan_s": 9000.0, "jain_fairness": 0.97 },
        "admission":  { "gpu_stall_s": 12.0, "ckpt_misses": 0,
                       "makespan_s": 8990.0, "jain_fairness": 0.99,
                       "kernel_admits": 42, "kernel_refusals": 3 },
        "verdict":    { "stall_reduction": 0.99,
                       "makespan_delta_s": -10.0, "pass": true }
      }
    ]
  }
}
```

The verdict passes on **≥20% GPU-stall reduction with no makespan
regression** (tolerance 1%). `kernel_admits` / `kernel_refusals` are the
real kernel's per-seed counters.

### GET /v1/scenarios/{id}

Fetch a previously run scenario result. Authenticated + TOC required.
`404` for an unknown id. Scenario results live in process memory (up to
`CH_MAX_STORED`, default 128) and reset on restart.

### POST /v1/admission/decide

The live kernel decision path: submit transfer requests for one
scheduling window and get grant/refuse decisions back.
Authenticated + TOC required. Quota: `quota_decide_per_min` per key
(default 60/min). This is the endpoint a storage controller would call
per scheduling window.

Request:

```json
{
  "now_s": 0,
  "window": 30,
  "requests": [
    { "dataset_id": "job0.ckpt", "job_id": 0, "kind": "checkpoint",
      "bytes_remaining": 200000000000, "deadline_s": 120 },
    { "dataset_id": "job2.prefetch", "job_id": 2, "kind": "prefetch",
      "bytes_remaining": 150000000000 }
  ]
}
```

| Field | Type | Bounds | Meaning |
|-------|------|--------|---------|
| now_s | float | ≥ 0 | Window start (s) |
| window | int | ≥ 0 | Window index (opaque to the kernel) |
| requests | object[] | 1–256 | Transfer requests |
| ↳ dataset_id | string | required | Dataset identifier |
| ↳ job_id | int | default 0 | Owning job |
| ↳ kind | string | `checkpoint` \| `prefetch` | Transfer kind |
| ↳ bytes_remaining | float | > 0 | Bytes still to move |
| ↳ deadline_s | float \| null | > now_s | Deadline; null = best effort |

Response (`200`):

```json
{
  "simulated_backend": true,
  "honesty": "Storage backend, contention model, ...",
  "window": 30,
  "admitted": { "job0.ckpt": 5000000000.0 },
  "refused": ["job2.prefetch"],
  "qos": { "job0.ckpt": 63 },
  "kernel": { "admits": 1, "refusals": 1 }
}
```

`admitted` maps dataset → granted bandwidth (B/s). `refused` lists
datasets the kernel declined this window (retry them in a later
window). `qos` maps dataset → QoS level 0–63, driven by the grant
decisions on the simulated DDN surface. `kernel` carries the kernel's
admit/refuse counters.

Admission policy: earliest-deadline-first against the provisioned
write/read pipes; best-effort (deadline-less) requests yield to
deadlined ones.

### GET /

Minimal eval console (HTML): the TOC step plus a scenario form.
Unauthenticated. Useful for a first look; scripted evaluation should
use the JSON endpoints.

## Quotas and rate limits

Quotas are per API key and configured at issuance:

| Quota | Default | Window | On exceed |
|-------|---------|--------|-----------|
| `quota_scenarios_per_day` | 50 | rolling 24 h | `429`, `Retry-After` header |
| `quota_decide_per_min` | 60 | rolling 60 s | `429`, `Retry-After` header |

`429` bodies carry `retry_after_s`. Quota counters reset on server
restart (documented limitation).

## Audit

Every authenticated call is appended to a JSONL audit log with the key
id, method, path, status, request-body SHA-256, and duration. Raw keys
and request bodies are never logged.

## Error catalog

| Status | `error` | Meaning |
|--------|---------|---------|
| 400 | *(various)* | Invalid parameters; the message says which |
| 401 | missing or malformed Authorization header | No/invalid credentials format |
| 401 | invalid or expired API key | Unknown key or past expiry |
| 403 | toc_acceptance_required | Key valid, TOC not yet executed |
| 403 | toc_acceptance_rejected | Token failed verification (`reason` explains) |
| 404 | not found / unknown scenario id | Bad path or id |
| 405 | use GET /v1/toc | Wrong method on the TOC document endpoint |
| 429 | scenario quota exceeded / decide quota exceeded | Slow down; honor `Retry-After` |

## Key management (self-hosted)

```
python3 tools/gen_key.py --id eval-01 --days 30 \
    --scenarios-per-day 50 --decide-per-min 60 \
    --existing /run/secrets/api_keys.json
```

The raw key prints **once** — hand it to the evaluator, then it lives
only as a salted hash in the keys file. Keys load at server startup; a
keys-file change needs a restart.

## Self-hosting

```
docker compose up --build
docker compose logs api   # grab the generated eval key
python3 examples/eval_walkthrough.py --api-url http://localhost:8080 ...
```

See README.md for the full quickstart.

## Versioning

The API version is reported by `GET /v1/health` (`version`) and in the
`Server` header. Additive endpoint changes bump the minor version;
breaking changes bump the major version.

| Version | Changes |
|---------|---------|
| 1.1.0 | TOC execution gate (`/v1/toc`, `/v1/toc/accept`, 403 gating) |
| 1.0.0 | Initial eval API |

© 2026 Layer1Labs Silicon Inc. All rights reserved. CONFIDENTIAL.
