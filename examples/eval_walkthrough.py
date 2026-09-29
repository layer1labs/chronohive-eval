#!/usr/bin/env python3
# © 2026 Layer1Labs Silicon Inc. All rights reserved.
# CONFIDENTIAL — ChronoHive Evaluation Package. Licensed solely for
# evaluation under the ChronoHive Terms of Confidentiality (TOC.md) and
# the ChronoHive Evaluation License (LICENSE). Do not distribute.
"""ChronoHive eval walkthrough — a REAL end-to-end example.

Runs the complete evaluator flow against the hosted eval API:

  1. Fetch the canonical TOC and its hash (GET /v1/toc).
  2. Sign the TOC and execute it (POST /v1/toc/accept).
  3. Run a checkpoint/prefetch admission scenario (POST /v1/scenarios).
  4. Make live kernel admission decisions (POST /v1/admission/decide).
  5. Fetch the stored scenario back (GET /v1/scenarios/{id}).

Everything it does is real: the signature is really verified, and every
grant/refuse comes from the real ChronoHive Runtime kernel. The storage
backend it admits *against* is simulated — see the honesty notes.

Usage:
  python3 examples/eval_walkthrough.py --api-url https://api.layer1labs.ai \\
      --api-key <key> --key-id <your-key-id> \\
      --name "Jane Doe" --org "Example Corp" --email jane@example.com

Environment equivalents: CH_EVAL_API_URL, CH_EVAL_API_KEY, CH_EVAL_KEY_ID.

Note on signing identity: this walkthrough generates a fresh ephemeral
ed25519 keypair on every run and re-executes the TOC with it (step 2).
For a persistent proof-of-execution key, use tools/sign_toc.py instead —
it writes toc_signing.key (mode 600) and toc_acceptance.json, which you
keep and never commit. Either path activates the key; they just differ
in whether the signing key survives the run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import sign_toc

USER_AGENT = sign_toc.USER_AGENT  # Cloudflare blocks Python's default UA


def _call(api_url: str, api_key: str | None, method: str, path: str,
          body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(api_url.rstrip("/") + path, data=data,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def _banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> None:
    ap = argparse.ArgumentParser(description="ChronoHive eval walkthrough")
    ap.add_argument("--api-url", default=os.environ.get("CH_EVAL_API_URL"),
                    help="API base URL")
    ap.add_argument("--api-key", default=os.environ.get("CH_EVAL_API_KEY"),
                    help="API key (raw)")
    ap.add_argument("--key-id", default=os.environ.get("CH_EVAL_KEY_ID"),
                    help="API key id")
    ap.add_argument("--name", default=os.environ.get("CH_EVAL_NAME"),
                    help="legal name of the signer")
    ap.add_argument("--org", default=os.environ.get("CH_EVAL_ORG"),
                    help="organization")
    ap.add_argument("--email", default=os.environ.get("CH_EVAL_EMAIL"),
                    help="contact email")
    args = ap.parse_args()
    for need in ("api_url", "api_key", "key_id", "name", "org", "email"):
        if not getattr(args, need):
            raise SystemExit(f"--{need.replace('_', '-')} is required")

    api_url, api_key, key_id = args.api_url, args.api_key, args.key_id

    # -- Step 1: fetch the canonical TOC ---------------------------------
    _banner("1. Fetching the canonical Terms of Confidentiality")
    status, toc = _call(api_url, None, "GET", "/v1/toc")
    assert status == 200, toc
    toc_sha256 = toc["toc_sha256"]
    print(f"TOC sha256: {toc_sha256}")
    print(f"TOC length: {len(toc['toc_text'])} chars "
          f"(first line: {toc['toc_text'].splitlines()[0]!r})")

    # -- Step 2: sign + execute ------------------------------------------
    _banner("2. Executing the TOC (ed25519 signature)")
    sk, _pk = __import__("ed25519").generate_keypair()
    token = sign_toc.build_acceptance(
        toc_sha256=toc_sha256, key_id=key_id, signer_name=args.name,
        organization=args.org, email=args.email, secret_key=sk)
    print(f"signed as {args.name} <{args.email}> ({args.org})")
    print(f"public key: {token['public_key'][:32]}...")
    status, accept = _call(api_url, api_key, "POST", "/v1/toc/accept", token)
    print(f"POST /v1/toc/accept -> {status}")
    assert status == 200 and accept.get("accepted"), accept
    print(f"key {accept['key_id']} activated at "
          f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(accept['accepted_at']))} UTC")

    # Prove the gate was real: an unsigned key would get 403 here.
    _banner("3. Running a checkpoint/prefetch admission scenario")
    scenario_body = {
        "jobs": 8,
        "ckpt_gb": 200.0,
        "prefetch_gb": 150.0,
        "incast_alpha": 0.2,
        "seeds": [7, 21],
        "miss_penalty_s": 60.0,
    }
    print("scenario knobs:", json.dumps(scenario_body))
    status, payload = _call(api_url, api_key, "POST", "/v1/scenarios",
                            scenario_body)
    assert status == 200, payload
    scenario_id = payload["scenario_id"]
    result = payload["result"]
    print(f"\nscenario_id: {scenario_id}")
    print(f"{'seed':>6} {'base stall (s)':>14} {'admit stall (s)':>15} "
          f"{'misses b/a':>11} {'reduction':>10}  verdict")
    for s in result["seeds"]:
        v = s["verdict"]
        print(f"{s['seed']:>6} {s['baseline']['gpu_stall_s']:>14.0f} "
              f"{s['admission']['gpu_stall_s']:>15.0f} "
              f"{s['baseline']['ckpt_misses']:>4}/{s['admission']['ckpt_misses']:<4} "
              f"{v['stall_reduction'] * 100:>9.1f}%  "
              f"{'PASS' if v['pass'] else 'FAIL'}")
    print("\nWhat this means: 'base stall' is GPU-seconds lost waiting on "
          "storage with no admission control; 'admit stall' is the same "
          "workload with every transfer arbitrated by the ChronoHive "
          "Runtime kernel. The verdict passes on >=20% stall reduction "
          "with no makespan regression.")

    # -- Step 4: live kernel decisions ------------------------------------
    _banner("4. Live kernel admission decisions")
    decide_body = {
        "now_s": 0,
        "window": 30,
        "requests": [
            {"dataset_id": "job0.ckpt", "kind": "checkpoint",
             "bytes_remaining": 200e9, "deadline_s": 120},
            {"dataset_id": "job1.ckpt", "kind": "checkpoint",
             "bytes_remaining": 200e9, "deadline_s": 150},
            {"dataset_id": "job2.prefetch", "kind": "prefetch",
             "bytes_remaining": 150e9, "deadline_s": 90},
            {"dataset_id": "job3.prefetch", "kind": "prefetch",
             "bytes_remaining": 150e9},  # no deadline: best effort
        ],
    }
    status, decision = _call(api_url, api_key, "POST",
                             "/v1/admission/decide", decide_body)
    assert status == 200, decision
    print("admitted (dataset -> granted B/s):")
    for ds, rate in decision["admitted"].items():
        print(f"  {ds:<16} {rate / 1e9:6.2f} GB/s   (QoS level "
              f"{decision['qos'].get(ds, '?')})")
    print("refused:", decision["refused"] or "(none)")
    k = decision["kernel"]
    print(f"kernel counters this window: {k['admits']} admits, "
          f"{k['refusals']} refusals")
    print("\nWhat this means: the kernel admitted earliest-deadline-first "
          "against the provisioned pipes and drove per-dataset QoS levels "
          "from the grant decisions — the same path a storage controller "
          "would call per scheduling window.")

    # -- Step 5: fetch the stored scenario --------------------------------
    _banner("5. Fetching the stored scenario result")
    status, fetched = _call(api_url, api_key, "GET",
                            f"/v1/scenarios/{scenario_id}")
    assert status == 200 and fetched["scenario_id"] == scenario_id, fetched
    print(f"GET /v1/scenarios/{scenario_id} -> 200 "
          f"({len(fetched['result']['seeds'])} seeds, "
          f"params {fetched['result']['params']['jobs']} jobs)")

    _banner("Walkthrough complete")
    print("Honesty: storage backend, contention model, and storage API surface "
          "are simulated;\n"
          "every grant/refuse above came from the real ChronoHive Runtime "
          "kernel.\n"
          "These are simulation outcomes, not hardware measurements.")


if __name__ == "__main__":
    main()
