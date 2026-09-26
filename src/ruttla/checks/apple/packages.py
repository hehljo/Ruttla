"""Apple: Swift-Paketauflösung eines App-Projekts muss eingecheckt sein.

Belegt am 26.09.2026 (tvOS/iOS-Mediaplayer mit einem Remote-Paket): der
Xcode-Cloud-Build brach ab mit „a resolved file is required when automatic
dependency resolution is disabled and should be placed at
…/<App>.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved".
Ursache: `*.resolved` stand in `.gitignore`. Lokal und in einer
GitHub-CI mit `-resolvePackageDependencies` fiel das nie auf, weil dort
automatisch aufgelöst wird. Xcode Cloud schaltet das ab und verlangt die
eingecheckte Datei.
"""

from __future__ import annotations

import fnmatch
import os

from ruttla.core import (
    CheckResult,
    Context,
    Finding,
    register,
    result_for,
    SelfTestCase,
    Severity,
    Status,
    to_posix,
    unmeasured,
)

from ._common import PLATFORM

_REMOTE_PACKAGE = "XCRemoteSwiftPackageReference"
_RESOLVED_IN_PROJECT = os.path.join("project.xcworkspace", "xcshareddata", "swiftpm",
                                    "Package.resolved")


def _gitignore_rules(root: str, rel_dir: str) -> list[tuple[str, str]]:
    """(Basisverzeichnis, Zeile) aller .gitignore-Dateien von der Wurzel bis
    rel_dir, in der Reihenfolge, in der Git sie anwendet."""
    rules: list[tuple[str, str]] = []
    parts = [p for p in to_posix(rel_dir).split("/") if p and p != "."]
    for depth in range(len(parts) + 1):
        base = "/".join(parts[:depth])
        path = os.path.join(root, base, ".gitignore")
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.rstrip("\n").rstrip()
                    if line and not line.startswith("#"):
                        rules.append((base, line))
        except OSError:
            continue
    return rules


def _ignored_by(rel_path: str, rules: list[tuple[str, str]]) -> str | None:
    """Letzte zutreffende Regel gewinnt; eine Negation hebt auf. Liefert die
    Regel, die den Pfad ignoriert, oder None."""
    rel_path = to_posix(rel_path)
    hit: str | None = None
    for base, pattern in rules:
        negate = pattern.startswith("!")
        pat = pattern[1:] if negate else pattern
        pat = pat.rstrip("/")
        sub = rel_path[len(base) + 1:] if base else rel_path
        if base and not rel_path.startswith(base + "/"):
            continue
        if "/" in pat.lstrip("/"):
            match = fnmatch.fnmatch(sub, pat.lstrip("/").replace("**/", "*"))
        else:
            match = any(fnmatch.fnmatch(seg, pat) for seg in sub.split("/"))
        if match:
            hit = None if negate else pattern
    return hit


_PBX_WITH_PACKAGE = (
    "/* Begin XCRemoteSwiftPackageReference section */\n"
    "\t\tA1 /* XCRemoteSwiftPackageReference \"Kit\" */ = {\n"
    "\t\t\tisa = XCRemoteSwiftPackageReference;\n"
    "\t\t\trepositoryURL = \"https://example.com/kit\";\n\t\t};\n"
)
_RESOLVED = '{\n  "pins" : [ ],\n  "version" : 2\n}\n'
_RESOLVED_PATH = "App.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"


@register(
    "apple.package_resolved_not_committed",
    "Package.resolved eines App-Projekts fehlt oder wird von .gitignore ausgeschlossen",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="IOS_DEBUGGING_GUIDELINES.md § Version Control",
    self_tests=[
        SelfTestCase(
            name="Remote-Paket, *.resolved in .gitignore",
            files={"App.xcodeproj/project.pbxproj": _PBX_WITH_PACKAGE,
                   _RESOLVED_PATH: _RESOLVED,
                   ".gitignore": ".build/\n*.resolved\n"},
            expect=Status.FAIL,
            expect_finding_contains="*.resolved",
        ),
        SelfTestCase(
            name="Remote-Paket, Package.resolved fehlt",
            files={"App.xcodeproj/project.pbxproj": _PBX_WITH_PACKAGE,
                   ".gitignore": ".build/\n"},
            expect=Status.FAIL,
            expect_finding_contains="fehlt",
        ),
        SelfTestCase(
            name="Remote-Paket, Datei da und per Negation freigegeben",
            files={"App.xcodeproj/project.pbxproj": _PBX_WITH_PACKAGE,
                   _RESOLVED_PATH: _RESOLVED,
                   ".gitignore": ".build/\n*.resolved\n!" + _RESOLVED_PATH + "\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Projekt ohne Remote-Paket",
            files={"App.xcodeproj/project.pbxproj": "isa = PBXNativeTarget;\n",
                   ".gitignore": "*.resolved\n"},
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_package_resolved(ctx: Context) -> CheckResult:
    """Gemessen wird je Xcode-Projekt mit Remote-Paket, ob die Auflösung dort
    liegt, wo Xcode sie sucht, und ob Git sie überhaupt aufnehmen würde.
    Reine Swift-Pakete (Package.swift ohne .xcodeproj) sind ausgenommen: für
    Bibliotheken ist ein nicht eingechecktes Package.resolved üblich."""
    cid = "apple.package_resolved_not_committed"
    title = "Package.resolved nicht eingecheckt"
    projects = [d for d in ctx.dirs_with_suffix(".xcodeproj")
                if os.path.isfile(os.path.join(d, "project.pbxproj"))]
    candidates = []
    for proj in projects:
        try:
            with open(os.path.join(proj, "project.pbxproj"), "r",
                      encoding="utf-8", errors="replace") as fh:
                if _REMOTE_PACKAGE in fh.read():
                    candidates.append(proj)
        except OSError:
            continue
    if not candidates:
        return unmeasured(cid, title, "Kein Xcode-Projekt mit Remote-Swift-Paket gefunden.",
                          PLATFORM)

    findings: list[Finding] = []
    for proj in candidates:
        rel_proj = to_posix(os.path.relpath(proj, ctx.root))
        paths = [os.path.join(proj, _RESOLVED_IN_PROJECT)]
        # Liegt daneben ein Workspace gleichen Namens, benutzt Xcode dessen Datei.
        ws = os.path.splitext(proj)[0] + ".xcworkspace"
        if os.path.isdir(ws):
            paths.insert(0, os.path.join(ws, "xcshareddata", "swiftpm", "Package.resolved"))
        existing = [p for p in paths if os.path.isfile(p)]
        target = existing[0] if existing else paths[0]
        rel_target = to_posix(os.path.relpath(target, ctx.root))
        if not existing:
            findings.append(Finding(
                check_id=cid, severity=Severity.ERROR,
                message=(f"{rel_proj} nutzt Remote-Swift-Pakete, aber {rel_target} fehlt. "
                         "Xcode Cloud (und jeder Build mit "
                         "-disableAutomaticPackageResolution) bricht ab: "
                         "\"a resolved file is required when automatic dependency "
                         "resolution is disabled\"."),
                file=rel_proj + "/project.pbxproj", line=1,
                evidence=_REMOTE_PACKAGE,
                fix="Pakete in Xcode einmal auflösen (File → Packages → Resolve Package "
                    "Versions) und die entstandene Package.resolved committen.",
                guideline="IOS_DEBUGGING_GUIDELINES.md § Version Control",
            ))
            continue
        rule = _ignored_by(rel_target, _gitignore_rules(ctx.root, os.path.dirname(rel_target)))
        if rule:
            findings.append(Finding(
                check_id=cid, severity=Severity.ERROR,
                message=(f"{rel_target} wird von der .gitignore-Regel '{rule}' ausgeschlossen "
                         "und landet nie im Repo. Xcode Cloud bricht ab: \"a resolved file "
                         "is required when automatic dependency resolution is disabled\"."),
                file=".gitignore", line=1, evidence=rule,
                fix=f"Ausnahme ergänzen: '!{rel_target}' unter die Regel '{rule}' "
                    "schreiben und die Datei committen.",
                guideline="IOS_DEBUGGING_GUIDELINES.md § Version Control",
            ))
    return result_for(cid, title, findings, len(candidates),
                      "Xcode-Projekte mit Remote-Paketen", PLATFORM)
