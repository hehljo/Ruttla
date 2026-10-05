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

## Amendment 2026-10-05 — declarative rules from the target

Declarative rules (`ruttla-rule/0`, data only) may come from the scanned
repository: hub packages pinned in `ruttla-hub.lock` (hash-checked, signed
when installed) and the project's own packages under `.ruttla/packages/`.
Both are validated like a hub submission, confined to the `hub.<name>.`
namespace, executed by the linear-time engine and can only add findings.
Executable Python plugins from the target remain forbidden.

## Validation
Security tests proving local target `.py` files cannot register/execute checks.
