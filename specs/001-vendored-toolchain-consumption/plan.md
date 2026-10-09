# Plan — Spec 001 vendored toolchain consumption (backfill)

## Purpose

Retrofit spec-kit + AEE coverage onto work already built and held in
PRs #11 and #12, plus one in-flight workstream (W5 re-vendor), without
changing any behavior, pin, or gate in the repo. This plan describes
how the as-built state maps to the spec; it is a record, not a proposal
for new implementation.

## Architecture as built

```
lf/IoCoordinator.lf ──► scripts/compile_lf.sh
                              │ resolves (env override → repo toolchain → PATH)
                              ├─ chronoc: toolchain/chronoc-linux-x86_64
                              │           (vendored, pinned, EVAL-001)
                              └─ lfc:     toolchain/lf-cli-0.13.0-…/bin/lfc
                                          (fetched + hash-verified, EVAL-002)
                              │ stages project via temp dir, relative path,
                              │ JAVA_HOME always set for the lfc gate
                              ▼
                        .cspec (CSP1) ── cmp ──► lf/IoCoordinator.cspec.reference
                                                     (byte-identical, EVAL-003)
```

Supporting pieces:

- `clients/compile_client.py` — same contract via the hosted API,
  `--local` (vendored toolchain), and `--check` (offline, verifies the
  reference specification's byte structure; no network, no chronoc).
- `scripts/fetch-lfc.sh` — the only sanctioned way lfc arrives.
- `scripts/check.py` + `.github/workflows/ci.yml` — the eval gates
  (EVAL-006): repo gate, Docker toolbox, PDF/diagram freshness.
- `.gitattributes` (PR #11, separate held branch) — byte-protection
  for the vendored payloads (EVAL-005).

## Decisions recorded

1. **Consume binaries, never build them here.** chronoc bugs are fixed
   in `layer1labs/chronohive-toolchain` and arrive by re-vendor
   (wholesale binary replacement + pin refresh). This repo never
   patches the binary — the same rule the W5 re-vendor is held to.
2. **lfc by fetch, not by vendoring.** The lfc tree is large and
   upstream-released; pinning is by version + SHA-256 in the fetch
   script, with the installed tree gitignored and `-text`-protected
   in `.gitattributes` should it ever be vendored.
3. **Reference specification as the conformance anchor.** Byte-identical
   reproduction of `lf/IoCoordinator.cspec.reference` is the strongest
   cheap gate available to a consumer repo: any toolchain drift —
   version, hash, lowering change — breaks `cmp` in CI immediately.
4. **Backfill as one extra held PR, stacked.** Per the coordinator
   call recorded in `TONIGHT-RUN-STATE.md` (2026-10-08): folding specs
   into PR #12's branch would collide with the W5 worker pushing the
   re-vendor to the same branch tonight, so this coverage lands as
   `chore/speckit-aee-coverage` stacked on `chore/rename-cspec`.
5. **Lightweight constitution.** Adapted from the ChronoHive
   constitution and scoped to a consumer repo (addendum: "lightweight
   constitution is fine" for eval).

## Risks / open items

- **Base-branch movement (already happened once):** the W2
  rename-audit fix landed on `chore/rename-cspec` mid-backfill
  (`35727d1` → `d77fb2e` → `b994856`); this branch was rebased onto
  `b994856` before push and EVAL-003/EVAL-004/EVAL-006 were updated to the new
  head. W5 pushes the re-vendor to the same branch later tonight;
  GitHub retargets the diff automatically since the base is the same
  branch, and EVAL-007 must be updated when it lands. Note `d77fb2e`
  left `pdf/ChronoHive-LF-Toolchain.pdf` stale (CI pdf-freshness red
  on PR #12, run 37866176424); the base-branch line closed it with
  `b994856` (PDF regenerated), so this PR stacks on `b994856`.
- **`.cspec` missing from PR #11's binary list** (EVAL-005 observed
  gap): fix belongs to the PR #11 line (T005).
- **Platform scope:** both pins are Linux x86_64 only; other platforms
  use the documented `CHRONOC=` / `LFC=` overrides. No claim is made
  beyond that boundary.

## Verification for this plan

- Pins re-verified on disk 2026-10-08: chronoc SHA-256 and `--version`
  match `toolchain/README.md`; lfc pin read from `scripts/fetch-lfc.sh`.
- CI state read via `gh pr checks 11` and `gh pr checks 12`:
  PR #11 all-pass; PR #12 all-pass at `35727d1`; at `d77fb2e`
  repo gate + docker pass with pdf freshness failing on the one
  stale PDF described above (run 37866176424, log inspected), closed
  by `b994856` (run 37866636846).
- AEE `after_specify` assessment run against `claims.json`; outputs in
  `assessments/` (see `tasks.md` T009–T011 and the assessment README
  note recorded alongside the outputs).
