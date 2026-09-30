# Changelog

Format: Keep a Changelog; versions: SemVer (ADR-0007). Rule IDs are listed
when added, changed or deprecated.

## [Unreleased] — 0.1.0 (public preview)

### Changed
- `i18n.orphan_catalog_keys`: zur Laufzeit zusammengesetzte Schlüssel in Template-Strings (`app.sort${x}`, `overview.${k}Hint`) zählen als benutzt, sofern das Blatt mindestens drei feste Zeichen trägt; reine Platzhalter sprechen nichts frei.
- `web.a11y_missing_label`: `<label for=…>`, umschließendes `<label>` und `data-i18n` an Knopf/Link (auch im Kind-Element) zählen als Beschriftung — der Fix-Text empfahl `<label for>`, der Check erkannte es nicht. `data-i18n` an Eingabefeldern bleibt ein Befund.
- `brand.hardcoded_in_display`: Swift PackageDescription module/product/dependency names are technical contracts; visible SwiftUI text in the same file remains checked. Includes separate healthy and broken probes.
- `i18n.catalog_key_parity`: supports flat static TS/JS locale constants in catalog paths, including typed dictionaries and member references. Dynamic, nested and JSON catalogs remain unmeasured; target code is never executed.
- `apple.project_settings`: `LastUpgradeCheck`-Schwelle auf Xcode 27.0 (2700) angehoben.

### Added
- `web.legal_placeholder`: Pflichtseiten (erkannt an `<title>`/`<h1>`: Impressum, Datenschutz, AGB, Terms …) mit unausgefülltem `[Platzhalter]`, „Lorem ipsum" oder Entwurfsvermerk („Entwurf.", „Noch auszufüllen:"). Code, Script und Fußnoten bleiben still. `safe_by_default`.
- `sql.plpgsql_outside_block`: `exception when` außerhalb eines `$$`-Rumpfs in PostgreSQL-Projekten — Syntaxfehler, der in Testskripten wie ein erwarteter Fehler aussieht. Oracle-PL/SQL ohne PostgreSQL-Merkmal bleibt `unmeasured`. `safe_by_default`.
- `web.server_only_reaches_browser`: follows explicit server-only modules from HTML runtime entries; local imports, barrels, literal dynamic imports and worker URLs, with healthy/broken probes and an explicit partial-graph limitation.
- `web.textarea_draft_memory_only`: bounded advisory for editable React textareas held directly in `useState` without a matching visible Web Storage save/restore path. Includes isolated write, read, storage-key and comment mutations; indirect hooks and IndexedDB remain unmeasured and require real reload/lifecycle tests.
- `apple.swiftui_async_data_focus_write`: advisory for direct FocusState assignments after `await` in load/fetch/refresh methods. Flags data completions that can remove or steal focus after navigation; explicit synchronous return actions and data-only loading stay green. Cross-method flows and runtime focus are not measured.
- `apple.swiftui_invisible_focus_target`: advisory for directly focusable, transparent 1-pixel SwiftUI targets; visible buttons, non-focusable geometry and disabled focus stay green.
- `apple.release.scheme_test_action_empty`: advisory when a shared scheme builds a project with XCTest targets for testing but has no active reference to one in its TestAction. This checks the local scheme, not remote Xcode Cloud workflow actions or destinations.
- `apple.platform_conditional_type_used_unguarded`: ein Typ, der nur innerhalb von `#if os(...)` deklariert ist, wird in einem Mehrplattform-Target auf einer anderen Plattform sicher kompiliert benutzt (`Cannot find '…' in scope`). Unbekannte Bedingungen (DEBUG, canImport) bleiben still; Einzelplattform-Projekte sind `unmeasured`.
- `apple.package_resolved_not_committed`: Xcode-Projekt mit Remote-Swift-Paket ohne `Package.resolved` am Xcode-Pfad oder mit `.gitignore`-Ausschluss (`*.resolved`); Xcode Cloud bricht sonst ab.
- `i18n.catalog_key_parity`: Apple-`<lang>.lproj/*.strings`-Kataloge müssen je Datei dieselben Schlüssel tragen; Apple zeigt sonst still den rohen Schlüssel. Nur eine Sprache ist `unmeasured`, nicht bestanden.
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
- `brand.*` ermittelt den Markennamen jetzt auch aus Xcode-Projekten (`INFOPLIST_KEY_CFBundleDisplayName`, wörtliches `PRODUCT_NAME`, `CFBundleDisplayName` in Info.plist); auf Apple-Projekten waren beide Checks bisher immer `unmeasured`. Entwicklerausgaben (`print`, `NSLog`, `logger.*`, …) und `@testable import` gelten nicht als Anzeigepfad.
- `i18n.orphan_catalog_keys` und `i18n.literal_in_markup` erkennen Apple-Stringskataloge (`*.lproj/*.strings`); `literal_in_markup` meldet SwiftUI-Literale (`Text`, `Button`, `Label`, `.navigationTitle`, …), die kein Katalogschlüssel sind. `Text(verbatim:)`, Interpolation, Kürzel und `#Preview` bleiben ausgenommen.
- `README.md` / `CHANGELOG.md` of the scanned project are measured (docs rules).
- `project.platform` now forces a pack on (additive); `dotnet` rejected there (no pack).
- Reported paths are always `/`-separated; output is UTF-8 on every OS.
- Rule guideline strings of `docs.*`, `media.*`, `python.*` point to `docs/GUIDELINES.md`.
- Broken stdout pipe exits 3 instead of a traceback with exit 1.

### Fixed
- `web.touch_target_too_small`: decorative pseudo-elements and line heights no longer count as control dimensions; mixed selectors still measure real controls.
- `web.legal_pages_missing`: documentation mentions and code comments cannot satisfy legal-page presence. This remains a source-presence heuristic.
- `gate.reads_from_gitignored_artifact`: direct browser-report and screenshot writes are outputs; actual reads on the same line remain findings.
- Catalog metadata covers the localization guideline; the historical healthy Godot projection reflects the existing main scene without weakening broken cases.
- `apple.unguarded_module_import`: recognize QuartzCore and MetalKit as Apple system frameworks; healthy framework imports and an isolated unknown-module mutation are covered.
- `protocol.version_bump_without_fallback`: Swift enums now require their own explicit Codable/Decodable conformance (including same-file extensions). An unrelated decoder no longer flags UI enums or namespace enums; CodingKey enums are excluded. The fix advice now requires a decoding fallback and an unknown-value test instead of promising that an Unknown case alone changes synthesized decoding.
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
