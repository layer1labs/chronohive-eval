# ChronoHive Evaluation Package Constitution

Version: 1.0.0 | Ratified: 2026-10-08

Lightweight constitution for `layer1labs/chronohive-eval`, adapted from
the ChronoHive constitution and scoped down to what this repository is:
a client evaluation package that consumes a pinned, vendored toolchain —
it does not build the compiler, the engine, or the hosted API.

1. **Pinned toolchain consumption.** This repo consumes the toolchain as
   pinned binaries, never as source it edits. The vendored `chronoc`
   binary (`toolchain/chronoc-linux-x86_64`) is replaced wholesale when
   re-vendored — never patched, text-swept, or line-ending-converted.
   `lfc` is obtained only through the pinned, hash-verified fetch
   (`scripts/fetch-lfc.sh`). Every pin carries a recorded version and
   SHA-256 in `toolchain/README.md` / `docs/LF_TOOLCHAIN.md`; a pin whose
   hash does not match its record is a defect, not a detail.
2. **Evidence-driven claims.** Evaluation gates are evidence. Claims in
   specs carry stable IDs and an explicit falsifier, and trace to CI
   runs, `scripts/check.py` output, byte-identical reproduction of the
   checked-in reference specification, or a saved transcript. An AEE
   assessment outcome (`iterate` / `gather_evidence` included) is
   recorded honestly; an unrun gate is never reported as passed.
3. **Honest evaluation numbers.** This package drives a hosted kernel
   against a simulated backend. Numbers produced here are simulation
   outcomes, never hardware measurements, and are labeled as such.
4. **Rename integrity.** Artifact naming is owner-settled: the compiled
   artifact is a Constraint Specification (`.cspec`, magic `CSP1`, debug
   form `cspec-ir`). Superseded names (`.chb`/`CHB1`, provisional
   `.csf`/`CSF1`) appear only in historical or pre-rename records, never
   in live code, scripts, docs, or gates.
5. **Small verified increments.** Work lands in branches and held PRs
   under the Chrono program merge hold. No merge without owner
   architecture sign-off, green CI, and the spec/AEE coverage defined in
   the program addendum (2026-10-08).

Amendments require a PR explaining affected requirements and evidence,
owner review, and a version update. Pin and gate rules cannot be waived
silently.
