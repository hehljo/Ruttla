"""Bounded existence check for literal SwiftPM local package dependencies.

Reproduced on a fresh Capacitor checkout: the Xcode product exists, but
its plugin paths point into an absent node_modules directory. Resolution fails
before any Xcode build phase can install those dependencies.
"""
from __future__ import annotations

import os
import re

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status, register,
    result_for, strip_comments, unmeasured,
)

_ID = "apple.swift_package_local_dependency_missing"
_TITLE = "Lokale Swift-Paketabhängigkeit fehlt vor der Paketauflösung"
_GUIDELINE = "docs/GUIDELINES.md § Local Swift package prerequisites"
# Skip quoted examples, including raw and multiline strings. Only the bounded
# literal .package(path:) / .package(name:path:) overload is evaluated.
_TOKENS = re.compile(
    r'(?P<string>\#*"""[\s\S]*?"""\#*|\#*"(?:\\.|[^"\\])*"\#*)'
    r'|(?P<package>\.package\s*\(\s*(?:name\s*:\s*"[^"\\\n]+"\s*,\s*)?'
    r'path\s*:\s*"(?P<path>[^"\\\n]+)"\s*\))'
)
_MAIN = 'let package = Package(dependencies: [.package(name: "Plugin", path: "../node_modules/plugin")])\n'


@register(
    _ID, _TITLE, platform="apple", severity=Severity.ERROR, guideline=_GUIDELINE,
    references=("https://docs.swift.org/package-manager/PackageDescription/PackageDescription.html",
                "https://capacitorjs.com/docs/ios/spm"),
    self_tests=[
        SelfTestCase("Healthy installed local package", {
            "App/Package.swift": _MAIN,
            "node_modules/plugin/Package.swift": "import PackageDescription\n",
        }, Status.PASS),
        SelfTestCase("Missing installed plugin directory", {
            "App/Package.swift": _MAIN,
        }, Status.FAIL, expect_finding_contains="Package.swift fehlt"),
        SelfTestCase("Directory exists but package manifest is absent", {
            "App/Package.swift": _MAIN,
            "node_modules/plugin/package.json": "{}",
        }, Status.FAIL, expect_finding_contains="Package.swift"),
        SelfTestCase("Comment only", {
            "App/Package.swift": "// " + _MAIN,
        }, Status.UNMEASURED),
        SelfTestCase("Remote package only", {
            "Package.swift": '.package(url: "https://example.com/a", from: "1.0.0")',
        }, Status.UNMEASURED),
        SelfTestCase("Computed path stays unknown", {
            "Package.swift": '.package(path: prefix + "/plugin")',
        }, Status.UNMEASURED),
        SelfTestCase("Interpolated path stays unknown", {
            "Package.swift": '.package(path: "\\(prefix)/plugin")',
        }, Status.UNMEASURED),
        SelfTestCase("Outside checkout stays unknown", {
            "Package.swift": '.package(path: "../external-plugin")',
        }, Status.UNMEASURED),
        SelfTestCase("Multiline string example is not code", {
            "Package.swift": 'let example = """\n.package(path: "missing")\n"""\n',
        }, Status.UNMEASURED),
    ],
)
def check_local_packages(ctx: Context) -> CheckResult:
    findings: list[Finding] = []
    measured = 0
    outside = 0
    root = os.path.realpath(ctx.root)
    for sf in ctx.files(".swift"):
        if os.path.basename(sf.rel) != "Package.swift":
            continue
        code = strip_comments(sf.text, ".swift")
        for match in _TOKENS.finditer(code):
            if not match.group("package"):
                continue
            path = match.group("path")
            target = os.path.realpath(os.path.join(root, os.path.dirname(sf.rel), path))
            try:
                inside = os.path.commonpath([root, target]) == root
            except ValueError:  # Different Windows drives are outside the checkout.
                inside = False
            if not inside:
                outside += 1
                continue
            measured += 1
            if not os.path.isfile(os.path.join(target, "Package.swift")):
                findings.append(Finding(
                    check_id=_ID, severity=Severity.ERROR, file=sf.rel,
                    line=code.count("\n", 0, match.start()) + 1, evidence=path,
                    message=(f"Lokales Swift-Paket {path}: Package.swift fehlt. "
                             "Xcode kann das abhängige Paketprodukt nicht auflösen."),
                    fix=("Lokales Paket vor dem Öffnen/der Paketauflösung bereitstellen; "
                         "bei node_modules zuerst npm ci, danach cap sync ausführen. "
                         "Eine Xcode-Build-Phase kommt dafür zu spät."),
                    guideline=_GUIDELINE,
                ))
    if not measured:
        return unmeasured(_ID, _TITLE,
                          "Keine innerhalb des Checkouts auflösbare literale .package(path:)-Abhängigkeit. "
                          f"Externe Pfade: {outside}; dynamische Pfade und Paketauflösung ungemessen.",
                          "apple")
    return result_for(_ID, _TITLE, findings, measured,
                      "direkte literale lokale Paketpfade (keine Paketauflösung)", "apple")
