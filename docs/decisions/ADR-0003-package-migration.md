# ADR-0003 — Staged Package Migration with Compatibility Shim

## Status
Proposed

## Context
Core logic currently lives in `core.py`, `master_gate.py` and large `checks/*.py` modules. A direct rewrite risks regressions across 90 checks.

## Decision
Move to `src/<module>/` incrementally. Preserve `master_gate.py` as a thin compatibility shim during 0.x.

## Alternatives
- big-bang rewrite
- never package, keep repo script only

## Why
Allows PyPI/CI integration while protecting existing semantics.

## Consequences
Temporary duplication/adapter code is acceptable if explicitly tracked.

## Validation
Golden fixtures and exact 90-check / 206-probe baseline across each migration slice.
