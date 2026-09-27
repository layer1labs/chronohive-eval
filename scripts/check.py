#!/usr/bin/env python3
"""chronohive-eval repository gate. Fails loudly on any regression.

  1. Byte-compile every Python file in the repo.
  2. Ed25519: reproduce the RFC 8032 test vectors byte-identically,
     plus round-trip and tamper-rejection checks.
  3. Boot the real API locally and run the FULL evaluator flow:
     health -> TOC fetch -> gated 403 -> sign -> accept -> scenario ->
     decide -> scenario fetch -> bad-token rejection.
  4. Run examples/eval_walkthrough.py against the same server.

Usage: python3 scripts/check.py
"""

from __future__ import annotations

import compileall
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))


def step(name: str) -> None:
    print(f"\n=== {name} ===", flush=True)


def _http(port: int, method: str, path: str, key: str | None = None,
          body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        return exc.code, json.loads(raw) if raw else {}


def check_compile() -> None:
    step("compile")
    ok = compileall.compile_dir(REPO_ROOT, quiet=1, force=True,
                                rx=re.compile(r"/\.git/"))
    if not ok:
        raise RuntimeError("compile failed")


def check_ed25519() -> None:
    step("ed25519 RFC 8032 vectors")
    import ed25519
    vectors = json.load(open(os.path.join(
        REPO_ROOT, "tools", "rfc8032_test_vectors.json")))
    assert len(vectors) >= 3, "need at least 3 RFC vectors"
    for v in vectors:
        skb, msgb = bytes.fromhex(v["sk"]), bytes.fromhex(v["msg"])
        pkb, sigb = bytes.fromhex(v["pk"]), bytes.fromhex(v["sig"])
        assert ed25519.publickey(skb) == pkb, f"TEST {v['n']}: pubkey"
        assert ed25519.sign(skb, msgb) == sigb, f"TEST {v['n']}: signature"
        assert ed25519.verify(pkb, msgb, sigb), f"TEST {v['n']}: verify"
        bad = bytearray(sigb)
        bad[0] ^= 1
        assert not ed25519.verify(pkb, msgb, bytes(bad)), "tamper accepted"
    # round-trip on fresh keys, incl. empty message
    for msg in (b"", b"hello", os.urandom(500)):
        sk, pk = ed25519.generate_keypair()
        sig = ed25519.sign(sk, msg)
        assert ed25519.verify(pk, msg, sig)
    print(f"{len(vectors)} RFC vectors byte-identical; "
          "round-trip + tamper rejection OK")


def check_api_flow() -> None:
    step("API end-to-end flow")
    import ed25519
    import toc_common
    import sign_toc

    tmp = tempfile.mkdtemp(prefix="cheval-")
    keys_file = os.path.join(tmp, "api_keys.json")
    # mint a test key via the real tool
    proc = subprocess.run(
        [sys.executable, "tools/gen_key.py", "--id", "check-01",
         "--days", "1", "--existing", keys_file],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    m = re.search(r"^(ch_\S+)$", proc.stdout, re.M)
    raw_key = m.group(1)

    env = dict(os.environ, PORT="18081",
               CH_API_KEYS_FILE=keys_file,
               CH_AUDIT_LOG=os.path.join(tmp, "audit.jsonl"),
               CH_TOC_STATE=os.path.join(tmp, "toc.json"),
               CH_TOC_PATH=os.path.join(REPO_ROOT, "TOC.md"))
    server = subprocess.Popen(
        [sys.executable, "service/chronohive_api.py"],
        cwd=REPO_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        port = 18081
        for _ in range(60):
            try:
                status, body = _http(port, "GET", "/v1/health")
                if status == 200:
                    break
            except OSError:
                time.sleep(0.5)
        else:
            server.terminate()
            out, _ = server.communicate(timeout=10)
            raise RuntimeError("server did not start\n" + out)

        status, body = _http(port, "GET", "/v1/health")
        assert status == 200 and body["status"] == "ok", body
        print("health 200, version", body["version"])

        status, toc = _http(port, "GET", "/v1/toc")
        assert status == 200 and toc["toc_sha256"], toc
        print("TOC fetched, sha256", toc["toc_sha256"][:16] + "...")

        # gate: eval endpoints 403 before acceptance
        status, body = _http(port, "POST", "/v1/scenarios", raw_key,
                             {"jobs": 2, "seeds": [7]})
        assert status == 403 and body["error"] == "toc_acceptance_required", body
        print("pre-accept scenario -> 403 toc_acceptance_required")

        # sign + accept
        sk, _pk = ed25519.generate_keypair()
        token = sign_toc.build_acceptance(
            toc_sha256=toc["toc_sha256"], key_id="check-01",
            signer_name="Check Harness", organization="CI",
            email="ci@example.com", secret_key=sk)
        status, body = _http(port, "POST", "/v1/toc/accept", raw_key, token)
        assert status == 200 and body.get("accepted"), body
        print("TOC accepted for check-01")

        # bad signature must be rejected
        evil = dict(token)
        evil_sig = bytearray(bytes.fromhex(evil["signature"]))
        evil_sig[10] ^= 1
        evil["signature"] = bytes(evil_sig).hex()
        status, body = _http(port, "POST", "/v1/toc/accept", raw_key, evil)
        assert status == 403 and body["error"] == "toc_acceptance_rejected", body
        print("forged token -> 403 rejected")

        # future-dated timestamp must be rejected
        import toc_common as _tc
        future_sk, _ = ed25519.generate_keypair()
        future_token = _tc.build_token(
            toc_sha256=toc["toc_sha256"], key_id="check-01",
            signer_name="Check Harness", organization="CI",
            email="ci@example.com",
            timestamp=int(time.time()) + 3600, secret_key=future_sk)
        status, body = _http(port, "POST", "/v1/toc/accept", raw_key,
                             future_token)
        assert status == 403 and body["error"] == "toc_acceptance_rejected" \
            and "future" in body["reason"], body
        print("future-dated token -> 403 rejected")

        # implausibly old timestamp must be rejected
        old_token = _tc.build_token(
            toc_sha256=toc["toc_sha256"], key_id="check-01",
            signer_name="Check Harness", organization="CI",
            email="ci@example.com",
            timestamp=1000000000, secret_key=future_sk)
        status, body = _http(port, "POST", "/v1/toc/accept", raw_key,
                             old_token)
        assert status == 403 and body["error"] == "toc_acceptance_rejected", body
        print("ancient timestamp token -> 403 rejected")

        # scenario (default knobs: the verified configuration)
        status, payload = _http(port, "POST", "/v1/scenarios", raw_key,
                                {"jobs": 8, "ckpt_gb": 200.0,
                                 "prefetch_gb": 150.0, "seeds": [7]})
        assert status == 200, payload
        sid = payload["scenario_id"]
        seed0 = payload["result"]["seeds"][0]
        assert seed0["verdict"]["pass"], seed0["verdict"]
        print(f"scenario {sid}: stall reduction "
              f"{seed0['verdict']['stall_reduction'] * 100:.1f}% PASS")

        # decide
        decide_body = {"now_s": 0, "window": 0, "requests": [
            {"dataset_id": "a.ckpt", "kind": "checkpoint",
             "bytes_remaining": 50e9, "deadline_s": 120},
            {"dataset_id": "b.prefetch", "kind": "prefetch",
             "bytes_remaining": 25e9},
        ]}
        status, decision = _http(port, "POST", "/v1/admission/decide",
                                 raw_key, decide_body)
        assert status == 200, decision
        assert decision["admitted"] and decision["kernel"]["admits"] >= 1
        print(f"decide 200: admitted={list(decision['admitted'])}, "
              f"refused={decision['refused']}")

        # fetch
        status, fetched = _http(port, "GET", f"/v1/scenarios/{sid}", raw_key)
        assert status == 200 and fetched["scenario_id"] == sid, fetched
        print("scenario fetch 200")

        # audit log has entries, no raw key
        audit = open(os.path.join(tmp, "audit.jsonl")).read()
        assert raw_key not in audit and '"key_id": "check-01"' in audit
        print("audit log sane (key_id only, no raw key)")

        # toc acceptance persisted, with server-side accepted_at
        persisted = json.load(open(os.path.join(tmp, "toc.json")))
        assert "check-01" in persisted
        rec = persisted["check-01"]
        assert isinstance(rec.get("accepted_at"), int), rec
        assert abs(rec["accepted_at"] - int(time.time())) < 300, rec
        assert rec["token"]["key_id"] == "check-01", rec
        print("TOC acceptance persisted (server-side accepted_at)")

        # run the shipped example against this server
        step("examples/eval_walkthrough.py")
        env2 = dict(os.environ, CH_EVAL_API_URL=f"http://127.0.0.1:{port}",
                    CH_EVAL_API_KEY=raw_key, CH_EVAL_KEY_ID="check-01",
                    CH_EVAL_NAME="Check Harness", CH_EVAL_ORG="CI",
                    CH_EVAL_EMAIL="ci@example.com")
        proc = subprocess.run(
            [sys.executable, "examples/eval_walkthrough.py"],
            cwd=REPO_ROOT, env=env2, capture_output=True, text=True,
            timeout=300)
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert "Walkthrough complete" in proc.stdout
        print("example ran end to end OK")
    finally:
        server.terminate()
        server.wait(timeout=10)


def main() -> None:
    check_compile()
    check_ed25519()
    check_api_flow()
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    import urllib.error  # noqa: E402
    main()
