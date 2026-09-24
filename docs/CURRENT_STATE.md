# CURRENT STATE / EXISTING PROJECT MODE

Analysequelle: hochgeladenes `CODE_QUALITY_GENERAL-main.zip`, Stand 2026-09-24.

## Baseline

- Python-Code + Markdown/Shell: ca. 10.9k Zeilen im analysierten Paket
- 90 registrierte Checks
- 206 Self-Test-Cases
- 41 Runner-Unittests
- 7 Rule-Plattformgruppen
- 0 Runtime-Drittanbieterabhängigkeiten erkannt
- `tomllib` macht Python 3.11 praktisch zur Mindestversion

### Checks nach Plattform

| Plattform | Checks |
|---|---:|
| apple | 28 |
| universal | 22 |
| godot | 12 |
| web | 11 |
| raspberry | 6 |
| unreal | 6 |
| python | 5 |

### Default Severity

| Severity | Anzahl |
|---|---:|
| error | 35 |
| warning | 50 |
| info | 5 |

- `safe_by_default=True`: 9 Checks
- alle 90 Checks besitzen Self-Test-Proben
- alle registrierten Checks haben einen `guideline`-String, dessen öffentliche Nachvollziehbarkeit jedoch noch nicht überall gegeben ist

## Build / Test Health

Ausgeführt auf Python 3.13.5:

```text
python3 -m unittest discover -s tests -v
→ 41/41 PASS

python3 master_gate.py --self-test
→ 90 Checks
→ 206/206 Sabotage-Proben PASS
```

Self-Scan des Repositories:

- Exit 0
- 7 Checks PASS
- 1 Check FAIL, aber nur Warning (`quality.assistant_trace`)
- 19 Checks UNMEASURED
- 0 Check-Crashes

## Existing Architecture

```text
master_gate.py
  ├─ CLI parsing
  ├─ plugin/module loading
  ├─ execution orchestration
  ├─ exit policy
  ├─ self-test runner
  └─ reporters (text/agent/json)

core.py
  ├─ domain models
  ├─ file discovery
  ├─ comment stripping
  ├─ platform detection
  ├─ git changed-only support
  ├─ config parser
  └─ registry helpers

checks/*.py
  └─ platform/domain checks + embedded SelfTestCase fixtures
```

## Strengths to Preserve

1. Drei-/Vierzustands-Denken statt „kein Treffer = Erfolg“.
2. Stabile Check-IDs.
3. Self-tests in beide Richtungen.
4. Ohne Runtime-Drittanbieterpakete.
5. Keine Netzwerkabhängigkeit.
6. Pfad-/Symlink-Grenzprüfungen.
7. Git-`--changed-only` berücksichtigt untracked Dateien.
8. Config lehnt unbekannte Tabellen/Keys überwiegend hart ab.
9. Maschinenformate existieren bereits.
10. `safe_by_default` trennt harte universelle Regeln von projektspezifischer Schärfe.

## Public-Readiness Gaps

### P0 — vor Veröffentlichung

- Keine `LICENSE` im analysierten Paket.
- Keine moderne Paketstruktur / kein `pyproject.toml`.
- Kein veröffentlichter CLI-Entry-Point.
- Keine GitHub Actions CI-/Release-Pipeline.
- Keine `CONTRIBUTING.md`, `SECURITY.md`, PR-/Issue-Templates, CODEOWNERS.
- Öffentliche Texte/Kommentare enthalten reale private Projektnamen und mindestens einen realen Bundle-Identifier.
- `qualitygate` ist als PyPI-Projektname bereits belegt; Distribution-Naming muss separat entschieden werden.
- interne `guideline`-Bezeichnungen wie `DH-003` sind für externe Nutzer nicht ausreichend selbsterklärend.

### P1 — Architektur-/Vertragsrisiken

1. `master_gate.py` (~727 Zeilen) bündelt CLI, Runner, Report und Self-Test.
2. `core.py` (~733 Zeilen) bündelt mehrere Verantwortungen.
3. `checks/apple_release.py` (~1700 Zeilen), `apple.py` (~1344), `universal.py` (~1217) erzeugen Merge-Konflikte und erschweren Ownership.
4. `project.platform` wird in Config validiert, aber aktuell nicht in den `Config`-State übernommen und nicht für die Plattformauswahl genutzt.
5. `dotnet` ist in Config/Detection erwähnt, besitzt aber keinen Check-Pack; `--platform dotnet` kann dadurch nicht als bekannte Check-Plattform funktionieren.
6. `DEFAULT_EXCLUDE_FILES` schließt Namen wie `README.md` global für jedes Scan-Ziel aus. Damit können Dokumentationschecks wichtige öffentliche Markdown-Dateien des Zielprojekts nie messen.
7. Dateien über `max_file_bytes` werden still übersprungen; das kollidiert mit dem Projektprinzip „kein False Green durch ungemessene Eingaben“.
8. Report unterscheidet einen inhaltlichen `FAIL` von einem blockierenden Fail teilweise nur indirekt über Exit-Code/Severity/Profil. Für externe Nutzer sollte `blocking` explizit werden.
9. Rule-Metadaten sind für ein öffentliches Ökosystem zu knapp: keine Tags, Introduced-Version, öffentliche Referenzen, Deprecation-State, Fingerprint-Strategie.
10. Keine explizite API-/Config-/Rule-Versionierungspolitik außer `schema_version = 1.0` im Report.

## Current Test Coverage Model

Gut abgedeckt:
- Runner-Verträge
- Config-Validierung
- Git-Pfade
- Plugin-Fehler
- null measurement
- Self-Test-Vollständigkeit
- jede Check-Regel mit mindestens gesund/kaputt

Noch auszubauen:
- Installations-/Wheel-Tests
- Multi-Python/OS Matrix
- Golden Tests für Text/Agent/JSON
- SARIF-Validierung
- Performance-/Large-Repo-Tests
- echte Fixture-Repositories je Plattform
- Fuzz/Property-Tests für Pfade/Config
- Public API Compatibility Tests

## Migration Principle

**Preserve behavior first. Refactor second. Extend third.**

Jeder Architektur-Split muss vor und nach dem Split dieselbe Check-Anzahl, dieselben Self-Test-Ergebnisse und für definierte Fixture-Repositories semantisch äquivalente Reports liefern.
