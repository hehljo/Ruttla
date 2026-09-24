# RISK REGISTER

| ID | Risk | Probability | Impact | Early Signal | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|---|
| R-001 | Private Projektnamen/IDs werden öffentlich | High | High | grep findet reale Namen/Bundle IDs | sanitization + history audit vor Public | Maintainer | Open |
| R-002 | Lizenz fehlt/unklar | High | High | kein LICENSE | Lizenzentscheidung vor Public, Provenienz klären | Maintainer | Open |
| R-003 | Package-/Produktname kollidiert | High | Medium | `qualitygate` auf PyPI belegt | Naming ADR + Registry/Trademark check | Maintainer | Open |
| R-004 | Refactor bricht 90 bestehende Checks | Medium | High | Self-test count/report delta | golden fixtures + compatibility phase gates | Core | Open |
| R-005 | False Positives zerstören Vertrauen | Medium | High | Nutzer schalten Regeln massenhaft ab | experimental lifecycle, healthy counterexamples, baseline/suppressions | Rules | Open |
| R-006 | False Green durch stille Scan-Lücken | Medium | Critical | große/ausgeschlossene relevante Files fehlen ohne Hinweis | coverage diagnostics; no silent relevant skip | Core | Open |
| R-007 | Public Rule IDs werden unkontrolliert gebrochen | Medium | High | Rename in PR ohne migration | ID policy + compatibility tests | Core | Open |
| R-008 | externe Plugins führen untrusted Repo-Code aus | Low now / High later | Critical | local repo plugin auto-discovery | only installed entry points; official-only mode | Security | Deferred boundary defined |
| R-009 | Core-Dateien werden zu Monolithen | High | Medium | >1k-line modules, frequent merge conflicts | staged module split by responsibility | Core | Open |
| R-010 | interne Guidelines sind öffentlich nicht nachvollziehbar | High | Medium | `DH-003` without public source | standard Rule reference metadata + docs | Rules | Open |
| R-011 | Plattformmodell inkonsistent (`dotnet`, project.platform) | High | Medium | config accepts unused values | normalize platform registry and tests | Core | Open |
| R-012 | README/global docs unintentionally excluded | High | Medium | docs checks report zero on top-level docs | separate self-description handling from basename exclusions | Core | Open |
| R-013 | Supply-chain risk in release automation | Medium | High | broad GITHUB_TOKEN/API token | OIDC trusted publishing, minimal permissions, pin actions | Release | Open |
| R-014 | Scope creep into generic linter aggregator | Medium | High | many speculative style rules | explicit acceptance standard; non-goals | Maintainer | Open |
| R-015 | Performance degrades as rule count grows | Medium | Medium | scan time rises superlinearly | benchmark, shared indexes, profile before optimizing | Core | Open |
| R-016 | Contributors cannot reproduce rule rationale | Medium | Medium | PRs rely on private project context | minimal public fixtures + references required | Rules | Open |
