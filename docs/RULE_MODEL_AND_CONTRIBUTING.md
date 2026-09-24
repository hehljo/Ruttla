# RULE MODEL & CONTRIBUTION PROTOCOL

## Why this matters

Der Katalog ist das Produkt. Öffentliche Skalierung funktioniert nur, wenn neue Regeln dieselbe Beweisqualität behalten wie der heutige „Fehler → Check → Gegenprobe“-Ansatz.

## Rule Acceptance Standard

### Required

- stabiler `check_id`
- klare Fehlerklasse
- technische Eigenschaft statt zufälliger Bauform
- reproduzierbares broken fixture
- healthy fixture
- öffentliche technische Referenz oder sauber dokumentierter empirischer Nachweis
- False-Positive-Analyse
- Fix-Richtung
- Severity-Begründung
- `safe_by_default` nur mit besonders hoher Sicherheit

### Rejected by default

- Stilgeschmack ohne Fehlerwirkung
- Regeln, die „meist richtig“ sind, aber viele legitime Gegenbeispiele haben
- Suchmuster, die Tests/Dokumentation der Regel selbst treffen und deshalb massenhaft Ausnahmen brauchen
- Regeln, deren Fix eine nicht verifizierte API empfiehlt
- Regeln, die nur auf einen privaten Projektnamen reagieren

## Public Evidence Record

Jede Rule-Doku sollte enthalten:

```text
ID
Summary
Why it exists
What it measures
What it intentionally does not measure
Broken example
Healthy example
False-positive notes
Default severity
Blocking-by-default rationale
References
Introduced in
Changes
```

Private Ursprungsgeschichten werden generalisiert:

```text
NICHT: "In Projekt <Privatname> war X falsch"
SONDERN: "Observed in a real macOS App Store submission: project-level SDK detection caused ..."
```

## Rule Lifecycle

### Experimental
Neue Regel, nur advisory, gezielt opt-in oder nonblocking.

### Stable
Ausreichend echte Gegenproben, dokumentierte Grenzen, normales Pack.

### Deprecated
Durch bessere Regel ersetzt; Alias/Mapping dokumentiert.

### Removed
Nur in Major-Version oder wenn nachweislich fehlerhaft/sicherheitskritisch; Migration dokumentieren.

## Check-ID Policy

- IDs werden nicht für Wording-Änderungen umbenannt.
- Semantik einer ID nicht still fundamental ändern.
- neue Semantik → neue ID + Deprecation der alten.
- Namespaces: `<pack>.<concise_rule_name>`.

## Self-Test Policy

Minimum:
- 1 FAIL fixture
- 1 PASS fixture

Für harte Regeln zusätzlich:
- mindestens 1 legitimer Grenzfall
- mindestens 1 negative counterexample gegen den häufigsten False Positive

## Community Issue Forms

### New real-world failure
Pflichtfelder:
- Toolchain/Platform
- exact failure text
- minimal broken code/config
- fixed code/config
- source/reference
- why existing tools missed it
- consent to publish anonymized reproduction

### False positive
Pflichtfelder:
- check ID
- minimal healthy reproduction
- why behavior is valid
- tool version
- config

### False negative
Pflichtfelder:
- check ID expected
- broken reproduction
- why rule should have matched

## PR Gate for New Rules

CI prüft automatisch:
- Self-tests completeness
- all self-tests
- unit suite
- check ID uniqueness
- public Rule metadata completeness
- docs generated/up-to-date
- no private provenance patterns
- own gate
