# ADR-0005 — Plugin Trust Boundary

## Status
Proposed

## Context
A larger public project will eventually need external rule packs. Importing Python from the scanned repository would execute untrusted source.

## Decision
Third-party executable plugins may only be loaded from explicitly installed Python distributions via entry points. Never auto-import plugins from the scan target.

## Alternatives
- local `.qualitygate/plugins/*.py`
- declarative-only extension model

## Why
Maintains the key trust boundary: target repository is data, not executable code.

## Consequences
Plugin installation is an explicit trust act. Declarative local rules can be considered separately later.

## Validation
Security tests proving local target `.py` files cannot register/execute checks.
