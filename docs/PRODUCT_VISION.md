# PRODUCT VISION

## Positionierung

Das öffentliche Projekt sollte **nicht** als allgemeiner „Super-Linter“ positioniert werden. Werkzeuge wie MegaLinter bündeln bereits viele etablierte Linters. Das Alleinstellungsmerkmal hier ist ein anderes:

> **Executable engineering memory for failures that normal linters miss.**

Der Katalog wächst aus realen Fehlern, und jede Regel muss ihre eigene Wirksamkeit in beide Richtungen beweisen.


## Competitive Positioning — GitHub Code Quality (2026)

GitHub Code Quality reached general availability in July 2026. It focuses on CodeQL-based maintainability/reliability findings, coverage gating and optional AI-assisted fixes inside GitHub. Supported deterministic language analysis is currently centered on C#, Go, Java, JavaScript/TypeScript, Python and Ruby.

CODE_QUALITY_GENERAL should therefore **not** compete on generic maintainability scoring or duplicate mature CodeQL/ESLint/Ruff rules. Its differentiated territory is:

- fully local/offline scanning with no source upload;
- evidence-backed rules born from real failures;
- platforms/workflows outside mainstream CodeQL coverage (Apple/Xcode, Godot, Unreal, Raspberry/hardware, FFmpeg/media pipelines, release/store workflows);
- agent-specific failure prevention and machine-friendly handoff;
- explicit `unmeasured` semantics and self-tested rule effectiveness.

GitHub/SARIF is a distribution surface, not the product boundary.

## Kernversprechen

### 1. Tokenfrei im Runtime-Pfad
Der eigentliche Scan startet kein LLM und braucht kein Netzwerk.

### 2. Keine stillen Erfolge
`unmeasured` bleibt explizit sichtbar; null Checks sind kein Erfolg.

### 3. Beweisbare Regeln
Jeder Check bringt Gegenproben mit und dokumentiert Ursprung/Rationale.

### 4. Agent-native Ausgabe
Stabile IDs, JSON, kompakte Agent-Ausgabe und später SARIF machen das Tool automatisierbar.

### 5. Community-Lernschleife
Ein GitHub-Issue für einen realen Fehler soll sich direkt in einen neuen Regression-Check übersetzen lassen.

## V1 / Public Beta Scope

Muss enthalten:

- installierbares Python-Paket mit CLI-Entry-Point;
- bestehende 90 Checks ohne Verhaltensverlust;
- klare Semantik für pass/fail/unmeasured/error;
- dokumentierte Config und Report-Schema-Version;
- Linux/macOS/Windows CI;
- Python 3.11–3.14 Matrix;
- JSON + Agent + Text;
- SARIF-Ausgabe für GitHub Code Scanning;
- öffentliche Rule-Dokumentation;
- `CONTRIBUTING.md`, `SECURITY.md`, Issue-/PR-Templates;
- Lizenz;
- anonymisierte öffentliche Beispiele;
- reproduzierbarer Release-Prozess;
- Changelog und SemVer-Policy.

## Deferred but Architecturally Relevant

- externe Python-Plugin-Packs;
- Baseline-/Suppression-Datei mit stabilen Fingerprints;
- VS Code/IDE-Integration;
- declarative checks / DSL;
- lokale Daemon-/Watch-Mode-Optimierung;
- Web-Dokumentationsportal / Rule Explorer;
- Paketaufteilung in Core + offizielle Packs;
- optionale Auto-Fixes;
- Homebrew/winget/choco Distribution;
- Community-Maintainer pro Rule-Pack.

Die Grenzen dafür werden jetzt definiert, aber V1 implementiert sie nicht alle.

## Explicit Non-Goals

V1 ist **nicht**:

- ein Ersatz für Compiler, Ruff, ESLint, SwiftLint, Clang-Tidy, CodeQL etc.;
- ein Build-System;
- ein Cloud-Service;
- ein LLM-Reviewer;
- ein automatischer Code-Rewriter;
- ein Security-Zertifikat;
- ein Versprechen, dass „grün“ gleich „fehlerfrei“ bedeutet;
- ein Sammelbecken für subjektive Stilregeln ohne belegte Fehlerwirkung.

## Product Principle

Ein Check muss mindestens eine dieser Fragen mit „ja“ beantworten:

1. Verhindert er einen realen Build-/Release-/Runtime-Fehler?
2. Verhindert er einen reproduzierbaren False-Green-/Messfehler?
3. Verhindert er einen konkreten Security-/Privacy-/Data-Integrity-Fehler?
4. Verhindert er einen wiederholt teuren Agent-/Debugging-Fehler, der statisch zuverlässig erkennbar ist?

Wenn nein, gehört er nicht automatisch in den offiziellen Core-Katalog.
