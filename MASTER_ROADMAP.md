# MASTER_ROADMAP – qualitygate

Stand: 2026-09-19

## Phase 1: Basis und ausführbarer Check-Katalog [x]
- [x] Plattformübergreifende Check-Registry und Drei-Ausgangsmodell
- [x] Maschinenlesbare Text-, Agent- und JSON-Ausgabe
- [x] Automatisches Laden aller Check-Module
- [x] Selbsttests in gesunder und negativer Richtung für jeden registrierten Check

## Phase 2: Runner-Härtung gegen falsches Grün [x]
- [x] Ungültige oder unbekannte Konfiguration ablehnen
- [x] Plugin-Importfehler und leere Plugins blockieren
- [x] Null Checks und null geprüfte Einheiten nicht als Erfolg werten
- [x] Unlesbare Eingaben und Pfadausbrüche blockieren
- [x] `--changed-only` auf Unterordner begrenzen und ungetrackte Dateien einbeziehen
- [x] Report-Trunkierung mit vollständigen Gesamtzahlen ausweisen
- [x] 41 Runner-Unittests etablieren

## Phase 3: Apple-Release-Checks [x]
- [x] Shared Scheme vorhanden und syntaktisch gültig
- [x] Scheme-Target verweist auf reales Xcode-Target
- [x] ArchiveAction und Build-Konfiguration konsistent
- [x] Plist-/Entitlements-/Privacy-Manifest-Syntax prüfen
- [x] String-Catalog-JSON prüfen
- [x] Asset-Catalog-Contents-JSON prüfen
- [x] Gegen Henga read-only erfolgreich durchgestochen

## Phase 4: Pflege und Ausbau [ ]
- [ ] Weitere Releaseformate nur mit gesunden und isolierten Negativproben ergänzen
- [ ] Bestehende breite Plattformchecks bei realen neuen Fehlerklassen gezielt erweitern
- [ ] Master-Gate-Regeln und projektspezifische Profile kompatibel versionieren
