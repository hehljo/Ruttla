# ADR-0006 — Open-Source License

## Status
Accepted — 2026-09-24 (maintainer decision: Apache-2.0)

## Context
No LICENSE was present in the analysed archive. Public contribution without an
explicit license creates ambiguity. The repository stays private for now, but
the license is decided up front so that every future contribution is made
under known terms.

## Decision
Apache License 2.0. The unmodified official text is in `LICENSE`
(SHA-256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`,
fetched from apache.org on 2026-09-24). `NOTICE` names the copyright holder.

## Alternatives
- MIT: minimal and permissive, but no explicit patent grant.
- AGPL-3.0: strong network copyleft; high adoption friction for a dev tool.

## Why
Apache-2.0 is permissive and includes explicit patent terms, which is useful
for a developer-tool ecosystem that invites third-party rule packs.

## Consequences
- Inbound = outbound: contributions are accepted under Apache-2.0 §5
  (stated in CONTRIBUTING.md). No CLA.
- `pyproject.toml` declares `license = "Apache-2.0"` (SPDX expression).

## Validation
Provenance checklist completed: `docs/audits/PROVENANCE_AUDIT_2026-09-24.md`
— no third-party code, no additional notices required.
