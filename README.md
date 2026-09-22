# CODE_QUALITY_GENERAL

Universelles, **tokenfreies** Quality Gate. Prüft ein Projekt lokal gegen die
destillierten Architektur- und Qualitätsregeln — ohne LLM, ohne Netz, in
Sekunden. Gedacht als Schritt **nach jedem Arbeitsblock**, in jeder CLI.

## 🔴 Fehler kommt herein → Check bauen, nicht Code fixen

Wer einen Build-/Compiler-/Laufzeitfehler aus einem Projekt hierher meldet,
will einen **Check** — nicht eine Reparatur im fremden Repo. Der Fix dort ist
Nebensache und passiert nur auf ausdrückliche Bitte.

Ablauf und die belegten Fallstricke: **`CLAUDE.md`** in diesem Ordner. Die
Kurzfassung:

1. Ursache belegen (Doku, nicht Gedächtnis) — 2. prüfen, ob ein bestehender
Check versagt hat — 3. Check mit **beiden** Sabotage-Richtungen — 4.
`--self-test` ohne Pipe — 5. gegen den echten Fehlerzustand messen.

## Warum

Eine Regel ohne Gate ist nur ein Vorsatz. Die Guidelines standen als Text da
und verhinderten trotzdem nichts, weil Text zum Lesen kein Schritt zum
Durchlaufen ist. Dieses Paket macht die maschinell prüfbaren davon ausführbar.

## Aufruf

```bash
python3 master_gate.py /pfad/zum/projekt              # Textbericht
python3 master_gate.py . --format agent               # eine Zeile je Befund
python3 master_gate.py . --format json                # vollständiger Report
python3 master_gate.py . --json report.json           # Report in eine Datei
python3 master_gate.py . --changed-only HEAD~1        # nur Geändertes
python3 master_gate.py . --platform apple             # nur eine Plattform
python3 master_gate.py . --check 'secrets.*'          # nur diese Checks
python3 master_gate.py --list                         # alle Checks zeigen
python3 master_gate.py --self-test                    # Sabotage-Gegenprobe
```

## Exit-Codes — der Vertrag mit der aufrufenden CLI

| Code | Bedeutung |
|---|---|
| `0` | grün: bestanden, soweit hier messbar |
| `1` | Fehler gefunden (mindestens ein Befund auf `error`-Ebene) |
| `2` | **nicht gemessen** — kein Check konnte laufen. Kein Erfolg. |
| `3` | Gate-Absturz oder Fehlbedienung |

Code `2` ist der Kern: „null Checks gelaufen" ist rot, nicht grün. Wer nur auf
`!= 0` prüft, verbucht einen Abbruch als Erfolg.

## Für eine KI als Aufrufer

`--format agent` gibt tabgetrennte Zeilen mit stabilen IDs aus:

```
VERDICT=failed EXIT=1 PASS=13 FAIL=15 UNMEASURED=12 ERRORS=7 WARNINGS=66
ERROR	godot.add_child_before_configure	zone.gd:158	…	FIX: …
UNMEASURED	apple.bundle_id_mismatch	Kein .xcodeproj gefunden.
NEXT_ACTION	Die Befunde mit severity=error beheben. …
```

`--format json` liefert zusätzlich `next_action`, `platforms_detected`,
`units_examined` je Check und den Grund jedes `unmeasured`. Angeknüpft wird an
`check_id` — nie an einen Anzeigetext, der sich beim nächsten Wording-Fix ändert.

**Wichtig beim Aufruf aus einem Skript:** Ausgabe in eine Variable, Status
sofort danach lesen, **dann** erst filtern. `gate.py | head -3` liefert immer
die 0 von `head`.

```bash
out=$(python3 master_gate.py . --format agent); status=$?
echo "$out" | head -20
```

## Profil: `.qualitygate.toml` — Ausschlüsse und Schärfe je Projekt

Die Datei kommt ins **Wurzelverzeichnis des geprüften Projekts** (nicht hierher).
Sie regelt zwei Dinge: **was gar nicht erst gelesen wird** und **wie scharf**
ein Befund zählt.

Ohne Profil laufen nur die universell sicheren Checks hart — ein Gate, das im
fremden Projekt sofort rot wird über Dinge, die funktionieren, verliert das
Vertrauen, mit dem es durchgesetzt wird. Mit Profil entscheidet das Projekt:

```toml
[gate]
strict = false
exclude = ["legacy/**", "vendor/**"]

[brand]
names   = ["Tellunia"]                  # sonst aus package.json abgeleitet
sources = ["src/brand.ts", "src/i18n/*"] # hier GEHÖRT der Name hin

[severity]
"secrets.*"                  = "error"
"i18n.literal_in_markup"     = "warning"
"godot.untyped_declaration"  = "off"
```

### Dateien und Ordner ausschließen

| Schlüssel | Matcht | Wirkung |
|---|---|---|
| `exclude` | den **relativen Pfad** per Glob (`fnmatch`) | Datei wird übersprungen. `"extracted/**"`, `"**/*.generated.ts"`, `"legacy/**"` |
| `exclude_dirs` | den **Verzeichnisnamen** allein, auf jeder Ebene | ganzer Ast wird beim Durchlaufen abgeschnitten — schneller bei großen Bäumen |

Pfade mit Leerzeichen brauchen keine Sonderbehandlung: `"extracted/**"` fängt
auch `extracted/dm Foto/web/index.html`.

Eine Reihe Ordner ist **immer** ausgeschlossen, ohne Profil: `node_modules`,
`.git`, `build`, `dist`, `DerivedData`, `Pods`, `.godot`, `vendor`, `venv`,
`__pycache__` und weitere (`DEFAULT_EXCLUDE_DIRS` in `core.py`).

> **`.gitignore` wird NICHT gelesen** — bewusst. „Nicht versioniert" und
> „nicht prüfenswert" sind zwei verschiedene Fragen: ein generierter Build
> gehört geprüft, ein entpacktes Fremdarchiv nicht. Wer ignorierte Ordner
> ausschließen will, schreibt sie hierher.

**Warum das kein Schönheitsthema ist:** Belegt am 18.09.2026 (FotobuchGenie) —
ein Lauf meldete **5825 Befunde**, davon **5812 (99,8 %)** aus `extracted/`,
einem 754 MB großen entpackten Fremdarchiv mit fremdem Marketing-HTML. Übrig
blieben **13** echte, alle auf INFO-Ebene. Ein Check, der tausendfach über
fremdes Material meldet, deckt die echten Befunde zu — ein grüner Lauf mit
Tausenden Warnungen ist kein grüner Lauf.

Gegenprobe nach jedem neuen Ausschluss, **beide Richtungen**: Fällt die Zahl
für das ausgeschlossene Verzeichnis auf null, **und** bleibt eine bekannte
Fundstelle außerhalb weiterhin gemeldet? Sonst ist aus dem Ausschluss eine
stille Freistellung geworden.

```bash
out=$(python3 master_gate.py /pfad --format agent --max-findings 9999); status=$?
echo "$out" | grep -E '^(ERROR|WARNING|INFO)' | awk -F'\t' '{print $1"\t"$2}' \
  | sort | uniq -c | sort -rn      # welcher Check macht die Masse?
```

## Die drei Ausgänge

Jeder Check meldet `pass`, `fail` **oder** `unmeasured` mit Begründung. Ein
Check, der seine Eingabe nicht herstellen konnte, meldet nie still grün —
„grün, soweit hier messbar" ist die ehrliche Aussage, und der Report sagt
dazu, welcher Teil dadurch **nicht** gemessen ist.

## Selbstgegenprobe

```bash
python3 master_gate.py --self-test
```

Jeder Check trägt mindestens zwei Proben: eine mit absichtlich kaputten Daten
(muss `fail` liefern) und eine mit gesunden (muss `pass` liefern). Nur kaputte
Daten zu testen zeigt, dass ein Gate rot werden *kann* — nicht, dass es bei
gesunden Daten grün bleibt. Ein falsch-positives Gate ist schlimmer als keins.

Der Lauf meldet außerdem, welche Checks **keine** Probe haben. Die sind
ungeprüfte Zusagen.

## Einen neuen Check ergänzen

Ein Build-Fehler, der einmal aufgetreten ist, gehört ab dann tokenfrei
abgefangen — das ist der Zweck dieses Repos, siehe `CLAUDE.md`. In
`checks/<plattform>.py`:

```python
@register(
    "apple.mein_check",              # stabile ID = der Vertrag
    "Kurzbeschreibung",
    platform="apple",
    severity=Severity.ERROR,
    guideline="IOS_DEBUGGING_GUIDELINES.md § …",
    self_tests=[
        SelfTestCase(name="kaputt", files={...}, expect=Status.FAIL),
        SelfTestCase(name="gesund", files={...}, expect=Status.PASS),
    ],
)
def check_mein_check(ctx: Context) -> CheckResult:
    """Warum es diese Regel gibt — mit dem belegten Fall."""
    ...
```

Das Modul wird automatisch geladen: der Runner iteriert über `checks/`, statt
eine Liste zu pflegen — eine gepflegte Liste ist die zweite Liste. Und er
wertet „null Module geladen" ausdrücklich als Fehler.

**Regeln für einen neuen Check:**

1. Miss die **Eigenschaft**, nicht die Bauform, die sie gerade liefert. Ein
   Gate, das einen konkreten Typ verlangt, verbietet die bessere Lösung.
2. Der Prüfgegenstand ist der **Kandidat**, nicht der Verstoß. Wer nur die
   Treffer zählt, meldet im gesunden Projekt `unmeasured` statt `pass`.
3. Kein Anzeigetext als Anker — gegen Bezeichner ankern.
4. Beide Richtungen als Sabotage-Probe, sonst ist der Check nicht fertig.
5. Der `fix:`-Text ist Code, den jemand abschreibt — jede darin genannte API
   gegen die Doku prüfen. Ein Check, der eine nicht existente API empfiehlt,
   baut den Fehler ein, den er verhindern soll (belegt: `hardcoded_font_size`
   empfahl `.system(size:relativeTo:)`).
6. Versionsschwellen als benannte Konstante mit ihrer Messung im Kommentar,
   nie als getippte Zahl im Vergleich.
7. `safe_by_default=True` nur, wenn ein falsch-positiver Fall ausgeschlossen
   ist — etwa weil die verwendete API nicht existiert. Sonst meldet das Gate
   rote Befunde und trotzdem Exit 0.

## Apple: Store-Pflichtangaben im App-Target

Fünf Checks aus einem einzigen belegten Upload nach App Store Connect
(Henga, `com.hehljo.Henga`, 2026-09-22). Alle fünf Fehler bauen lokal
fehlerfrei durch und fallen erst bei Apple auf:

- `apple.release.app_category_missing` — kein `LSApplicationCategoryType`
  (hart ohne Profil; ASC lehnt den Upload ab)
- `apple.release.app_sandbox_missing` — `com.apple.security.app-sandbox`
  fehlt oder steht auf `false` (hart; App Review verlangt sie für jede
  Mac-App-Store-App)
- `apple.release.signing_team_missing` — `DEVELOPMENT_TEAM` fehlt oder ist
  leer **im App-Target**
- `apple.release.display_name_missing` — kein `CFBundleDisplayName`
- `apple.release.xcstrings_incomplete` — String Catalog mit unübersetzten
  Schlüsseln

**Warum der Prüfbereich das Target ist, nicht die Datei.** Der bestehende
Check `apple.project_settings` sucht `DEVELOPMENT_TEAM` mit einem
dateiweiten `re.search`. Bei Henga blieb er dadurch grün, obwohl das
App-Target kein Team trug: irgendein anderes Objekt in der `project.pbxproj`
enthielt den Schlüssel. Die neuen Checks lösen deshalb
`PBXNativeTarget` → `XCConfigurationList` → `XCBuildConfiguration` auf und
messen jede App-Konfiguration einzeln. Gefiltert wird über
`productType == com.apple.product-type.application`, also die **Eigenschaft**
„ist eine Anwendung" — Testbundles, Helper und Extensions brauchen diese
Angaben nicht.

**Die Plattformerkennung war die eigentliche Falle.** Zwei Fehlversuche, beide
am echten Projekt gefunden:

| Erste Fassung | Warum sie falsch war |
|---|---|
| `SDKROOT` nur in der Target-Konfiguration lesen | Xcode legt es auf **Projektebene** ab. Henga galt dadurch als plattformlos, der Sandbox-Check meldete `UNMEASURED` statt des vorhandenen Fehlers |
| `MACOSX_DEPLOYMENT_TARGET` als Mac-Merkmal werten | Ein reines iOS-Projekt (Dienstreise, `SDKROOT = iphoneos`) trägt es als Beiwerk von Mac Catalyst. Jede iOS-App hätte eine fehlende Mac-Sandbox gemeldet — ein falsch-positives **hartes** Gate |

Maßgeblich ist das SDK, gegen das gebaut wird. Gegengeprobt an vier realen
Projekten: Henga (macOS) rot, Dienstreise und GreetGen (iOS, GreetGen ist
final im App Store) grün beziehungsweise ehrlich `UNMEASURED`.

**Zwei Checks stehen hart ohne Profil** (`safe_by_default=True`), weil ein
falsch-positiver Fall ausgeschlossen ist: beide zulässigen Bauformen werden
geprüft (Plist-Key **und** `INFOPLIST_KEY_*`), und ein nicht auflösbares
Target liefert `UNMEASURED` statt `FAIL`.

## Medien-Pipelines

`checks/media.py` fängt vier belegte Fehlerklassen statisch und ohne FFmpeg-,
GPU-, Netz- oder Modellstart ab:

- `media.ffmpeg_limiter_auto_level`: `alimiter` ohne abgeschaltetes Auto-Level
- `media.tts_without_duration_guard`: TTS gelangt ohne harte Dauerprüfung in Mix oder Mux
- `media.mux_without_stream_probe`: Output-Streams und Sprachmetadaten werden nach dem Mux nicht wirkungsgeprüft
- `media.powershell_text_argument_split`: dynamischer Freitext wird über `Start-Process -ArgumentList` zerlegt

Die Checks prüfen Quellcode und Orchestrierung. Peak, Streamreihenfolge,
Decodierbarkeit und Hörqualität des fertigen Artefakts bleiben zusätzliche
Ausgabeprüfungen; Existenz eines Filters ist nicht seine Wirkung.

## Python-Dienste

`checks/python_services.py` — fünf Fehlerklassen aus dem Live-Trading-Bot
CondrianoInvest (23.09.2026), alle code-technisch vermeidbar:

- `python.apscheduler_misfire_default` (error): Scheduler ohne
  `misfire_grace_time` — Default 1 s, verspätete Jobs werden **verworfen**.
  Belegt: Stop-Loss-Check 255× übersprungen, Schwesterbots 177× / 119×.
- `python.telegram_token_log_leak` (error): Root-Logger auf INFO/DEBUG in
  einem Prozess mit Telegram-Client, ohne `httpx` (bzw. `urllib3` bei DEBUG)
  zu drosseln — die Request-URL enthält `/bot<TOKEN>/`. Geprüft wird die
  Datei, die Telegram tatsächlich ruft; Drosselung zählt im selben Projekt
  (nächstes `requirements.txt`/`pyproject.toml`).
- `python.yahoo_chart_last_bar_dropped` (error): Yahoo `v8/finance/chart`
  liefert die letzte Tageskerze (XETRA u. a.) mit `close=None`; `dropna`
  ohne Auffüllen aus `meta.regularMarketPrice` = Kurs von vorgestern.
- `python.http_retry_non_idempotent` (warning): Retry-Schleife wiederholt
  POST/PUT/beliebige Methode nach Timeout — mögliche Doppelorder.
- `python.hardcoded_fx_fallback` (warning): Wechselkursfunktion fällt still
  auf eine feste Zahl zurück (belegt: 1.05 griff monatelang, echt 1,146).

**Nicht statisch prüfbar, deshalb kein Gate:** ob ein Signal vor der Order
gegen einen Live-Kurs gehalten wird (Kurs-Schutz) und ob async-Jobs
synchron blockieren — beides steht als Regel in `Finanz/AGENTS.md` und ist
im Projekt per Test (`tests/test_signal_freshness.py`) abgesichert.
Dateirechte (`.env` weltlesbar) lassen sich im Selbsttest-Format nicht
herstellen — ebenfalls kein Gate.

## Was das Gate NICHT kann

Statische Textanalyse sieht Positionen, keine Kollisionen und keine Kontraste.
Für Gerendertes (PDF, Canvas, Layout im Browser) bleibt die Messung an der
Ausgabe nötig — `web-pruefstand`, `pdf-pruefstand`. Dieses Gate fängt die
Fälle ab, die schon in der Quelle sichtbar sind.

# Repo: https://github.com/hehljo/CODE_QUALITY_GENERAL
