# STATUS

## SwiftUI Story-Text / Modulgrenze (2026-10-02)

- Neues Offline-Advisory `apple.swiftui_sensitive_text_blur`: Blur an Story-Text
  mit spoiler/shield/redact-Steuerung; kein gerenderter Accessibility-Nachweis.
  Im alten Appcode zwei Befunde, nach sicherer Projektion null. Gesundes Paket
  vor isoliertem Titel-/Summary-Defekt: Exit 0, beide Defekte im Strict-Modus Exit 1.
- 488/488 Selbsttestproben grün; neue Regel mit 11 gesund/defekt/ungemessen-Proben.
- Godot-Modulgrenze repariert: 18 Funktions-ASTs exakt unverändert, drei Regeln
  nach `physics.py`, gemeinsamer Helper separat; sieben Pakettests bestanden.
- Privaten Bezeichner aus lokalem HANDOVER neutralisiert. Regelkatalog aktuell;
  121 Unit-/Contracttests (120 grün, ein optionaler SARIF-Schema-Skip),
  Changed-only ohne Blocker und Diff-Check grün. Ruff ist nicht installiert;
  Lint ungemessen. Main-Sicherung im laufenden Block freigegeben.

## Katalogparität bei Templatewerten und Service-Handover (2026-10-01)

- Reale flache DE/EN-Kataloge mit einer Begrüßung wie
  `welcome: \`Hallo, ${BRAND.name}\`` waren vollständig ungemessen.
  Der Parser akzeptiert jetzt schlichte Templatewerte und einfache
  Member-Referenzen; Zielcode und importierte Markenwerte werden nicht ausgeführt.
  Funktionsaufrufe, verschachtelte Templates, Spreads und berechnete Schlüssel
  bleiben ungemessen. Bestehende Regel-ID/Exit-/Schweregradverträge erhalten.
- Intakter realer Katalog vor isolierter Schlüsselentfernung/-ergänzung geprüft:
  gesund Exit0, beide Einzeldefekte im Strict-Modus Exit1 mit konkretem Schlüssel.
  Acht neue Referenz-/Defekt-/Unknown-Proben;463/463 Selbsttestproben bestanden.
-119 Unit-/Contracttests:118 bestanden/ein optionaler SARIF-Schema-Skip.
  Zunächst veraltete Regeldoku reproduziert (Registry134, Katalog133),
  anschließend generiert und vollständige Suite erneut bestanden.
  `gen_rule_docs.py --check` und Diff-Check bestanden. Changed-only und
  strikter Selbstscan:je11PASS/0FAIL/22UNMEASURED/0Blocker.
  Ruff auf dem verwendeten Startpfad nicht vorhanden; Lint ungemessen.
- Wiederverwendbare Service-Guideline trennt Env-Startweg, nachträglich
  eingelesene Prozessvariablen, HTTP-Readiness, Verarbeitungsfreigabe und echten
  Provider-/Kosten-/Speichernachweis. Nur eigene Unit neu starten, Dienst beim
  Sessionabschluss erhalten. Keine spekulative Runtime-Regel hinzugefügt.
- Dieser Patch bleibt lokal; kein Commit/Push beauftragt oder ausgeführt.
  Vorherige Main-Sicherungen unten gehören zu früheren freigegebenen Blöcken.

## Main-Sicherung und Integrationsnachweis (2026-10-01)

- Nutzer hat Commit/Push des geprüften Ruttla-Arbeitsstands auf main freigegeben.
  Enthalten sind die vorhandenen Linux-, WPF-, SMTP-, Literal-, Shell- und
  Browser-Supabase-Erweiterungen; keine fremden Änderungen zurückgesetzt.
- Generische Guideline zu Testpaketen: vorhandene XML-/Auftragsstruktur nutzen,
  bestätigten Produkttyp von noch unbestätigten Vertragszweigen trennen.
  Kein neuer Offline-Check behauptet eine Providerannahme oder Produktion.
- Private Projektbezeichnungen vor öffentlichem Push anonymisiert, bestehende
  Provenienz-Denylist um einen Hash ergänzt. Gesund-/Defektprobe getrennt prüfen.
  GetTempFileName-Begründung gegen offizielle .NET-Doku korrigiert; keine
  allgemeine 65.535-Dateigrenze für aktuelle .NET-Versionen behaupten.
- Abschlussgates bestanden: 119 Unit-/Contracttests (118 bestanden, ein
  optionaler SARIF-Schema-Skip), 442/442 Selbsttestproben, Regeldoku und Ruff.
  Wheel/sdist gebaut und mit Twine strikt geprüft; Collector/Ablauf im sdist,
  Linux/WPF-Regeln im Wheel. Frische Installation außerhalb des Checkouts:
  133 Regeln, 442/442 Proben, gesundes Webpaket Exit 0/defektes Exit 1.
  Strikter Vollscan: PASS 11, FAIL/BLOCKING/ADVISORY 0, UNMEASURED 21,
  SKIPPED 0. Isolierte Provenienz-Gesund-/Defektprobe bestanden.
- Abschließend Changed-only und Diff prüfen, dann mit Nutzerfreigabe main
  sichern. Aktuellen Commit/Remote-Gleichstand per Git lesen; historische
  „kein Commit/Push“-Abschnitte unten bezeichnen deren damaligen Abschluss.

## Linux-VPS / tzdata-Host-Zeitzone (2026-10-01)

- `linux.tzdata_host_timezone` als enges Offline-Advisory ergänzt: expliziter
  Host-Snapshot, localtime-Link auf Host, keine passende registrierte Vorlage.
  Drei gesunde Referenzen vor vier isolierten Defektproben; zehn ungültige oder
  unvollständige Eingaben bleiben ungemessen. Eigene Host-Vorlage bleibt gesund.
- Read-only-Collector und wiederverwendbarer 1blu/OpenVZ/Tailnet-Ablauf unter
  `docs/operations/1blu-vps.md`. Keine IPs, Hostnamen, Keys oder privaten
  Projektzugänge im öffentlichen Ablauf. Collector explizit starten; normale
  Scans führen weder SSH noch Zielcode aus. Aufnahme im sdist ergänzt.
- Tatsächlicher gesunder VPS-Snapshot: CLI Exit 0; isoliertes Host-Link-Mutant
  Exit 1 im Strict-Modus; fehlende Vorlagen Exit 2. Keine Live-Sabotage.
- Prüfung: 442/442 Selbsttestproben, 119 Unit-/Contracttests (118 bestanden,
  ein optionaler Skip), Regeldoku aktuell, Python-Parse und Diff-Check bestanden.
  Wheel und sdist gebaut; neue Regel im Wheel, Collector und Ablauf im sdist
  enthalten.
  Vollscan, strikter Selbstscan und Changed-only ohne Befunde, jeweils 21
  ungemessen. Bei diesem ursprünglichen Gate-Abschluss noch kein Commit/Push;
  spätere Git-Sicherung siehe oben.

## WPF-Regelpaket `dotnet` (2026-10-01)

- Neues Paket `src/ruttla/checks/dotnet/wpf.py`, `dotnet` von „ohne Paket“ zu Paketplattform. Vier Fehler (Run.Text ohne Mode, CommandParameter-Literal an Werttyp-RelayCommand, Style doppelt, `new Thickness(a, b)`), drei Hinweise (ComboBox-Template ohne `PART_EditableTextBox`, gebundene LayoutTransform-Skalierung, `async void` außerhalb von Event-Handlern). WPF erkannt am XAML-Namespace bzw. `using System.Windows`; Avalonia/MAUI ausgenommen.
- Belege aus einem WPF-Desktopprojekt (Linux-Host, Windows-Build nur in CI). Grün-Referenz dort: 5 bestanden mit echten Einheiten, 2 ungemessen.
- Contract-Tests zu R-011 nutzen jetzt eine Kunstplattform statt `dotnet`; der Report-Pfad `platforms_without_pack` hat damit keinen eigenen Subprozess-Test mehr (kein echtes Beispiel vorhanden).
- Prüfung: 421/421 Selbsttestproben; 119 Unit-/Contracttests, 118 bestanden, ein optionaler Skip; Regeldoku aktuell. `ruff` auf diesem Host nicht installiert — Lint nicht gemessen. Kein Commit/Push; vorhandene parallele Änderungen unberührt.

## SMTP-Nachweis und lange Stringliterale (2026-09-30)

- Vorhandenen SMTP-Check gehärtet: gesunde Referenz zuerst; aktiv ohne Host,
  leerer Host und deaktiviert mit Inline-Kommentar waren reproduzierbare
  False-Greens. TOML-Parser und typgeprüfte Felder, ungültiges TOML ungemessen.
  Befund/Fixtext trennt lokale Konfiguration von Remote-SMTP, Limits/Zustellung.
- `i18n.string_concatenation`: echter Changed-only-Lauf hing über drei Minuten
  im Regex; isoliertes gesundes 6-KB-Datenliteral überschritt ebenfalls den
  Diagnose-Timeout. Vollständige Stringtokens statt überlappender Quantifizierer;
  echte Verkettung nach langem Literal und escaped Quotes bleiben erkannt.
  30-KB-CLI-Regression prüft Gesund-/Defektfall jeweils mit fünf Sekunden Budget.
- Prüfung: 407/407 Selbsttestproben; 119 Unit-/Contracttests, 118 bestanden und
  ein optionaler Skip. Regeldoku aktuell; strikter Selbstscan und Changed-only
  ohne Befunde (11 bestanden, 20 ungemessen). Im geänderten Zielprojekt:
  Changed-only ohne Befunde; lokaler SMTP-Hinweis separat triagiert, kein
  Rückschluss auf funktionierende oder defekte Remote-Zustellung.
- Vorhandene unabhängige Änderungen erhalten; kein Commit/Push. Keine
  Offline-Vollständigkeitsbehauptung für Runtime-Mail oder VPS-Sicherheit.

## Browser-Supabase auf Remote-Dev-Hosts (2026-09-30)

- Additiver Web-Check `web.supabase_loopback_on_remote_dev_host`: erkennt eine statische Dev-Konfiguration mit externem Vite-Host und Browser-Supabase auf Loopback. Die tatsächlich gemessene Env-Datei wird nach Vite-Priorität gewählt; Secret-Werte erscheinen nicht im Befund.
- Reale Fehlerklasse: Ein über einen anderen Rechner erreichbares Dev-Frontend schickte OAuth zu `127.0.0.1:54321`; dieser Port kann einem anderen lokalen Supabase-Projekt gehören. Gesunde Cloud-URL und rein lokaler Host bleiben grün, zwei isolierte Loopback-Defekte werden rot, fehlende Hostliste bleibt ausdrücklich ungemessen.
- Prüfung: 391/391 Selbsttestproben, 118 Unit-/Contracttests (117 bestanden, 1 optionaler Skip), Regeldoku aktuell; strikter Selbstscan und Changed-only ohne Befunde. Laufende Prozess-Overrides, Reverse-Proxys und Portbelegung sind keine Offline-Aussage. Kein Commit/Push.

## Shell-Status und Integrationsnachweise (2026-09-30)

- `gate.pipe_swallows_exit_status`: Pipelines in Argument-Substitutionen von Filtern auf der Gate-Ausgabe getrennt. Reale verschachtelte Dateiauswahl bleibt gesund; äußerer Filter, Ausgabezuweisung und Statusabfrage im Argument bleiben rot. Vier gesunde und sechs isoliert kaputte Proben; tatsächliche Bash-Ausführung erhält Exit 0 bzw. 37.
- Öffentliche Guideline ergänzt: MCP-Registrierung, tatsächliche Session-Tools und lesend geprüfter Zugriff auf die Zielressource sind getrennte Nachweise. Offline-Regeln messen weder Authentifizierung noch Mailzustellung; direkter offizieller API-Zugang ist ein eigenständig prüfbarer Weg.
- Prüfung dieses Arbeitsstands: 385/385 Selbsttestproben, 118 Unit-/Contracttests (117 bestanden, 1 optionaler Skip), Regeldokumentation aktuell. Strikter Selbstscan und Changed-only: jeweils 11 bestanden, 20 ungemessen, keine Befunde. Die Regel ist eine begrenzte Syntaxprüfung; dynamischer Shell-Kontrollfluss und Heredocs bleiben offen. Vorhandene unabhängige Änderungen erhalten; kein Commit/Push.

## Server-only-Grenze (2026-09-30)

- Neue explizite Browser-Importgrenze: reale private Matching-/Zitatmodule vor Verlagerung erkannt. Laufzeitimporte, Barrel-Exports, dynamische Literalimporte und Worker-URLs werden verfolgt; Typimporte ausgenommen. Keine IP-Klassifikation aus Namen.
- 15 gesunde/isoliert kaputte Proben; ungeklärte Framework-/Alias-/berechnete Einstiege bleiben ungemessen. Ergänzende echte Build-Grenze ist Aufgabe des Zielprojekts; gesunder Build und isolierter privater Import im Zielprojekt separat geprüft.
- Artefakt-Gate: HTTP-Referenzadressen und AST-genau begrenzte `SelfTestCase`-Aufrufe sind keine lokalen Dateizugriffe. Echte Zugriffe daneben bleiben rot, auch auf derselben Zeile. Isolierte Gesund-/Defektproben ergänzt.
- Öffentliche wiederverwendbare Guideline und Katalogzuordnung ergänzt. Letzter Gesamtbestandslauf: 377/377 Gegenproben; 118 Unit-/Contracttests, 117 bestanden und ein optionaler Skip. Keine eigenen Commits/Pushes; parallele Aktualisierungen im gemeinsamen Repository erhalten.

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
