# Changelog

## Capacitor plugin thenable and required-reason APIs (2026-10-07)

- Added `web.capacitor_plugin_resolved_from_promise` (warning, TOML). A
  Capacitor plugin proxy answers `then`; returning it from an async arrow or a
  `.then` hangs forever. Found on device in Merkma (blank app, all tests
  green). Four fixtures; fires on Merkma's broken revision, silent on the fix.
- Added `apple.required_reason_api_undeclared` (error, Python: resolves local
  SPM packages from `Package.swift`, including under `node_modules`, and
  compares their Swift sources with package and app privacy manifests, plus
  the manifest's presence in `project.pbxproj`). Missing local packages and
  macOS-only apps are unmeasured. Nine self-tests. Real positives: Merkma
  (`@capacitor/preferences` → `UserDefaults`) and eight iOS repos without any
  `PrivacyInfo.xcprivacy`.
- Added `web.capacitor_oauth_without_native_return` (entry was missing since
  2026-10-07, commit 4a722a8).
- Public guideline families `capacitor-plugin-thenable`, `required-reason-api`;
  catalogue regenerated.

## Brand candidates skip app plugin packages (2026-10-07)

- `_brand_candidates` no longer reads brand words from a `package.json` that carries a Capacitor (`capacitor.ios`/`.android`) or Cordova plugin manifest. A local plugin named `merkma-apple-sign-in` turned "apple" and "sign" into brand anchors, and every "Mit Apple fortfahren" became a `brand.hardcoded_in_display` finding (18 in Merkma, now 0, check still measured). Three new controls: plugin words pass, the real brand next to a plugin still fails, a nested package without plugin manifest still counts.

## Godot scene ownership ordering (2026-10-07)

- `godot.add_child_before_configure` no longer treats native `Node.owner` after parenting as late gameplay configuration. Owner must be an ancestor, so the old fix direction was invalid for PackedScene builders. Later custom configuration remains detected; three new healthy/defect controls.

## REST mock select projection (2026-10-06)

- Added `web.rest_mock_ignores_select` (warning, Python: the finding is the
  absence of `select` handling in a file, which the lookaround-free engine
  regex cannot express). A Playwright mock that answers `/rest/v1/` with full
  rows hides pages that read columns their query never selects. Three
  healthy/defect/unmeasured fixtures; measured against a real broken and fixed
  harness and one further real finding. Guideline section and public
  guideline family `rest-mock-select` added; catalogue regenerated.

## Godot CSV reference guard (2026-10-06)

- Extended `i18n.catalog_key_parity`: configured CSV catalogs are checked against literal `tr()` calls, scene text keys and explicit title/description/name/unlock key fields. Missing keys in both locales are detected even when catalog parity passes.
- Reference scope follows the nearest `project.godot` and configured valid CSV files. Unconfigured/dynamic/non-CSV references do not count as measured; existing catalog-parity coverage remains separate. Target code is never executed. Import freshness and rendered labels still require engine evidence.
- Nine added healthy/isolated defect/unknown controls; 645/645 total self-test probes. CLI tests verify four independent defects and cross-project isolation. Full suite: 297 tests, 294 passed and three optional skips. Full and changed-only scans: 13 PASS, 26 UNMEASURED, no blockers/advisories; generated catalog current. Existing unrelated working-tree changes are preserved.


Format: Keep a Changelog; versions: SemVer (ADR-0007). Rule IDs are listed
when added, changed or deprecated.
- Clean baseline plus this change: 636/636 self-test probes; 297 unit/contract tests (294 passed, three optional skips); strict full scan 14 PASS, 25 UNMEASURED, no blockers/advisories; generated catalogue current.


## [Unreleased] — 0.1.0 (public preview)

### Added
- `web.vite_define_secret`: Rust advisory for direct secret-like `process.env` replacements through `JSON.stringify(env.KEY)` in `loadEnv` configurations, including aliases without a `VITE_` prefix. Healthy, isolated defect and absent-scope controls; no claim about actual secret values or bundle usage.
- `ruttla rule test PATH…`: conformance kit for declarative rules (schema, ID clash, fixtures, untested exclusions, runtime budget), each rule loaded in isolation (P10-T009).

### Fixed
- `rpi.io_without_timeout`: no longer recommends the unsupported `timeout` constructor argument for asynchronous `subprocess.Popen`. Direct blocking convenience calls remain checked; Popen-only lifecycles stay unmeasured. Healthy, defect and unknown counterprobes added.
- `ruttla update`: reads releases via direct download URLs (`releases/latest/download`, `releases/download/nightly`) instead of the GitHub API, which allows 60 unauthenticated requests per hour and IP (`HTTP 403 rate limit exceeded` on a shared CI runner).
- `ruttla-engine`: evidence and `exclude on = "line"` are computed once per line, not per hit. Many hits on one long line (minified file) were hits × line length — 22 s for 100 KB.
- `ruttla-engine`: a pattern over the `regex` size limit is reported as too large, no longer as lookaround.
- `ruttla-engine`: `scope.extensions` and fixture paths with `\`, `:` or NUL are rejected at load. `..\x` and `C:/x` passed the `/`-only check and escape the fixture directory on Windows; an extension like `.py/../x` became a path in the kit's stress files.
- `web.hardcoded_endpoint`, `web.secret_reaches_browser`: one `pass` fixture per exclusion; the exclusions were untested.

### Changed
- `godot.balance_value_in_code`: exclude explicitly named touch width/height/size bounds from gameplay balance advisories; touch damage remains detected. Healthy geometry and isolated damage probes added.
- `godot.mobile_button_touch_target_too_small`: scope scenes to the nearest portrait project, accept normal configuration whitespace/comments, and distinguish declared minima from actual platform hit regions. Remove the invalid universal 96–120-unit recommendation.
- `godot.ui_container_masks_buttons`: replace name-based guesses with a bounded fresh Full-Rect sibling pattern. IGNORE passes through; PASS and z-index do not repair sibling input. Unknown geometry and dynamic setup remain unmeasured. Healthy/isolated defect and native Godot input probes validated.
- Split the final three Godot physics checks into their own module without changing function ASTs, rule IDs or behavior; the package monolith gate now passes. Remove a private app identifier from the public handover.
- `i18n.catalog_key_parity`: read template string values with plain text and simple member substitutions. A central brand in a greeting no longer hides an otherwise flat catalogue. Missing/extra keys remain findings; interpolation calls, nested templates, spreads and computed keys remain unmeasured. Target code is never executed.
- Integration guidance distinguishes a sample payload's demonstrated product branch from unconfirmed target-product contracts. Public provenance is anonymised and the hash guard extended; the temporary-file rationale no longer implies a legacy file-count limit on current .NET.
- `i18n.string_concatenation`: replace overlapping literal quantifiers with complete string tokens; a healthy 6 KB data literal previously stalled the scan. Long-literal and following-defect probes plus a bounded CLI regression prevent recurrence.
- `web.supabase_email_login_without_smtp`: parse TOML instead of regex fragments; enabled SMTP needs a nonempty host, commented `enabled=false` stays disabled, invalid configuration remains unmeasured. Diagnostic distinguishes local configuration from unmeasured remote SMTP and delivery.
- `i18n.orphan_catalog_keys`: zur Laufzeit zusammengesetzte Schlüssel in Template-Strings (`app.sort${x}`, `overview.${k}Hint`) zählen als benutzt, sofern das Blatt mindestens drei feste Zeichen trägt; reine Platzhalter sprechen nichts frei.
- `web.a11y_missing_label`: `<label for=…>`, umschließendes `<label>` und `data-i18n` an Knopf/Link (auch im Kind-Element) zählen als Beschriftung — der Fix-Text empfahl `<label for>`, der Check erkannte es nicht. `data-i18n` an Eingabefeldern bleibt ein Befund.
- `brand.hardcoded_in_display`: Swift PackageDescription module/product/dependency names are technical contracts; visible SwiftUI text in the same file remains checked. Includes separate healthy and broken probes.
- `i18n.catalog_key_parity`: supports flat static TS/JS locale constants in catalog paths, including typed dictionaries and member references. Dynamic, nested and JSON catalogs remain unmeasured; target code is never executed.
- `apple.project_settings`: `LastUpgradeCheck`-Schwelle auf Xcode 27.0 (2700) angehoben.

### Added
- `godot.collider_write_in_physics_signal`: bounded advisory for attached typed collider assignments in explicitly connected Area physics signals, including direct local helpers. Deferred writes/connections remain healthy; dynamic flags, awaits and closures remain unmeasured. Real cross-script pickup rewards need engine-backed project contracts. Healthy controls precede isolated disabled/shape/helper/signal defects; no target code execution.
- `apple.swiftui_sensitive_text_blur`: bounded advisory for title/summary/tagline Text rendered with a spoiler/shield/redact-controlled blur. Healthy controls and isolated title/summary probes verify the concrete source pattern; actual VoiceOver, transitions and metadata provenance remain unmeasured.
- `linux.tzdata_host_timezone`: offline advisory for an explicitly captured Linux host whose localtime link uses `Host` without a registered tzdata template. Healthy UTC/custom-template controls, isolated Host defects and unknown-input probes included. Read-only collector and reusable 1blu/OpenVZ/Tailnet setup procedure added; no automatic SSH or host execution during scans.
- `dotnet.temp_file_name_with_suffix` (Hinweis): `Path.GetTempFileName() + ".ext"` legt die .tmp-Datei an und lässt sie liegen. Belegt in einem WPF-Desktopprojekt (ICS-Export); Altstand rot, Fix grün.
- `dotnet.data_path_single_source` (Hinweis): `GetFolderPath(SpecialFolder.ApplicationData/LocalApplicationData/CommonApplicationData)` in mehr als einer Datei = Datenort ohne eine Quelle. Belegt in einem WPF-Desktopprojekt (11 Aufrufe in 8 Dateien, gefunden beim Umzug der Daten in den festen Installationsordner); Altstand rot, Stand mit `AppPaths` grün. `MyDocuments` u. ä. (Dialog-Startordner) zählen nicht.
- Neues Regelpaket `dotnet` (WPF): `dotnet.wpf_run_text_binding_without_mode`, `dotnet.wpf_commandparameter_literal_to_value_type`, `dotnet.wpf_style_set_twice`, `dotnet.wpf_thickness_two_args` (Fehler) sowie `dotnet.wpf_combobox_template_without_editable_part`, `dotnet.wpf_layouttransform_ui_scaling`, `dotnet.async_void_outside_event_handler` (Hinweise). Belegt in einem WPF-Desktopprojekt: Fehler, die sonst erst im Windows-CI-Build oder beim Öffnen der Ansicht auffallen. Avalonia-/MAUI-XAML und -C# bleiben außen vor; `dotnet` ist damit keine Plattform ohne Paket mehr.
- `web.supabase_loopback_on_remote_dev_host`: erkennt eine statische Browser-Supabase-Loopback-URL bei extern erreichbarem Vite-Dev-Host; Env-Priorität, lokale Gegenprobe und isolierte Defektproben enthalten. Laufzeit-Overrides und reale Portbelegung bleiben ungemessen.
- `web.local_asset_missing`: Verweise in HTML, CSS `url()` und Web-Manifest auf Bilder, Symbole, Schriften, die es nicht gibt. Wurzel wird je Ebene gesucht (public/, static/, Vite-Teilprojekte); Skripte und Stylesheets bleiben außen vor, weil sie oft erst im Build entstehen. `safe_by_default`. Gegen alle Web-Projekte unter /root geprüft: ein echter Befund, kein Fehlalarm.
- `web.i18n_target_has_children`: Element mit `data-i18n`/`data-brand-name`, das Kind-Elemente enthält — das Setzen des Textes löscht sie. Hinweis, weil ein Rückfalltext mit Auszeichnung absichtlich ersetzt werden darf.
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
- `apple.swiftui_sensitive_text_blur`: resolve simple aliases by lexical block, declaration order and shadowing rather than file-wide names. Nine healthy/broken probes cover sibling views, local/parameter shadows, conditional bindings and protocol declarations; this remains a bounded advisory, not Swift type/dataflow analysis.
- `gate.pipe_swallows_exit_status`: distinguish argument-selection pipelines from filters on the gate output, including nested and wrapped command substitutions. Four healthy and six broken probes preserve detection of real status loss; this remains a bounded syntax check.
- `web.touch_target_too_small`: decorative pseudo-elements and line heights no longer count as control dimensions; mixed selectors still measure real controls.
- `web.legal_pages_missing`: documentation mentions and code comments cannot satisfy legal-page presence. This remains a source-presence heuristic.
- `gate.reads_from_gitignored_artifact`: direct browser-report and screenshot writes are outputs. HTTP reference URLs and exact Python `SelfTestCase` AST spans are data; actual reads beside them, including on the same line, remain findings. Healthy and isolated broken cases cover each boundary.
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
