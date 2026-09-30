# STATUS

## Server-only-Grenze (2026-09-30)

- Neue explizite Browser-Importgrenze: reale private Matching-/Zitatmodule vor Verlagerung erkannt. Laufzeitimporte, Barrel-Exports, dynamische Literalimporte und Worker-URLs werden verfolgt; Typimporte ausgenommen. Keine IP-Klassifikation aus Namen.
- 14 gesunde/isoliert kaputte Proben; ungeklärte Framework-/Alias-/berechnete Einstiege bleiben ungemessen. Ergänzende echte Build-Grenze ist Aufgabe des Zielprojekts.
- Öffentliche wiederverwendbare Guideline und Katalogzuordnung ergänzt. Kein Commit/Push.

## Entwurfswiederherstellung (2026-09-30)

- Neues Advisory `web.textarea_draft_memory_only`: echte flüchtige CV-/Profiltext- und Antwortfelder vor dem Fix erkannt; direkte useState-Textareas und passende Web-Storage-Lese-/Schreibpfade werden eng geprüft. Indirekte Hooks/IndexedDB bleiben bewusst ungemessen.
- Gesunde Referenz zuerst; fehlendes Speichern, fehlendes Wiederherstellen, falscher Schlüssel, fremdes Feld und Kommentar-Nachweis jeweils isoliert rot. Read-only-Anzeigen und indirekte Hooks werden nicht als geprüfte Wiederherstellung ausgegeben.
- Fehlerklasse durch echten Dev-WebSocket-Abbruch mit nachfolgendem automatischem Reload reproduziert. Die App-Reparatur wurde gesondert im realen Browser über Reload, Browser-Neustart, konkurrierende Tabs und tatsächlichen Quota-Fehler geprüft; keine künstlichen Bewerber-/Providerantworten.
- Öffentliche Web-Guideline um Entwurfsumfang, Save/Restore, Fehler/Löschung und Lifecycle-Gates ergänzt. Aktueller Gesamtbestand beim Lauf: 333/333 Gegenproben; 110 Unit-/Contracttests (109 bestanden, 1 optionaler Skip). Andere gleichzeitig vorhandene Änderungen bleiben erhalten.

## Web-/Katalogprüfung (2026-09-30)

- `web.touch_target_too_small`: dekorative Pseudoelemente und `line-height` sind keine realen Trefferflächen; gemischte Selektoren und kleine echte Controls bleiben erkennbar.
- `web.legal_pages_missing`: Markdown-Nennungen und Kommentare belegen keine Pflichtseiten. Quellenpräsenz bleibt eine Heuristik, keine rechtliche oder Browserprüfung.
- `gate.reads_from_gitignored_artifact`: direkt geschriebene Browserberichte/Screenshots gelten als Ausgabe; echte Reads auf derselben Zeile bleiben Befunde.
- `i18n.catalog_key_parity`: flache statische TS/JS-Locale-Konstanten ergänzt. Tatsächlicher DE/EN-Katalog bestanden; isoliert entfernter EN-Schlüssel erkannt. Keine Ausführung von Zielcode; dynamische/verschachtelte und JSON-Kataloge bleiben ungemessen.
- Katalog-Rationale zu Lokalisierung ergänzt; ausschließlich den historischen Healthy-Befund einer vorhandenen Godot-Szene korrigiert; private Roadmap-Bezeichnungen anonymisiert.
- Aktueller Gesamtbestand einschließlich separat vorhandener Apple-Erweiterung: 317/317 Gegenproben, 110 Unit-/Contracttests (109 bestanden, 1 optionaler Skip); Changed-only ohne Blocker, 11 bestanden/18 ungemessen. Kein Commit/Push dieses Arbeitsblocks.

## Fokusprüfung (2026-09-30)

- Additiver Check `apple.swiftui_async_data_focus_write`: direkte FocusState-Zuweisung nach `await` in Datenmethoden als Advisory. Erkennt zwei reale Bibliotheks-Refreshstellen; reine Datenladung, synchrone Rückkehr und gleichnamiger normaler State bleiben unbeanstandet.
- `self.`-Zuweisungen und Zuordnung zum konkreten Swift-Typ ergänzt; acht isolierte Gegenproben verhindern den Fehlalarm bei gleichnamigem gewöhnlichem State in einer anderen View.
- `brand.hardcoded_in_display`: technische Swift-Package-Modul-/Produktnamen bleiben unbeanstandet; sichtbarer SwiftUI-Markentext im selben Manifest wird weiterhin gemeldet (zwei neue Gegenproben).
- Prüfung dieses Fokus-Arbeitsstands: zunächst 330/330, abschließend 345/345 Selbsttestproben einschließlich gleichzeitig ergänzter Regeln; 110 Unit-/Contracttests beim Fokuslauf (109 bestanden, 1 optionaler Skip). Changed-only abschließend ohne Blocker, mit einem Advisory in der fremden server-only-Regelerweiterung (Referenz-URL als Build-Artefakt fehlklassifiziert). Eigene Fokus-/Package-Regeln bestanden. Kein Commit/Push dieses Fokus-Arbeitsblocks wegen gleichzeitig bearbeiteter unabhängiger Änderungen; diese bleiben erhalten.
- Keine Behauptung einer vollständigen Swift-Datenflussanalyse oder Geräteprüfung; indirekte Helper/Bindings und tatsächliche Modalität bleiben offen.

## Validierte Korrekturen (2026-09-29)

- Zwei additive Apple-Advisories: `apple.swiftui_invisible_focus_target` erkennt direkt fokussierbare transparente 1-Pixel-Ziele; `apple.release.scheme_test_action_empty` erkennt fehlende/leer gelassene Testaktionen im Shared Scheme bei vorhandenem Test-Target.
- Reale Gegenprobe: erster Check meldet drei Fokusflächen in einer tvOS-App; das Shared Scheme mit aktivem XCTest-Target bleibt grün. Xcode-Cloud-Aktionen und Zielplattformen sind remote und durch diese Offline-Regel nicht messbar.
- Prüfung: 110 Unit-/Contracttests (109 bestanden, 1 optionaler Skip), 283/283 Selbsttestproben, Regeldokumentation aktuell, strikter Selbstscan und `ruttla --changed-only --format agent` ohne Blocker. Main-Push am 29.09. vom Nutzer freigegeben.

## Validierte Korrekturen (2026-09-28)

- `protocol.version_bump_without_fallback`: Swift-Konformität dem konkreten Enum zuordnen; fremde JSONDecoder/Codable-Structs und CodingKeys lösen keinen falschen Befund mehr aus. Decoder-Fallback statt bloßem Unknown-Case empfehlen; Cross-file-/Laufzeitgrenzen ausdrücklich benennen.
- `apple.unguarded_module_import`: QuartzCore und MetalKit als Apple-Systemframeworks erkannt; gesunde Imports und isolierte Fremdmodulmutation ergänzt.
- Prüfung: 110 Unit-/Contracttests, 109 bestanden und 1 bestehender optionaler Skip; 259/259 Selbsttestproben für 104 Checks; generierte Regeldokumentation aktuell. Kein Commit/Push.

## Current Phase
P05 abgeschlossen (P00–P05 umgesetzt). P06 aktiv; Repository ist seit 2026-09-24 öffentlich.

## Last Completed (2026-09-24)
- P00 Anonymisierung, History-/Provenienz-Audit, Apache-2.0, Golden-Baseline
- P01 Verträge: Blocking-Modell, Report-Schema 1.1, Profil-Alias, Plattform-Registry, Regel-Metadaten
- P02 Paket `ruttla`, Shims, Aufteilung der Regelmodule, README-Ausschluss, Skip-Diagnose
- P03 CI-Matrix, Coverage-Floor, Benchmark, Fuzz-Tests, Regex-Performance-Fix
- P04 SARIF, --version/--list json/--explain, Workflow-Beispiel (ADR-0009)
- P05 README (en/de), CONTRIBUTING, SECURITY, CoC, CODEOWNERS, Templates, CHANGELOG, RULES.md
- LESSONS_LEARNED.md
- `web.empty_catch_block`: advisory Check für leere JS/TS-catch-Blöcke, mit broken/healthy Proben und False-Positive-Hinweis
- `ruttla update`: explizites pip-Update von GitHub `main`; normale Scans bleiben offline
- `python.compare_digest_unicode_password`: echte Unicode-Passwort-Fehlerstelle erkannt, UTF-8-kodierten Fix unbeanstandet; Golden-Baseline berücksichtigt weiter nur historische Checks

## Next Unblocked Task
- P06-T001 Finding-Fingerprint (Basis `ruttla/v1` in SARIF existiert)
- Performance: restliche Hotspots (siehe docs/PERFORMANCE_BUDGET.md)

## Blockers (nur für Veröffentlichung)
- P08: neue, bereinigte Git-Historie vor Visibility=Public (docs/audits/HISTORY_AUDIT_2026-09-24.md)
- P04-T003: Code-Scanning-Upload braucht ein öffentliches Fixture-Repo oder GitHub Code Security
- Trademark-Kurzcheck für „Ruttla“ vor 0.1.0

## Validation State
- unit/contract/golden/fuzz: 107 Tests grün (lokal)
- self-test: 216/216 Proben, 92/92 Checks beide Richtungen
- self-scan strict: Exit 0
- coverage: 87 % gesamt (Kern 86 %), CI-Floor 86 %
- wheel/sdist: gebaut, frische Installation getestet

## Last Updated
2026-09-24
