# Lessons Learned — welche Fehler wie verhindert worden wären

Stand: 2026-09-24. Quelle: alle im Repo belegten Befunde (Check-Docstrings,
Commit-Historie, README, CLAUDE.md) plus die Befunde der Public-Scale-Umsetzung.
Private Projektnamen sind anonymisiert. Jede Zeile nennt den Fehler, die
Maßnahme, die ihn früher abgefangen hätte, und den Check, der das heute
tokenfrei erledigt.

**Kurzfassung der Muster:**

1. **Grün ist keine Messung.** Fast jeder teure Fehler hatte einen Prüfschritt,
   der grün meldete, ohne gemessen zu haben: Pipe-Status, null Tests,
   Dateiweit-Suche statt Target, still übersprungene Dateien, ignorierte
   Konfiguration.
2. **Der Build ist nicht der Abnehmer.** Store-Upload, Runtime, Hardware und
   Logs finden Fehler, die lokal fehlerfrei bauen. Diese Klassen brauchen
   eigene statische Gates.
3. **Eigenschaft statt Bauform.** Checks, die einen Namen, eine Datei oder ein
   Muster statt der Eigenschaft suchten, waren falsch grün oder falsch rot.
4. **Jeder Check braucht beide Richtungen.** Die meisten Gate-Fehler fand die
   Gegenprobe, nicht der Einsatz.

---

## 1 · Prozess und Gate-Infrastruktur

| # | Fehler (belegt) | Wie verhindert | Heute abgefangen durch |
|---|---|---|---|
| 1.1 | Gemeldeter Compilerfehler wurde im fremden Projekt „repariert“ (5 Dateien), statt einen Check zu bauen — derselbe Fehler wäre im nächsten Projekt wieder aufgetreten | Fester Ablauf: Ursache belegen → bestehenden Check prüfen → Check mit beiden Sabotage-Richtungen → Self-Test → gegen echten Fehlerzustand messen → erst dann Fix | `CLAUDE.md` (Reihenfolge-Tabelle), `CONTRIBUTING.md`, PR-Template |
| 1.2 | Drei Sabotage-Läufe meldeten alle `EXIT: 0`, weil `gate \| tail` den Status von `tail` liefert | Status zuerst in eine Variable, dann filtern | `gate.pipe_swallows_exit_status` (hart ohne Profil), CI-Dogfood-Job |
| 1.3 | Test-Runner wertete „null Tests gefunden“ als Erfolg | Dritter Ausgang: null gemessen ist rot | `gate.runner_accepts_zero_tests`; Runner selbst: Exit 2 |
| 1.4 | Gate las aus einem git-ignorierten Build-Artefakt und prüfte damit den letzten Build statt die Quelle | Gates lesen die Quelle oder erzeugen das Artefakt selbst | `gate.reads_from_gitignored_artifact` |
| 1.5 | Der Fix-Vorschlag eines Checks empfahl `.system(size:relativeTo:)`, eine API, die es nicht gibt; der PASS-Selbsttest nutzte genau diesen kaputten Aufruf als „richtig“ | Jeder `fix:`-Text wird gegen die Doku geprüft; PASS-Proben müssen übersetzbaren Code enthalten | Self-Test prüft alle Fix-Texte gegen bekannte Nicht-APIs; `apple.system_font_relative_to` |
| 1.6 | Compiler meldete **eine** Fundstelle, im Projekt standen **fünf** identische | Nach jedem Einpflegen `grep -rn` über die Eigenschaft; Gesamtzahl melden | Gate misst alle Dateien, nicht nur die gemeldete |
| 1.7 | Zwei Compilermeldungen (`Extra argument 'relativeTo'` + `Cannot infer contextual base`) für **eine** Ursache | Folgefehler in der Meldung nennen statt zweiten Check bauen | `apple.system_font_relative_to` nennt beide Texte |
| 1.8 | Versionsschwelle `LastUpgradeCheck < 1600` fest getippt, Toolchain stand auf Xcode 26.4 — jedes Projekt hatte „Update to recommended settings“, das Gate schwieg | Schwellen als benannte Konstante mit Messung im Kommentar | `apple.project_settings`, Regel in `CLAUDE.md` |
| 1.9 | Roter Befund, aber `EXIT: 0` — Check war fälschlich weich | `safe_by_default=True` genau dann, wenn ein Falsch-Positiv ausgeschlossen ist | explizites Feld `blocking` je Befund (Report 1.1) |
| 1.10 | Ein Lauf meldete 5825 Befunde, 99,8 % aus einem entpackten Fremdarchiv — die 13 echten gingen unter | `exclude`-Globs im Profil; `.gitignore` wird bewusst nicht gelesen | `.ruttla.toml` `[gate] exclude` |
| 1.11 | Raspberry-Erkennung kannte `import serial` nicht; der Check schon — ein echter Verstoß meldete grün, weil das Pack nie lief | Erkennungsliste und Check-Liste müssen übereinstimmen | Kommentar-Vertrag in `platforms.py`, Golden-Fixtures je Pack |
| 1.12 | Godot-Balance-Regex ohne `MULTILINE` traf nie (`^` nur am Dateianfang) — die Gegenprobe fand es | Jede Regel braucht eine FAIL-Probe | Self-Test (beide Richtungen Pflicht) |

## 2 · Apple / App Store

| # | Fehler (belegt) | Wie verhindert | Check |
|---|---|---|---|
| 2.1 | Upload einer macOS-App an App Store Connect abgelehnt: keine App-Kategorie | `LSApplicationCategoryType` im **App-Target** prüfen (Plist **oder** `INFOPLIST_KEY_*`) | `apple.release.app_category_missing` (hart) |
| 2.2 | Entitlements ohne `com.apple.security.app-sandbox`, obwohl Unterschlüssel da waren | Wert des Schalters messen, nicht Existenz der Datei | `apple.release.app_sandbox_missing` (hart) |
| 2.3 | `DEVELOPMENT_TEAM` im App-Target leer; der bestehende `apple.project_settings` blieb grün, weil ein dateiweites `re.search` den Schlüssel in einem anderen Target fand (**bestehender Check mitschuldig**) | Prüfbereich ist die Target-Konfiguration, aufgelöst über PBXNativeTarget → XCConfigurationList | `apple.release.signing_team_missing` |
| 2.4 | Kein `CFBundleDisplayName` — App hieß im Dock wie das Produkt | Anzeigenamen je App-Target prüfen | `apple.release.display_name_missing` |
| 2.5 | String Catalog wuchs von 27 auf 52 Schlüssel, 47 blieben unübersetzt | Vollständigkeit gegen die Sprachen des Katalogs selbst messen | `apple.release.xcstrings_incomplete` |
| 2.6 | Plattformerkennung las `SDKROOT` nur im Target → echte macOS-App galt als plattformlos (UNMEASURED statt FAIL) | Alle Build-Konfigurationen lesen (Projektebene erbt) | `_release_common` |
| 2.7 | `MACOSX_DEPLOYMENT_TARGET` als Mac-Merkmal hätte jede iOS-App rot gemacht (Catalyst-Beiwerk) — falsch-positives **hartes** Gate | Maßgeblich ist das SDK, gegen das gebaut wird; an zwei iOS-Apps gegengeprobt | `apple.release.app_sandbox_missing` |
| 2.8 | Generierte Info.plist war in der Quelle nicht sichtbar → wäre „bestanden“ gewesen | Nicht auflösbar = UNMEASURED, nie PASS | alle `apple.release.*` |
| 2.9 | Grauer Balken verdeckte Formularfelder (NavigationSplitView ohne `.navigationTitle`) | Detail-Ansicht braucht einen Titel | `apple.splitview_detail_without_navigation_title` |
| 2.10 | SMB-Mounts erschienen im Finder, obwohl der Mountpunkt unter `~/Library` lag | Sichtbarkeit hängt an `-o nobrowse`, nicht am Pfad (`mount_smbfs(8)`) | `apple.smb_mount_without_nobrowse` (hart) |
| 2.11 | Wahrscheinlich echte Apple Team-ID stand in einem Selbsttest-Fixture | Fixtures nur mit Platzhaltern (`ABCDE12345`) | `tests/test_provenance.py` (gehashte Deny-List) |

## 3 · Game-Engines

| # | Fehler (belegt) | Wie verhindert | Check |
|---|---|---|---|
| 3.1 | 20 Fußgänger im Baum, 0 in Bewegung: Werte nach `add_child()` gesetzt, `_ready()` hatte schon gelesen | Werte **vor** `add_child()` setzen | `godot.add_child_before_configure` |
| 3.2 | 18 Raycasts, null Treffer — Abfrage vor dem ersten Physikschritt, Prüfung meldete „alles frei“ | `await get_tree().physics_frame` vor der Abfrage | `godot.physics_query_before_first_step` |
| 3.3 | 180 gleichlautende Warnungen pro Frame verdeckten einen Bug in einem grünen Lauf | Nur beim Wechsel melden | `godot.warning_in_hot_loop` |
| 3.4 | Pawn ohne Mesh: `FObjectFinder` schlug still fehl, zehn hart getippte `/Game/…`-Pfade | Else-Zweig mit lautem Fehler | `unreal.objectfinder_silent_failure` |
| 3.5 | Figur lief durch die Stadt und blieb in T-Pose (modulare Meshes ohne Leader Pose) | `SetLeaderPoseComponent` | `unreal.modular_mesh_without_leader_pose` |
| 3.6 | `ApplyDamage` hatte außerhalb der Tests keinen Aufrufer; das Vertragsgate war grün, weil der Name als String existierte (**Gate mitschuldig**) | Aufrufer außerhalb von Tests zählen | `unreal.definition_without_caller` |
| 3.7 | `OnComponentHit` feuerte nie — sah aus wie „kein Crash“ | `SetNotifyRigidBodyCollision(true)` | `unreal.hit_binding_without_notify` |

## 4 · Python-Dienste, Web, Medien

| # | Fehler (belegt) | Wie verhindert | Check |
|---|---|---|---|
| 4.1 | Stop-Loss-Prüfung 255× verworfen (Schwesterprojekte 177× / 119×): APScheduler-Default `misfire_grace_time` = 1 s | Toleranz explizit setzen, Blockaden im Event-Loop vermeiden | `python.apscheduler_misfire_default` |
| 4.2 | 1,37 Mio. Logzeilen mit Telegram-Bot-Token im Klartext (`httpx` loggt URLs auf INFO) | `httpx`/`urllib3`-Logger drosseln | `python.telegram_token_log_leak` |
| 4.3 | EU-Signal rechnete mit dem Kurs von vorgestern: Yahoo liefert die letzte Kerze mit `close=None`, `dropna` warf sie weg | Aus `meta.regularMarketPrice` auffüllen | `python.yahoo_chart_last_bar_dropped` |
| 4.4 | Retry wiederholte `POST /orders` nach Timeout — mögliche Doppelorder | Nur idempotente Methoden wiederholen | `python.http_retry_non_idempotent` |
| 4.5 | Wechselkurs fiel monatelang still auf `1.05` zurück (echt 1,146) | Laut scheitern statt Notwert | `python.hardcoded_fx_fallback` |
| 4.6 | Fehlalarme im Einsatz (Monorepo-Grenze, Betrags- statt Kursfunktion) | Jeden Fehlalarm als eigene gesunde Probe einpflegen | Proben in `python/services.py` |
| 4.7 | Drei Grid-Spalten wurden 285,5 / 251,2 / 251,2 px statt gleich breit | `minmax(0, 1fr)` statt `1fr` | `web.grid_fr_without_minmax` |
| 4.8 | Labor-Flag-Check meldete `buildCheckerLabel`/`mirrorLabel` | Bezeichner an Wortgrenzen messen, nicht Teilstrings | `lab.flag_not_statically_evaluable` |
| 4.9 | 1042 von 1045 `service_role`-Treffern kamen aus generierten Dumps | Nur Wertzuweisungen melden | `secrets.hardcoded_credential` |
| 4.10 | Limiter hob den Mix trotz `limit` wieder auf 0 dB | `level=disabled` | `media.ffmpeg_limiter_auto_level` |
| 4.11 | TTS lieferte 655 s Audio für 6,96 s Zielzeit | Harte Dauerschranke vor dem Mix | `media.tts_without_duration_guard` |
| 4.12 | Englischer Untertitel nach dem Mux als Deutsch markiert | Streams und Sprachen nach dem Mux prüfen | `media.mux_without_stream_probe` |
| 4.13 | `Start-Process -ArgumentList` zerlegte Freitext an Leerzeichen | Eigenes Quoting oder argumenttreuer Aufruf | `media.powershell_text_argument_split` |

## 5 · Befunde der Public-Scale-Umsetzung (2026-09-24)

| # | Fehler | Wie verhindert | Heute abgefangen durch |
|---|---|---|---|
| 5.1 | `README.md` und `CHANGELOG.md` waren global ausgeschlossen — die Docs-Checks konnten die öffentliche Doku eines Projekts **nie** messen (Self-Scan: „Null Markdown-Dateien“) | Ausschluss nach Eigenschaft (Marker `<!-- ruttla:rule-docs -->`), nicht nach Dateiname | ADR-0010, Vertragstest |
| 5.2 | Dateien über `max_file_bytes` wurden still übersprungen → mögliches falsches Grün | Übersprungenes sichtbar machen | `coverage.files_skipped`, Agent-Zeile `SKIPPED` |
| 5.3 | `project.platform` wurde validiert und dann verworfen; `dotnet` akzeptiert, aber ohne Regeln | Keine akzeptierten, aber wirkungslosen Werte | ADR-0010, `platforms_without_pack` |
| 5.4 | Profil-`exclude` galt nicht für Verzeichnissuchen: ein ausgeschlossenes `.xcodeproj` schaltete das Apple-Pack ein und wurde gemeldet (gefunden vom **Dogfood-Scan**) | Globs in jeder Verzeichnissuche anwenden | Regressionstest beide Richtungen |
| 5.5 | `^\s*`-Muster liefen über auskommentierte Blöcke quadratisch (bis 165 s pro Regel) und meldeten die **Zeile des Kommentarblocks** statt der Deklaration | Einrückung als `^[ \t]*` ausdrücken; Performance messen, bevor Budgets gelten | `tests/test_performance.py`, `scripts/benchmark.py` |
| 5.6 | `ruttla \| head` endete mit Traceback und Exit 1 („Befund“) | Abgebrochene Ausgabe = Exit 3 | `cli.run` |
| 5.7 | Windows-Pipes (cp1252) hätten ✓/✗ und Umlaute nicht kodieren können | Ausgabe immer UTF-8 | CI-Matrix Windows |
| 5.8 | Private Projektnamen, Bundle-ID, Team-ID und persönliche E-Mail in Code und Historie | Anonymisieren vor Veröffentlichung; neue Historie beim Public-Start | `tests/test_provenance.py`, History-Audit |
| 5.9 | SARIF ohne Location lässt GitHub den **ganzen** Upload verwerfen | Jeder Befund bekommt eine Location | `tests/test_sarif.py` |
| 5.10 | Beispiel-Workflow hätte `pip install ruttla` von PyPI empfohlen, bevor der Name uns gehört | Commit pinnen bis zum Release | `docs/integrations/github-actions.md` |
