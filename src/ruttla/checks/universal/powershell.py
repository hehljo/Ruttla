"""
PowerShell-Skripte, die eine nur in PowerShell 7 vorhandene API benutzen.

Python statt Regeldatei: die Eigenschaft ist das *Fehlen* einer
Versionssperre irgendwo in derselben Datei (drei zulässige Bauformen), das
ist kein Muster ohne Lookaround.
"""

from __future__ import annotations

import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, result_for, strip_comments,
)

CHECK_ID = "powershell.ps7_api_without_guard"
TITLE = "PowerShell-7-API ohne Versionssperre"
GUIDELINE = "GUIDELINES.md § CI and script runtimes — Laufzeitversion vor der API prüfen"

# Nur APIs, deren Fehlen in Windows PowerShell 5.1 belegt ist:
# ProcessStartInfo.ArgumentList gibt es erst ab .NET Core 2.1 (5.1 läuft auf
# .NET Framework) — belegt in Drink-and-Hide DH004-LL-003; ForEach-Object
# -Parallel ist laut Doku neu in PowerShell 7.0.
PS7_API = re.compile(r"\.ArgumentList\b|\bForEach-Object\b[^\n|]*\s-Parallel\b", re.IGNORECASE)

# Zulässige Sperren: `#Requires -Version 6+` bzw. `-PSEdition Core` oder eine
# Abfrage der Hauptversion, die das Skript mit klarer Meldung abbricht.
REQUIRES = re.compile(r"(?im)^[ \t]*#requires\s+(?:-version\s+(?:[6-9]|\d{2,})|-psedition\s+core)\b")
VERSION_QUERY = re.compile(r"\$PSVersionTable\.PSVersion\.Major\b", re.IGNORECASE)

BASE = """param([string[]]$Arguments)
$info = [System.Diagnostics.ProcessStartInfo]::new('godot')
foreach ($argument in $Arguments) { [void]$info.ArgumentList.Add($argument) }
"""


@register(
    CHECK_ID, TITLE,
    platform="universal",
    severity=Severity.WARNING,
    guideline=GUIDELINE,
    references=[
        "https://learn.microsoft.com/dotnet/api/system.diagnostics.processstartinfo.argumentlist",
        "https://learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_requires",
    ],
    rationale="Windows PowerShell 5.1 bricht an ArgumentList erst zur Laufzeit ab, "
              "mit einer Meldung, die nicht auf die Version zeigt.",
    self_tests=[
        SelfTestCase("defekt: ArgumentList ohne Sperre", {"tools/common.ps1": BASE},
                     Status.FAIL, expect_finding_contains="ArgumentList"),
        SelfTestCase("defekt: ForEach-Object -Parallel ohne Sperre",
                     {"tools/run.ps1": "1..4 | ForEach-Object -ThrottleLimit 2 -Parallel { $_ }\n"}, Status.FAIL),
        SelfTestCase("defekt: Sperre auf Version 5 reicht nicht",
                     {"tools/common.ps1": "#Requires -Version 5.1\n" + BASE}, Status.FAIL),
        SelfTestCase("gesund: #Requires -Version 7", {"tools/common.ps1": "#requires -version 7.2\n" + BASE}, Status.PASS),
        SelfTestCase("gesund: -PSEdition Core", {"tools/common.ps1": "#Requires -PSEdition Core\n" + BASE}, Status.PASS),
        SelfTestCase("gesund: Abfrage der Hauptversion",
                     {"tools/common.ps1": "if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'pwsh 7 noetig' }\n" + BASE},
                     Status.PASS),
        SelfTestCase("ungemessen: nur im Kommentar",
                     {"tools/common.ps1": "# $info.ArgumentList.Add() braucht pwsh\nWrite-Host ok\n"}, Status.UNMEASURED),
    ],
)
def check_ps7_api_without_guard(ctx: Context) -> CheckResult:
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(".ps1"):
        code = strip_comments(sf.text, sf.ext)
        hit = PS7_API.search(code)
        if not hit:
            continue
        units += 1
        if REQUIRES.search(sf.text) or VERSION_QUERY.search(code):
            continue
        line = code.count("\n", 0, hit.start()) + 1
        findings.append(Finding(
            CHECK_ID, Severity.WARNING,
            f"'{hit.group(0).strip()}' gibt es erst in PowerShell 7; unter Windows PowerShell 5.1 bricht das Skript "
            "zur Laufzeit ab, ohne die Version zu nennen.",
            file=sf.rel, line=line, evidence=sf.lines[line - 1].strip() if line <= len(sf.lines) else None,
            fix="Als erste Zeile '#Requires -Version 7' setzen (oder die Hauptversion abfragen und mit klarer "
                "Meldung abbrechen) und das Skript mit pwsh starten.",
            guideline=GUIDELINE,
        ))
    return result_for(CHECK_ID, TITLE, findings, units, "PowerShell-Skripte mit PS7-API")
