# Documentation

This directory contains the engineering and maintenance documentation for the
SolidWorks MCP fork. The README is the user-facing entry point; these documents
are for contributors, reviewers and maintainers.

## Start here

| Document | Audience | What it covers |
|---|---|---|
| [`ENGINEERING.md`](ENGINEERING.md) | everyone | Non-negotiable principles, required checks, definition of done, module boundaries, testing and release standards |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | contributors | Request flow, layer responsibilities, session mixin composition, state ownership, adding a tool |
| [`TESTING.md`](TESTING.md) | contributors | Unit/integration layers, commands, markers, coverage, CI matrix, writing tests |
| [`RELEASING.md`](RELEASING.md) | maintainers | Versioning, changelog, release checklist, tag/release process, fork publish policy |
| [`COMPATIBILITY.md`](COMPATIBILITY.md) | users and maintainers | Supported Windows/SOLIDWORKS/Python/MCP versions, selftest, reporting compatibility |
| [`MAINTENANCE.md`](MAINTENANCE.md) | maintainers | Upstream sync, dependency policy, security response, module ownership, deprecation |
| [`PROGRESS.md`](PROGRESS.md) | historians | Upstream milestone log from the single-file era |
| [`SolidWorks-MCP-Kickoff.md`](SolidWorks-MCP-Kickoff.md) | contributors | Original design brief and verification-loop rationale |

The fork relationship and upstream sync procedure are in
[`../UPSTREAM.md`](../UPSTREAM.md). Contribution rules are in
[`../CONTRIBUTING.md`](../CONTRIBUTING.md). Security reporting is in
[`../SECURITY.md`](../SECURITY.md).

## Documentation rules

- Update the document that owns a fact; do not duplicate the same explanation in
  several places.
- A user-visible change updates `README.md` and/or
  `src/solidworks_mcp/guide.md`.
- A process change updates `ENGINEERING.md` and the relevant guide.
- A module split or new layer updates `ARCHITECTURE.md`.
- A test/CI change updates `TESTING.md`.
- A release-process change updates `RELEASING.md`.
- Keep code identifiers in backticks and paths relative to the repository root.
