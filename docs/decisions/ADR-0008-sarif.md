# ADR-0008 — SARIF 2.1.0 as Standard CI Interchange

## Status
Proposed

## Context
JSON/agent output is machine-friendly but not directly integrated into standard code-scanning UIs.

## Decision
Add SARIF 2.1.0 reporter using existing stable `check_id` values as rule IDs.

## Alternatives
- custom GitHub annotations only
- JSON-only

## Why
SARIF enables GitHub Code Scanning and broader static-analysis interoperability without changing the scan engine.

## Consequences
Rule metadata must be rich enough for help/description fields and stable locations.

## Validation
Schema validation + GitHub upload integration test in a public fixture repo before release.
