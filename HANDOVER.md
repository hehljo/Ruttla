# HANDOVER – qualitygate

Stand: 2026-09-20

## Letzter abgeschlossener Arbeitsblock

- Runner gegen falsches Grün gehärtet: ungültige Konfiguration, Pluginfehler, null Checks, null geprüfte Einheiten und unlesbare Eingaben liefern keinen Erfolg.
- `--changed-only` berücksichtigt jetzt auch ungetrackte Dateien und begrenzt Pfade auf die Prüfwurzel.
- Maschinenreport weist abgeschnittene Befunde aus und hält Agent-Felder einzeilig.
- 41 Runner-Unittests grün.
- Alle 70 registrierten Checks besitzen beide Selbsttestrichtungen; 153/153 Proben grün.
- Neues Apple-Release-Modul mit sieben Checks für Shared Schemes, Target-Verweise, Archivierung sowie Plist-/String-Catalog-/Asset-JSON-Syntax.
- Bestehendes Henga-Profil (`[project]`, `brand.source`) bleibt trotz strikter Konfiguration kompatibel.
- Henga read-only mit `apple.release.*`: 7 bestanden, 0 fehlgeschlagen, 0 nicht gemessen.
- Neues `checks/media.py` mit vier tokenfreien Checks: FFmpeg-Limiter-Auto-Level, fehlende TTS-Dauerschranke, fehlende Stream-/Sprachprüfung nach Mux und PowerShell-Freitextzerlegung über `Start-Process`.
- PowerShell-Zeilen- und Blockkommentare werden in `core.py` jetzt korrekt aus statischen Prüfflächen entfernt.
- 74 Checks registriert; alle besitzen beide Selbsttestrichtungen. 161/161 Selbsttest-Proben grün; alle vier neuen Checks zusätzlich isoliert über die echte CLI jeweils gesund grün und sabotiert rot.

## Exakter Startpunkt für die nächste Session

1. Diff-Hygiene der Medienchecks prüfen.
2. Optional die vier Medienchecks read-only gegen weitere echte Medienprojekte laufen lassen und False Positives dokumentieren.
3. Commit nur nach ausdrücklicher Freigabe erstellen und normal zu `origin/main` pushen.
4. Keine neue Sabotage-Runde nötig; 161/161 Selbsttest-Proben und die isolierten CLI-Gegenproben sind bereits grün.

## Offen

- Der breite strikte Universal-Lauf meldet in diesem Repo weiterhin den schon vorhandenen Assistentenhinweis in `autopush.sh`; das ist nicht Teil dieses Slices.
- `checks/unreal.py` war bereits uncommittet vorhanden und wurde nicht fachlich neu auditiert; seine bestehenden Selbsttests sind grün.
