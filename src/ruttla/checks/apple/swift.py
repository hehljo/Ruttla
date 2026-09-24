"""Apple: Swift compiler traps, API availability and logging.

Split from the original checks/apple.py; background and
shared helpers in _common.py.
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
    strip_comments,
    unmeasured,
)

from ._common import _pbx_text, PLATFORM


@register(
    "apple.force_unwrap_or_try",
    "Force-Unwrap oder try! im Produktivcode",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="IOS_DEBUGGING_GUIDELINES.md § Swift-Compiler-Fallen",
    self_tests=[
        SelfTestCase(
            name="try! im Code",
            files={"App/A.swift": "import Foundation\nlet c = try! JSONDecoder().decode(X.self, from: d)\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="sauberes try",
            files={"App/A.swift": "import Foundation\nlet c = try? JSONDecoder().decode(X.self, from: d)\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_force_unwrap(ctx: Context) -> CheckResult:
    title = "Force-Unwrap oder try! im Produktivcode"
    swift = [sf for sf in ctx.files(".swift")
             if not re.search(r"(?i)(test|mock|preview|fixture|sample)", sf.rel)]
    if not swift:
        return unmeasured("apple.force_unwrap_or_try", title,
                          "Keine Produktiv-Swift-Dateien gefunden.", PLATFORM)
    try_bang = re.compile(r"\btry!\s")
    force_unwrap = re.compile(r"(?<![!=<>/*+\-])\b(\w+(?:\.\w+)*)\!(?=\s*[.,)\]\s]|$)")
    findings: list[Finding] = []
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        for m in try_bang.finditer(body):
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="apple.force_unwrap_or_try", severity=Severity.WARNING,
                message="try! stürzt bei jedem Fehler ab.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="'try?' mit Fallback oder 'do/catch' mit echter Behandlung.",
            ))
        for m in force_unwrap.finditer(body):
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            # IBOutlets und Typ-Deklarationen sind reguläres Swift.
            if re.search(r"(@IBOutlet|:\s*\w+!|as!|var\s+\w+\s*:\s*\w+!)", raw):
                continue
            if "!" in raw.split("//")[0] and re.search(r"(URL\(string:|!=|!\s*\w)", raw):
                if "!=" in raw or re.search(r"!\s*[A-Za-z_(]", raw):
                    continue
            findings.append(Finding(
                check_id="apple.force_unwrap_or_try", severity=Severity.INFO,
                message="Force-Unwrap — stürzt bei nil ab.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="'guard let' / 'if let' oder einen Vorgabewert verwenden.",
            ))
    return result_for("apple.force_unwrap_or_try", title, findings, len(swift),
                      "Swift-Dateien", PLATFORM)


@register(
    "apple.api_availability_unguarded",
    "Neue API ohne #available-Schutz gegen das Deployment-Target",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="guides/ios-api-compat.md",
    self_tests=[
        SelfTestCase(
            name="neue API ungeschuetzt",
            files={"P.xcodeproj/project.pbxproj": "IPHONEOS_DEPLOYMENT_TARGET = 16.0;\n",
                   "App/V.swift": "import SwiftUI\nstruct V: View { var body: some View { ContentUnavailableView(\"leer\", systemImage: \"x\") } }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="mit available",
            files={"P.xcodeproj/project.pbxproj": "IPHONEOS_DEPLOYMENT_TARGET = 16.0;\n",
                   "App/V.swift": "import SwiftUI\nstruct V: View { var body: some View {\n  if #available(iOS 17.0, *) {\n    ContentUnavailableView(\"leer\", systemImage: \"x\")\n  }\n} }\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_availability(ctx: Context) -> CheckResult:
    title = "Neue API ohne #available-Schutz gegen das Deployment-Target"
    pbx = _pbx_text(ctx)
    if not pbx:
        return unmeasured("apple.api_availability_unguarded", title,
                          "Kein .xcodeproj — Deployment-Target nicht ermittelbar.",
                          PLATFORM)
    content, _ = pbx
    targets = [
        float(v) for v in re.findall(
            r"IPHONEOS_DEPLOYMENT_TARGET\s*=\s*([\d.]+);", content)
    ]
    if not targets:
        return unmeasured("apple.api_availability_unguarded", title,
                          "IPHONEOS_DEPLOYMENT_TARGET nicht gefunden.", PLATFORM)
    min_target = min(targets)
    # API -> ab welcher iOS-Version verfügbar
    api_since = {
        r"\.scrollTargetBehavior\b": 17.0,
        r"\bContentUnavailableView\b": 17.0,
        r"\.symbolEffect\(": 17.0,
        r"\bObservable\b(?=\s*\(|\s*macro)": 17.0,
        r"\.onScrollGeometryChange\b": 18.0,
        r"\bTabViewBottomAccessory\b": 18.0,
        r"\.glassEffect\b": 26.0,
        r"\bGlassEffectContainer\b": 26.0,
    }
    swift = ctx.files(".swift")
    findings: list[Finding] = []
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        for pat, since in api_since.items():
            if since <= min_target:
                continue
            for m in re.finditer(pat, body):
                line_no = body.count("\n", 0, m.start()) + 1
                window = "\n".join(lines[max(0, line_no - 12): line_no + 1])
                if re.search(r"#available|@available", window):
                    continue
                raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
                findings.append(Finding(
                    check_id="apple.api_availability_unguarded",
                    severity=Severity.WARNING,
                    message=f"API braucht iOS {since}, Deployment-Target ist "
                            f"{min_target}.",
                    file=sf.rel, line=line_no, evidence=snippet(raw),
                    fix=f"In 'if #available(iOS {since}, *)' einschließen oder das "
                        "Deployment-Target anheben.",
                    guideline="guides/ios-api-compat.md",
                ))
    return result_for("apple.api_availability_unguarded", title, findings,
                      len(swift), "Swift-Dateien", PLATFORM)


@register(
    "apple.print_in_production",
    "print() statt Logger im Produktivcode",
    platform=PLATFORM,
    severity=Severity.INFO,
    guideline="IOS_DEBUGGING_GUIDELINES.md § Dateisystem & Logging",
    self_tests=[
        SelfTestCase(
            name="print ungeschuetzt",
            files={"App/Service.swift": "import Foundation\nfunc go() { print(\"start\") }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="print hinter DEBUG",
            files={"App/Service.swift": "import Foundation\nfunc go() {\n#if DEBUG\n  print(\"start\")\n#endif\n}\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_print(ctx: Context) -> CheckResult:
    title = "print() statt Logger im Produktivcode"
    swift = [sf for sf in ctx.files(".swift")
             if not re.search(r"(?i)(test|mock|preview|debug|sample)", sf.rel)]
    if not swift:
        return unmeasured("apple.print_in_production", title,
                          "Keine Produktiv-Swift-Dateien gefunden.", PLATFORM)
    pat = re.compile(r"(?<![\w.])print\s*\(")
    findings: list[Finding] = []
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        for m in pat.finditer(body):
            line_no = body.count("\n", 0, m.start()) + 1
            window = "\n".join(lines[max(0, line_no - 4): line_no])
            if "#if DEBUG" in window:
                continue
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="apple.print_in_production", severity=Severity.INFO,
                message="print() im Produktivcode.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="os.Logger verwenden oder in '#if DEBUG' einschließen.",
            ))
    return result_for("apple.print_in_production", title, findings, len(swift),
                      "Swift-Dateien", PLATFORM)
