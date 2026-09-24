# PUBLIC RELEASE PLAN


## Positioning Against GitHub Code Quality

Public messaging should say clearly:

- use GitHub Code Quality / CodeQL for the mainstream issues it already covers well;
- use this project for deterministic, local, cross-toolchain failure classes and organization/project knowledge that standard analyzers do not encode;
- SARIF lets both coexist in the same GitHub Security/Code Scanning workflow.

Do not market the tool as a replacement for CodeQL, Ruff, ESLint, SwiftLint or compiler diagnostics.

## Recommended Launch Shape

Nicht direkt „1.0“. Zuerst **0.1.0 Public Beta**.

Warum:
- der Kern ist funktional stark;
- öffentliche API/Config/SARIF/Plugin-Verträge wurden aber noch nie extern belastet;
- 0.x erlaubt saubere Evolution ohne den Eindruck eines bereits eingefrorenen Ökosystems.

## Pre-Publish Sanitization

Pflicht vor Visibility=Public:

1. Working Tree nach Namen, IDs, absoluten Pfaden, Secrets scannen.
2. Reale private Projektnamen in generische Regression Cases umbenennen.
3. Bundle-Identifier anonymisieren.
4. interne Referenzen (`DH-...`) öffentlich erklären oder ersetzen.
5. Git-Historie auditieren.
6. Falls Historie sensible Inhalte enthält: sanitisierten Public-Repo-Start erwägen statt nur HEAD zu säubern.
7. `autopush.sh` nicht als Standard-Public-Workflow bewerben; nach `scripts/maintainer/` verschieben oder entfernen.

## Naming

`qualitygate` ist als PyPI-Name bereits belegt. Darum getrennt entscheiden:

- Brand/Repo name
- Python distribution name
- Python import module
- CLI command
- GitHub Action identifier

Keinen Namen festschreiben, bevor Registry-/GitHub-/Trademark-Schnellcheck erfolgt ist.

## License Decision

Vor Public zwingend.

Praktische Optionen:

### Apache-2.0
Empfohlen, wenn breite Adoption, kommerzielle Nutzung und expliziter Patentgrant gewünscht sind.

### MIT
Noch simpler/permissiver, aber weniger explizite Patentregelung.

### AGPL-3.0
Nur wenn Copyleft auch bei Netzwerkdiensten strategisch gewollt ist; deutlich höhere Adoption-Reibung.

Default-Planannahme: **Apache-2.0**, bis Maintainer anders entscheidet. Vor Anwendung Herkunft aller Codebestandteile klären.

## Public README Structure

1. one-line value proposition
2. 30-second install
3. 30-second scan example
4. what makes it different
5. exit codes
6. config
7. supported packs
8. GitHub Action/SARIF
9. rule quality model
10. contributing
11. privacy/offline promise
12. roadmap

## Distribution

### Python
PyPI + pipx/uv tool.

### GitHub CI
V0.1 docs snippet; V0.2 own Action once packaging is stable.

### Pre-commit
Document local hook; dedicated pre-commit repository/integration optional later.

## Public Beta Success Signals

- external user can install in <2 commands;
- external repo can run scan without reading internal docs;
- false-positive issue contains enough data to reproduce;
- new-rule contributor can follow template and pass self-tests;
- report integrates with GitHub PR via SARIF;
- no private source leaves local machine.
