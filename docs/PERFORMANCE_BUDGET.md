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

## Measured baseline — 2026-09-24 (P03-T006)

Container: Linux, 4 CPUs, Python 3.11 (not a GitHub runner). `scripts/benchmark.py`.

| Scenario | Result | Target |
|---|---:|---:|
| CLI startup (`--list`) | 0.09 s | < 0.5 s ✅ |
| 1k files / 0.4 MB, all packs | 1.3 s | < 2 s ✅ |
| 10k files / 3.9 MB, inventory + universal rules | 5.3 s | < 10 s ✅ |
| 10k files / 3.9 MB, all 78 applicable rules | 11.8 s | — |
| 10k files / 69 MB (commented sources), all rules, **before fix** | 277 s, peak RSS 300 MB | < 10 s ❌ |

Root cause of the 277 s: MULTILINE `^\s*` patterns backtracking over stripped
comment blocks (one rule: 98 s). Fixed and guarded by `tests/test_performance.py`.
**Open (P03-T007):** re-run the 100 MB budget after the fix and profile the
remaining top rules before accepting or changing the targets via ADR.
