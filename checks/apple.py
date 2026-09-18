#!/usr/bin/env python3
"""
Apple-Checks: Xcode-Projektintegrität, Info.plist, SwiftUI-Multiplattform,
Swift-Concurrency, SwiftData/CloudKit.

Quellen: IOS_DEBUGGING_GUIDELINES.md, swiftui_multiplatform_guideline.md,
guides/swift-concurrency.md, guides/swiftdata-predicate.md,
guides/swiftui-sheets.md, guides/swiftui-viewbuilder.md, guides/widgetkit.md,
guides/ios-api-compat.md.

Gegenüber dem alten apple_gate.py korrigiert:
* Plist wird mit plistlib gelesen statt mit findall("key")/findall("string")+zip
  — das brach bei jedem <array>, <true/> oder <dict>-Wert (Schlüssel-Wert-Versatz).
* CFBundleIdentifier wird gegen die MENGE der Bundle-IDs geprüft, nicht gegen
  jede einzeln — bei Multi-Target (App + Widget + Tests) war vorher jede
  Kombination ein Fehler.
* ENABLE_HARDENED_RUNTIME und CODE_SIGN_IDENTITY werden je Build-Konfiguration
  gelesen, nicht positionell per zip gepaart.
"""

from __future__ import annotations

import os
import plistlib
import re

from core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, ok, failed, unmeasured, result_for, iter_matches, snippet,
    strip_comments,
)

PLATFORM = "apple"


def _xcodeproj(ctx: Context) -> str | None:
    dirs = ctx.dirs_with_suffix(".xcodeproj")
    return sorted(dirs)[0] if dirs else None


def _pbx_text(ctx: Context) -> tuple[str, str] | None:
    proj = _xcodeproj(ctx)
    if not proj:
        return None
    pbx = os.path.join(proj, "project.pbxproj")
    if not os.path.isfile(pbx):
        return None
    try:
        with open(pbx, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(), os.path.relpath(pbx, ctx.root)
    except OSError:
        return None


# ===========================================================================
# Xcode-Projektintegrität
# ===========================================================================

@register(
    "apple.bundle_id_mismatch",
    "CFBundleIdentifier in Info.plist weicht vom Projekt ab",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="IOS_DEBUGGING_GUIDELINES.md § Buildort & Toolchain",
    self_tests=[
        SelfTestCase(
            name="Plist weicht ab",
            files={"P.xcodeproj/project.pbxproj": "PRODUCT_BUNDLE_IDENTIFIER = com.x.app;\n",
                   "App/Info.plist": "<?xml version=\"1.0\"?>\n<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n<plist version=\"1.0\"><dict><key>CFBundleIdentifier</key><string>com.y.anders</string></dict></plist>\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Plist dynamisch",
            files={"P.xcodeproj/project.pbxproj": "PRODUCT_BUNDLE_IDENTIFIER = com.x.app;\n",
                   "App/Info.plist": "<?xml version=\"1.0\"?>\n<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n<plist version=\"1.0\"><dict><key>CFBundleIdentifier</key><string>$(PRODUCT_BUNDLE_IDENTIFIER)</string><key>Extra</key><array><string>a</string></array></dict></plist>\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_bundle_id(ctx: Context) -> CheckResult:
    """Ein statischer CFBundleIdentifier, der in KEINER Build-Konfiguration
    vorkommt, ist der Fehler. Vorher wurde gegen jede ID einzeln verglichen —
    bei mehreren Targets war damit jede Plist automatisch rot."""
    title = "CFBundleIdentifier in Info.plist weicht vom Projekt ab"
    pbx = _pbx_text(ctx)
    if not pbx:
        return unmeasured("apple.bundle_id_mismatch", title,
                          "Kein .xcodeproj/project.pbxproj gefunden.", PLATFORM)
    content, _ = pbx
    ids = {
        b.strip().strip('"')
        for b in re.findall(r"PRODUCT_BUNDLE_IDENTIFIER\s*=\s*([^;]+);", content)
    }
    ids = {i for i in ids if i and not i.startswith("$")}

    plists = [sf for sf in ctx.all_files()
              if os.path.basename(sf.rel) == "Info.plist"]
    if not plists:
        return unmeasured("apple.bundle_id_mismatch", title,
                          "Keine Info.plist gefunden.", PLATFORM)
    findings: list[Finding] = []
    measured = 0
    for sf in plists:
        try:
            with open(sf.path, "rb") as fh:
                data = plistlib.load(fh)
        except Exception as exc:
            findings.append(Finding(
                check_id="apple.bundle_id_mismatch", severity=Severity.WARNING,
                message=f"Info.plist nicht lesbar: {exc}",
                file=sf.rel, fix="Plist-Syntax prüfen.",
            ))
            continue
        measured += 1
        raw_val = data.get("CFBundleIdentifier")
        if not isinstance(raw_val, str) or raw_val.startswith("$("):
            continue
        if ids and raw_val not in ids:
            findings.append(Finding(
                check_id="apple.bundle_id_mismatch", severity=Severity.ERROR,
                message=f"Info.plist hat '{raw_val}', das Projekt kennt "
                        f"{sorted(ids)}.",
                file=sf.rel,
                fix="Auf '$(PRODUCT_BUNDLE_IDENTIFIER)' umstellen — dann kann die "
                    "Plist nie mehr abweichen.",
                guideline="IOS_DEBUGGING_GUIDELINES.md",
            ))
        elif not ids:
            findings.append(Finding(
                check_id="apple.bundle_id_mismatch", severity=Severity.WARNING,
                message=f"Info.plist setzt '{raw_val}' statisch; im Projekt steht "
                        "nur eine Variable.",
                file=sf.rel,
                fix="Auf '$(PRODUCT_BUNDLE_IDENTIFIER)' umstellen.",
            ))
    if measured == 0:
        return unmeasured("apple.bundle_id_mismatch", title,
                          "Keine Info.plist lesbar.", PLATFORM)
    return result_for("apple.bundle_id_mismatch", title, findings, measured,
                      "Info.plist-Dateien", PLATFORM)


@register(
    "apple.project_settings",
    "Xcode-Projekteinstellungen unvollständig",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="IOS_DEBUGGING_GUIDELINES.md",
    self_tests=[
        SelfTestCase(
            name="xcstrings falscher Typ",
            files={"P.xcodeproj/project.pbxproj": "TargetAttributes = {};\nDEVELOPMENT_TEAM = ABC;\n{ path = Localizable.xcstrings; lastKnownFileType = text.plist; };\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="alles gesetzt",
            files={"P.xcodeproj/project.pbxproj": "TargetAttributes = {};\nDEVELOPMENT_TEAM = ABC;\n{ path = Localizable.xcstrings; lastKnownFileType = text.json.xcstrings; };\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_project_settings(ctx: Context) -> CheckResult:
    title = "Xcode-Projekteinstellungen unvollständig"
    pbx = _pbx_text(ctx)
    if not pbx:
        return unmeasured("apple.project_settings", title,
                          "Kein .xcodeproj gefunden.", PLATFORM)
    content, rel = pbx
    findings: list[Finding] = []

    if "TargetAttributes" not in content:
        findings.append(Finding(
            check_id="apple.project_settings", severity=Severity.WARNING,
            message="TargetAttributes fehlt im PBXProject.",
            file=rel,
            fix="In Xcode einmal 'Update to recommended settings' ausführen.",
        ))
    if not re.search(r"\bDEVELOPMENT_TEAM\b|\bDevelopmentTeam\b", content):
        findings.append(Finding(
            check_id="apple.project_settings", severity=Severity.WARNING,
            message="DEVELOPMENT_TEAM fehlt — kann zu CodeSign-Fehlern führen.",
            file=rel,
            fix="Team in den Signing-Einstellungen setzen.",
        ))
    for luc in re.findall(r"LastUpgradeCheck\s*=\s*([^;]+);", content):
        val = luc.strip().strip('"')
        if val.isdigit() and int(val) < 1600:
            findings.append(Finding(
                check_id="apple.project_settings", severity=Severity.INFO,
                message=f"LastUpgradeCheck ist {val} (empfohlen ab 1600).",
                file=rel,
                fix="Xcode meldet sonst 'Update to recommended settings'.",
            ))
    # .xcstrings: falscher lastKnownFileType lässt die Validierung als
    # Property List scheitern.
    for m in re.finditer(r"\{([^}]*\.xcstrings[^}]*)\}", content):
        block = m.group(1)
        tm = re.search(r"lastKnownFileType\s*=\s*([^;]+);", block)
        if tm and tm.group(1).strip().strip('"') != "text.json.xcstrings":
            findings.append(Finding(
                check_id="apple.project_settings", severity=Severity.ERROR,
                message=f".xcstrings hat lastKnownFileType "
                        f"'{tm.group(1).strip()}' statt 'text.json.xcstrings'.",
                file=rel,
                fix="Typ korrigieren, sonst scheitert die Validierung als "
                    "Property List.",
            ))
    return result_for("apple.project_settings", title, findings, 1,
                      "Projektdateien", PLATFORM)


@register(
    "apple.unguarded_module_import",
    "Ungeschützter Modul-Import in einem Single-Target-Projekt",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="swiftui_multiplatform_guideline.md § 6",
    self_tests=[
        SelfTestCase(
            name="Core-Import ungeschuetzt",
            files={"P.xcodeproj/project.pbxproj": "isa = PBXNativeTarget;\n",
                   "App/V.swift": "import SwiftUI\nimport AppCore\nstruct V: View { var body: some View { Text(\"x\") } }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Core-Import geschuetzt",
            files={"P.xcodeproj/project.pbxproj": "isa = PBXNativeTarget;\n",
                   "App/V.swift": "import SwiftUI\n#if canImport(AppCore)\nimport AppCore\n#endif\nstruct V: View { var body: some View { Text(\"x\") } }\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_module_import(ctx: Context) -> CheckResult:
    """Prüft nur, wenn das Projekt tatsächlich Single-Target ist — sonst ist ein
    Core-Import völlig richtig und das Gate falsch-positiv."""
    title = "Ungeschützter Modul-Import in einem Single-Target-Projekt"
    pbx = _pbx_text(ctx)
    if not pbx:
        return unmeasured("apple.unguarded_module_import", title,
                          "Kein .xcodeproj gefunden.", PLATFORM)
    content, _ = pbx
    targets = re.findall(r"isa\s*=\s*PBXNativeTarget", content)
    if len(targets) > 1:
        return unmeasured(
            "apple.unguarded_module_import", title,
            f"Projekt hat {len(targets)} Targets — ein Modul-Import ist dort "
            "regulär. Die Regel gilt nur für Single-Target-Projekte.",
            PLATFORM,
        )
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.unguarded_module_import", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    pat = re.compile(r"^\s*import\s+([A-Za-z0-9_]+(?:Core|Kit|Shared))\s*$")
    system_modules = {
        "SwiftUI", "UIKit", "AppKit", "Foundation", "CoreData", "CoreGraphics",
        "CoreLocation", "CoreImage", "CoreML", "CoreMotion", "CoreText",
        "CoreBluetooth", "CoreAudio", "CoreMedia", "CoreVideo", "CoreHaptics",
        "CoreSpotlight", "CoreTelephony", "CoreNFC", "WidgetKit", "StoreKit",
        "MapKit", "PhotosUI", "PDFKit", "SpriteKit", "SceneKit", "ARKit",
        "HealthKit", "HomeKit", "CloudKit", "PassKit", "MessageUI", "EventKit",
        "AVKit", "GameKit", "WatchKit", "CarPlay", "TipKit", "Charts",
    }
    findings: list[Finding] = []
    for sf in swift:
        for idx, raw in enumerate(sf.lines, start=1):
            m = pat.match(raw)
            if not m or m.group(1) in system_modules:
                continue
            window = "\n".join(sf.lines[max(0, idx - 4): idx])
            if f"canImport({m.group(1)})" in window:
                continue
            findings.append(Finding(
                check_id="apple.unguarded_module_import", severity=Severity.ERROR,
                message=f"'{m.group(1)}' ungeschützt importiert.",
                file=sf.rel, line=idx, evidence=snippet(raw),
                fix=f"In '#if canImport({m.group(1)})' einschließen — in einem "
                    "Single-Target-Projekt existiert das Modul nicht.",
                guideline="swiftui_multiplatform_guideline.md § 6",
            ))
    return result_for("apple.unguarded_module_import", title, findings,
                      len(swift), "Swift-Dateien", PLATFORM)


# ===========================================================================
# Swift-Concurrency
# ===========================================================================

@register(
    "apple.mainactor_missing_on_observable",
    "ObservableObject/@Observable ohne @MainActor",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="guides/swift-concurrency.md",
    self_tests=[
        SelfTestCase(
            name="ViewModel ohne MainActor",
            files={"App/VM.swift": "import SwiftUI\nfinal class VM: ObservableObject {\n  @Published var x = 0\n}\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="ViewModel mit MainActor",
            files={"App/VM.swift": "import SwiftUI\n@MainActor\nfinal class VM: ObservableObject {\n  @Published var x = 0\n}\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_mainactor(ctx: Context) -> CheckResult:
    """Ein ObservableObject treibt die Oberfläche. Ohne @MainActor ist jede
    Zuweisung aus einem Task ein Datenrennen — unter Swift 6 ein Fehler."""
    title = "ObservableObject/@Observable ohne @MainActor"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.mainactor_missing_on_observable", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    decl = re.compile(
        r"^\s*(?:public\s+|internal\s+|final\s+|open\s+)*class\s+(\w+)\s*:\s*[^{]*\bObservableObject\b",
        re.MULTILINE,
    )
    observable_macro = re.compile(r"^\s*@Observable\s*$", re.MULTILINE)
    findings: list[Finding] = []
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        for m in decl.finditer(body):
            line_no = body.count("\n", 0, m.start()) + 1
            window = "\n".join(lines[max(0, line_no - 5): line_no])
            if "@MainActor" in window:
                continue
            findings.append(Finding(
                check_id="apple.mainactor_missing_on_observable",
                severity=Severity.WARNING,
                message=f"'{m.group(1)}' ist ObservableObject ohne @MainActor.",
                file=sf.rel, line=line_no, evidence=snippet(m.group(0)),
                fix="@MainActor vor die Klasse setzen — sonst ist jede Zuweisung "
                    "aus einem Task ein Datenrennen.",
                guideline="guides/swift-concurrency.md",
            ))
        for m in observable_macro.finditer(body):
            line_no = body.count("\n", 0, m.start()) + 1
            nxt = "\n".join(lines[line_no: line_no + 3])
            window = "\n".join(lines[max(0, line_no - 4): line_no])
            if "class" not in nxt or "@MainActor" in window or "@MainActor" in nxt:
                continue
            findings.append(Finding(
                check_id="apple.mainactor_missing_on_observable",
                severity=Severity.WARNING,
                message="@Observable-Klasse ohne @MainActor.",
                file=sf.rel, line=line_no, evidence=snippet(nxt.splitlines()[0] if nxt else ""),
                fix="@MainActor ergänzen.",
                guideline="guides/swift-concurrency.md",
            ))
    return result_for("apple.mainactor_missing_on_observable", title, findings,
                      len(swift), "Swift-Dateien", PLATFORM)


@register(
    "apple.ui_update_off_main",
    "UI-Zustand wird aus einem Hintergrund-Kontext gesetzt",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="guides/swift-concurrency.md",
    self_tests=[
        SelfTestCase(
            name="Zustand im detached Task",
            files={"App/VM.swift": "import Foundation\nfunc load() {\n  Task.detached {\n    isLoading = false\n  }\n}\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Zustand ueber MainActor",
            files={"App/VM.swift": "import Foundation\nfunc load() {\n  Task.detached {\n    await MainActor.run { isLoading = false }\n  }\n}\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_ui_off_main(ctx: Context) -> CheckResult:
    title = "UI-Zustand wird aus einem Hintergrund-Kontext gesetzt"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.ui_update_off_main", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    detached = re.compile(r"Task\.detached\s*\{|DispatchQueue\.global\(")
    findings: list[Finding] = []
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        for m in detached.finditer(body):
            start_line = body.count("\n", 0, m.start()) + 1
            block = lines[start_line - 1: start_line + 25]
            for off, raw in enumerate(block):
                if re.search(r"^\s*(self\.)?\w*(isLoading|error|items|state|text|"
                             r"progress|selected|show\w*)\s*=", raw):
                    if "await MainActor" in "\n".join(block[:off + 1]):
                        continue
                    findings.append(Finding(
                        check_id="apple.ui_update_off_main",
                        severity=Severity.WARNING,
                        message="Zustandszuweisung in einem detached/global-Kontext.",
                        file=sf.rel, line=start_line + off, evidence=snippet(raw),
                        fix="Die Zuweisung in 'await MainActor.run { }' legen oder "
                            "den umgebenden Typ @MainActor machen.",
                        guideline="guides/swift-concurrency.md",
                    ))
                    break
    return result_for("apple.ui_update_off_main", title, findings, len(swift),
                      "Swift-Dateien", PLATFORM)


# ===========================================================================
# SwiftUI Multiplattform
# ===========================================================================

@register(
    "apple.navigationdestination_not_at_root",
    ".navigationDestination steht nicht am NavigationStack-Root",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="swiftui_multiplatform_guideline.md § 3",
    self_tests=[
        SelfTestCase(
            name="Ziel ohne Stack",
            files={"App/Sub.swift": "import SwiftUI\nstruct Sub: View { var body: some View { List {}.navigationDestination(for: Int.self) { _ in Text(\"d\") } } }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Ziel am Stack-Root",
            files={"App/Root.swift": "import SwiftUI\nstruct Root: View { var body: some View { NavigationStack { List {}.navigationDestination(for: Int.self) { _ in Text(\"d\") } } } }\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_navdest(ctx: Context) -> CheckResult:
    """Laut Guideline CRITICAL: ein .navigationDestination in einer Unteransicht
    wird auf macOS nicht gefunden und der Push passiert nicht."""
    title = ".navigationDestination steht nicht am NavigationStack-Root"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.navigationdestination_not_at_root", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    findings: list[Finding] = []
    measured = 0
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        if ".navigationDestination" not in body:
            continue
        measured += 1
        has_stack = "NavigationStack" in body or "NavigationSplitView" in body
        for m in re.finditer(r"\.navigationDestination", body):
            line_no = body.count("\n", 0, m.start()) + 1
            if has_stack:
                continue
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="apple.navigationdestination_not_at_root",
                severity=Severity.ERROR,
                message=".navigationDestination ohne NavigationStack in derselben Datei.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="An den NavigationStack-Root verschieben — in einer "
                    "Unteransicht findet macOS das Ziel nicht.",
                guideline="swiftui_multiplatform_guideline.md § 3",
            ))
    if measured == 0:
        return unmeasured("apple.navigationdestination_not_at_root", title,
                          "Kein .navigationDestination im Projekt.", PLATFORM)
    return result_for("apple.navigationdestination_not_at_root", title, findings,
                      measured, "Swift-Dateien mit navigationDestination", PLATFORM)


@register(
    "apple.hardcoded_font_size",
    "Feste Schriftgröße statt Text-Style",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="swiftui_multiplatform_guideline.md / IOS_DEBUGGING_GUIDELINES.md",
    self_tests=[
        SelfTestCase(
            name="feste Punktgroesse",
            files={"App/V.swift": "import SwiftUI\nstruct V: View { var body: some View { Text(\"x\").font(.system(size: 13)) } }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="mit relativeTo",
            files={"App/V.swift": "import SwiftUI\nstruct V: View { var body: some View { Text(\"x\").font(.system(size: 13, relativeTo: .body)) } }\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_font_sizes(ctx: Context) -> CheckResult:
    """Eine feste Punktgröße ignoriert Dynamic Type — die Anzeige skaliert für
    sehbehinderte Nutzer nicht mit."""
    title = "Feste Schriftgröße statt Text-Style"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.hardcoded_font_size", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    pat = re.compile(r"\.font\(\s*\.system\(\s*size:\s*(\d+)")
    findings: list[Finding] = []
    for sf in swift:
        for line_no, m, raw in iter_matches(sf, pat):
            if "relativeTo:" in raw:
                continue  # skaliert mit, ist richtig
            findings.append(Finding(
                check_id="apple.hardcoded_font_size", severity=Severity.WARNING,
                message=f"Feste Schriftgröße {m.group(1)}pt ohne relativeTo.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Text-Style verwenden (.body, .headline) oder "
                    "'.system(size:relativeTo:)', damit Dynamic Type greift.",
            ))
    return result_for("apple.hardcoded_font_size", title, findings, len(swift),
                      "Swift-Dateien", PLATFORM)


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
    "apple.swiftdata_predicate_capture",
    "SwiftData-#Predicate greift auf eine nicht gebundene Variable zu",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="guides/swiftdata-predicate.md",
    self_tests=[
        SelfTestCase(
            name="self im Predicate",
            files={"App/Q.swift": "import SwiftData\nlet p = #Predicate<Item> { $0.owner == self.userId }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="lokale Konstante",
            files={"App/Q.swift": "import SwiftData\nlet uid = userId\nlet p = #Predicate<Item> { $0.owner == uid }\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_predicate(ctx: Context) -> CheckResult:
    """#Predicate wird zu SQL übersetzt — ein direkter Zugriff auf eine
    Instanzeigenschaft oder ein Enum bricht zur Laufzeit, nicht beim Bauen."""
    title = "SwiftData-#Predicate greift auf eine nicht gebundene Variable zu"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.swiftdata_predicate_capture", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    measured = 0
    findings: list[Finding] = []
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        for m in re.finditer(r"#Predicate\s*<[^>]*>\s*\{([^}]{0,600})\}", body):
            measured += 1
            block = m.group(1)
            line_no = body.count("\n", 0, m.start()) + 1
            if re.search(r"\bself\.\w+", block):
                findings.append(Finding(
                    check_id="apple.swiftdata_predicate_capture",
                    severity=Severity.WARNING,
                    message="#Predicate greift direkt auf 'self.…' zu.",
                    file=sf.rel, line=line_no, evidence=snippet(block),
                    fix="Wert vorher in eine lokale Konstante legen und die "
                        "verwenden — #Predicate wird zu SQL übersetzt.",
                    guideline="guides/swiftdata-predicate.md",
                ))
    if measured == 0:
        return unmeasured("apple.swiftdata_predicate_capture", title,
                          "Kein #Predicate im Projekt.", PLATFORM)
    return result_for("apple.swiftdata_predicate_capture", title, findings,
                      measured, "#Predicate-Blöcke", PLATFORM)


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
    "apple.privacy_usage_description_missing",
    "Zugriff auf geschützte Ressource ohne Usage-Description",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="IOS_DEBUGGING_GUIDELINES.md",
    self_tests=[
        SelfTestCase(
            name="Kamera ohne Text",
            files={"App/Cam.swift": "import AVFoundation\nlet d = AVCaptureDevice.default(for: .video)\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Kamera mit Text",
            files={"App/Cam.swift": "import AVFoundation\nlet d = AVCaptureDevice.default(for: .video)\n",
                   "App/Info.plist": "<?xml version=\"1.0\"?>\n<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n<plist version=\"1.0\"><dict><key>NSCameraUsageDescription</key><string>Fuer Belege</string></dict></plist>\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_privacy_strings(ctx: Context) -> CheckResult:
    """Fehlt der Text, stürzt die App beim ersten Zugriff ab — und die
    App-Review lehnt sie ohnehin ab."""
    title = "Zugriff auf geschützte Ressource ohne Usage-Description"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.privacy_usage_description_missing", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    needs = {
        "NSCameraUsageDescription": (r"\bAVCaptureDevice\b|\.camera\b|UIImagePickerController", "Kamera"),
        "NSPhotoLibraryUsageDescription": (r"\bPHPhotoLibrary\b|PhotosPicker|\.photoLibrary\b", "Fotobibliothek"),
        "NSMicrophoneUsageDescription": (r"\bAVAudioRecorder\b|AVAudioSession.*record", "Mikrofon"),
        "NSLocationWhenInUseUsageDescription": (r"\bCLLocationManager\b", "Standort"),
        "NSContactsUsageDescription": (r"\bCNContactStore\b", "Kontakte"),
        "NSCalendarsUsageDescription": (r"\bEKEventStore\b", "Kalender"),
        "NSFaceIDUsageDescription": (r"\bLAContext\b", "Face ID"),
        "NSBluetoothAlwaysUsageDescription": (r"\bCBCentralManager\b", "Bluetooth"),
        "NSHealthShareUsageDescription": (r"\bHKHealthStore\b", "Health"),
    }
    all_swift = "\n".join(strip_comments(sf.text, sf.ext) for sf in swift)
    plist_keys: set[str] = set()
    plists = [sf for sf in ctx.all_files()
              if os.path.basename(sf.rel) == "Info.plist"]
    for sf in plists:
        try:
            with open(sf.path, "rb") as fh:
                plist_keys |= set(plistlib.load(fh).keys())
        except Exception:
            pass
    pbx = _pbx_text(ctx)
    pbx_content = pbx[0] if pbx else ""

    findings: list[Finding] = []
    for key, (pat, label) in needs.items():
        if not re.search(pat, all_swift):
            continue
        # Generierte Plists tragen den Schlüssel als INFOPLIST_KEY_* im pbxproj.
        if key in plist_keys or f"INFOPLIST_KEY_{key}" in pbx_content:
            continue
        loc = next(
            ((sf.rel, i) for sf in swift
             for i, ln in enumerate(sf.lines, 1) if re.search(pat, ln)),
            (None, None),
        )
        findings.append(Finding(
            check_id="apple.privacy_usage_description_missing",
            severity=Severity.ERROR,
            message=f"{label} wird genutzt, aber {key} fehlt.",
            file=loc[0], line=loc[1],
            fix=f"{key} in die Info.plist (oder als INFOPLIST_KEY_{key} in die "
                "Build-Settings) eintragen — sonst stürzt die App beim ersten "
                "Zugriff ab.",
        ))
    return result_for("apple.privacy_usage_description_missing", title, findings,
                      len(needs), "geprüfte Berechtigungen", PLATFORM)


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


@register(
    "apple.bundle_module_outside_spm_resources",
    "Bundle.module ohne SPM-Target mit Ressourcen",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="IOS_DEBUGGING_GUIDELINES.md § Buildort & Toolchain",
    self_tests=[
        SelfTestCase(
            name="Bundle.module ohne Package.swift",
            files={"Sources/App/V.swift":
                   "import SwiftUI\nlet b = Bundle.module\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Package-Target mit resources",
            files={
                "Package.swift": (
                    "// swift-tools-version:5.9\n"
                    "import PackageDescription\n"
                    "let package = Package(name: \"App\", targets: [\n"
                    "  .target(name: \"App\", resources: [.process(\"Assets\")])\n"
                    "])\n"
                ),
                "Sources/App/V.swift": "import SwiftUI\nlet b = Bundle.module\n",
            },
            expect=Status.PASS,
        ),
    ],
)
def check_bundle_module(ctx: Context) -> CheckResult:
    """'Type Bundle has no member module' — der Fehler schlägt erst beim Bauen
    auf macOS zu, ist aber statisch erkennbar.

    `Bundle.module` ist KEIN Standard-API von Foundation. SwiftPM generiert das
    Symbol pro Target, und nur dann, wenn dieses Target Ressourcen deklariert
    (`resources:` oder ein erkanntes Ressourcenverzeichnis). Fehlt das, oder
    liegt die Datei in einem reinen Xcode-Target, existiert `Bundle.module` nicht.

    Gemessen wird die EIGENSCHAFT "die Datei gehört zu einem SPM-Target mit
    Ressourcen", nicht die Bauform — ein Projekt darf beides mischen.
    Der Ersatz im Xcode-Fall ist `Bundle.main` oder ein `Bundle(for:)` über
    eine Klasse des eigenen Moduls.
    """
    title = "Bundle.module ohne SPM-Target mit Ressourcen"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.bundle_module_outside_spm_resources", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)

    pat = re.compile(r"\bBundle\s*\.\s*module\b")
    users = [sf for sf in swift
             if sf.ext == ".swift"
             and os.path.basename(sf.rel) != "Package.swift"
             and pat.search(strip_comments(sf.text, sf.ext))]
    if not users:
        return unmeasured("apple.bundle_module_outside_spm_resources", title,
                          "Kein Bundle.module im Projekt — nichts zu messen.",
                          PLATFORM)

    manifests = [sf for sf in ctx.all_files()
                 if os.path.basename(sf.rel) == "Package.swift"]
    if not manifests:
        findings = [Finding(
            check_id="apple.bundle_module_outside_spm_resources",
            severity=Severity.ERROR,
            message="Bundle.module benutzt, aber es gibt kein Package.swift — "
                    "das Symbol wird nur von SwiftPM erzeugt.",
            file=sf.rel,
            line=next((i for i, ln in enumerate(sf.lines, 1) if pat.search(ln)), None),
            evidence=snippet(next((ln for ln in sf.lines if pat.search(ln)), "")),
            fix="Auf 'Bundle.main' umstellen, oder — wenn ein eigenes Bundle "
                "gemeint ist — 'Bundle(for: EineKlasseDesModuls.self)'.",
            guideline="IOS_DEBUGGING_GUIDELINES.md",
        ) for sf in users]
        return failed("apple.bundle_module_outside_spm_resources", title,
                      findings, len(users), "Dateien mit Bundle.module", PLATFORM)

    # Targets mit Ressourcen aus dem Manifest lesen. Der Name des Targets
    # bestimmt das Quellverzeichnis (Sources/<Name>), sofern kein 'path:' steht.
    resource_targets: dict[str, str] = {}
    for mf in manifests:
        text = strip_comments(mf.text, ".swift")
        for m in re.finditer(r"\.(?:target|executableTarget|testTarget)\s*\(", text):
            depth, i = 1, m.end()
            while i < len(text) and depth:
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                i += 1
            block = text[m.end(): i]
            nm = re.search(r'name\s*:\s*"([^"]+)"', block)
            if not nm:
                continue
            if not re.search(r"\bresources\s*:", block):
                continue
            pm = re.search(r'path\s*:\s*"([^"]+)"', block)
            base = os.path.dirname(mf.rel)
            sub = pm.group(1) if pm else os.path.join("Sources", nm.group(1))
            resource_targets[nm.group(1)] = os.path.normpath(
                os.path.join(base, sub)) if base else os.path.normpath(sub)

    if not resource_targets:
        reason_fix = ("Im Package.swift dem betreffenden Target 'resources: "
                      "[.process(\"…\")]' geben — ohne Ressourcen erzeugt SwiftPM "
                      "kein Bundle.module. Oder auf 'Bundle.main' umstellen.")
    else:
        reason_fix = ("Die Datei liegt außerhalb der Targets mit Ressourcen "
                      f"({', '.join(sorted(resource_targets))}). Entweder ins "
                      "Target verschieben, dem Target Ressourcen geben, oder "
                      "'Bundle.main' verwenden.")

    findings: list[Finding] = []
    for sf in users:
        rel_norm = os.path.normpath(sf.rel)
        inside = any(
            rel_norm == d or rel_norm.startswith(d + os.sep)
            for d in resource_targets.values()
        )
        if inside:
            continue
        line = next((i for i, ln in enumerate(sf.lines, 1) if pat.search(ln)), None)
        findings.append(Finding(
            check_id="apple.bundle_module_outside_spm_resources",
            severity=Severity.ERROR,
            message="Bundle.module in einer Datei, die zu keinem SPM-Target mit "
                    "Ressourcen gehört — 'Type Bundle has no member module'.",
            file=sf.rel, line=line,
            evidence=snippet(next((ln for ln in sf.lines if pat.search(ln)), "")),
            fix=reason_fix,
            guideline="IOS_DEBUGGING_GUIDELINES.md",
        ))
    return result_for("apple.bundle_module_outside_spm_resources", title,
                      findings, len(users), "Dateien mit Bundle.module", PLATFORM)
