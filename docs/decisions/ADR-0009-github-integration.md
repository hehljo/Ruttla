# ADR-0009 — Workflow-only GitHub integration for 0.1

## Status
Accepted — 2026-09-24 (P04-T007)

## Decision
No own Marketplace Action in 0.1. Users run the CLI in a workflow step and
upload SARIF with `github/codeql-action/upload-sarif@v4`
(docs/integrations/github-actions.md).

## Why
An Action is a second release artefact with its own tags and security
surface; the CLI already produces everything needed. Revisit once PyPI
releases are stable (FUTURE.md).

## Consequences
The example pins a commit until the first PyPI release, because installing an
unpublished name from PyPI is a supply-chain risk.
