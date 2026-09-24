# REPORTING & PUBLIC CONTRACTS

## Public Contracts

Für ein öffentliches CLI sind nicht nur Python-Funktionen API. Stabil zu behandeln sind:

1. CLI command + flags
2. exit codes
3. check IDs
4. config keys
5. JSON schema
6. agent output field ordering/escaping, soweit dokumentiert
7. SARIF rule IDs

## Exit Codes

Bestehender Vertrag beibehalten:

| Code | Meaning |
|---:|---|
| 0 | Messung erfolgreich; keine blockierenden Findings |
| 1 | mindestens ein blockierendes Finding |
| 2 | keine aussagekräftige Messung möglich |
| 3 | Runner/Input/Config/Plugin-Fehler |

## Blocking Model

V1 Report soll explizit machen:

```json
{
  "blocking_findings": 0,
  "advisory_findings": 4,
  "verdict": "green"
}
```

Ein `CheckResult.status = fail` kann dann weiterhin ausdrücken „Regel hat Findings“, während `blocking` die CI-Wirkung beschreibt.

## JSON

### Schema policy

- `report_schema_version` separat von Toolversion.
- additive Felder innerhalb derselben Major-Schema-Version erlaubt.
- Entfernen/Umdeuten erfordert Schema-Major.
- maschinenlesbares JSON Schema im Repo veröffentlichen.

### Minimum fields

- tool + tool_version
- report_schema_version
- root (optional redaction mode überlegen)
- config source
- platforms detected/selected
- scan coverage diagnostics
- counts
- results
- next action

## Agent Format

Ziel: sehr kompakt, stabil und zeilenbasiert.

Erweitern um:
- `BLOCKING=true|false`
- `SCHEMA=<version>` im Header
- eindeutige escaping policy

Keine freie multiline Ausgabe in Maschinenfeldern.

## SARIF

V1 soll SARIF 2.1.0 generieren.

Mapping:

```text
check_id              → ruleId
rule title            → shortDescription
rationale             → fullDescription/help
severity              → level (error/warning/note)
file + line            → physicalLocation
message               → result.message
stable fingerprint    → partialFingerprints (später/baseline)
```

Nutzen:
- GitHub Code Scanning Alerts für Public Repos
- PR-Annotations
- standardisierte Integration mit anderen CI-Systemen

## Config Versioning

V1 fügt optional/empfohlen hinzu:

```toml
config_version = 1
```

Legacy-Profile ohne Feld bleiben in 0.x kompatibel. Vor 1.0 Entscheidung treffen, ob es Pflicht wird.

## Rule Catalog Versioning

Neben Tool-SemVer soll jeder Check `introduced_in` tragen. Änderungen an einer Rule werden im Changelog unter ihrer ID dokumentiert.
