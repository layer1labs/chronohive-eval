<!-- © 2026 Layer1Labs Silicon Inc. All rights reserved. -->
<!-- CONFIDENTIAL — ChronoHive Evaluation Package. Licensed solely for -->
<!-- evaluation under the ChronoHive Terms of Confidentiality (TOC.md) and -->
<!-- the ChronoHive Evaluation License (LICENSE). -->

# Changelog

All notable changes to the ChronoHive evaluation package are recorded
in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this package adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The package version is the version the clients in this repository
identify themselves with in every request to the hosted evaluation API
(`ChronoHive-Eval-Client/<version>`).

## [Unreleased]

## [0.1.0] - 2026-10-25

First released version of the ChronoHive evaluation package. The
clients already identified themselves as version 0.1.0, and the hosted
API documentation already listed 0.1.0; this release marks that
version as released instead of pre-release.

### Added

- Initial evaluation package: Python clients and tools that drive the
  hosted ChronoHive evaluation API, with the Terms of Confidentiality
  execution gate (TOC reading, ed25519 signing, and acceptance
  submission) required before any evaluation endpoint serves a request.
- Worked end-to-end admission example covering TOC execution, scenario
  setup, live kernel decisions, and result fetching.
- Lingua Franca workload project (`lf/IoCoordinator.lf`) with a
  checked-in reference specification for offline verification.
- Portable LF toolchain: the vendored `chronoc` compiler binary, the
  pinned `lfc` fetch script with SHA-256 verification, compile
  helpers, and a guided demo of the source-to-specification chain.
- Complete-project compile client with hosted API mode, local
  pinned-toolchain mode, and an offline `--check` self-test.
- Customer documentation: architecture explainer, request-gating and
  compile-pipeline diagrams, the full hosted API reference, and
  print-ready deterministic PDFs of every document.
- Docker toolbox image containing the clients, the LF project, and
  the pinned toolchain, defaulting to the offline self-check.
- Repository gate (`scripts/check.py`) and CI covering the gate, the
  project-to-specification byte-comparison proof, PDF and diagram
  freshness, and the Docker toolbox build and proof.
- Spec-kit and AEE coverage (spec 001) for vendored toolchain
  consumption, with recorded assessments.

### Changed

- Specification artifact renamed from `.chb` (magic `CHB1`) to
  Constraint Specification `.cspec` (magic `CSP1`); the vendored
  `chronoc` was re-vendored from the renamed toolchain and the
  reference specification regenerated.
- API documentation corrected to version 0.1.0 throughout, including
  the health-response example and the versioning table; with this
  release the versioning table no longer marks 0.1.0 as pre-release.
- Naming made vendor-neutral across the public evaluation package.
- Terms of Confidentiality: governing law set to Delaware
  (section 10.3), the draft legal-review notice removed, and
  TOC-update policy and troubleshooting guidance documented.
- Standard cross-platform `.gitattributes`: LF line endings by
  default, CRLF only for Windows batch files, and binary treatment
  for generated artifacts and vendored binaries.

### Fixed

- Hosted API requests blocked by Cloudflare when sent with Python's
  default user agent: every client and tool now identifies itself as
  `ChronoHive-Eval-Client/0.1.0`.
- PDF rendering of ordered lists and tables (escaped pipes and bold
  text wrapping) in the document generator.

### Removed

- Server-side code and snapshots from the evaluation package: the
  package is client-only, and the repository gate rejects any of the
  removed server artifacts if they reappear.
