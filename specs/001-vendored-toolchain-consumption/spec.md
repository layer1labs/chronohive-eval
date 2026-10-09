# Spec 001 — Vendored toolchain consumption (chronohive-eval)

Status: backfill, describing the work AS BUILT (spec-kit + AEE coverage
addendum, 2026-10-08). This repository previously had zero spec-kit
coverage; this spec is its first. Branch `chore/speckit-aee-coverage`,
stacked on `chore/rename-cspec` (PR #12). HELD under the Chrono program
merge hold — no merges without owner architecture sign-off.

## Scope — what this repository is

`chronohive-eval` is the ChronoHive evaluation client package: Python
clients and tools that drive the hosted eval API, plus a self-contained
local compile path. There is no server in this repo, and this repo does
not build the compiler or the engine. It **consumes** the toolchain as
pinned binaries:

- vendored `chronoc` (Rust, LF subset → `.cspec`), tracked at
  `toolchain/chronoc-linux-x86_64`;
- pinned `lfc` v0.13.0 (the LF language validation gate), fetched —
  never hand-installed — by `scripts/fetch-lfc.sh`.

Evaluation numbers produced through this package are simulation
outcomes from the hosted kernel against a simulated backend, not
hardware measurements (constitution §3).

## Program documents indexed by reference

These program documents live in the coordinator workspace
(`goals/chronohive-repository-and-cpsc-integration/files/chrono-program/`)
and are indexed here so a reader can walk spec → plan doc → PR →
evidence without chat history:

- `CHRONO-PROGRAM-PLAN.md` — overall Chrono program plan.
- `TONIGHT-EXECUTION-PLAN-2026-10-08.md` — W5 Part 2 (toolchain
  production + eval re-vendor) is the workstream this spec's pending
  re-vendor task traces to.
- `SPECKIT-AEE-COVERAGE-ADDENDUM-2026-10-08.md` — the owner directive
  requiring this backfill; its audit row for this repo reads
  "NOT COVERED — backfill: init (lightweight constitution is fine) +
  one spec covering vendored-toolchain consumption, rename, and the
  W5 re-vendor; chore PRs (#11/#12) referenced from its tasks".
- `BLOB-CONSUMPTION-CONTRACT.md` — how one `.cspec` feeds two engines;
  defines the artifact this repo's compile path produces.

## Requirements and AEE claims

Claim IDs are stable. The machine-readable claim bundle is
`claims.json` in this directory; each claim carries the same falsifier
stated here. Assessment outputs are in `assessments/`.

### EVAL-001 — Vendored chronoc is a single pinned binary, replaced never edited

- **Statement:** The repo vendors exactly one `chronoc` binary,
  `toolchain/chronoc-linux-x86_64`, version `0.1.0-alpha.1`, SHA-256
  `ab12076b76c095438b43b56ff71dc38db783c5fc988ce61b8caf396db89281e1`,
  with version, hash, and provenance (built from
  `layer1labs/chronohive-toolchain`, `chronoc/`, release profile)
  recorded in `toolchain/README.md`. A re-vendor replaces the binary
  wholesale and updates the recorded pin; the binary is never patched
  or text-swept.
- **Falsifier:** `sha256sum toolchain/chronoc-linux-x86_64` differs from
  the README record; or `chronoc --version` reports anything other
  than `0.1.0-alpha.1` for this pin; or a commit modifies the binary
  by text edit / line-ending conversion instead of wholesale
  replacement.
- **Evidence:** SHA-256 and `--version` re-verified on disk
  2026-10-08 during this backfill (both match the record); PR #12
  replaced the binary wholesale (849,888 → 1,528,304 bytes) for the
  rename.

### EVAL-002 — lfc is consumed only through the pinned, hash-verified fetch

- **Statement:** `lfc` v0.13.0 is obtained only via
  `scripts/fetch-lfc.sh`, which downloads
  `lf-cli-0.13.0-Linux-x86_64.tar.gz` from the lf-lang v0.13.0 release,
  verifies SHA-256
  `175784319935e388a5ebe44f33dc4e3367eed9f24d071c82af8b50afe013a1c2`
  before unpacking, refuses to unpack on mismatch, and installs under
  `toolchain/lf-cli-0.13.0-Linux-x86_64/` (gitignored). Non-Linux-x86_64
  platforms exit with instructions to supply `LFC=` explicitly.
- **Falsifier:** the fetch script unpacks a tarball whose SHA-256 does
  not match the pin; or the default compile path uses an unpinned /
  different-version `lfc`; or the installed tree is committed instead
  of fetched.
- **Evidence:** `scripts/fetch-lfc.sh` source (read 2026-10-08); CI
  "install pinned JRE + lfc" step runs the same script on every PR.

### EVAL-003 — Local compile reproduces the reference specification byte-identically

- **Statement:** `scripts/compile_lf.sh` (and
  `clients/compile_client.py --local`) compile the checked-in LF
  project (`lf/IoCoordinator.lf`) through the pinned `lfc` validation
  gate and the vendored `chronoc`, producing a `.cspec` byte-identical
  to the checked-in reference `lf/IoCoordinator.cspec.reference`.
  Resolution order is pinned: `CHRONOC`/`LFC` env overrides first, then
  the repo toolchain, then PATH; a JVM (Java 17+) is required for `lfc`
  and `JAVA_HOME` is always set for chronoc's validation gate.
- **Falsifier:** a local compile's output differs from
  `lf/IoCoordinator.cspec.reference` (`cmp` non-zero), in plain CI or
  in the Docker toolbox image; or compilation succeeds on a source the
  pinned `lfc` rejects.
- **Evidence:** CI on PR #12 — at head `35727d1` (run 37863896647)
  all three jobs pass, including the explicit `cmp`
  project-to-specification steps; at the current head `d77fb2e`
  (run 37866176424) `repo gate` and `docker toolbox` pass (the `cmp`
  steps included), while `pdf + diagram freshness` failed for an
  unrelated stale PDF (see EVAL-006 note; fixed on the base by
  `b994856`). Reference artifact at
  `d77fb2e`: SHA-256
  `a7b685e16a3f9892fc16ceb56a114609a614b5a35327815b022ce830fbad76d7`,
  3,308 bytes (regenerated by the W2 fix, T007).

### EVAL-004 — The .chb → .cspec rename as applied to this repo (PR #12)

- **Statement:** PR #12 applies the owner-final rename to this repo:
  artifact `.chb`/`CHB1` → Constraint Specification `.cspec` / magic
  `CSP1` (debug form `cspec-ir`). The vendored chronoc is the renamed
  toolchain build (EVAL-001 pin); the reference artifact is renamed
  and regenerated via the pinned toolchain + real `lfc` gate
  (`lf/IoCoordinator.cspec.reference`, 3,308 bytes); the compile client
  verifies `CSP1` and the current v1 meta layout (incl. `lf_target`);
  scripts, CI, Dockerfile, and docs are swept; diagrams/PDFs are
  regenerated with the CI-pinned renderer.
- **Falsifier:** any live (non-historical) `.chb` / `CHB1` / `.csf` /
  `CSF1` reference remains in code, scripts, CI, or docs on the PR #12
  head; or the client accepts a `CHB1` artifact; or the checked-in
  reference is still a `.chb` file.
- **Evidence:** PR #12 diff stat (21 files, binary replaced, reference
  renamed 3,286 → 3,308 bytes) and CI on its heads (above). The W2
  rename-residue audit for this repo is on file
  (`hidden_files/chrono-program/w2-evidence/audit-summary.txt` +
  per-pattern files): at `35727d1` it found exactly two `.chb` lines —
  one live residue (the `lf/IoCoordinator.lf` header comment, "lowers
  this to a .chb blob") and one historical note
  (`toolchain/README.md`: the previous pin "emitting `.chb`/`CHB1`",
  a pre-rename record, out of scope). The live residue was fixed on
  the base branch by commit `d77fb2e` (W2), which also regenerated
  the reference through the real pinned `lfc` gate and updated the
  source SHA-256 pins (`72297054…`) in `lf/README.md` and
  `docs/LF_TOOLCHAIN.md`.

### EVAL-005 — Cross-platform .gitattributes protects the vendored payloads (PR #11)

- **Statement:** PR #11 adds the standard Chrono `.gitattributes`
  (this repo previously had none; the PR adds only that file, 33
  lines): `* text=auto eol=lf`; CRLF only for `*.bat`/`*.cmd`; `*.sh`
  pinned LF; binary artifacts marked `binary`; and the vendored
  payloads protected with `-text` — `toolchain/chronoc-linux-x86_64`
  and `toolchain/lf-cli-*/**`. Renormalization
  (`git add --renormalize .`) touched zero files.
- **Falsifier:** `git add --renormalize .` on the PR #11 branch
  modifies any file; or a checkout on any platform changes the SHA-256
  of `toolchain/chronoc-linux-x86_64`; or `.gitattributes` is absent
  once PR #11 merges.
- **Evidence:** PR #11 diff (`.gitattributes` only) and body
  (renormalize check); CI green on its original head `ca0b709` (run
  37852282519, all three jobs pass).
- **Observed gap — CLOSED on the PR #11 line tonight:** as originally
  built (`ca0b709`), the explicit binary list named `*.csf` and
  `*.chb` but not `*.cspec` (the list predated the final naming).
  This backfill recorded the gap rather than papering over it; the
  W2 audit line closed it with commit `90f9922` on
  `chore/gitattributes` ("W2 rename audit: .gitattributes names the
  final .cspec extension" — `*.csf binary` replaced by
  `*.cspec binary`, comment corrected), the current PR #11 head;
  CI all-pass on `90f9922` (run 37866885547). Task T005 is
  therefore done, by its owner.

### EVAL-006 — Eval gates are the evidence

- **Statement:** Every change to this repo is gated by
  `scripts/check.py` (byte-compiles all Python; RFC 8032 ed25519 test
  vectors; branding and header sweeps; compile-client checks including
  reference-specification `CSP1` structure verification; negative
  paths; tracked-artifact and secret-hygiene checks — prints
  `ALL CHECKS PASSED`) and by CI (`.github/workflows/ci.yml`: repo
  gate, project-to-specification byte-identical proof in CI and in the
  Docker toolbox, PDF/diagram freshness).
- **Falsifier:** CI is red on a held PR head while the work is claimed
  done; or `scripts/check.py` passes while the reference specification
  fails its `CSP1` structure check; or a gate is bypassed / a check
  removed to make a change pass.
- **Evidence:** `gh pr checks` on 2026-10-08 — PR #11 heads
  `ca0b709` and `90f9922`: all three jobs pass (runs 37852282519
  and 37866885547). PR #12 head `35727d1`: all
  three pass (run 37863896647). PR #12 head `d77fb2e`:
  `repo gate` and `docker toolbox` pass, `pdf + diagram freshness`
  FAILED (run 37866176424) — the job caught exactly one stale
  artifact, `pdf/ChronoHive-LF-Toolchain.pdf`, left stale by the W2
  commit `d77fb2e` changing `docs/LF_TOOLCHAIN.md` without
  regenerating PDFs: the gate working as designed. The base-branch
  line closed it the same night with commit `b994856` (PDF
  regenerated via `scripts/make_pdfs.py`), the current PR #12 head
  this PR is stacked on; its CI run is 37866636846.

### EVAL-007 — Tonight's W5 re-vendor from the renamed toolchain build (PENDING)

- **Statement:** Under W5 of the tonight execution plan, this repo's
  chronoc is re-vendored from the RENAMED toolchain build (binary
  replacement only, per EVAL-001), pins/hashes in
  `toolchain/README.md` are refreshed to match the new binary, and the
  eval gate (EVAL-006) is run with CI green on the updated PR.
- **Falsifier:** no re-vendor transcript is on file; or the refreshed
  README hash does not match the re-vendored binary; or CI is red
  after the re-vendor; or the re-vendor is performed by text-sweeping
  the old binary/repo instead of replacing the binary.
- **Evidence:** **PENDING — marked as such, per the addendum.** As of
  this backfill (2026-10-08 evening EDT), the W5 evidence directory
  (`hidden_files/chrono-program/w5-evidence/` in the coordinator
  workspace) does not exist and no re-vendor commit is on
  `chore/rename-cspec` beyond the W2 fix `d77fb2e`. A second worker (W5) performs
  the re-vendor later tonight on `chore/rename-cspec`; this PR's base
  tip is expected to move when it does. Claim status in `claims.json`:
  `unsupported` / `insufficient_evidence` until that evidence lands.

## Non-goals

- Building chronoc, lfc, the engine, or the hosted API from this repo.
- Changing any pin, the reference specification, or gate behavior —
  this backfill is specs/scaffolding only.
- Merging anything. All Chrono PRs stay held pending Gate G.
