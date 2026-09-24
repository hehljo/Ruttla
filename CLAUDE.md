# CLAUDE.md — Arbeitsanweisung für dieses Repo

Dieses Repo ist das **tokenfreie Quality Gate**. Es hat genau einen Zweck: ein
Fehlerbild, das einmal aufgetreten ist, ab dann ohne LLM abzufangen.

Bedienung, Exit-Codes, Profil: siehe `README.md`. Hier steht nur, **was zu tun
ist, wenn ein Fehler hereinkommt**.

---

## 🔴 Ein gemeldeter Fehler wird EINGEPFLEGT, nicht repariert

**Wenn der User einen Build-Fehler, Compilerfehler, Laufzeitfehler oder Absturz
aus irgendeinem Projekt hierher meldet, ist die Aufgabe der CHECK — nicht der
Fix im fremden Code.**

Der Fix im Projekt ist Nebensache und wird nur auf ausdrückliche Bitte gemacht.
Ohne Check ist der Fix wertlos: derselbe Fehler kommt im nächsten Projekt
wieder, und dann kostet er wieder Token.

Belegt am 18.09.2026: gemeldet wurden zwei Swift-Compilerfehler aus einem App-Projekt (Fotobuch-App).
Statt den Check zu bauen, wurden fünf Quelldateien im fremden Repo editiert.
Der User musste korrigieren: *„du sollst eigentlich nur die check pythons
entsprechend das Fehlerbild implementieren, net den Code ändern"*. Die Regel
stand zu dem Zeitpunkt bereits in `README.md` unter „Einen neuen Check
ergänzen" — sie war Text zum Lesen, kein Schritt zum Durchlaufen.

**Reihenfolge, wenn ein Fehler hereinkommt:**

| # | Schritt |
|---|---|
| 1 | Ursache belegen — API nachschlagen, nicht aus dem Gedächtnis urteilen (`context7`, `WebSearch` mit Jahreszahl) |
| 2 | Prüfen, ob ein **bestehender** Check den Fall hätte fangen müssen und warum er es nicht tat |
| 3 | Check schreiben oder korrigieren, mit beiden Sabotage-Richtungen |
| 4 | `--self-test` **ohne Pipe**, Status sofort lesen |
| 5 | Gegen den **echten** Fehlerzustand messen (rekonstruiert im Scratchpad) und gegen den gefixten |
| 6 | Erst jetzt, und nur wenn gewünscht, den Fix im Projekt |

---

## Folgefehler sind kein zweiter Befund

Ein Compiler meldet oft zwei Zeilen für **eine** Ursache. Der Check prüft die
Ursache und nennt den Folgetext in der Meldung, damit man beim Suchen darauf
kommt.

Belegt: `Extra argument 'relativeTo' in call` **und** `Cannot infer contextual
base in reference to member 'largeTitle'` — die zweite Meldung entsteht nur,
weil der falsche Parameter den Basistyp unbestimmt lässt. Ein Check, zwei
Meldungen im Text.

---

## Der Compiler zeigt EINE Fundstelle, das Gate misst alle

Ein Compiler bricht je Datei bei der ersten fehlerhaften Stelle ab. Die
gemeldete Zeile ist deshalb **nie** die Menge der Fundstellen.

Belegt im selben Fall: gemeldet war `ExportSheetView.swift:17`. Im Projekt
standen **fünf** identische Stellen in fünf Dateien. Nach jedem Einpflegen
`grep -rn` über die Eigenschaft laufen lassen und die **Gesamtzahl** melden.

---

## Ein Check, der einen Fix vorschlägt, wird auf diesen Fix geprüft

Der `fix:`-Text ist Code, den jemand abschreibt. Ein falscher Vorschlag baut
den Fehler ein, den das Gate verhindern soll — die schlimmste Sorte Befund,
weil er als Autorität auftritt.

Belegt: `apple.hardcoded_font_size` empfahl wörtlich `.system(size:relativeTo:)`
— eine API, die es nicht gibt (FB9772279 ist ein offener Feature-Request). Sein
PASS-Selbsttest benutzte den kaputten Aufruf als Beispiel für „richtig", und
sein Filter `if "relativeTo:" in raw: continue` deckte damit auch noch den
echten Befund zu. Ein Gate hat den Fehler also nicht nur übersehen, sondern
empfohlen.

**Regel:** Jeder `fix:`-Text, der eine API nennt, wird gegen die Doku geprüft.
Jeder PASS-Selbsttest muss Code enthalten, der **tatsächlich übersetzt**.

---

## Eine Versionsschwelle ist eine Messung, keine runde Zahl

Eine fest getippte Versionsnummer im Check veraltet mit der Toolchain und
meldet dann entweder nichts mehr oder alles.

Belegt: `LastUpgradeCheck < 1600` (Xcode 16.0) stand fest im Code, während die
Toolchain auf Xcode 26.4 stand — jedes aktuelle Projekt zeigte „Update to
recommended settings", ohne dass das Gate etwas sagte. Schwellen gehören in
eine **benannte Konstante** mit ihrer Messung im Kommentar, sonst werden sie
beim nächsten Aufräumen auf eine runde Zahl gesetzt.

Der aktuelle Toolchain-Stand wird in der globalen Agent-Konfiguration des
Maintainers gepflegt (nicht Teil dieses Repos).

---

## Hart oder weich: Compilerfehler ist hart

Ohne Profil stuft `master_gate.py` auf Exit 0 zurück, wenn kein Befund aus
einem `safe_by_default`-Check kommt. Das ist richtig für Stilurteile und
falsch für Fehler, die nachweislich nicht übersetzen.

**`safe_by_default=True` genau dann**, wenn ein falsch-positiver Fall
ausgeschlossen ist — etwa weil die verwendete API nicht existiert. Für alles,
was „meist falsch, manchmal Absicht" ist, bleibt es weich.

Warnzeichen: das Gate druckt rote Befunde und meldet trotzdem `EXIT: 0`.

---

## Gegenprobe ohne Pipe

`python3 master_gate.py … | grep …` liefert den Status von `grep`. Bei einer
Sabotage-Runde steht der Exit-Code für „hat das Gate angeschlagen?" — eine
wirkungslose Sabotage sieht dann aus wie eine bestandene Prüfung.

```bash
out=$(python3 master_gate.py /pfad 2>&1); status=$?
echo "EXIT: $status"
echo "$out" | grep -i …
```

Warnzeichen: in einer Prüfzeile stehen `|` und `$?` beide.

---

## Nach dem Einpflegen

1. `--self-test` muss grün sein **und** die Probenzahl muss gestiegen sein
2. Der neue Check muss am rekonstruierten Originalfehler **rot** werden
3. Am gefixten Stand **grün**
4. Beim User melden: Check-ID, Anzahl gefundener Fundstellen, ob ein
   bestehender Check mitschuldig war
