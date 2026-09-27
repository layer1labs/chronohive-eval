#!/usr/bin/env python3
"""Generate an API key entry for the ChronoHive admission API service.

The raw key is printed ONCE for the operator to hand to the evaluator
(under NDA). Only a per-key salted SHA-256 hash goes into the keys file —
the raw key never touches the repo, the image, or any committed file.

Usage:
  python3 service/gen_key.py --id ddn-eval-01 --days 30 \\
      --scenarios-per-day 50 --decide-per-min 60 >> api_keys.jsonl
  # then assemble entries into a JSON array at deploy time, or:
  python3 service/gen_key.py --id ddn-eval-01 --days 30 --emit-array --existing api_keys.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import time


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="key id, e.g. ddn-eval-01")
    ap.add_argument("--days", type=float, default=30.0,
                    help="validity in days (default 30)")
    ap.add_argument("--scenarios-per-day", type=int, default=50)
    ap.add_argument("--decide-per-min", type=int, default=60)
    ap.add_argument("--existing", default=None,
                    help="existing keys JSON array file to append to")
    args = ap.parse_args()

    raw = "ch_" + secrets.token_urlsafe(32)
    salt = secrets.token_hex(16)  # 128-bit per-key salt
    entry = {
        "id": args.id,
        "salt": salt,
        "key_hash": hashlib.sha256(salt.encode() + raw.encode()).hexdigest(),
        "created_at": int(time.time()),
        "expires_at": int(time.time() + args.days * 86400),
        "quota_scenarios_per_day": args.scenarios_per_day,
        "quota_decide_per_min": args.decide_per_min,
    }

    entries = []
    if args.existing:
        try:
            with open(args.existing) as fh:
                entries = json.load(fh)
        except FileNotFoundError:
            entries = []
    entries.append(entry)
    out_path = args.existing or "api_keys.json"
    with open(out_path, "w") as fh:
        json.dump(entries, fh, indent=2)
        fh.write("\n")

    print("=" * 64)
    print("RAW API KEY (hand to the evaluator under NDA; shown once):")
    print(raw)
    print("=" * 64)
    print(f"entry for key id '{args.id}' written to {out_path} "
          f"(hash only; expires in {args.days} days)")


if __name__ == "__main__":
    main()
