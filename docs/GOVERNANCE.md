# GOVERNANCE & COMMUNITY

## Initial Governance

Start als maintainer-led Open-Source-Projekt.

Maintainer entscheidet:
- Core architecture
- release
- official rule inclusion
- security fixes

Rule-Packs können später eigene Code Owners erhalten.

## Required Community Files

Vor Public Beta:
- `LICENSE`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `CODE_OF_CONDUCT.md`
- `.github/CODEOWNERS`
- `.github/pull_request_template.md`
- `.github/ISSUE_TEMPLATE/bug.yml`
- `.github/ISSUE_TEMPLATE/new-rule.yml`
- `.github/ISSUE_TEMPLATE/false-positive.yml`
- `.github/ISSUE_TEMPLATE/false-negative.yml`
- `CHANGELOG.md`

## Contribution Philosophy

Das Projekt belohnt **belegte Regeln**, nicht die Menge an Regexen.

Ein Community-PR soll klein genug sein, dass Reviewer die technische Eigenschaft und die Gegenbeispiele verstehen können.

## Labels

Empfohlen:
- `new-rule`
- `false-positive`
- `false-negative`
- `core`
- `reporting`
- `pack:apple`
- `pack:web`
- `pack:python`
- `pack:godot`
- `pack:unreal`
- `pack:raspberry`
- `pack:media`
- `security`
- `breaking-change`
- `good-first-issue`
- `needs-reproduction`

## Review Rules

Neue harte Default-Regel:
- mindestens 2 Reviewer-Perspektiven oder Maintainer + unabhängiger AI-Review
- False-Positive-Risiko explizit dokumentiert

Core-/Schema-/Exit-Code-Änderung:
- ADR
- compatibility tests
- changelog

## Maintainer Scaling

Ab messbarem externem Beitrag:
- CODEOWNER je Rule-Pack
- zwei Maintainer für Release-Rechte anstreben
- keine einzelnen Third-Party-Contributors direkt in PyPI Publishing aufnehmen, bevor Governance klar ist
