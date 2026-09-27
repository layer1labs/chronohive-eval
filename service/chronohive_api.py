#!/usr/bin/env python3
"""ChronoHive admission API service (evaluation build).

Exposes the ChronoHive storage-admission capability over HTTP:

  * GET  /v1/toc              canonical Terms of Confidentiality text + hash
  * POST /v1/toc/accept       execute the TOC (signed acceptance token)
  * POST /v1/scenarios        run the deterministic checkpoint/prefetch
                              admission simulation with chosen knobs
  * GET  /v1/scenarios/{id}   fetch a previous scenario result
  * POST /v1/admission/decide  live kernel decision path: submit transfer
                              requests, get grant/refuse + QoS levels back
  * GET  /v1/health            unauthenticated liveness probe
  * GET  /                     minimal eval UI (TOC step + scenario knobs)

TOC gating: every eval endpoint (scenarios, decide, scenario fetch)
requires the calling API key to have an accepted TOC on file. The
evaluator signs the canonical TOC text with ed25519 (tools/sign_toc.py),
POSTs the acceptance token to /v1/toc/accept, and the server verifies
the signature against the pinned TOC hash before activating the key.
Acceptances persist in CH_TOC_STATE across restarts.

Honesty boundaries (also stamped on every response and the UI):
  * The storage backend, the incast contention model, and the storage API
    surface are SIMULATED. No storage-vendor hardware is involved.
  * The admission decisions are REAL: every grant/refuse comes from the
    ChronoHive Runtime kernel's capacity discipline, re-evaluated per
    scheduling window. The service never reimplements admission logic;
    it calls AdmissionCoordinator.admit_window directly.

Evaluation controls:
  * API-key auth: Authorization: Bearer <key>. Keys are stored as
    salted SHA-256 hashes with expiry; raw keys never touch the repo.
  * Per-key quotas: scenario runs per day, decide calls per minute.
  * Append-only JSONL audit log of every authenticated call.

Stdlib only. Configuration via environment:

  PORT                  listen port (default 8080)
  CH_API_KEYS_FILE      JSON file with key entries (default ./api_keys.json)
  CH_AUDIT_LOG          audit log path (default ./audit.jsonl)
  CH_TOC_PATH           canonical TOC.md path (default: searched)
  CH_TOC_STATE          TOC acceptance store (default ./toc_acceptances.json)
  CH_MAX_STORED         max cached scenario results (default 128)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SERVICE_ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SERVICE_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import demo_admission as demo  # noqa: E402
from demo_admission import AdmissionCoordinator, SimulatedStorage  # noqa: E402
import toc_common  # noqa: E402

VERSION = "1.1.0"
HONESTY = (
    "Storage backend, contention model, and storage API surface are simulated; "
    "admission decisions come from the real ChronoHive Runtime kernel; "
    "results are simulation outcomes, not hardware measurements."
)

# --------------------------------------------------------------------------
# Terms of Confidentiality (TOC) loading
# --------------------------------------------------------------------------

_TOC_CANDIDATES = (
    os.environ.get("CH_TOC_PATH"),
    "/app/TOC.md",
    os.path.join(REPO_ROOT, "TOC.md"),
    os.path.join(SERVICE_ROOT, "TOC.md"),
    os.path.join(os.getcwd(), "TOC.md"),
)


def load_toc() -> tuple[str, bytes]:
    """Return (sha256, text) of the canonical TOC. Fail fast if missing:
    the gate must never run without a pinned TOC document."""
    for candidate in _TOC_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            with open(candidate, "rb") as fh:
                text = fh.read()
            digest = hashlib.sha256(text).hexdigest()
            print(f"TOC loaded from {candidate} (sha256={digest})")
            return digest, text
    raise RuntimeError(
        "canonical TOC.md not found; set CH_TOC_PATH. The API refuses to "
        "start without a pinned Terms of Confidentiality document.")


TOC_SHA256, TOC_TEXT = load_toc()

# --------------------------------------------------------------------------
# Scenario runner (mirrors scripts/demo_admission.py::main payload shape)
# --------------------------------------------------------------------------

_SCENARIO_GLOBALS = ("N_JOBS", "CKPT_BYTES", "PREFETCH_BYTES", "ALPHA",
                     "MISS_PENALTY_S")
_scenario_lock = threading.Lock()


def _jain(xs: list[float]) -> float:
    s1, s2 = sum(xs), sum(x * x for x in xs)
    return (s1 * s1) / (len(xs) * s2) if s2 else 1.0


def run_scenario(jobs: int, ckpt_gb: float, prefetch_gb: float, alpha: float,
                 seeds: list[int], miss_penalty_s: float = 60.0) -> dict:
    """Run baseline + admission for each seed. Deterministic per seed.

    The demo script keeps scenario knobs as module globals; they are set
    under a lock and restored afterwards so concurrent decide() calls
    (which are stateless) are unaffected.
    """
    with _scenario_lock:
        saved = {name: getattr(demo, name) for name in _SCENARIO_GLOBALS}
        try:
            demo.N_JOBS = jobs
            demo.CKPT_BYTES = ckpt_gb * 1e9
            demo.PREFETCH_BYTES = prefetch_gb * 1e9
            demo.ALPHA = alpha
            demo.MISS_PENALTY_S = miss_penalty_s
            per_seed = []
            for seed in seeds:
                base = demo.run_policy(seed, coordinated=False)
                adm = demo.run_policy(seed, coordinated=True)
                stall_cut = ((base.stall - adm.stall) / base.stall
                             if base.stall else 0.0)
                makespan_tol = 0.01 * base.makespan
                per_seed.append({
                    "seed": seed,
                    "baseline": {
                        "gpu_stall_s": base.stall,
                        "ckpt_misses": base.misses,
                        "makespan_s": base.makespan,
                        "jain_fairness": _jain(base.per_job_stall),
                    },
                    "admission": {
                        "gpu_stall_s": adm.stall,
                        "ckpt_misses": adm.misses,
                        "makespan_s": adm.makespan,
                        "jain_fairness": _jain(adm.per_job_stall),
                        "kernel_admits": adm.admits,
                        "kernel_refusals": adm.refusals,
                    },
                    "verdict": {
                        "stall_reduction": stall_cut,
                        "makespan_delta_s": adm.makespan - base.makespan,
                        "pass": bool(stall_cut >= 0.20
                                     and adm.makespan <= base.makespan + makespan_tol),
                    },
                })
        finally:
            for name, value in saved.items():
                setattr(demo, name, value)
    return {
        "simulated_backend": True,
        "honesty": HONESTY,
        "params": {"jobs": jobs, "ckpt_gb": ckpt_gb,
                   "prefetch_gb": prefetch_gb, "incast_alpha": alpha,
                   "seeds": seeds, "miss_penalty_s": miss_penalty_s},
        "seeds": per_seed,
    }


# --------------------------------------------------------------------------
# Live kernel decision path
# --------------------------------------------------------------------------

def decide_once(now_s: float, window: int, requests: list[dict]) -> dict:
    """Run one admission window through the REAL kernel.

    Each request becomes a PendingTransfer; AdmissionCoordinator.admit_window
    builds a fresh Runtime kernel, admits earliest-deadline-first against
    the provisioned write/read pipes, and drives QoS levels on the
    (simulated) storage surface from the grant decisions.
    """
    transfers = []
    for r in requests:
        deadline = r.get("deadline_s")
        transfers.append(demo.PendingTransfer(
            dataset_id=r["dataset_id"],
            job_id=int(r.get("job_id", 0)),
            kind=r["kind"],
            remaining=float(r["bytes_remaining"]),
            deadline=float(deadline) if deadline is not None else math.inf,
        ))
    coord = AdmissionCoordinator()
    storage = SimulatedStorage(coord)
    coord.storage = storage
    coord.admit_window(now_s, transfers, window)
    return {
        "simulated_backend": True,
        "honesty": HONESTY,
        "window": window,
        "admitted": dict(coord.admitted_this_window),  # dataset_id -> B/s
        "refused": sorted(coord.refused_this_window),
        "qos": dict(storage.qos),  # dataset_id -> 0-63, driven by grant decisions
        "kernel": {"admits": coord.admits, "refusals": coord.refusals},
    }


# --------------------------------------------------------------------------
# Key auth, quotas, audit, TOC acceptances
# --------------------------------------------------------------------------

def _key_digest(salt: str, raw_key: str) -> str:
    """Salted SHA-256 of a raw API key. The salt is per-key and stored
    alongside the hash; an empty salt reproduces the legacy unsalted
    scheme for backward compatibility with old keys files."""
    return hashlib.sha256(salt.encode() + raw_key.encode()).hexdigest()


class KeyStore:
    """API keys as salted hashes with expiry and quotas. Raw keys are never
    stored; the operator keeps the raw key, the file keeps the hash."""

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._keys: dict[str, dict] = {}  # key_hash -> entry
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path) as fh:
                entries = json.load(fh)
        except FileNotFoundError:
            entries = []
        with self._lock:
            self._keys = {e["key_hash"]: e for e in entries}

    def lookup(self, raw_key: str) -> dict | None:
        with self._lock:
            entries = list(self._keys.values())
        entry = None
        for e in entries:
            digest = _key_digest(e.get("salt", ""), raw_key)
            if hmac.compare_digest(e["key_hash"], digest):
                entry = e
                break
        if entry is None:
            return None
        if entry.get("expires_at", 0) < time.time():
            return None
        return entry


class TocAcceptances:
    """Persisted TOC acceptances: key_id -> {"token": token, "accepted_at": ts}.

    The token's signature was verified at accept time against the pinned
    TOC hash; the store is the record that a given key executed the TOC.
    accepted_at is the server's own clock at accept time — the authoritative
    execution time — never the client-supplied token timestamp.
    """

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path) as fh:
                self._accepted = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            self._accepted = {}

    def is_accepted(self, key_id: str) -> bool:
        with self._lock:
            return key_id in self._accepted

    def record(self, key_id: str, token: dict) -> None:
        with self._lock:
            self._accepted[key_id] = {
                "accepted_at": int(time.time()),
                "token": token,
            }
            tmp = self._path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(self._accepted, fh, indent=2)
                fh.write("\n")
            os.replace(tmp, self._path)


class Quotas:
    """Per-key token buckets: scenarios per rolling day, decides per minute."""

    def __init__(self):
        self._lock = threading.Lock()
        self._scenario_ts: dict[str, list[float]] = {}
        self._decide_ts: dict[str, list[float]] = {}

    def _take(self, bucket: dict[str, list[float]], key_id: str,
              limit: int, window_s: float) -> tuple[bool, float]:
        now = time.time()
        with self._lock:
            ts = [t for t in bucket.get(key_id, []) if now - t < window_s]
            if len(ts) >= limit:
                retry = window_s - (now - ts[0])
                bucket[key_id] = ts
                return False, max(retry, 0.0)
            ts.append(now)
            bucket[key_id] = ts
            return True, 0.0

    def check_scenario(self, key_id: str, limit: int) -> tuple[bool, float]:
        return self._take(self._scenario_ts, key_id, limit, 86400.0)

    def check_decide(self, key_id: str, limit: int) -> tuple[bool, float]:
        return self._take(self._decide_ts, key_id, limit, 60.0)


class AuditLog:
    """Append-only JSONL. Records call metadata, never raw keys; request
    bodies are recorded as a SHA-256 digest (eval params can be large)."""

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def record(self, key_id: str | None, method: str, path: str,
               status: int, body: bytes, ms: float) -> None:
        entry = {
            "ts": time.time(),
            "key_id": key_id,
            "method": method,
            "path": path,
            "status": status,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "duration_ms": round(ms, 2),
        }
        with self._lock:
            with open(self._path, "a") as fh:
                fh.write(json.dumps(entry) + "\n")


# --------------------------------------------------------------------------
# HTTP service
# --------------------------------------------------------------------------

def _bad(msg: str) -> tuple[int, dict]:
    return 400, {"error": msg, "simulated_backend": True}


def _toc_required() -> tuple[int, dict]:
    return 403, {
        "error": "toc_acceptance_required",
        "message": ("This API key has not executed the Terms of "
                    "Confidentiality. Sign TOC.md with tools/sign_toc.py "
                    "and POST the acceptance token to /v1/toc/accept."),
        "toc_sha256": TOC_SHA256,
        "accept_endpoint": "/v1/toc/accept",
        "toc_endpoint": "/v1/toc",
        "simulated_backend": True,
    }


def validate_scenario(body: dict) -> tuple[dict | None, tuple[int, dict] | None]:
    try:
        jobs = int(body.get("jobs", 8))
        ckpt_gb = float(body.get("ckpt_gb", 200.0))
        prefetch_gb = float(body.get("prefetch_gb", 150.0))
        alpha = float(body.get("incast_alpha", 0.2))
        seeds = [int(s) for s in body.get("seeds", [7])]
        miss_penalty_s = float(body.get("miss_penalty_s", 60.0))
    except (TypeError, ValueError):
        return None, _bad("scenario params must be numeric")
    if not 1 <= jobs <= 64:
        return None, _bad("jobs must be 1..64")
    if not 1.0 <= ckpt_gb <= 10000.0:
        return None, _bad("ckpt_gb must be 1..10000")
    if not 1.0 <= prefetch_gb <= 10000.0:
        return None, _bad("prefetch_gb must be 1..10000")
    if not 0.0 <= alpha <= 1.0:
        return None, _bad("incast_alpha must be 0..1")
    if not 1 <= len(seeds) <= 10:
        return None, _bad("seeds must list 1..10 seeds")
    if not 0.0 <= miss_penalty_s <= 3600.0:
        return None, _bad("miss_penalty_s must be 0..3600")
    return {"jobs": jobs, "ckpt_gb": ckpt_gb, "prefetch_gb": prefetch_gb,
            "alpha": alpha, "seeds": seeds,
            "miss_penalty_s": miss_penalty_s}, None


def validate_decide(body: dict) -> tuple[dict | None, tuple[int, dict] | None]:
    try:
        now_s = float(body.get("now_s", 0.0))
        window = int(body.get("window", 0))
        requests = body.get("requests", [])
    except (TypeError, ValueError):
        return None, _bad("now_s/window must be numeric, requests a list")
    if not isinstance(requests, list) or not 1 <= len(requests) <= 256:
        return None, _bad("requests must list 1..256 transfer requests")
    if now_s < 0 or window < 0:
        return None, _bad("now_s and window must be non-negative")
    for r in requests:
        if not isinstance(r, dict):
            return None, _bad("each request must be an object")
        if not r.get("dataset_id") or not isinstance(r["dataset_id"], str):
            return None, _bad("each request needs a dataset_id string")
        if r.get("kind") not in ("checkpoint", "prefetch"):
            return None, _bad("kind must be 'checkpoint' or 'prefetch'")
        try:
            remaining = float(r.get("bytes_remaining", 0))
        except (TypeError, ValueError):
            return None, _bad("bytes_remaining must be numeric")
        if remaining <= 0:
            return None, _bad("bytes_remaining must be positive")
        deadline = r.get("deadline_s")
        if deadline is not None:
            try:
                deadline = float(deadline)
            except (TypeError, ValueError):
                return None, _bad("deadline_s must be numeric or null")
            if deadline <= now_s:
                return None, _bad("deadline_s must be after now_s")
    return {"now_s": now_s, "window": window, "requests": requests}, None


UI_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>ChronoHive admission API — eval console</title>
<style>body{font-family:system-ui,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;color:#0f172a}
.banner{background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:12px 16px;margin-bottom:16px}
.toc{background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:12px 16px;margin-bottom:16px}
label{display:block;margin:8px 0 2px;font-size:13px;color:#475569}
input{padding:6px 8px;border:1px solid #cbd5e1;border-radius:6px;width:220px}
button{background:#0f172a;color:#fff;border:0;border-radius:6px;padding:8px 18px;margin-top:12px;cursor:pointer}
pre{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px;overflow:auto;font-size:12px}
code{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:12px}
.pass{color:#059669;font-weight:700}.fail{color:#e11d48;font-weight:700}
table{border-collapse:collapse;margin-top:12px}td,th{border:1px solid #cbd5e1;padding:6px 10px;font-size:13px;text-align:right}
th{background:#f1f5f9}</style></head><body>
<h2>ChronoHive admission API — eval console</h2>
<div class="banner"><b>Evaluation build.</b> Storage backend, contention model, and
storage API surface are <b>simulated</b>; every grant/refuse decision comes from the
real ChronoHive Runtime kernel. Numbers are simulation outcomes, not hardware
measurements.</div>
<div class="toc"><b>Step 1 — execute the Terms of Confidentiality.</b>
Eval endpoints stay locked until your API key has a verified TOC acceptance on
file. <a href="/v1/toc">Read the canonical TOC</a>, then sign it:
<pre>python3 tools/sign_toc.py --api-url <em>&lt;this server&gt;</em> --key-id <em>&lt;your key id&gt;</em> --submit</pre>
Your signature is verified against the pinned TOC hash before your key is
activated. <span id="tochash"></span></div>
<label>API key</label><input id="key" type="password" placeholder="Bearer key">
<label>Jobs</label><input id="jobs" type="number" value="8">
<label>Checkpoint GB</label><input id="ckpt" type="number" value="200">
<label>Prefetch GB</label><input id="prefetch" type="number" value="150">
<label>Incast alpha</label><input id="alpha" type="number" step="0.05" value="0.2">
<label>Seeds (comma-separated)</label><input id="seeds" value="7">
<br><button onclick="run()">Run scenario</button>
<div id="out"></div>
<script>
fetch('/v1/toc').then(r=>r.json()).then(j=>{
  document.getElementById('tochash').innerHTML='Pinned TOC sha256: <code>'+j.toc_sha256.slice(0,16)+'…</code>';
}).catch(()=>{});
async function run(){
  const key=document.getElementById('key').value.trim();
  const seeds=document.getElementById('seeds').value.split(',').map(s=>parseInt(s.trim())).filter(Number.isInteger);
  const body={jobs:parseInt(document.getElementById('jobs').value),
    ckpt_gb:parseFloat(document.getElementById('ckpt').value),
    prefetch_gb:parseFloat(document.getElementById('prefetch').value),
    incast_alpha:parseFloat(document.getElementById('alpha').value), seeds};
  const out=document.getElementById('out');
  out.innerHTML='<p>Running…</p>';
  try{
    const r=await fetch('/v1/scenarios',{method:'POST',
      headers:{'Content-Type':'application/json','Authorization':'Bearer '+key},
      body:JSON.stringify(body)});
    const j=await r.json();
    if(!r.ok){out.innerHTML='<pre>'+JSON.stringify(j,null,2)+'</pre>';return;}
    let h='<h3>Scenario '+j.scenario_id+'</h3><table><tr><th>seed</th><th>baseline stall (s)</th><th>admission stall (s)</th><th>misses base/adm</th><th>reduction</th><th>verdict</th></tr>';
    for(const s of j.result.seeds){
      const v=s.verdict;
      h+='<tr><td>'+s.seed+'</td><td>'+s.baseline.gpu_stall_s.toFixed(0)+'</td><td>'+s.admission.gpu_stall_s.toFixed(0)+'</td><td>'+s.baseline.ckpt_misses+' / '+s.admission.ckpt_misses+'</td><td>'+(v.stall_reduction*100).toFixed(1)+'%</td><td class="'+(v.pass?'pass':'fail')+'">'+(v.pass?'PASS':'FAIL')+'</td></tr>';
    }
    out.innerHTML=h+'</table><pre>'+JSON.stringify(j.result.params,null,2)+'</pre>';
  }catch(e){out.innerHTML='<pre>request failed: '+e+'</pre>';}
}
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "ChronoHiveAdmissionAPI/" + VERSION

    # set by make_server
    keystore: KeyStore
    toc: TocAcceptances
    quotas: Quotas
    audit: AuditLog
    scenarios: dict
    scenario_order: list
    max_stored: int
    store_lock: threading.Lock

    def log_message(self, *args):  # keep stdout for audit-relevant lines only
        pass

    def _send(self, status: int, obj: dict, extra_headers: dict | None = None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        return self.rfile.read(min(n, 4 * 1024 * 1024)) if n else b""

    def _auth(self) -> tuple[dict | None, tuple[int, dict] | None]:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or len(auth) < 9:
            return None, (401, {"error": "missing or malformed Authorization header",
                                "simulated_backend": True})
        entry = self.keystore.lookup(auth[7:].strip())
        if entry is None:
            return None, (401, {"error": "invalid or expired API key",
                                "simulated_backend": True})
        return entry, None

    def _toc_gate(self, entry: dict) -> tuple[int, dict] | None:
        if not self.toc.is_accepted(entry["id"]):
            return _toc_required()
        return None

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/v1/health":
            self._send(200, {"status": "ok", "version": VERSION,
                             "toc_sha256": TOC_SHA256,
                             "simulated_backend": True})
            return
        if path == "/v1/toc":
            self._send(200, {"toc_sha256": TOC_SHA256,
                             "toc_text": TOC_TEXT.decode("utf-8"),
                             "accept_endpoint": "/v1/toc/accept",
                             "simulated_backend": True})
            return
        if path == "/":
            body = UI_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/v1/scenarios/"):
            entry, err = self._auth()
            t0 = time.time()
            raw = b""
            if err:
                status, obj = err
                key_id = None
            else:
                key_id = entry["id"]
                gate = self._toc_gate(entry)
                if gate:
                    status, obj = gate
                else:
                    sid = path[len("/v1/scenarios/"):]
                    with self.store_lock:
                        result = self.scenarios.get(sid)
                    if result is None:
                        status, obj = 404, {"error": "unknown scenario id",
                                            "simulated_backend": True}
                    else:
                        status, obj = 200, {"scenario_id": sid,
                                            "simulated_backend": True,
                                            "result": result}
            self._send(status, obj)
            self.audit.record(key_id, "GET", path, status, raw,
                              (time.time() - t0) * 1000)
            return
        self._send(404, {"error": "not found", "simulated_backend": True})

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/v1/toc", "/v1/toc/accept", "/v1/scenarios",
                        "/v1/admission/decide"):
            self._send(404, {"error": "not found",
                             "simulated_backend": True})
            return
        t0 = time.time()
        raw = self._read_body()
        if path == "/v1/toc":  # canonical TOC is fetched with GET
            self._send(405, {"error": "use GET /v1/toc",
                             "simulated_backend": True})
            return
        entry, err = self._auth()
        if err:
            status, obj = err
            key_id = None
        else:
            key_id = entry["id"]
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                status, obj = _bad("request body must be JSON")
            else:
                status, obj = self._dispatch(path, entry, body)
        extra = None
        if status == 429:
            extra = {"Retry-After": str(obj.get("retry_after_s", 60))}
        self._send(status, obj, extra)
        self.audit.record(key_id, "POST", path, status, raw,
                          (time.time() - t0) * 1000)

    def _dispatch(self, path: str, entry: dict,
                  body: dict) -> tuple[int, dict]:
        if path == "/v1/toc/accept":
            ok, reason = toc_common.verify_token(body, TOC_SHA256,
                                                 entry["id"])
            if not ok:
                return 403, {"error": "toc_acceptance_rejected",
                             "reason": reason,
                             "toc_sha256": TOC_SHA256,
                             "simulated_backend": True}
            self.toc.record(entry["id"], body)
            return 200, {"accepted": True, "key_id": entry["id"],
                         "toc_sha256": TOC_SHA256,
                         "signer": body.get("signer_name"),
                         "organization": body.get("organization"),
                         "accepted_at": int(time.time()),
                         "simulated_backend": True}
        gate = self._toc_gate(entry)
        if gate:
            return gate
        if path == "/v1/scenarios":
            ok, retry = self.quotas.check_scenario(
                entry["id"], int(entry.get("quota_scenarios_per_day", 50)))
            if not ok:
                return 429, {"error": "scenario quota exceeded",
                             "retry_after_s": int(retry) + 1,
                             "simulated_backend": True}
            params, err = validate_scenario(body)
            if err:
                return err
            result = run_scenario(**params)
            sid = secrets.token_hex(8)
            with self.store_lock:
                self.scenarios[sid] = result
                self.scenario_order.append(sid)
                while len(self.scenario_order) > self.max_stored:
                    self.scenarios.pop(self.scenario_order.pop(0), None)
            return 200, {"scenario_id": sid, "simulated_backend": True,
                         "result": result}
        # /v1/admission/decide
        ok, retry = self.quotas.check_decide(
            entry["id"], int(entry.get("quota_decide_per_min", 60)))
        if not ok:
            return 429, {"error": "decide quota exceeded",
                         "retry_after_s": int(retry) + 1,
                         "simulated_backend": True}
        params, err = validate_decide(body)
        if err:
            return err
        return 200, decide_once(params["now_s"], params["window"],
                                params["requests"])


def make_server(port: int, keys_file: str, audit_log: str,
                toc_state: str, max_stored: int) -> ThreadingHTTPServer:
    Handler.keystore = KeyStore(keys_file)
    Handler.toc = TocAcceptances(toc_state)
    Handler.quotas = Quotas()
    Handler.audit = AuditLog(audit_log)
    Handler.scenarios = {}
    Handler.scenario_order = []
    Handler.max_stored = max_stored
    Handler.store_lock = threading.Lock()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    keys_file = os.environ.get("CH_API_KEYS_FILE",
                               os.path.join(SERVICE_ROOT, "api_keys.json"))
    audit_log = os.environ.get("CH_AUDIT_LOG",
                               os.path.join(SERVICE_ROOT, "audit.jsonl"))
    toc_state = os.environ.get("CH_TOC_STATE",
                               os.path.join(SERVICE_ROOT,
                                            "toc_acceptances.json"))
    max_stored = int(os.environ.get("CH_MAX_STORED", "128"))
    server = make_server(port, keys_file, audit_log, toc_state, max_stored)
    print(f"chronohive admission API v{VERSION} listening on :{port} "
          f"(simulated backend; every response stamped; "
          f"TOC sha256={TOC_SHA256[:16]}...)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
