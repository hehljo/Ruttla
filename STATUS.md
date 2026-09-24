# STATUS

## Current Phase
P05 abgeschlossen (P00–P05 umgesetzt). P06 aktiv; Repository ist seit 2026-09-24 öffentlich.

## Last Completed (2026-09-24)
- P00 Anonymisierung, History-/Provenienz-Audit, Apache-2.0, Golden-Baseline
- P01 Verträge: Blocking-Modell, Report-Schema 1.1, Profil-Alias, Plattform-Registry, Regel-Metadaten
- P02 Paket `ruttla`, Shims, Aufteilung der Regelmodule, README-Ausschluss, Skip-Diagnose
- P03 CI-Matrix, Coverage-Floor, Benchmark, Fuzz-Tests, Regex-Performance-Fix
- P04 SARIF, --version/--list json/--explain, Workflow-Beispiel (ADR-0009)
- P05 README (en/de), CONTRIBUTING, SECURITY, CoC, CODEOWNERS, Templates, CHANGELOG, RULES.md
- LESSONS_LEARNED.md
- `web.empty_catch_block`: advisory Check für leere JS/TS-catch-Blöcke, mit broken/healthy Proben und False-Positive-Hinweis
- `ruttla update`: explizites pip-Update von GitHub `main`; normale Scans bleiben offline

## Next Unblocked Task
- P06-T001 Finding-Fingerprint (Basis `ruttla/v1` in SARIF existiert)
- Performance: restliche Hotspots (siehe docs/PERFORMANCE_BUDGET.md)

## Blockers (nur für Veröffentlichung)
- P08: neue, bereinigte Git-Historie vor Visibility=Public (docs/audits/HISTORY_AUDIT_2026-09-24.md)
- P04-T003: Code-Scanning-Upload braucht ein öffentliches Fixture-Repo oder GitHub Code Security
- Trademark-Kurzcheck für „Ruttla“ vor 0.1.0

## Validation State
- unit/contract/golden/fuzz: 107 Tests grün (lokal)
- self-test: 208/208 Proben, 91/91 Checks beide Richtungen
- self-scan strict: Exit 0
- coverage: 87 % gesamt (Kern 86 %), CI-Floor 86 %
- wheel/sdist: gebaut, frische Installation getestet

## Last Updated
2026-09-24
