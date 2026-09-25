# Changelog

Format: Keep a Changelog; versions: SemVer (ADR-0007). Rule IDs are listed
when added, changed or deprecated.

## [Unreleased] — 0.1.0 (public preview)

### Added
- `web.search_selection_resets_category`: detects search result item selections that clear the search query without synchronizing the active category or tab state, causing the item to disappear immediately after selection.
- `godot.mobile_renderer_forward_plus`, `godot.mobile_orientation_mismatch`, `godot.ios_export_preset_missing_signing`: mobile renderer and export configuration checks for Godot.
- `python.compare_digest_unicode_password`: advisory check for password-like Python strings passed directly to `hmac`/`secrets.compare_digest`, which raises on non-ASCII input; includes healthy and broken Unicode probes.
- Explicit `ruttla update` command installs the current GitHub `main` revision in the active Python environment through pip; scans stay offline and source checkouts are not pulled or modified.
- `web.empty_catch_block`: detects empty JavaScript/TypeScript catch blocks that silently discard exceptions; advisory only because intentional best-effort catches can be valid.
- Package `ruttla` (console script, `python -m ruttla`); `master_gate.py` and `core.py` remain as shims.
- `--version`, `--explain ID`, `--list --format json|markdown`, `--format sarif`, `--sarif FILE`.
- SARIF 2.1.0 reporter; JSON report schema 1.1 (`schemas/report.schema.json`) with
  `blocking`, `blocking_findings`, `advisory_findings`, `coverage`, `tool_name`,
  `tool_version`, `platforms_without_pack`; agent header `SCHEMA/BLOCKING/ADVISORY/SKIPPED`,
  trailing `BLOCKING=` field, `SKIPPED` and `NO_PACK` lines.
- Profile name `.ruttla.toml` (legacy `.qualitygate.toml` still read), `config_version = 1`.
- Rule metadata (tags, references, lifecycle, `introduced_in`), public guideline mapping,
  generated `docs/RULES.md`.
- CI matrix, coverage floor, golden baseline, provenance guard, fuzz tests, benchmark.
- Baseline catalog: all 90 rules `introduced_in = 0.1.0` (see `tests/golden/check_ids.txt`).

### Changed
- `README.md` / `CHANGELOG.md` of the scanned project are measured (docs rules).
- `project.platform` now forces a pack on (additive); `dotnet` rejected there (no pack).
- Reported paths are always `/`-separated; output is UTF-8 on every OS.
- Rule guideline strings of `docs.*`, `media.*`, `python.*` point to `docs/GUIDELINES.md`.
- Broken stdout pipe exits 3 instead of a traceback with exit 1.

### Fixed
- Frozen golden projections now compare only historical rule IDs; additive checks no longer require rewriting the legacy baseline.
- Profile `exclude` globs were ignored by directory lookups (platform detection, apple packs).
- Oversize files were skipped silently (now `coverage.files_skipped`).
- Quadratic backtracking and wrong line numbers after comment blocks in
  `apple.mainactor_missing_on_observable`, `godot.balance_value_in_code`,
  `python.telegram_token_log_leak`, `protocol.*`, `rpi.no_restart_policy`,
  apple release pbxproj parsing and raspberry platform detection.

### Removed
- Private project names, a real bundle ID and a probable real Team ID from code and docs.

### Maintainer
- `autopush.sh` moved to `scripts/maintainer/` (not part of the contributor flow).
