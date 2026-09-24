# SECURITY DESIGN

## Trust Boundaries

### Trusted
- installierte Tool-Version
- offiziell ausgelieferte Rule-Packs
- explizit installierte externe Plugins
- lokale Config des Nutzers

### Untrusted
- jeder zu prüfende Repository-Inhalt
- Dateinamen
- Symlinks
- Git metadata / changed paths
- eingebettete Strings, Shell, JSON, plist, XML etc.

## Security Invariants

1. Zielcode niemals importieren oder ausführen.
2. keine Shell-Aufrufe mit zusammengesetzten User-Strings.
3. subprocess argument lists verwenden.
4. Symlink/realpath darf Scan-Root nicht verlassen.
5. kein Netzwerk im Scan-Pfad.
6. keine Secrets/Source hochladen.
7. keine Telemetrie in V1.
8. externe Plugins niemals automatisch aus dem Scan-Ziel laden.

## Plugin Security

Python-Plugins sind Code Execution. Darum:

- nur installierte Entry-Point-Plugins;
- in Report auflisten, welche Plugins + Versionen geladen wurden;
- Option `--no-third-party-plugins` vorsehen, wenn Plugin-System eingeführt wird;
- CI kann „official-only“ erzwingen;
- kein `./checks/*.py` aus fremdem Repo automatisch importieren.

## GitHub Actions

Öffentliche PRs von Forks dürfen keine Release-Credentials bekommen.

Release-Workflow:
- eigener `release.yml`
- minimal permissions
- PyPI OIDC Trusted Publishing
- optional geschützte GitHub Environment Approval
- Actions möglichst auf commit SHA pinnen oder Dependabot/Renovate kontrolliert nutzen

## Vulnerability Reporting

Öffentliches Repo braucht `SECURITY.md` mit:
- unterstützten Versionen
- privatem Meldeweg (GitHub Private Vulnerability Reporting bevorzugt)
- keine Security-Bugs als öffentliche Issue, bevor Fix/Disclosure koordiniert sind

## Privacy / Provenance Pre-Publish

Vor Public:
- reale private Projektnamen anonymisieren;
- reale Bundle IDs/URLs prüfen;
- lokale absolute Pfade entfernen;
- private Screenshots/Fixture-Daten ausschließen;
- Commit-History separat auditieren, nicht nur Working Tree.

Wichtig: Wenn die bisherige Git-Historie private Daten enthält, reicht ein Cleanup im aktuellen Tree nicht. Dann Public Repo aus sanitisiertem Export neu initialisieren oder History gezielt bereinigen.
