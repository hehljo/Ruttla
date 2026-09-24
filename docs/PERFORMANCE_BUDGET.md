# PERFORMANCE BUDGET

## Why

Das Tool soll nach jedem Agent-Arbeitsblock oder in Pre-Commit/CI laufen können. Latenz ist Produktqualität.

## Initial Targets — validate before enforcing

Auf einem normalen GitHub-hosted Linux Runner:

| Scenario | Target |
|---|---:|
| CLI startup / list | < 0.5 s |
| 1k files / 10 MB universal | < 2 s |
| 10k files / 100 MB universal | < 10 s |
| peak RSS at 10k/100 MB | < 512 MB |

Diese Zahlen sind Startbudgets, keine Behauptung über den aktuellen Stand. P03 misst die echte Baseline und passt das Budget per ADR an, falls unrealistisch.

## Instrumentation

Optionaler Maintainer-Benchmark-Modus soll messen:
- discovery time
- platform detection time
- time per check
- total time
- files / bytes examined
- skipped files / bytes
- max RSS, wenn portabel messbar

## Optimization Order

1. messen
2. Hotspots identifizieren
3. gemeinsame Indizes/Parsing-Caches erwägen
4. Regex/IO optimieren
5. Parallelisierung erst nach Determinismus-/Overhead-Analyse

Kein Rust-/Native-Rewrite ohne belegtes Problem.
