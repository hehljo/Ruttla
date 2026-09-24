# Public contracts (source of truth, English)

Versioning policy: ADR-0007. Tool = SemVer; report schema = major.minor
(fields only added within a major); config = `config_version` integer; rules =
stable ID + `introduced_in` / lifecycle.

| Surface | Contract | Breaking change needs |
|---|---|---|
| Exit codes | 0 measured & no blocking finding · 1 blocking finding · 2 nothing measured · 3 runner/input/config/plugin error | major |
| Check IDs | stable, `<namespace>.<rule>`; frozen list `tests/golden/check_ids.txt` | deprecation cycle, major for removal |
| CLI flags | `--format text|agent|json|sarif`, `--json`, `--sarif`, `--platform`, `--check`, `--config`, `--strict`, `--changed-only`, `--max-findings`, `--list`, `--explain`, `--self-test`, `--version`, `update` | major |
| Profile | `.ruttla.toml` (alias `.qualitygate.toml`), unknown keys are errors | config_version bump |
| JSON report | `schemas/report.schema.json`, `schema_version` 1.1; consumers ignore unknown fields; `tool` stays `master_quality_gate` for 1.x, `tool_name` = `ruttla` | schema major |
| Agent format | tab-separated; new header keys and trailing fields are only appended; every field is one line | schema major |
| SARIF | 2.1.0, `ruleId` = check ID, every result has a location, `partialFingerprints["ruttla/v1"]` | major |
| Encoding | all output UTF-8 on every OS; paths `/`-separated, relative to the scan root | major |

## Blocking model

A finding blocks (`blocking: true`, decides exit 1) iff its check FAILED and
- `--strict` / `gate.strict`: always; else
- severity `error` **and** (a profile is present **or** the rule is `safe_by_default`).

Proven equivalent to the pre-0.1 exit logic (tests/test_contracts.py).

## Coverage diagnostics

`coverage.files_skipped` lists files above `gate.max_file_bytes`;
`platforms_without_pack` lists detected platforms without rules (e.g. `dotnet`).
Agent format: `SKIPPED` and `NO_PACK` lines.
