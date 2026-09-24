# PROJECT BRIEF

Stand: 2026-09-24

## Working Title
CODE_QUALITY_GENERAL

Öffentlicher Produktname: **TBD**. Nicht vor Abschluss des Naming-/Distribution-Checks festschreiben.

## Project Type
Open-Source Developer Tool / Static Quality Gate / CLI / CI Integration.

## Primary Users

1. Entwickler, die KI-Coding-Agents einsetzen.
2. Maintainer mit mehreren heterogenen Projekten.
3. Teams, die wiederkehrende reale Fehlerklassen als deterministische Gates konservieren wollen.
4. Open-Source-Contributors, die neue Regeln aus reproduzierten Fehlern beisteuern.

## Primary Problem

Wissen über Fehlerbilder liegt oft nur in Chats, Postmortems oder Entwicklererfahrung. Das gleiche Problem wird deshalb mehrfach mit LLM-/Debugging-Aufwand gelöst. Klassische Linters decken viele dieser projektspezifischen oder workflowbezogenen Fehlerklassen nicht ab.

## Core Value

Ein einmal verstandenes Fehlerbild wird zu einem reproduzierbaren, lokalen Check mit Gegenproben und stabiler Maschinen-Schnittstelle.

## Primary Workflow

```text
realer Fehler / belegte Schwachstelle
→ Ursache verifizieren
→ vorhandenen Check prüfen
→ Check + kaputte Probe + gesunde Probe
→ Gate-Selbsttest
→ echte Regression/Fix-Gegenprobe
→ versioniert veröffentlichen
→ lokal / Pre-Commit / CI / Coding-Agent wiederverwenden
```

## Target Platforms

### Runtime des Tools
- Linux
- macOS
- Windows
- Python 3.11–3.14 als anfängliche stabile Matrix
- Python 3.15 frühzeitig im Pre-Release-Kanal testen

### analysierte Projektarten
Bestehend:
- universal
- Apple/Xcode/Swift
- Web
- Godot
- Unreal
- Raspberry/Python-Hardware
- Python Services
- Media Pipelines

Architektonisch vorbereiten:
- .NET
- GitHub/CI
- Docker/Container
- Node/backend
- weitere Rule-Packs

## Online / Offline

Runtime: **offline by default, no network, no LLM, no telemetry.**

Netz wird nur für Maintainer-Prozesse benötigt: Quellenrecherche, Release, PyPI/GitHub, optional Doku-Build.

## Expected Scale

Public Beta:
- 100–150 offizielle Checks
- 10k–50k Dateien pro Repository als realistischer Scan-Bereich
- Monorepos mit Subroot-Scan
- mehrere externe Contributors

Langfristig:
- Core + offizielle Rule-Packs + optional externe Pakete
- stabile JSON/SARIF-Verträge

## Data Sensitivity

Das Tool liest fremde Quelltrees. Deshalb gelten:
- keine Übertragung nach außen;
- keine Ausführung von Zielcode;
- keine Telemetrie;
- keine automatische Ausführung von Plugins aus dem Zielrepo;
- Pfad-/Symlink-Grenzen strikt halten.

## Monetization

Nicht für V1 erforderlich. Architektur soll kommerzielle Dienstleistungen oder Sponsoring später nicht verhindern, aber keine Cloud-Abhängigkeit erzwingen.

## Delivery Target

### First meaningful public release
`0.1.0` Public Beta nach Abschluss der Phasen P00–P05.

### 1.0
Erst wenn CLI, Config, Report-Schema, Rule-Lifecycle und Plugin-Grenze als stabil gelten.

## Hard Constraints

- Bestehendes Verhalten möglichst bewahren.
- Keine Big-Bang-Neuschreibung.
- Check-IDs stabil behandeln.
- false green ist schwerwiegender als sichtbares `unmeasured`.
- Runtime möglichst dependency-free.
- neue Regeln evidenzbasiert, nicht geschmacksbasiert.

## North Star

**CODE_QUALITY_GENERAL enables developers and coding agents to turn real, recurring engineering failures into deterministic local checks that prevent the same class of mistake from consuming debugging time again.**
