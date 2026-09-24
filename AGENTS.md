# AGENTS.md — Ruttla (CODE_QUALITY_GENERAL) Project Rules

## Mission

Dieses Repository ist ein lokales, deterministisches Quality Gate. Ein Fehlerbild, das real aufgetreten und belastbar verstanden wurde, soll danach ohne LLM, ohne Netzwerk und reproduzierbar abgefangen werden.

## North Star

**Reale Fehler in ausführbare, beweisbare und wiederverwendbare Checks verwandeln — ohne False-Green und ohne unnötige False-Positives.**

## Resume Protocol

1. `AGENTS.md` lesen.
2. `STATUS.md` lesen.
3. aktuelle Phase in `MASTER_ROADMAP.md` lesen.
4. referenzierte ADRs und Subsystem-Dokumente lesen.
5. vorhandenen Code und Tests inspizieren.
6. ersten unblocked Task ausführen.
7. kleinste kohärente Änderung machen.
8. validieren, Diff prüfen, Doku/Status/Roadmap aktualisieren.

## Invariants — nicht still brechen

- Exit 0/1/2/3 bleibt ein dokumentierter CLI-Vertrag.
- `unmeasured` ist kein stilles `pass`.
- Check-IDs sind öffentliche, stabile Identitäten.
- Kein Check darf allein wegen „kein Treffer“ als gemessen gelten, wenn sein Prüfgegenstand nie existierte.
- Jeder neue Check braucht mindestens eine kaputte und eine gesunde Gegenprobe.
- Runtime bleibt standardmäßig offline; keine Telemetrie.
- Zielcode wird gelesen, aber nicht ausgeführt.
- Ein öffentlicher Check braucht nachvollziehbare technische Begründung/Referenz.
- Neue harte Default-Regeln brauchen besonders strenge False-Positive-Begründung.

## Public Contribution Rule

Ein neuer Check ist nur mergefähig, wenn folgende Evidenz vorliegt:

1. reales oder minimal reproduziertes Fehlerbild;
2. dokumentierte Ursache;
3. negative Probe, die rot wird;
4. gesunde Probe, die grün bleibt;
5. False-Positive-Analyse;
6. klare Fix-Richtung ohne erfundene APIs;
7. Rule-Dokumentation und Changelog-Eintrag.

## Architecture Guardrails

- `qualitygate`-Core kennt keine plattformspezifische Business-Logik.
- Rule-Packs hängen vom Core ab, nie umgekehrt.
- Reporter (text/json/agent/sarif) konsumieren ein gemeinsames internes Result-Modell.
- Konfiguration wird vor dem Scan vollständig validiert.
- externe Plugins werden nur aus explizit installierten/trusted Python-Packages geladen; niemals automatisch aus dem Scan-Ziel.
- keine Plattformerkennung über Projektnamen oder Ordnernamen, wenn eine technische Eigenschaft messbar ist.

## Change Classes

### Patch
Bugfix ohne Vertragsänderung. Keine neue hart-blockierende Default-Regel.

### Minor
Neue additive Checks, additive Report-Felder, neue Plattformunterstützung, neue optionale Integrationen.

### Major
Breaking CLI-/Config-/JSON-Schema-Änderung, Check-ID-Entfernung/Umdeutung oder grundlegender Exit-Code-Wechsel.

## Model Orchestration

- Principal Architect: GPT-5.6 Sol, High; bei schwer rückgängig zu machender Architektur unabhängig challengen lassen.
- Lead Implementer: GPT-5.6 Sol, High.
- Worker: schnellstes verfügbares Modell mit zuverlässiger Repo-Arbeit, Medium.
- Independent Reviewer: stärkstes verfügbares Claude-Modell; Stand 2026-09-24 bevorzugt Opus 5.5, sofern im Account verfügbar.
- Alternate/Fallback: Gemini 3.8 Flash High für unabhängige zweite Implementierung/Diagnose.

Modellnamen bei Projektstart erneut prüfen; Rollen bleiben stabil.

## Two-Attempt Rule

Nach zwei ernsthaften Fehlversuchen auf demselben Modell-/Effort-Level:

1. Editieren stoppen.
2. Diff und exakte Fehler sichern.
3. Root Cause neu analysieren.
4. auf Lead/Principal eskalieren oder Independent Reviewer einsetzen.

## Definition of Done

Ein Task ist erst fertig, wenn relevante Akzeptanzkriterien, Tests, Build/Packaging, Doku und Diff-Review abgeschlossen sind und Evidenz in der Roadmap steht.

## Repository-specific duties

- Read existing code before larger changes; do not guess.
- A reported failure is turned into a CHECK first (see CLAUDE.md), not a fix in the foreign project.
- Keep STATUS.md, MASTER_ROADMAP.md and CHANGELOG.md current at milestones.
- No secrets and no private project names in commits (tests/test_provenance.py).
- Gates: `python -m unittest discover -s tests`, `python master_gate.py --self-test`,
  `python scripts/gen_rule_docs.py --check`, `python master_gate.py . --strict`.
