"""Swift bridging headers are compiled as the main precompiled-header input.

Clang diagnoses active #pragma once there, unlike an ordinary included header:
https://clang.llvm.org/docs/DiagnosticsReference.html#wpragma-once-outside-header
https://developer.apple.com/documentation/xcode/build-settings-reference
Only project-referenced headers in the scan inventory are measured. Macro paths,
excluded/missing inputs and conditional directives remain explicitly unmeasured.
"""

from __future__ import annotations

from pathlib import Path
import re

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status,
    register, result_for, strip_comments, unmeasured,
)
from ._common import PLATFORM


@register(
    "apple.bridging_header_pragma_once",
    "#pragma once im Swift-Bridging-Header",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="IOS_DEBUGGING_GUIDELINES.md § Buildort & Toolchain",
    self_tests=[
        SelfTestCase(
            name="Gesund: Include-Guard, gewöhnlicher Header mit Pragma erlaubt",
            files={"App.xcodeproj/project.pbxproj": 'SWIFT_OBJC_BRIDGING_HEADER = "App/Bridge.h";',
                   "App/Bridge.h": "#ifndef APP_BRIDGE_H\n#define APP_BRIDGE_H\n#endif\n",
                   "App/Ordinary.h": "#pragma once\n"}, expect=Status.PASS,
        ),
        SelfTestCase(
            name="Defekt: referenzierter verschachtelter Bridging-Header",
            files={"App.xcodeproj/project.pbxproj": 'SWIFT_OBJC_BRIDGING_HEADER = "App/Bridge.h";',
                   "App/Bridge.h": "/* license */\n#pragma once\n"}, expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Nur Kommentar ist gesund",
            files={"App.xcodeproj/project.pbxproj": 'SWIFT_OBJC_BRIDGING_HEADER = "$(SRCROOT)/App/Bridge.h";',
                   "App/Bridge.h": "/*\n#pragma once\n*/\n"}, expect=Status.PASS,
        ),
        SelfTestCase(
            name="Unbekannte Build-Variable bleibt ungemessen",
            files={"App.xcodeproj/project.pbxproj": 'SWIFT_OBJC_BRIDGING_HEADER = "$(CUSTOM_ROOT)/Bridge.h";',
                   "App/Bridge.h": "#pragma once\n"}, expect=Status.UNMEASURED,
        ),
        SelfTestCase(
            name="Fehlender Header bleibt ungemessen",
            files={"App.xcodeproj/project.pbxproj": 'SWIFT_OBJC_BRIDGING_HEADER = "App/Bridge.h";'},
            expect=Status.UNMEASURED,
        ),
        SelfTestCase(
            name="Inaktive Direktive ist ohne Präprozessor ungemessen",
            files={"App.xcodeproj/project.pbxproj": 'SWIFT_OBJC_BRIDGING_HEADER = "App/Bridge.h";',
                   "App/Bridge.h": "#if 0\n#pragma once\n#endif\n"}, expect=Status.UNMEASURED,
        ),
    ],
)
def check_bridging_header_pragma_once(ctx: Context) -> CheckResult:
    check_id = "apple.bridging_header_pragma_once"
    title = "#pragma once im Swift-Bridging-Header"
    root = Path(ctx.root).resolve()
    inventory = {Path(sf.path).resolve(): sf for sf in ctx.all_files()}
    headers = set()
    uncertain = False
    for sf in ctx.files(".pbxproj"):
        base = Path(sf.path).parent.parent.resolve()
        for raw in re.findall(r"\bSWIFT_OBJC_BRIDGING_HEADER\s*=\s*([^;]+);", strip_comments(sf.text, ".cpp")):
            raw = raw.strip().strip('"')
            if not raw:
                continue
            for variable in ("$(SRCROOT)", "$(PROJECT_DIR)", "${SRCROOT}", "${PROJECT_DIR}"):
                raw = raw.replace(variable, str(base))
            path = (base / raw).resolve()
            if "$" in raw or not path.is_relative_to(root) or path not in inventory:
                uncertain = True
                continue
            headers.add(path)
    findings = []
    measured = 0
    for path in sorted(headers):
        sf = inventory[path]
        body = strip_comments(sf.text, ".cpp")
        conditional = False
        unknown_directive = False
        for number, line in enumerate(body.splitlines(), 1):
            if re.match(r"\s*#\s*(if|ifdef|ifndef)\b", line):
                conditional = True
            if re.match(r"\s*#\s*pragma\s+once\b", line):
                if conditional:
                    unknown_directive = True
                    continue
                findings.append(Finding(
                    check_id=check_id, severity=Severity.WARNING, file=sf.rel, line=number,
                    message="Clang meldet beim Swift-Bridging-Header '#pragma once in main file'.",
                    fix="Include-Guard einsetzen und Lizenz sowie vorhandene Deklarationen erhalten.",
                ))
        if unknown_directive:
            uncertain = True
        else:
            measured += 1
    if uncertain and not findings:
        return unmeasured(check_id, title, "Mindestens ein Header/Pfad oder eine bedingte Direktive ist nicht offline auflösbar.", PLATFORM)
    if not measured and not findings:
        return unmeasured(check_id, title, "Kein lokal auflösbarer Swift-Bridging-Header gefunden.", PLATFORM)
    return result_for(check_id, title, findings, max(measured, len(findings)), "Bridging-Header", PLATFORM)
