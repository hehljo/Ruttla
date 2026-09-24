# TECH STACK

## Runtime Language

**Python 3.11+**

Warum:
- bestehender Code ist Python;
- `tomllib` ist ab Python 3.11 in der Stdlib;
- Python 3.10 erreicht im Oktober 2026 sein Support-Ende;
- 3.11–3.14 sind am 24.09.2026 unterstützte stabile Linien.

Version Policy:
- `requires-python = ">=3.11"`
- CI: 3.11, 3.12, 3.13, 3.14
- 3.15 prerelease zunächst allowed-to-fail, ab 3.15 final regulär
- neue Syntax erst verwenden, wenn Mindestversion bewusst angehoben wird

## Runtime Dependencies

**Keine Drittanbieterabhängigkeiten als Default-Ziel.**

Das ist ein Produktmerkmal: schneller Install, geringe Supply-Chain-Fläche, offline zuverlässig.

Ausnahmen nur per ADR, wenn eine Abhängigkeit einen klaren Nutzen bietet, der den Wartungs-/Supply-Chain-Preis rechtfertigt.

## Packaging

- `pyproject.toml`
- `src/`-Layout
- Build backend: **Hatchling** als vorgeschlagener Default
- Console script via `[project.scripts]`
- Wheel + sdist

Alternative: setuptools. Entscheidung in ADR-0003 finalisieren; kein Feature darf vom Backend abhängen.

## Module Layout Target

```text
src/<module_name>/
├── __init__.py
├── __main__.py
├── cli.py
├── engine.py
├── models.py
├── config.py
├── discovery.py
├── git.py
├── selftest.py
├── reporting/
│   ├── text.py
│   ├── agent.py
│   ├── json_report.py
│   └── sarif.py
└── checks/
    ├── universal/
    ├── apple/
    ├── web/
    ├── python/
    ├── raspberry/
    ├── godot/
    ├── unreal/
    └── media/
```

## Dev Tooling

Dev-only, nicht Runtime:

- pytest für ergonomische Test-Suites und parametrische Tests
- coverage.py / pytest-cov für Messung
- Ruff für Format/Lint
- mypy oder pyright für statische Typprüfung des Core
- build für Wheel/sdist
- twine-check oder äquivalente Metadata-Prüfung

Einführung schrittweise; keine Tooling-Migration darf die vorhandenen 41 Tests oder 206 Self-Probes ersetzen.

## CI

GitHub Actions:
- unit + self-tests auf OS/Python Matrix
- package build/install smoke
- own-gate dogfood
- docs checks
- SARIF schema/golden validation
- release workflow getrennt von normaler CI

## Release

- GitHub Releases
- PyPI Distribution unter neuem, verfügbaren Namen
- PyPI Trusted Publishing via OIDC
- SemVer
- `CHANGELOG.md`

## Reporting

- Human text
- Agent TSV-style format
- JSON versioned schema
- SARIF 2.1.0

## Why Not Main Alternatives

### Rust rewrite
Nicht für V1. Würde eine große Verhaltensmigration erzwingen, ohne dass Performance derzeit als Bottleneck belegt ist.

### Node/TypeScript rewrite
Kein Nutzen gegenüber dem existierenden, dependency-light Python-Code und schlechtere Wiederverwendung der aktuellen Check-Implementierungen.

### Docker-only
Zu schwergewichtig für lokalen Agent-/Pre-Commit-Einsatz und Windows/macOS. Docker kann später optionale Distribution sein.

### Cloud service
Widerspricht dem Kernwert „lokal, tokenfrei, private source stays local“.

## Reconsider When

- Scan-Performance verfehlt messbar Budgets trotz Profiling/Optimierung;
- Python-Packaging verhindert wichtige native Integrationen;
- externer Plugin-Markt verlangt stärkere Isolation;
- Rule-Katalog wird so groß, dass Pack-Splitting zwingend wird.
