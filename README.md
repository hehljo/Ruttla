# CODE_QUALITY_GENERAL

Universelles, **tokenfreies** Quality Gate. Prüft ein Projekt lokal gegen die
destillierten Architektur- und Qualitätsregeln — ohne LLM, ohne Netz, in
Sekunden. Gedacht als Schritt **nach jedem Arbeitsblock**, in jeder CLI.

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

## Profil: `.qualitygate.toml`

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
abgefangen. In `checks/<plattform>.py`:

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

## Was das Gate NICHT kann

Statische Textanalyse sieht Positionen, keine Kollisionen und keine Kontraste.
Für Gerendertes (PDF, Canvas, Layout im Browser) bleibt die Messung an der
Ausgabe nötig — `web-pruefstand`, `pdf-pruefstand`. Dieses Gate fängt die
Fälle ab, die schon in der Quelle sichtbar sind.

# Repo: https://github.com/hehljo/CODE_QUALITY_GENERAL
