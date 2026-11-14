# Ruttla-Statistik — gesamt

Stand 2026-11-08T08:27:34Z · erfasst seit 2026-10-30T09:40:44Z · Format `ruttla-stats/1`

## Bilanz

```
Bilanz seit 2026-10-30 (8 Tage, 434 Scans, 58 Projekte)
  Probleme gefunden  2.958 verschiedene · 73 Regeln · in 53 von 58 Projekten
  davon behoben      309 (10,4 %) · offen 2.649
  Regressionen       62 × wieder aufgetreten und erneut gemeldet
  Läufe mit Stopp    121 von 434 Scans hatten einen blockierenden Befund
  Neu gefunden       7 / 30 / 90 Tage / gesamt: 2.678 / 2.958 / 2.958 / 2.958
```

## Zeitraum: gesamt

| Kennzahl | gesamt | lokal | CI |
|---|---:|---:|---:|
| Scans | 434 | 434 | 0 |
| Projekte | 58 | 58 | 0 |
| Dateien | 185933 | 185933 | 0 |
| Checks ausgeführt | 40404 | 40404 | 0 |
| Befunde | 28252 | 28252 | 0 |
| blockierend | 1800 | 1800 | 0 |
| neu | 2958 | 2958 | 0 |
| weiter vorhanden | 25232 | 25232 | 0 |
| wieder aufgetreten | 62 | 62 | 0 |
| behoben | 371 | 371 | 0 |
| unbestimmt | 6848 | 6848 | 0 |

## Regeln

| | Scans | Befunde | blockierend | neu | behoben | wieder |
|---|---:|---:|---:|---:|---:|---:|
| `brand.hardcoded_in_display` | 382 | 8151 | 117 | 543 | 61 | 1 |
| `i18n.string_concatenation` | 377 | 2941 | 0 | 186 | 6 | 0 |
| `i18n.catalog_key_parity` | 377 | 2453 | 0 | 387 | 0 | 0 |
| `quality.duplicate_literal_list` | 377 | 1808 | 0 | 77 | 4 | 0 |
| `apple.string_localized_in_swiftui` | 158 | 1334 | 1334 | 292 | 83 | 0 |
| `web.emoji_in_display_text` | 217 | 1309 | 0 | 190 | 21 | 0 |
| `web.a11y_missing_label` | 217 | 1208 | 0 | 54 | 4 | 0 |
| `godot.hardcoded_ui_text` | 96 | 843 | 0 | 41 | 1 | 0 |
| `godot.private_call_on_other_object` | 96 | 786 | 0 | 30 | 0 | 0 |
| `web.hardcoded_endpoint` | 217 | 610 | 0 | 123 | 5 | 0 |

… 63 weitere im JSON-Export.

## Pakete

| | Scans | Befunde | blockierend | neu | behoben | wieder |
|---|---:|---:|---:|---:|---:|---:|
| `universal` | 427 | 17666 | 377 | 1598 | 185 | 62 |
| `web` | 218 | 4520 | 0 | 507 | 63 | 0 |
| `godot` | 98 | 3319 | 2 | 247 | 2 | 0 |
| `apple` | 159 | 2733 | 1421 | 604 | 120 | 0 |
| `python` | 328 | 14 | 0 | 2 | 1 | 0 |

## Fehlerklassen

| | Scans | Befunde | blockierend | neu | behoben | wieder |
|---|---:|---:|---:|---:|---:|---:|
| `brand` | 382 | 8170 | 118 | 549 | 63 | 1 |
| `i18n` | 377 | 6049 | 0 | 743 | 16 | 1 |
| `web` | 218 | 4520 | 0 | 507 | 63 | 0 |
| `godot` | 98 | 3319 | 2 | 247 | 2 | 0 |
| `apple` | 183 | 2733 | 1421 | 604 | 120 | 0 |
| `quality` | 416 | 2281 | 185 | 144 | 84 | 60 |
| `docs` | 377 | 561 | 2 | 88 | 10 | 0 |
| `gate` | 378 | 260 | 5 | 16 | 7 | 0 |
| `secrets` | 378 | 119 | 17 | 8 | 1 | 0 |
| `protocol` | 377 | 93 | 0 | 15 | 0 | 0 |

… 8 weitere im JSON-Export.

## Projekte (lokale ID)

| | Scans | Befunde | blockierend | neu | behoben | wieder |
|---|---:|---:|---:|---:|---:|---:|
| `5f9c552af4bff8e3` | 32 | 6986 | 3 | 501 | 9 | 0 |
| `11f5d4eb285dafde` | 122 | 6617 | 79 | 125 | 84 | 40 |
| `0c70ec0aa826cd84` | 21 | 5439 | 1542 | 1073 | 156 | 2 |
| `07b2c4a18ab4bf8d` | 41 | 5202 | 1 | 322 | 13 | 0 |
| `bc0eb5c12f8f6f63` | 10 | 1728 | 2 | 188 | 6 | 0 |
| `943d1ea106546c26` | 15 | 778 | 0 | 103 | 0 | 0 |
| `8524731f30fe2778` | 5 | 751 | 4 | 251 | 2 | 0 |
| `94dcd6178fab0aab` | 40 | 125 | 0 | 40 | 40 | 0 |
| `b45e840359a5aa8d` | 25 | 115 | 46 | 44 | 27 | 20 |
| `28a91b11beb429a9` | 5 | 104 | 39 | 80 | 15 | 0 |

… 43 weitere im JSON-Export.

## Hinweise

- Nur Läufe ab Aktivierung; nichts hochgerechnet. Scans im Temp-Verzeichnis (Testläufe, Wegwerf-Klone) zählen nicht.
- behoben = Regel lief gemessen, Datei im Prüfbereich und noch vorhanden, Befund weg. Sonst unbestimmt.
- Projekte sind lokale Zufalls-IDs; Pfade und Repo-Namen werden nicht gespeichert.
- Bilanz zählt verschiedene Fingerabdrücke über alle Läufe, nicht Befunde je Scan; „gefunden“ schließt Probleme ein, die beim ersten Scan schon da waren.
