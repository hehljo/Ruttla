"""Godot export checks (iOS, Android, Web).

Split from rules.py to maintain modularity.
"""

from __future__ import annotations

import re

from ruttla.core import (
    CheckResult,
    Context,
    Finding,
    register,
    result_for,
    SelfTestCase,
    Severity,
    snippet,
    Status,
    unmeasured,
)

PLATFORM = "godot"


@register(
    "godot.ios_pck_ignored_in_gitignore",
    "Exportierte Godot .pck Datei für iOS-Xcode-Projekt wird durch .gitignore ignoriert (bricht Xcode-Build ab)",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Multiplattform & Export",
    self_tests=[
        SelfTestCase(
            name="iOS pck in gitignore ignoriert",
            files={
                "project.godot": 'config/name="Game"\n',
                "ios/game.xcodeproj/project.pbxproj": "// Xcode project\n",
                ".gitignore": "ios/*.pck\n",
            },
            expect=Status.FAIL,
            expect_finding_contains="pck",
        ),
        SelfTestCase(
            name="iOS pck nicht ignoriert",
            files={
                "project.godot": 'config/name="Game"\n',
                "ios/game.xcodeproj/project.pbxproj": "// Xcode project\n",
                ".gitignore": "build/\n",
            },
            expect=Status.PASS,
        ),
    ],
)
def check_ios_pck_ignored_in_gitignore(ctx: Context) -> CheckResult:
    """Wenn ein Godot-Projekt nach iOS exportiert wird, generiert Godot eine
    .pck-Datei (z. B. ios/game.pck), die zwingend von Xcode ins App-Bundle kopiert
    werden muss. Steht *.pck oder ios/*.pck in der .gitignore, fehlt die Datei nach
    einem Git-Clone auf dem Mac und der Xcode-Build bricht mit 'The file *.pck couldn't
    be opened because there is no such file' ab."""
    title = "iOS-Export .pck in .gitignore ignoriert"
    xcode_projects = [sf for sf in ctx.all_files() if sf.rel.endswith(".xcodeproj/project.pbxproj")]
    if not xcode_projects:
        return unmeasured("godot.ios_pck_ignored_in_gitignore", title,
                          "Kein iOS-Xcode-Projekt gefunden.", PLATFORM)

    gitignore_files = ctx.files_named(".gitignore")
    if not gitignore_files:
        return unmeasured("godot.ios_pck_ignored_in_gitignore", title,
                          "Keine .gitignore gefunden.", PLATFORM)

    findings: list[Finding] = []
    pck_ignore_pat = re.compile(r'^\s*([^#\n]*\b(?:ios/)?[\w\*\-]*\.pck\b)', re.MULTILINE)

    for gi in gitignore_files:
        for idx, line in enumerate(gi.lines, start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if ".pck" in stripped:
                m = pck_ignore_pat.search(stripped)
                if m:
                    findings.append(Finding(
                        check_id="godot.ios_pck_ignored_in_gitignore",
                        severity=Severity.ERROR,
                        message=f".pck-Datei für iOS-Export wird durch .gitignore-Regel '{stripped}' ignoriert — bricht Xcode-Build ab.",
                        file=gi.rel,
                        line=idx,
                        evidence=snippet(line),
                        fix="Entferne die .pck-Ignore-Regel aus .gitignore oder erlaube '!ios/*.pck', damit Xcode die Spieldaten findet.",
                        guideline="CODE_QUALITY_GUIDELINES_GAMEDEV.md § Multiplattform & Export",
                    ))

    return result_for("godot.ios_pck_ignored_in_gitignore", title, findings, len(xcode_projects),
                      "iOS-Xcode-Projekte", PLATFORM)
