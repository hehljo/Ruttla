# Ruttla-Statistik — gesamt

Stand 2026-11-04T21:14:23Z · erfasst seit 2026-10-30T09:40:44Z · Format `ruttla-stats/1`

## Bilanz

```
Bilanz seit 2026-10-30 (5 Tage, 266 Scans, 18 Projekte)
  Probleme gefunden  1.077 verschiedene · 57 Regeln · in 16 von 18 Projekten
  davon behoben      101 (9,4 %) · offen 976
  Regressionen       54 × wieder aufgetreten und erneut gemeldet
  Läufe mit Stopp    60 von 266 Scans hatten einen blockierenden Befund
  Neu gefunden       7 / 30 / 90 Tage / gesamt: 1.077 / 1.077 / 1.077 / 1.077
```

## Zeitraum: gesamt

| Kennzahl | gesamt | lokal | CI |
|---|---:|---:|---:|
| Scans | 266 | 266 | 0 |
| Projekte | 18 | 18 | 0 |
| Dateien | 141128 | 141128 | 0 |
| Checks ausgeführt | 26448 | 26448 | 0 |
| Befunde | 16932 | 16932 | 0 |
| blockierend | 205 | 205 | 0 |
| neu | 1077 | 1077 | 0 |
| weiter vorhanden | 15801 | 15801 | 0 |
| wieder aufgetreten | 54 | 54 | 0 |
| behoben | 155 | 155 | 0 |
| unbestimmt | 2805 | 2805 | 0 |

## Regeln

| | Scans | Befunde | blockierend | neu | behoben | wieder |
|---|---:|---:|---:|---:|---:|---:|
| `brand.hardcoded_in_display` | 251 | 4933 | 54 | 227 | 26 | 0 |
| `i18n.string_concatenation` | 246 | 2213 | 0 | 100 | 6 | 0 |
| `quality.duplicate_literal_list` | 246 | 1499 | 0 | 54 | 3 | 0 |
| `web.emoji_in_display_text` | 120 | 1005 | 0 | 107 | 1 | 0 |
| `web.a11y_missing_label` | 120 | 984 | 0 | 30 | 3 | 0 |
| `godot.private_call_on_other_object` | 82 | 713 | 0 | 30 | 0 | 0 |
| `godot.hardcoded_ui_text` | 82 | 696 | 0 | 36 | 1 | 0 |
| `godot.balance_value_in_code` | 82 | 352 | 0 | 31 | 0 | 0 |
| `web.viewport_height_unit` | 120 | 336 | 0 | 25 | 2 | 0 |
| `web.hardcoded_endpoint` | 120 | 323 | 0 | 33 | 4 | 0 |

… 47 weitere im JSON-Export.

## Pakete

| | Scans | Befunde | blockierend | neu | behoben | wieder |
|---|---:|---:|---:|---:|---:|---:|
| `universal` | 259 | 10017 | 201 | 526 | 128 | 54 |
| `web` | 121 | 3417 | 0 | 263 | 10 | 0 |
| `godot` | 84 | 2870 | 2 | 203 | 2 | 0 |
| `apple` | 107 | 615 | 2 | 83 | 14 | 0 |
| `python` | 234 | 13 | 0 | 2 | 1 | 0 |

## Fehlerklassen

| | Scans | Befunde | blockierend | neu | behoben | wieder |
|---|---:|---:|---:|---:|---:|---:|
| `brand` | 251 | 4950 | 54 | 231 | 27 | 0 |
| `web` | 121 | 3417 | 0 | 263 | 10 | 0 |
| `godot` | 84 | 2870 | 2 | 203 | 2 | 0 |
| `i18n` | 246 | 2560 | 0 | 152 | 6 | 0 |
| `quality` | 248 | 1892 | 137 | 85 | 75 | 54 |
| `apple` | 107 | 615 | 2 | 83 | 14 | 0 |
| `docs` | 246 | 227 | 2 | 20 | 10 | 0 |
| `gate` | 247 | 207 | 5 | 13 | 7 | 0 |
| `secrets` | 247 | 93 | 1 | 4 | 1 | 0 |
| `ci` | 246 | 41 | 0 | 1 | 0 | 0 |

… 4 weitere im JSON-Export.

## Projekte (lokale ID)

| | Scans | Befunde | blockierend | neu | behoben | wieder |
|---|---:|---:|---:|---:|---:|---:|
| `11f5d4eb285dafde` | 96 | 5932 | 75 | 118 | 75 | 39 |
| `07b2c4a18ab4bf8d` | 40 | 4893 | 1 | 233 | 13 | 0 |
| `5f9c552af4bff8e3` | 21 | 3150 | 0 | 162 | 8 | 0 |
| `bc0eb5c12f8f6f63` | 10 | 1728 | 2 | 188 | 6 | 0 |
| `943d1ea106546c26` | 11 | 691 | 0 | 95 | 0 | 0 |
| `b45e840359a5aa8d` | 22 | 110 | 41 | 44 | 22 | 15 |
| `28a91b11beb429a9` | 5 | 104 | 39 | 80 | 15 | 0 |
| `f1427c56db26c95b` | 3 | 101 | 0 | 35 | 2 | 0 |
| `996ab7f5ce220efa` | 4 | 87 | 19 | 24 | 7 | 0 |
| `e76f500afc8fc149` | 1 | 50 | 6 | 50 | 0 | 0 |

… 6 weitere im JSON-Export.

## Hinweise

- Nur Läufe ab Aktivierung; nichts hochgerechnet. Scans im Temp-Verzeichnis (Testläufe, Wegwerf-Klone) zählen nicht.
- behoben = Regel lief gemessen, Datei im Prüfbereich und noch vorhanden, Befund weg. Sonst unbestimmt.
- Projekte sind lokale Zufalls-IDs; Pfade und Repo-Namen werden nicht gespeichert.
- Bilanz zählt verschiedene Fingerabdrücke über alle Läufe, nicht Befunde je Scan; „gefunden“ schließt Probleme ein, die beim ersten Scan schon da waren.
