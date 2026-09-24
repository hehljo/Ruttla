# ARCHITECTURE

## Architectural Goal

Den existierenden funktionierenden Runner in einen öffentlichen, testbaren Kern überführen, ohne Check-Verhalten während der Migration zu verändern.

## Target Components

### 1. CLI Adapter
Verantwortung:
- argv parsing
- UX
- Exit-Code-Mapping
- Auswahl des Reporters

Nicht verantwortlich für:
- Check-Logik
- File Discovery
- Report-Datenmodell

### 2. Engine
Verantwortung:
- Rule Registry
- Selektion
- Ausführung
- Result-Validierung
- Policy für Blocking/Advisory

### 3. Scan Context / Discovery
Verantwortung:
- sichere Dateiinventur
- Excludes
- Größenlimit
- Plattformerkennung
- relevante Skip-Diagnostics

Wichtig: „zu groß/ausgeschlossen/ungelesen“ muss als Messabdeckung nachvollziehbar sein.

### 4. Config
Verantwortung:
- TOML Parse/Validation
- versioniertes Config-Modell
- Severity Overrides
- Excludes
- optionale explizite Plattformwahl

`project.platform` muss entweder tatsächlich wirken oder entfernt/deprecated werden; nur Validieren und Wegwerfen ist nicht zulässig.

### 5. Rule Model

```text
Rule
- id
- title
- pack/platform
- default_severity
- safe_by_default
- tags
- references[]
- introduced_in
- deprecated_in?
- rationale
- check(context) -> CheckResult
- self_tests[]
```

### 6. Report Model

Ein internes kanonisches Modell wird von allen Reportern konsumiert.

```text
RunReport
- tool_version
- report_schema_version
- config_version
- root
- detected_platforms
- coverage diagnostics
- check results
- blocking findings
- advisory findings
- skipped/relevant-unmeasured inputs
- next_action
```

### 7. Reporters

- Text
- Agent
- JSON
- SARIF

Kein Reporter darf eigene Scan-Semantik erfinden.

### 8. Official Rule Packs

Checks werden in kleine fachliche Module gesplittet. Ziel: grob 100–400 Zeilen pro Datei, wenn fachlich sinnvoll; kein starres LOC-Limit.

Beispiel Apple:

```text
checks/apple/
├── project.py
├── swift.py
├── release.py
├── xcode.py
├── privacy.py
└── resources.py
```

### 9. External Plugin Boundary — deferred implementation

Später über Python Entry Points, nicht durch Scannen/Importieren von `.py` aus dem Zielrepo.

Trust Model:
- installiertes Plugin = explizit vertrauter ausführbarer Code;
- Scan-Ziel = untrusted data;
- niemals beides vermischen.

## Data Flow

```text
argv
→ config load + validate
→ safe file inventory
→ platform detection / explicit selection
→ rule selection
→ rule execution
→ result validation
→ blocking policy
→ canonical run report
→ text | agent | json | sarif
→ exit code
```

## Compatibility Migration

### Stage A
Neue Package-Module um existierende Logik legen; `master_gate.py` bleibt Frontdoor.

### Stage B
Logik aus `core.py` / `master_gate.py` in Module extrahieren, aber öffentliche Ausgabe mit Golden Fixtures vergleichen.

### Stage C
Console Script wird primäre Frontdoor; `master_gate.py` ruft nur noch `package.cli:main`.

### Stage D
Shim nach mindestens zwei Minor-Releases deprecaten; Entfernung erst 1.0+ oder Major.

## Error Boundaries

- Input/Config/Git failure → Runner Error, Exit 3
- null meaningful measurement → Exit 2
- blocking finding → Exit 1
- erfolgreiche Messung ohne blockierende Findings → Exit 0

Advisory Findings dürfen Exit 0 begleiten, müssen im Report explizit als `blocking=false` erkennbar sein.

## Key Architecture Corrections Before Public Scale

1. Globales Ausschließen von `README.md` & Co. neu modellieren.
2. silent skip großer Dateien beseitigen oder als Coverage Diagnostic reporten.
3. `project.platform`-Semantik reparieren.
4. Dotnet-Detection/Config/Rule-Registry konsistent machen.
5. Report-Blocking explizit modellieren.
6. private/projektspezifische Provenienz aus öffentlichen Rule-Metadaten lösen.
7. große Rule-Dateien splitten, ohne IDs/Verhalten zu ändern.
