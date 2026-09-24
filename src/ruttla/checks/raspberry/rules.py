"""
Raspberry-/Messtechnik-Checks aus CODE_QUALITY_GUIDELINES_RASPBERRY.md.

* § 1  Testbarkeit ohne Hardware ist keine Kür — Zustand vom Laufzeitkram
       getrennt (zugleich Grundsatz D aus der CLAUDE.md).
* § 3  Das Feld ist feindlich — jede Hardware-Operation braucht Zeitlimit
       und Fehlerbehandlung, sonst hängt der Dienst still.
* § 4  Konfiguration hart prüfen, VOR dem Start.
* § 5  Messwerte, die zu Geld werden — Rohdaten unantastbar.
* § 8  Betrieb: kein Prozess ohne Neustartregel.
"""

from __future__ import annotations

import os
import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, unmeasured, result_for, snippet, strip_comments,
)

PLATFORM = "raspberry"

HW_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(RPi\.GPIO|RPi|gpiozero|smbus2?|spidev|pigpio|"
    r"serial|w1thermsensor|board|busio|adafruit_\w+|picamera2?|luma\.\w+)"
)


def _py(ctx: Context):
    return ctx.files(".py")


@register(
    "rpi.hardware_import_not_isolated",
    "Hardware-Zugriff im selben Modul wie die Logik",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_RASPBERRY.md § 1 / CLAUDE.md § Grundsatz D",
    self_tests=[
        SelfTestCase(
            name="Logik und GPIO gemischt",
            files={"app/meter.py": (
                "import RPi.GPIO as GPIO\n\n"
                "def berechne_energie(werte):\n"
                "    return sum(werte) / len(werte)\n"
            )},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Logik ohne Hardware",
            files={
                "app/hw.py": "import RPi.GPIO as GPIO\n\ndef lies_pin(p):\n    return GPIO.input(p)\n",
                "app/logic.py": "def berechne_energie(werte):\n    return sum(werte) / len(werte)\n",
            },
            expect=Status.PASS,
        ),
    ],
)
def check_hw_isolation(ctx: Context) -> CheckResult:
    """Die Probe: lässt sich die Eigenschaft ohne echte Umgebung testen?

    Wenn nein, sitzt die Zuständigkeit falsch — nicht der Test ist zu schwach,
    die Aufteilung ist es. Gemessen wird: ein Modul importiert Hardware UND
    enthält Rechenlogik, die ohne sie auskommen könnte.
    """
    title = "Hardware-Zugriff im selben Modul wie die Logik"
    files = _py(ctx)
    if not files:
        return unmeasured("rpi.hardware_import_not_isolated", title,
                          "Keine Python-Dateien gefunden.", PLATFORM)
    # Reine Rechenfunktion: nimmt Argumente, hat return, ruft keine Hardware auf.
    # Kein führendes \s* : im MULTILINE-Modus frisst das den Zeilenumbruch der
    # Vorzeile mit, und m.start() zeigt dann auf die Zeile DAVOR. Die Gegenprobe
    # hat genau das gefunden — die Ausrückung wurde an einer Leerzeile gemessen.
    logic_fn = re.compile(r"^[ \t]*def\s+(\w+)\s*\([^)]*\w[^)]*\)\s*(?:->\s*[\w\[\], .]+)?:",
                          re.MULTILINE)
    hw_call = re.compile(
        r"\b(GPIO\.|gpiozero|SMBus|spidev|pigpio|serial\.|\.read_byte|"
        r"\.write_byte|busio\.|board\.|picamera)"
    )
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        if not any(HW_IMPORT.match(ln) for ln in body.splitlines()):
            continue
        measured += 1
        lines = body.splitlines()
        for m in logic_fn.finditer(body):
            start = body.count("\n", 0, m.start())
            if start >= len(lines):
                continue
            block: list[str] = []
            base_indent = len(lines[start]) - len(lines[start].lstrip())
            for ln in lines[start + 1: start + 40]:
                # Leerzeilen beenden einen Block nicht — nur eine Zeile mit
                # Inhalt auf gleicher oder geringerer Ausrückung tut das.
                if ln.strip() and (len(ln) - len(ln.lstrip())) <= base_indent:
                    break
                block.append(ln)
            text = "\n".join(block)
            if not text.strip() or hw_call.search(text):
                continue
            if "return" not in text:
                continue
            if m.group(1).startswith("_") or m.group(1) in ("main", "setup", "run"):
                continue
            findings.append(Finding(
                check_id="rpi.hardware_import_not_isolated",
                severity=Severity.WARNING,
                message=f"'{m.group(1)}()' ist reine Logik, liegt aber in einem "
                        "Modul, das Hardware importiert — ohne Gerät nicht testbar.",
                file=sf.rel, line=start + 1, evidence=snippet(lines[start]),
                fix="Logik in ein Modul OHNE Hardware-Import verschieben. Zwei "
                    "Typen statt einem: <Ding>State (Daten) neben <Ding>Runtime "
                    "(Gerät, Verbindung).",
                guideline="CLAUDE.md § Grundsatz D",
            ))
    if measured == 0:
        return unmeasured("rpi.hardware_import_not_isolated", title,
                          "Keine Module mit Hardware-Importen gefunden.", PLATFORM)
    return result_for("rpi.hardware_import_not_isolated", title, findings,
                      measured, "Hardware-Module", PLATFORM)


@register(
    "rpi.io_without_timeout",
    "Hardware-/Netz-Zugriff ohne Zeitlimit",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_RASPBERRY.md § 3",
    self_tests=[
        SelfTestCase(
            name="serial ohne timeout",
            files={"app/io.py": "import serial\ns = serial.Serial('/dev/ttyUSB0', 9600)\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="serial mit timeout",
            files={"app/io.py": "import serial\ns = serial.Serial('/dev/ttyUSB0', 9600, timeout=2)\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_timeouts(ctx: Context) -> CheckResult:
    """Das Feld ist feindlich: ohne Zeitlimit hängt der Dienst still, statt
    einen fangbaren Fehler zu werfen. Ein hart abgebrochener Prozess führt
    keinen catch-Zweig aus."""
    title = "Hardware-/Netz-Zugriff ohne Zeitlimit"
    files = _py(ctx)
    if not files:
        return unmeasured("rpi.io_without_timeout", title,
                          "Keine Python-Dateien gefunden.", PLATFORM)
    calls = re.compile(
        r"\b(serial\.Serial|requests\.(?:get|post|put|delete|patch)|"
        r"urlopen|socket\.create_connection|http\.client\.HTTP\w*Connection|"
        r"subprocess\.(?:run|check_output|call|Popen))\s*\("
    )
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        for m in calls.finditer(body):
            measured += 1
            # Argumentliste per Klammerzählung herausschneiden.
            depth, i = 1, m.end()
            while i < len(body) and depth:
                if body[i] == "(":
                    depth += 1
                elif body[i] == ")":
                    depth -= 1
                i += 1
            args = body[m.end(): i]
            if re.search(r"\btimeout\s*=", args):
                continue
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="rpi.io_without_timeout", severity=Severity.ERROR,
                message=f"'{m.group(1)}' ohne timeout — der Aufruf kann still hängen.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Eigenes Zeitlimit unterhalb des Plattform-Limits setzen — "
                    "das verwandelt einen stillen Abbruch in einen fangbaren Fehler.",
                guideline="CODE_QUALITY_GUIDELINES_RASPBERRY.md § 3",
            ))
    if measured == 0:
        return unmeasured("rpi.io_without_timeout", title,
                          "Keine Hardware-/Netzaufrufe gefunden.", PLATFORM)
    return result_for("rpi.io_without_timeout", title, findings, measured,
                      "I/O-Aufrufe", PLATFORM)


@register(
    "rpi.config_not_validated_at_start",
    "Konfiguration wird gelesen, aber nicht vor dem Start geprüft",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_RASPBERRY.md § 4",
    self_tests=[
        SelfTestCase(
            name="ohne Validierung",
            files={"app/c.py": "import os\nPORT = os.environ.get('PORT')\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="mit Abbruch",
            files={"app/c.py": "import os\nPORT = os.environ.get('PORT')\nif not PORT:\n    raise ValueError('PORT fehlt')\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_config_validation(ctx: Context) -> CheckResult:
    """Ein Dienst, der mit halber Konfiguration startet, läuft — und misst
    Unsinn. Halb konfigurierte Sicherheit ist ein Abbruch, nie ein Rückfall."""
    title = "Konfiguration wird gelesen, aber nicht vor dem Start geprüft"
    files = _py(ctx)
    if not files:
        return unmeasured("rpi.config_not_validated_at_start", title,
                          "Keine Python-Dateien gefunden.", PLATFORM)
    reads = re.compile(
        r"(os\.environ(?:\.get)?|os\.getenv|configparser|yaml\.safe_load|"
        r"json\.load|tomllib\.load|dotenv)"
    )
    validates = re.compile(
        r"(?i)(raise\s+\w*(Error|Exception)|sys\.exit|SystemExit|assert\s|"
        r"pydantic|BaseModel|validate|jsonschema|voluptuous|argparse.*required)"
    )
    candidates = [sf for sf in files if reads.search(strip_comments(sf.text, sf.ext))]
    if not candidates:
        return unmeasured("rpi.config_not_validated_at_start", title,
                          "Kein Konfigurationszugriff gefunden.", PLATFORM)
    findings: list[Finding] = []
    for sf in candidates:
        body = strip_comments(sf.text, sf.ext)
        if validates.search(body):
            continue
        m = reads.search(body)
        line_no = body.count("\n", 0, m.start()) + 1
        raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
        findings.append(Finding(
            check_id="rpi.config_not_validated_at_start", severity=Severity.WARNING,
            message="Konfiguration wird gelesen, aber nirgends validiert.",
            file=sf.rel, line=line_no, evidence=snippet(raw),
            fix="Vollständigkeit und Wertebereiche beim Start prüfen und bei "
                "Lücken abbrechen — nicht mit Vorgabewerten weiterlaufen.",
            guideline="CODE_QUALITY_GUIDELINES_RASPBERRY.md § 4",
        ))
    return result_for("rpi.config_not_validated_at_start", title, findings,
                      len(candidates), "Konfigurationsmodule", PLATFORM)


@register(
    "rpi.raw_measurement_overwritten",
    "Rohmessdaten werden überschrieben statt fortgeschrieben",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_RASPBERRY.md § 5",
    self_tests=[
        SelfTestCase(
            name="Messdatei ueberschrieben",
            files={"app/m.py": "def save(v):\n    with open('rohdaten.csv', 'w') as f:\n        f.write(v)\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="angehaengt",
            files={"app/m.py": "def save(v):\n    with open('rohdaten.csv', 'a') as f:\n        f.write(v)\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_raw_data(ctx: Context) -> CheckResult:
    """Rohdaten sind unantastbar — Korrekturen als Offset danebenschreiben,
    nie den Messwert selbst ändern. Ein überschriebener Wert ist weg."""
    title = "Rohmessdaten werden überschrieben statt fortgeschrieben"
    files = _py(ctx)
    if not files:
        return unmeasured("rpi.raw_measurement_overwritten", title,
                          "Keine Python-Dateien gefunden.", PLATFORM)
    # Prüfgegenstand ist jeder Zugriff auf eine Messdatei; der Modus entscheidet
    # dann über Befund oder nicht. Nur die Verstöße zu zählen machte aus dem
    # gesunden Fall ein "nicht gemessen".
    any_open = re.compile(
        r"open\s*\(\s*([^,)]*(?:raw|roh|measure|mess|log|record|data)[^,)]*)"
        r"\s*,\s*[\"']([rwax]b?\+?)[\"']",
        re.IGNORECASE,
    )
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        for m in any_open.finditer(body):
            measured += 1
            if not m.group(2).lower().startswith("w"):
                continue
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="rpi.raw_measurement_overwritten", severity=Severity.ERROR,
                message=f"Messdatei wird im Modus '{m.group(2)}' geöffnet — "
                        "vorhandene Daten gehen verloren.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Im Anhängemodus 'a' schreiben. Korrekturen als Offset "
                    "danebenlegen, nie den Rohwert ändern.",
                guideline="CODE_QUALITY_GUIDELINES_RASPBERRY.md § 5",
            ))
    if measured == 0:
        return unmeasured("rpi.raw_measurement_overwritten", title,
                          "Keine Schreibzugriffe auf Messdateien gefunden.",
                          PLATFORM)
    return result_for("rpi.raw_measurement_overwritten", title, findings,
                      measured, "Schreibzugriffe", PLATFORM)


@register(
    "rpi.no_restart_policy",
    "Dauerbetrieb ohne Neustartregel",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_RASPBERRY.md § 8",
    self_tests=[
        SelfTestCase(
            name="Dauerlaeufer ohne Unit",
            files={"app/d.py": "while True:\n    pass\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="mit Restart",
            files={"app/d.py": "while True:\n    pass\n",
                   "deploy/app.service": "[Service]\nExecStart=/usr/bin/python3 d.py\nRestart=always\nRestartSec=5\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_restart(ctx: Context) -> CheckResult:
    """Ein Dienst im Feld muss einen Neustart überleben, ohne dass jemand
    hinfährt."""
    title = "Dauerbetrieb ohne Neustartregel"
    units = [sf for sf in ctx.all_files() if sf.ext == ".service"]
    has_loop = any(
        re.search(r"while\s+True\s*:", strip_comments(sf.text, sf.ext))
        for sf in _py(ctx)
    )
    if not has_loop:
        return unmeasured("rpi.no_restart_policy", title,
                          "Kein Dauerläufer (while True) gefunden.", PLATFORM)
    if not units:
        compose = [sf for sf in ctx.all_files()
                   if os.path.basename(sf.rel).startswith("docker-compose")]
        if compose and any("restart:" in sf.text for sf in compose):
            return result_for("rpi.no_restart_policy", title, [], len(compose),
                              "Compose-Dateien", PLATFORM)
        return result_for(
            "rpi.no_restart_policy", title,
            [Finding(
                check_id="rpi.no_restart_policy", severity=Severity.WARNING,
                message="Dauerläufer vorhanden, aber keine systemd-Unit oder "
                        "Compose-Datei mit Neustartregel.",
                fix="systemd-Unit mit 'Restart=always' und 'RestartSec=' anlegen.",
                guideline="CODE_QUALITY_GUIDELINES_RASPBERRY.md § 8",
            )], 1, "Dauerläufer", PLATFORM)
    findings: list[Finding] = []
    for sf in units:
        if re.search(r"^[ \t]*Restart\s*=\s*(always|on-failure)", sf.text, re.MULTILINE):
            continue
        findings.append(Finding(
            check_id="rpi.no_restart_policy", severity=Severity.WARNING,
            message="systemd-Unit ohne 'Restart=always'.",
            file=sf.rel,
            fix="'Restart=always' und 'RestartSec=5' ergänzen.",
            guideline="CODE_QUALITY_GUIDELINES_RASPBERRY.md § 8",
        ))
    return result_for("rpi.no_restart_policy", title, findings, len(units),
                      "systemd-Units", PLATFORM)


@register(
    "rpi.bare_except",
    "Nackter except-Block verschluckt jeden Fehler",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_RASPBERRY.md § 3",
    self_tests=[
        SelfTestCase(
            name="nackter except",
            files={"app/a.py": "def go():\n    try:\n        x = 1\n    except:\n        pass\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="mit Typ und Log",
            files={"app/a.py": "import logging\ndef go():\n    try:\n        x = 1\n    except ValueError as e:\n        logging.error(e)\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_bare_except(ctx: Context) -> CheckResult:
    """Ein except ohne Typ und ohne Logging macht aus einem Hardware-Ausfall
    ein stilles Weiterlaufen mit falschen Werten."""
    title = "Nackter except-Block verschluckt jeden Fehler"
    files = _py(ctx)
    if not files:
        return unmeasured("rpi.bare_except", title,
                          "Keine Python-Dateien gefunden.", PLATFORM)
    # Prüfgegenstand ist JEDER except-Block; nackt oder nicht entscheidet dann
    # über den Befund. Sonst meldet ein Projekt mit lauter sauberen Blöcken
    # "nicht gemessen" statt "bestanden".
    any_except = re.compile(r"^(\s*)except\b")
    bare = re.compile(r"^\s*except\s*(?:Exception\s*)?:\s*$")
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        for idx, raw in enumerate(lines):
            if not any_except.match(raw):
                continue
            measured += 1
            if not bare.match(raw):
                continue
            block = "\n".join(lines[idx + 1: idx + 6])
            if re.search(r"(?i)(log|print|raise|warn|report|track|sentry)", block):
                continue
            orig = sf.lines[idx] if idx < len(sf.lines) else raw
            findings.append(Finding(
                check_id="rpi.bare_except", severity=Severity.WARNING,
                message="except-Block ohne Typangabe und ohne Protokollierung.",
                file=sf.rel, line=idx + 1, evidence=snippet(orig),
                fix="Konkreten Fehlertyp fangen und protokollieren — sonst läuft "
                    "der Dienst mit falschen Werten weiter.",
                guideline="CODE_QUALITY_GUIDELINES_RASPBERRY.md § 3",
            ))
    if measured == 0:
        return unmeasured("rpi.bare_except", title,
                          "Keine except-Blöcke gefunden.", PLATFORM)
    return result_for("rpi.bare_except", title, findings, measured,
                      "except-Blöcke", PLATFORM)
