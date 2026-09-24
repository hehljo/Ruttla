# TESTING STRATEGY

## Baseline to Preserve

- 41 Runner-Unittests
- 206/206 Self-Test-Proben
- 90/90 Checks mit beiden Richtungen

Kein Tooling-Umbau darf diese Baseline einfach ersetzen.

## Test Pyramid

### 1. Unit
Core-Modelle, Config, Discovery, Git, Report Mapping, Selection, exit policy.

### 2. Rule Self-Tests
Jede Rule: broken + healthy. Für harte Regeln zusätzliche Counterexamples.

### 3. Fixture Integration
Kleine synthetische Repositories pro Plattform/Pack:
- universal
- web
- apple
- python
- raspberry
- godot
- unreal
- media

### 4. CLI Golden Tests
Definierte Inputs → erwartete semantische Outputs für:
- text
- agent
- json
- sarif

Text darf Wording bewusst ändern; maschinelle Felder werden streng verglichen.

### 5. Packaging Tests

Auf frischem Environment:

```text
build wheel + sdist
install wheel
<cli> --version
<cli> --list
<cli> --self-test
scan fixture
```

### 6. OS / Python Matrix

- ubuntu: 3.11, 3.12, 3.13, 3.14
- windows: 3.11, 3.13, 3.14
- macOS: 3.11, 3.13, 3.14
- 3.15 prerelease zunächst separate compatibility job

### 7. Security / Robustness

- symlink escape
- weird filenames
- spaces/unicode
- invalid TOML
- oversized files
- unreadable entries where platform allows
- malicious-looking source text without execution
- invalid git refs/path escapes
- plugin result contract violations

### 8. Property/Fuzz Tests

Später gezielt auf:
- path normalization
- selector patterns
- reporter escaping
- config parser

## Coverage Policy

Nicht blind eine hohe Zahl setzen.

Phase P03:
1. aktuelle Line/Branch Coverage messen;
2. Core-Paket separat ausweisen;
3. Baseline in CI einfrieren (no regression);
4. für Core/Runner schrittweise ≥90% Line Coverage anstreben;
5. Rule-Wert primär über semantische Self-Tests beurteilen, nicht nur Coverage.

## Performance Tests

Benchmark-Datensatz erzeugen:
- 1k / 10k / 50k Textdateien
- 10 / 100 / 500 MB
- Mix relevanter Extensions

Messen:
- wall clock
- max RSS
- file inventory time
- per-rule time

Kein Optimieren ohne Profiling.

## Release Gate

Vor Release:
- alle Required CI Jobs grün
- Self-Test count darf nicht unerklärt sinken
- Rule count darf nicht unerklärt sinken
- wheel/sdist installierbar
- JSON/SARIF valid
- changelog vorhanden
- privacy/provenance scan grün
