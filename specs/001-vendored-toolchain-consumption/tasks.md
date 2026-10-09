# Tasks — Spec 001 vendored toolchain consumption

Traceability: implementation tasks trace to the PRs that implement
them; verification tasks trace to evidence (CI runs, on-disk checks,
assessment outputs). All PRs HELD — no merges under the Chrono program
merge hold / Gate G.

## As-built implementation (already landed, held)

- [x] T001 — Vendored chronoc consumption model: vendored binary +
  provenance/hash record in `toolchain/README.md`, resolution order
  (env → repo → PATH) in `scripts/compile_lf.sh`.
  Traces to: repo history on `main`; pin refreshed by PR #12.
  Claims: EVAL-001.
- [x] T002 — Pinned lfc via `scripts/fetch-lfc.sh` (v0.13.0, SHA-256
  verified before unpack, refuse on mismatch, gitignored install).
  Traces to: repo history on `main`. Claims: EVAL-002.
- [x] T003 — `.gitattributes` standardization.
  Traces to: PR #11 (`chore/gitattributes`, OPEN; head `ca0b709` at
  backfill start, CI green run 37852282519; current head `90f9922`
  after the T005 fix). Claims: EVAL-005.
- [x] T004 — `.chb`/`CHB1` → `.cspec`/`CSP1` rename as applied to eval:
  binary replaced with renamed toolchain build, reference artifact
  regenerated via pinned toolchain + real lfc gate, client/scripts/
  CI/Dockerfile/docs swept, diagrams+PDFs regenerated.
  Traces to: PR #12 (`chore/rename-cspec`, OPEN; head `35727d1` at
  backfill start, CI green run 37863896647; then `d77fb2e` (W2 fix,
  pdf freshness failed on one stale PDF, run 37866176424, see T007);
  current head `b994856` (PDF regenerated), run 37866636846.
  Claims: EVAL-004, EVAL-001, EVAL-003.
- [x] T005 — Close the EVAL-005 observed gap: DONE by its owner, the
  PR #11 / W2 audit line — commit `90f9922` on `chore/gitattributes`
  replaces `*.csf binary` with `*.cspec binary` and corrects the
  comment (the list had named the superseded provisional extension).
  NOT done by this backfill PR. Falsifier for completion was: the
  merged `.gitattributes` still lacks a `*.cspec` entry.

## In flight tonight

- [ ] T006 — W5 re-vendor: replace vendored chronoc with the renamed
  toolchain build on `chore/rename-cspec`, refresh pins/hashes in
  `toolchain/README.md`, run the eval gate. Owner: W5 worker (separate
  worker, pushes to the base branch of this PR tonight). Evidence:
  transcript in coordinator workspace
  `hidden_files/chrono-program/w5-evidence/` — ABSENT at backfill time
  (checked 2026-10-08 evening EDT); claims EVAL-007 stays
  `unsupported` / `insufficient_evidence` until it lands.
- [x] T007 — W2 rename-residue audit for this repo: CLOSED for eval.
  Audit on file (`w2-evidence/audit-summary.txt` + per-pattern files):
  at `35727d1` exactly two `.chb` lines — one live residue
  (`lf/IoCoordinator.lf` comment), fixed by W2 commit `d77fb2e` on
  `chore/rename-cspec` (reference regenerated via the real pinned
  lfc gate, source pins updated); one historical note
  (`toolchain/README.md` pre-rename pin, out of scope). EVAL-004
  upgraded to supported on this evidence. FOLLOW-UP OWNED BY THE
  BASE-BRANCH LINE (W2/W5), not this PR: `d77fb2e` left
  `pdf/ChronoHive-LF-Toolchain.pdf` stale — CI pdf-freshness job
  fails on PR #12 at `d77fb2e` (run 37866176424) until PDFs are
  regenerated there. CLOSED by base commit `b994856` the same
  night (run 37866636846); this PR stacked on `b994856` inherits no
  failure from it.

## This backfill PR (chore/speckit-aee-coverage)

- [x] T008 — spec-kit scaffolding: `specify init --here --force
  --non-interactive --integration copilot --script sh` (specify
  1.0.10); extensions `aee` v1.2.0 and `evaluator` v1.0.0 installed
  from the local clones (`spec-kit-aee`, `spec-kit-evaluator`) via
  `specify extension add <path> --dev`. Additive only — no existing
  file under `toolchain/`, `scripts/`, or `lf/` modified.
- [x] T009 — Lightweight constitution at
  `.specify/memory/constitution.md` (adapted from ChronoHive's,
  scoped to a toolchain-consumer repo).
- [x] T010 — This spec: `spec.md` + `plan.md` + `tasks.md` +
  `claims.json` (stable claim IDs EVAL-001…EVAL-007, explicit
  falsifier per claim, evidence tied to PRs #11/#12, CI runs
  37852282519 / 37863896647, and on-disk pin verification).
- [x] T011 — AEE assessments: RAN 2026-10-08 via the installed aee
  extension runner (`run_aee.py assess --phase after_specify`, aee
  1.0.2) against `claims.json`; both the rich AEE assessment and the
  Evaluator Contract result were produced, plus `aee gate`. Outcome:
  `clarify` (7 claims, 16 failure modes, EVAL-005 and EVAL-007 below
  the 0.70 threshold — both genuinely open items, T005/T006). Outputs
  in `assessments/` (copies) and `.specify/extensions/` (canonical),
  full record in `assessments/README.md`.
- [x] T012 — Verify CI on this PR via PR #13, head `0c9538d`:
  ALL THREE JOBS PASS (run 37867072814 — repo gate, pdf + diagram
  freshness, docker toolbox). (This checkbox commit itself triggers
  one more CI run on the new head.) Original task text:
  `gh pr checks <n> --repo layer1labs/chronohive-eval` and record the
  result in the coordinator run state. Note: this branch was created
  from base head `35727d1` and REBASED onto `b994856` before push
  (the W2 fix `d77fb2e` and its PDF follow-up `b994856` landed
  mid-backfill); the base may move again tonight (T006), which
  GitHub retargets automatically.
- [x] T013 — Gate coexistence fix in `scripts/check.py` (the ONLY
  non-scaffolding code change in this PR): the branding/header sweeps
  now skip the `.specify/` tooling tree and the spec-kit generated
  `.github/skills/` tree — third-party tool content that otherwise
  fails the banner sweep (32 files) and crashes the branding sweep
  on extension skill symlinks. Our own `specs/` tree is NOT skipped
  and passes both sweeps (verified locally 2026-10-08: branding
  clean, headers present, plus compile/ed25519/negative-paths/
  tracked-artifact/secret-hygiene steps pass; the compile-client
  `--check` step needs the pinned lfc + JRE that CI installs).
  Also removed, before commit, the local junk the `--dev` extension
  copy dragged in (nested `.git`, `.venv-hatch` ~129 MB, caches)
  from `.specify/extensions/*` — matching the toolchain W0 tree —
  while restoring the generated `.specify-dev/extension-skills`
  the `.github/skills` symlinks point at.
