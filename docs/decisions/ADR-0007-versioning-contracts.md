# ADR-0007 — Versioning of Tool, Reports, Config and Rules

## Status
Proposed

## Context
The current JSON report has `schema_version = 1.0`, but public compatibility policy is not defined.

## Decision
Version separately:
- tool: SemVer
- report schema: major.minor
- config schema: integer/major
- rules: stable ID + `introduced_in` / deprecation metadata

## Compatibility Rule
Patch releases cannot introduce a new default-blocking rule or break machine contracts.

## Validation
Compatibility tests and release checklist.
