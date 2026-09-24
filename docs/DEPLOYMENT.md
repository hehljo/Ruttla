# DEPLOYMENT & RELEASE

## Release Channels

### Source
GitHub public repository.

### Python
PyPI wheel + sdist unter noch festzulegendem Distribution-Namen.

### GitHub Action
Nach stabiler CLI zunächst eine einfache dokumentierte Workflow-Integration; danach optional eigene Action/Marketplace-Distribution.

## Recommended Versioning

SemVer für Tool:
- `0.1.0`: first public beta
- 0.x: APIs noch evolvierbar, Änderungen aber dokumentiert
- `1.0.0`: CLI/config/report/rule lifecycle stabil

## Release Workflow

```text
PR merged
→ CI green
→ changelog/version PR
→ signed/tagged release
→ build wheel/sdist
→ verify artifacts
→ PyPI Trusted Publishing
→ GitHub Release + artifacts
→ action major tag update (wenn Action existiert)
→ smoke install from PyPI
```

## Release Security

PyPI via OIDC Trusted Publishing statt langlebigem API-Token.

Release Workflow minimal berechtigen und isolieren.

## Branch Protection

Für `main`:
- PR required
- CI required
- no force push
- signed commits optional, nicht als Startblocker
- CODEOWNERS für Core/Release/Security sensible Bereiche

## Artifacts

- sdist
- pure-Python wheel
- checksums von GitHub/PyPI
- generated rule catalog
- optional SARIF schema examples

## Rollback

Python-Pakete auf PyPI werden nicht „überschrieben“. Fehlerhafte Release:
- yanken
- Patch-Version veröffentlichen
- Changelog/Advisory

Breaking Rule-Regression:
- betroffene Rule notfalls in Patch temporär nonblocking/deprecated setzen, mit dokumentierter Begründung; ID nicht heimlich umdeuten.
