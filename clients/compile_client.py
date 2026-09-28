#!/usr/bin/env python3
# © 2026 Layer1Labs Silicon Inc. All rights reserved.
# CONFIDENTIAL — ChronoHive Evaluation Package. Licensed solely for
# evaluation under the ChronoHive Terms of Confidentiality (TOC.md) and
# the ChronoHive Evaluation License (LICENSE). Do not distribute.
"""ChronoHive LF compile test client.

Submits a COMPLETE Lingua Franca project (a file map: relative path ->
LF source) to the compile API and verifies that a valid .chb blob comes
back. Also verifies blobs produced by the local pinned toolchain.

Request contract (mirrors POST /v1/lf/compile in the authoritative API):

    {
      "files":      {"IoCoordinator.lf": "<utf-8 LF source>", ...},
      "entrypoint": "IoCoordinator.lf",
      "params":     {"steps": 200},          # chronoc --param (int64)
      "capacities": {"storage_bw": 100}      # chronoc --capacity (uint32)
    }

Validation rules enforced client-side (the server enforces the same):
  * 1..64 files; each path is a clean relative POSIX path ending in .lf
    (no backslashes, no leading '/' or '~', no '.'/'..' segments,
    max 256 chars); each file is non-empty UTF-8, <= 512 KiB;
    aggregate <= 2 MiB.
  * entrypoint must name a file in the map.
  * params values are integers (int64); capacities values are integers
    (0..2**32-1).

Blob verification parses the CHB1 envelope directly:
  magic "CHB1" | version u16 (=1) | flags u16 | step_ns u64 |
  string table | capacities | operations | schedule | LF->op bindings |
  meta (source sha256, lfc/chronoc version strings, target steps) |
  CRC-32 (IEEE) trailer over every preceding byte.

Modes:
  --api-url URL --api-key KEY   POST the project to /v1/lf/compile and
                               verify the returned blob.
  --local                      Compile with the local pinned toolchain
                               (lfc via $LFC, chronoc via $CHRONOC).
  --check                      CI mode: build the file map, run the pinned
                               lfc validation gate on the entrypoint, check
                               the request schema, and verify the checked-in
                               reference blob. No chronoc, no network.

Stdlib only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import posixpath
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zlib

# Pins — must match docs/LF_TOOLCHAIN.md and the authoritative API.
LFC_VERSION_PIN = "0.13.0"
CHRONOC_VERSION_PIN = "0.1.0"

# Limits — mirror the authoritative API's validation.
MAX_LF_SOURCE_BYTES = 512 * 1024
MAX_PROJECT_FILES = 64
MAX_PROJECT_BYTES = 2 * 1024 * 1024
MAX_PATH_CHARS = 256

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CompileError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Project handling
# --------------------------------------------------------------------------

def project_path_error(path: str) -> str | None:
    """Reject anything that is not a clean relative .lf path inside the
    project root. Returns an error string, or None when valid."""
    if not isinstance(path, str) or not path:
        return "project paths must be non-empty strings"
    if len(path) > MAX_PATH_CHARS:
        return f"project path too long (>{MAX_PATH_CHARS} chars): {path!r}"
    if "\\" in path:
        return f"project path must use '/' separators: {path!r}"
    if path.startswith("/") or path.startswith("~"):
        return f"project path must be relative: {path!r}"
    norm = posixpath.normpath(path)
    if norm != path or norm == "." or norm.startswith(".."):
        return f"project path escapes the project root: {path!r}"
    if not norm.endswith(".lf"):
        return f"project files must end in .lf: {path!r}"
    return None


def build_file_map(lf_dir: str) -> dict[str, str]:
    """Read every .lf file under lf_dir into {relative path: source}."""
    if not os.path.isdir(lf_dir):
        raise CompileError(f"LF project dir not found: {lf_dir}")
    files: dict[str, str] = {}
    total = 0
    for root, _dirs, names in os.walk(lf_dir):
        for name in sorted(names):
            if name.startswith(".") or not name.endswith(".lf"):
                continue
            full = os.path.join(root, name)
            rel = posixpath.join(
                *os.path.relpath(full, lf_dir).split(os.sep))
            err = project_path_error(rel)
            if err:
                raise CompileError(err)
            with open(full, "r", encoding="utf-8") as fh:
                content = fh.read()
            if not content.strip():
                raise CompileError(f"file {rel!r} is empty")
            nbytes = len(content.encode("utf-8"))
            if nbytes > MAX_LF_SOURCE_BYTES:
                raise CompileError(
                    f"file {rel!r} too large ({nbytes} > "
                    f"{MAX_LF_SOURCE_BYTES} bytes)")
            total += nbytes
            files[rel] = content
    if not files:
        raise CompileError(f"no .lf files found under {lf_dir}")
    if len(files) > MAX_PROJECT_FILES:
        raise CompileError(f"too many files ({len(files)} > "
                           f"{MAX_PROJECT_FILES})")
    if total > MAX_PROJECT_BYTES:
        raise CompileError(f"project too large ({total} > "
                           f"{MAX_PROJECT_BYTES} bytes)")
    return files


def coerce_int_map(mapping: dict, kind: str, lo: int, hi: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, value in mapping.items():
        if not isinstance(key, str) or not key.replace("_", "").isalnum():
            raise CompileError(f"{kind} keys must be identifier strings: "
                               f"{key!r}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise CompileError(f"{kind} '{key}' must be an integer, got "
                               f"{value!r}")
        if not lo <= value <= hi:
            raise CompileError(f"{kind} '{key}' out of range [{lo}, {hi}]")
        out[key] = value
    return out


def build_request(files: dict[str, str], entrypoint: str,
                  params: dict[str, int] | None = None,
                  capacities: dict[str, int] | None = None) -> dict:
    """Build the exact JSON body POSTed to /v1/lf/compile."""
    if entrypoint not in files:
        raise CompileError(f"entrypoint {entrypoint!r} is not in the "
                           f"file map ({sorted(files)})")
    params = coerce_int_map(params or {}, "param", -(2 ** 63), 2 ** 63 - 1)
    capacities = coerce_int_map(capacities or {}, "capacity", 0, 2 ** 32 - 1)
    return {
        "files": files,
        "entrypoint": entrypoint,
        "params": params,
        "capacities": capacities,
    }


def input_sha256(files: dict[str, str]) -> str:
    """Deterministic fingerprint of the project: sorted paths and their
    exact contents. The server returns this as `input_sha256`."""
    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(files[rel].encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


# --------------------------------------------------------------------------
# CHB1 blob verification
# --------------------------------------------------------------------------

def _crc32_ieee(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def verify_blob(blob: bytes) -> dict:
    """Parse and verify a .chb blob. Returns provenance metadata.

    Raises CompileError on any structural problem (bad magic, version,
    truncation, CRC mismatch).
    """
    if len(blob) < 4 + 2 + 2 + 8 + 4 + 32 + 4 + 4:
        raise CompileError(f"blob too short ({len(blob)} bytes)")
    if blob[:4] != b"CHB1":
        raise CompileError(f"bad magic: {blob[:4]!r} (want b'CHB1')")
    body, trailer = blob[:-4], blob[-4:]
    stored = struct.unpack("<I", trailer)[0]
    computed = _crc32_ieee(body)
    if stored != computed:
        raise CompileError(f"CRC-32 mismatch: stored {stored:08x} != "
                           f"computed {computed:08x}")

    off = 4
    version, flags = struct.unpack_from("<HH", body, off)
    off += 4
    if version != 1:
        raise CompileError(f"unsupported blob version: {version}")
    step_ns = struct.unpack_from("<Q", body, off)[0]
    off += 8

    def need(n: int) -> None:
        if off + n > len(body):
            raise CompileError("blob truncated while parsing")

    need(4)
    n_strings = struct.unpack_from("<I", body, off)[0]
    off += 4
    strings: list[str] = []
    for _ in range(n_strings):
        need(4)
        ln = struct.unpack_from("<I", body, off)[0]
        off += 4
        need(ln)
        strings.append(body[off:off + ln].decode("utf-8"))
        off += ln

    def get_string(idx: int) -> str:
        if not 0 <= idx < len(strings):
            raise CompileError(f"string index out of range: {idx}")
        return strings[idx]

    need(4)
    n_cap = struct.unpack_from("<I", body, off)[0]
    off += 4
    capacities: dict[str, int] = {}
    for _ in range(n_cap):
        need(8)
        name_idx, units = struct.unpack_from("<II", body, off)
        off += 8
        capacities[get_string(name_idx)] = units

    need(4)
    n_ops = struct.unpack_from("<I", body, off)[0]
    off += 4
    for _ in range(n_ops):
        need(4 + 4 + 1 + 2)
        off += 4 + 4 + 1
        n_demands = struct.unpack_from("<H", body, off)[0]
        off += 2 + n_demands * 8
        need(2)
        n_deps = struct.unpack_from("<H", body, off)[0]
        off += 2 + n_deps * 4

    need(4)
    n_steps = struct.unpack_from("<I", body, off)[0]
    off += 4
    for _ in range(n_steps):
        need(4 + 2)
        off += 4
        n_sops = struct.unpack_from("<H", body, off)[0]
        off += 2 + n_sops * 4

    need(4)
    n_bindings = struct.unpack_from("<I", body, off)[0]
    off += 4 + n_bindings * 8

    need(32 + 4 + 4 + 4)
    lf_sha256 = body[off:off + 32].hex()
    off += 32
    lfc_idx, chronoc_idx, target_steps = struct.unpack_from("<III", body, off)
    off += 12
    if off != len(body):
        raise CompileError(f"trailing bytes after meta: {len(body) - off}")

    return {
        "version": version,
        "flags": flags,
        "step_ns": step_ns,
        "n_strings": n_strings,
        "capacities": capacities,
        "n_ops": n_ops,
        "n_steps": n_steps,
        "n_bindings": n_bindings,
        "lf_sha256": lf_sha256,
        "lfc_version": get_string(lfc_idx),
        "chronoc_version": get_string(chronoc_idx),
        "target_steps": target_steps,
        "crc_ok": True,
        "blob_sha256": hashlib.sha256(blob).hexdigest(),
        "blob_bytes": len(blob),
    }


def check_provenance(meta: dict, expect_source_sha256: str | None = None
                    ) -> None:
    """Assert the blob came from the pinned toolchain (and optionally the
    expected LF source)."""
    if LFC_VERSION_PIN not in meta["lfc_version"]:
        raise CompileError(f"blob lfc version {meta['lfc_version']!r} does "
                           f"not match pin {LFC_VERSION_PIN}")
    if meta["chronoc_version"] != CHRONOC_VERSION_PIN:
        raise CompileError(f"blob chronoc version {meta['chronoc_version']!r} "
                           f"does not match pin {CHRONOC_VERSION_PIN}")
    if expect_source_sha256 and meta["lf_sha256"] != expect_source_sha256:
        raise CompileError(f"blob source sha256 {meta['lf_sha256']} != "
                           f"expected {expect_source_sha256}")


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------

def _http_post_json(url: str, api_key: str, payload: dict,
                    timeout: int = 180) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api_key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[-500:]}  # noqa: BLE001


def compile_via_api(api_url: str, api_key: str, payload: dict) -> dict:
    """POST the project to /v1/lf/compile and verify the returned blob."""
    url = api_url.rstrip("/") + "/v1/lf/compile"
    status, resp = _http_post_json(url, api_key, payload)
    if status == 403 and resp.get("error") == "toc_acceptance_required":
        raise CompileError("server requires TOC acceptance for this key: "
                           "execute the TOC first (tools/sign_toc.py)")
    if status == 403 and "license" in str(resp.get("error", "")):
        raise CompileError("server requires a 'compile' license for this "
                           f"key: {resp}")
    if status != 200:
        raise CompileError(f"compile API returned {status}: {resp}")
    try:
        blob = base64.b64decode(resp["blob_base64"])
    except (KeyError, ValueError) as exc:
        raise CompileError(f"response has no decodable blob_base64: {exc}")
    meta = verify_blob(blob)
    if resp.get("blob_sha256") != meta["blob_sha256"]:
        raise CompileError("server blob_sha256 does not match the "
                           "downloaded blob")
    if resp.get("input_sha256") != input_sha256(payload["files"]):
        raise CompileError("server input_sha256 does not match the "
                           "submitted project")
    check_provenance(meta)
    return {"blob": blob, "meta": meta, "response": resp}


def _find_tool(name: str, env_var: str) -> str:
    """Resolve an external tool: explicit env var, then the repo's
    toolchain/ directory (vendored chronoc / fetched pinned lfc), then
    PATH. Raises CompileError when not found."""
    path = os.environ.get(env_var, "")
    if path and os.path.isfile(path) and os.access(path, os.X_OK):
        return path
    if name == "chronoc":
        vendored = os.path.join(REPO_ROOT, "toolchain",
                                "chronoc-linux-x86_64")
        if os.path.isfile(vendored) and os.access(vendored, os.X_OK):
            return vendored
    if name == "lfc":
        pinned = os.path.join(REPO_ROOT, "toolchain",
                              "lf-cli-0.13.0-Linux-x86_64", "bin", "lfc")
        if os.path.isfile(pinned) and os.access(pinned, os.X_OK):
            return pinned
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(directory, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    hint = ("run scripts/fetch-lfc.sh" if name == "lfc"
            else "see toolchain/README.md")
    raise CompileError(f"{name} not found: set ${env_var} to the pinned "
                       f"{name} binary, put it on PATH, or {hint}")


def lfc_gate(lfc: str, project_dir: str, entrypoint: str) -> str:
    """Run the pinned lfc validation gate (must exit 0). Returns the lfc
    version string.

    lfc computes its `-o` output tree from the source path: it only works
    reliably with a path relative to the working directory, so we run it
    with cwd=project_dir and the relative entrypoint path (the server
    materializes projects the same way)."""
    proc = subprocess.run([lfc, "--version"], capture_output=True, text=True,
                          timeout=120)
    version = (proc.stdout or "").strip()
    gate_tmp = tempfile.mkdtemp(prefix="ch-lfc-gate-")
    try:
        proc = subprocess.run(
            [lfc, "-n", "-q", "-o", gate_tmp, entrypoint],
            capture_output=True, text=True, timeout=180, cwd=project_dir)
    finally:
        import shutil
        shutil.rmtree(gate_tmp, ignore_errors=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise CompileError("pinned lfc validation gate rejected the "
                           f"entrypoint:\n{detail[-2000:]}")
    return version or "unknown"


def materialize_project(files: dict[str, str]) -> str:
    """Write the validated file map into a temp dir. Returns the dir.
    Paths were validated (relative, no '..', .lf only) so this cannot
    escape the temp dir. The caller must clean it up."""
    tmp = tempfile.mkdtemp(prefix="ch-lf-project-")
    for rel, content in files.items():
        dest = os.path.join(tmp, *rel.split("/"))
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(content)
    return tmp


def compile_local(files: dict[str, str], entrypoint: str,
                  params: dict[str, int], capacities: dict[str, int],
                  lfc: str, chronoc: str) -> dict:
    """Compile with the local pinned toolchain (lfc gate + chronoc)."""
    import shutil
    tmp = materialize_project(files)
    try:
        lfc_version = lfc_gate(lfc, tmp, entrypoint)
        out = os.path.join(tmp, "workload.chb")
        cmd = [chronoc, "compile", entrypoint, "-o", out, "--lfc", lfc]
        for key, value in params.items():
            cmd += ["--param", f"{key}={value}"]
        for key, value in capacities.items():
            cmd += ["--capacity", f"{key}={value}"]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=180, cwd=tmp)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise CompileError("chronoc compile failed:\n" + detail[-2000:])
        with open(out, "rb") as fh:
            blob = fh.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    meta = verify_blob(blob)
    meta["lfc_gate_version"] = lfc_version
    check_provenance(meta, input_source_sha256(files[entrypoint]))
    return {"blob": blob, "meta": meta}


def input_source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _kv_pairs(pairs: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise CompileError(f"expected key=value, got {pair!r}")
        key, _, value = pair.partition("=")
        try:
            out[key] = int(value, 0)
        except ValueError:
            raise CompileError(f"{key!r} value must be an integer, got "
                               f"{value!r}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="ChronoHive LF compile test client: submit a complete "
                    "LF project and verify the .chb blob that comes back.")
    ap.add_argument("--lf-dir", default=os.path.join(REPO_ROOT, "lf"),
                    help="LF project directory (default: lf/)")
    ap.add_argument("--entrypoint", default=None,
                    help="project entrypoint (default: the single .lf file, "
                         "else required)")
    ap.add_argument("--param", action="append", default=[],
                    help="chronoc --param key=value (repeatable, integer)")
    ap.add_argument("--capacity", action="append", default=[],
                    help="chronoc --capacity key=value (repeatable, integer)")
    ap.add_argument("--api-url", default=os.environ.get("CH_EVAL_API_URL"),
                    help="compile API base URL (or $CH_EVAL_API_URL)")
    ap.add_argument("--api-key", default=os.environ.get("CH_EVAL_API_KEY"),
                    help="API key (or $CH_EVAL_API_KEY)")
    ap.add_argument("--local", action="store_true",
                    help="compile with the local pinned toolchain instead "
                         "of the API ($LFC / $CHRONOC)")
    ap.add_argument("--check", action="store_true",
                    help="CI mode: file map + lfc gate + request schema + "
                         "reference-blob verification (no chronoc, no API)")
    ap.add_argument("--reference-blob",
                    default=os.path.join(REPO_ROOT, "lf",
                                         "IoCoordinator.chb.reference"),
                    help="reference blob verified in --check mode")
    ap.add_argument("-o", "--out", default=None,
                    help="write the compiled blob to this path")
    args = ap.parse_args()

    try:
        files = build_file_map(args.lf_dir)
        entrypoint = args.entrypoint
        if entrypoint is None:
            if len(files) == 1:
                entrypoint = next(iter(files))
            else:
                raise CompileError(
                    "project has several .lf files; pass --entrypoint")
        params = _kv_pairs(args.param)
        capacities = _kv_pairs(args.capacity)
        payload = build_request(files, entrypoint, params, capacities)
        print(f"project: {len(files)} file(s), entrypoint {entrypoint!r}, "
              f"input_sha256 {input_sha256(files)[:16]}...")

        if args.check:
            lfc = _find_tool("lfc", "LFC")
            tmp = materialize_project(files)
            try:
                version = lfc_gate(lfc, tmp, entrypoint)
            finally:
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
            print(f"pinned lfc gate passed ({version})")
            json.dumps(payload)  # schema must be JSON-serializable
            print(f"request schema OK "
                  f"({len(json.dumps(payload))} bytes JSON)")
            with open(args.reference_blob, "rb") as fh:
                ref = fh.read()
            meta = verify_blob(ref)
            check_provenance(
                meta, input_source_sha256(files[entrypoint]))
            print(f"reference blob OK: {meta['blob_bytes']} bytes, "
                  f"{meta['n_ops']} ops, {meta['n_steps']} steps, "
                  f"lfc {meta['lfc_version']}, chronoc {meta['chronoc_version']}, "
                  f"source sha256 matches {entrypoint!r}")
            print("COMPILE CLIENT CHECK PASSED")
            return

        if args.local:
            lfc = _find_tool("lfc", "LFC")
            chronoc = _find_tool("chronoc", "CHRONOC")
            result = compile_local(files, entrypoint, params, capacities,
                                   lfc, chronoc)
            meta = result["meta"]
        elif args.api_url and args.api_key:
            result = compile_via_api(args.api_url, args.api_key, payload)
            meta = result["meta"]
        else:
            raise CompileError("choose one: --api-url + --api-key, --local, "
                               "or --check")

        print(f"blob OK: {meta['blob_bytes']} bytes, sha256 "
              f"{meta['blob_sha256'][:16]}..., {meta['n_ops']} ops, "
              f"{meta['n_steps']} steps, target_steps {meta['target_steps']}, "
              f"lfc {meta['lfc_version']}, chronoc {meta['chronoc_version']}")
        if args.out:
            with open(args.out, "wb") as fh:
                fh.write(result["blob"])
            print(f"wrote {args.out}")
        print("COMPILE OK")
    except CompileError as exc:
        print(f"COMPILE CLIENT FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
