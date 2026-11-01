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

## Project runtime proof inputs (`.ruttla-contracts.json`, version 1)

The optional `proofs` array binds self-reported test results to source hashes.
Each proof has a unique `id`, project-relative `receipt` and nonempty
`required_cases`. Sources use one or more additive selectors:

- `sources`: the original nonempty list of exact paths. Still supported without
  Git, including ignored inputs. Every listed file must exist and be readable.
- `source_globs`: nonempty project-relative patterns. On **every** snapshot,
  derive tracked plus untracked, nonignored files using local
  `git ls-files --cached --others --exclude-standard -z`. Tracked files win
  over ignore rules. Deleted tracked paths leave the derived set.
- `include_ignored_globs`: explicit opt-in patterns for generated inputs such
  as `build/qa/report*.json`. These select ordinary files **and** ignored
  untracked files. This is needed only when existing evidence intentionally
  binds generated reports; it does not opt the whole project out of Git-ignore.
- `exclude_globs`: optional patterns applied to both derived selectors.
  They never remove an explicitly required `sources` entry.

Example (the receipt lies outside the selected directories):

```json
{
  "version": 1,
  "proofs": [{
    "id": "layout",
    "receipt": ".layout-evidence.json",
    "source_globs": ["src/**", "assets/**", "tests/**", "tools/test_layout.py"],
    "exclude_globs": ["assets/previews/**"],
    "required_cases": ["mobile", "desktop"]
  }]
}
```

Patterns are anchored at the contract's directory, `/`-separated and
case-sensitive on every platform. `*`, `?`, `[abc]` and `[!abc]` match within
one segment; a whole `**` segment matches zero or more segments. Thus
`src/**/*.py` includes `src/a.py` and `src/nested/a.py`, while `src/*.py`
only includes the former. Dotfiles follow the same rules. Absolute paths,
parent traversal, backslashes, drive prefixes and partial `**` segments are
invalid. Paths and symlinks must remain inside the project. Submodule contents
are not recursively inventoried. Git calls disable fsmonitor and inherited
`GIT_*` overrides; they do not execute target hooks, filters or code or use
the network. Missing Git or an unreadable/non-Git working tree is invalid
for patterns; exact-list contracts do not acquire a Git dependency.

The result is a sorted, deduplicated union; `.ruttla-contracts.json` is always
hashed too. No match for one pattern is allowed (e.g. a not-yet-created
generated report), but **zero selected source files overall is invalid**.
Require particular generated results in the project's runner and bind their
case IDs through `required_cases`; a glob does not assert file existence.
The receipt cannot select itself. New files, edits, removals and changed
requirements invalidate earlier receipts. `write_receipt` re-resolves the set
and rejects changes during a test run. Existing version-1 list contracts and
receipt hashes retain their format; migrating the contract invalidates old
receipts intentionally. This additive format change needs no version bump.

`quality.contract_runtime_evidence` distinguishes:

| Situation | Result / CLI exit |
|---|---|
| Current, complete receipt | PASS / 0 |
| Missing/stale/failed receipt or failed required case | FAIL / 1 |
| Missing exact input, empty derived set, unavailable Git, unsafe/unreadable input | ERROR / 3 (invalid; fix inputs and measure again) |
| No proof contract | UNMEASURED / 2 when nothing else is measured |

Existing malformed-schema handling remains a contract finding (FAIL / 1).
Normal scan exit policy still combines all selected checks. Diagnostics name
the invalid input and repair direction without a CLI traceback. The Python API
raises `ContractInputError` (a compatible subclass of `ContractError`) for
unmeasurable inputs. A project runner must catch it at its own process boundary
and print the message/exit 3; a library cannot suppress an arbitrary caller's
uncaught exceptions. Ruttla never launches that runner. Receipts establish
freshness and declared completeness, not execution authenticity, human review
or device acceptance.

Avoid hand-maintained lists for growing source trees: directory patterns
derive membership from the real working tree. Use exact lists only when each
path is intentionally mandatory. No generic warning is emitted for unlisted
siblings of exact sources: those siblings may be unrelated outputs or fixtures;
inferring their proof scope would create false positives.

References: [Git ls-files](https://git-scm.com/docs/git-ls-files),
[Python fnmatchcase](https://docs.python.org/3/library/fnmatch.html#fnmatch.fnmatchcase).
