# ADR-0002 — Stdlib-Only Runtime and Python >=3.11

## Status
Proposed

## Context
Current code uses only the stdlib and already relies on `tomllib`, effectively requiring Python 3.11 without fallback.

## Decision
Keep default runtime dependency-free and declare Python >=3.11.

## Alternatives
- vendor TOML support for Python 3.10
- require Python 3.12+
- add a CLI framework/runtime dependencies

## Why
Python 3.10 reaches EOL in October 2026; supporting it adds complexity for little future value. Zero runtime dependencies is a strong reliability/supply-chain property.

## Consequences
Rich CLI frameworks are not used in V1 unless justified by a later ADR.

## Validation
CI on 3.11–3.14; 3.15 prerelease compatibility job.
