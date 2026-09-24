# FUTURE

## Post-Public-Beta Themes

### 1. Baselines & Suppressions
Für Legacy-Repos braucht es kontrollierte Adoption ohne `off`-Hammer.

Boundary now:
- Finding-Fingerprint wird Teil des Modells.
- Suppression braucht Grund + optional Expiry.
- Baseline unterdrückt nur bekannte Findings; neue Findings bleiben sichtbar.

### 2. Official Rule Packs
Wenn Core/Katalog wachsen:
- gemeinsame Engine
- Packs separat versionierbar oder mindestens logisch isoliert
- default install soll weiterhin nützlich bleiben

### 3. Third-Party Plugins
Python Entry Points mit klarer API-Version und Trust-Warnung.

### 4. Generated Rule Documentation
Rule Metadata → statische Docs/Website.

### 5. IDE Integration
SARIF/Problems API zuerst nutzen; keine IDE-spezifische Logik im Core.

### 6. Declarative Rules
Nur wenn genügend wiederkehrende Regeltypen belegen, dass eine kleine DSL sinnvoller als Python ist.

### 7. Watch Mode
Nur nach Performance-Messung. Aktueller `autopush --watch` ist Maintainer-Automation, kein öffentliches Scan-Watch-Design.

### 8. Ecosystem Expansion Priority

Priorität nach generischem Nutzen:
1. CI/GitHub workflows
2. Python packaging/services
3. Web/Node backend
4. Docker/container configs
5. .NET
6. weitere release/store pipelines
7. domain packs aus realen User-Reports

## 1.0 Criteria

1. CLI stable
2. config stable
3. JSON schema stable
4. SARIF stable
5. rule lifecycle documented
6. deprecation policy proven in practice
7. package + action release automated
8. no known P0 privacy/security gaps
9. at least one external contribution cycle successfully completed
10. baseline/suppression design decided, whether shipped or explicitly deferred
