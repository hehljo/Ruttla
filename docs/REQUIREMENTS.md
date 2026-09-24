# REQUIREMENTS

## Functional Requirements

### FR-001 Scan
Das Tool scannt einen lokalen Projektbaum, ohne dessen Quellcode auszuführen.

### FR-002 Result States
Jeder Check liefert `pass`, `fail`, `unmeasured` oder `error` nach dokumentierten Regeln.

### FR-003 Stable Rule Identity
Jede Regel besitzt eine global eindeutige stabile `check_id`.

### FR-004 Machine Output
Text, Agent, JSON und SARIF müssen denselben semantischen Resultatkern abbilden.

### FR-005 Incremental Scan
Git-basierter Changed-Only-Scan muss Subroots, untracked Dateien und Pfadgrenzen korrekt behandeln.

### FR-006 Config
Konfiguration muss streng validiert werden; unbekannte Felder dürfen nicht still ignoriert werden.

### FR-007 Profiles / Severity
Projekte können Checks abschalten oder Severity kontrolliert überschreiben.

### FR-008 Self-Test
Jeder offizielle Check muss mindestens eine erwartete FAIL- und eine erwartete PASS-Probe besitzen.

### FR-009 Explainability
Für jeden öffentlichen Check müssen Titel, Rationale, Default Severity, Plattform, Referenzen und Fix-Richtung abrufbar sein.

### FR-010 Public Rule Listing
CLI muss Checks strukturiert listen können, später auch als JSON.

### FR-011 SARIF
Befunde sollen als SARIF 2.1.0 exportierbar sein, inklusive Location und stabiler Rule-ID.

### FR-012 Determinism
Gleiche Eingabe + gleiche Toolversion + gleiche Config → gleiche semantische Ausgabe und stabile Sortierung.

### FR-013 Scan Diagnostics
Übersprungene/ungelesene/zu große relevante Dateien müssen als diagnostischer Zustand sichtbar sein; kein stiller Coverage-Verlust.

### FR-014 Package Install
Installation via standardkonformem Python-Paket und isolierter CLI-Installation (z. B. pipx/uv tool) muss möglich sein.

### FR-015 Backward Compatibility
Während der Migration bleibt `python3 master_gate.py ...` als Shim verfügbar, bis dokumentiert deprecated.

## Public V1 Rule Requirements

Jede neue offizielle Regel benötigt:

- ID
- Titel
- Plattform/Pack
- Default Severity
- `safe_by_default`-Begründung
- öffentliche Rationale/Referenz
- Broken Fixture
- Healthy Fixture
- False-Positive-Notiz
- Fix-Hinweis
- Introduced-Version
- Changelog-Eintrag

## Non-Functional Requirements

### NFR-001 Offline
Kein Netz im Scan-Pfad.

### NFR-002 Zero Telemetry
Keine Telemetrie oder Uploads ohne spätere explizite Opt-in-Entscheidung; für V1 keine Telemetrie.

### NFR-003 Runtime Dependencies
Ziel: Python-Stdlib-only Runtime. Build-/Dev-Abhängigkeiten sind erlaubt.

### NFR-004 Cross Platform
Core und CLI laufen auf Linux/macOS/Windows.

### NFR-005 Security
Symlink-/Path-Escape bleibt blockiert; untrusted target files werden nie importiert/ausgeführt.

### NFR-006 Performance
Initiales Budget: 10k Textdateien / 100 MB Quelltext auf Standard-GitHub-Runner in unter 10 s für universelle Checks als Zielwert. Vor harter Durchsetzung zuerst Baseline messen.

### NFR-007 Memory
Zielbudget < 512 MB bei obigem Benchmark; Streaming/Indexierung prüfen, falls überschritten.

### NFR-008 Compatibility
Python 3.11–3.14 stabil; 3.15 pre-release CI bis zur finalen Veröffentlichung.

### NFR-009 Documentation
Englisch ist öffentliche Primärsprache; deutsche Dokumentation kann parallel gepflegt werden.

### NFR-010 Provenance
Private Kundennamen/Projektnamen/Identifiers dürfen nicht versehentlich in öffentliche Beispiele gelangen.
