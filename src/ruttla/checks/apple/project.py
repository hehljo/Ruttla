"""Apple: project, bundle and Info.plist consistency.

Split from the original checks/apple.py; background and
shared helpers in _common.py.
"""

from __future__ import annotations

import os
import plistlib
import re

from ruttla.core import (
    CheckResult,
    Context,
    failed,
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

from ._common import _MIN_LAST_UPGRADE_CHECK, _pbx_text, PLATFORM


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
        if val.isdigit() and int(val) < _MIN_LAST_UPGRADE_CHECK:
            findings.append(Finding(
                check_id="apple.project_settings", severity=Severity.INFO,
                message=f"LastUpgradeCheck ist {val} "
                        f"(empfohlen ab {_MIN_LAST_UPGRADE_CHECK}).",
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


@register(
    "apple.empty_usage_description",
    "Leerer Privacy-String (NS*UsageDescription) in Info.plist (bricht Xcode-Build ab)",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="IOS_DEBUGGING_GUIDELINES.md § Privacy Keys",
    self_tests=[
        SelfTestCase(
            name="Leere Kamera-Beschreibung",
            files={
                "App/Info.plist": (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<plist version="1.0"><dict>\n'
                    '<key>NSCameraUsageDescription</key>\n'
                    '<string></string>\n'
                    '</dict></plist>\n'
                )
            },
            expect=Status.FAIL,
            expect_finding_contains="NSCameraUsageDescription",
        ),
        SelfTestCase(
            name="Gültige Kamera-Beschreibung",
            files={
                "App/Info.plist": (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<plist version="1.0"><dict>\n'
                    '<key>NSCameraUsageDescription</key>\n'
                    '<string>Wird für Belege benötigt.</string>\n'
                    '</dict></plist>\n'
                )
            },
            expect=Status.PASS,
        ),
    ],
)
def check_empty_usage_description(ctx: Context) -> CheckResult:
    """Xcode und App Store Connect verlangen, dass jede deklarierte Usage-Description
    einen nicht-leeren Begründungstext enthält. Leere Strings brechen den Build sofort ab."""
    title = "Leerer Privacy-String (NS*UsageDescription) in Info.plist"
    plists = [sf for sf in ctx.all_files() if sf.rel.endswith(".plist") or sf.rel.endswith("-Info.plist")]
    if not plists:
        return unmeasured("apple.empty_usage_description", title,
                          "Keine Info.plist-Dateien gefunden.", PLATFORM)

    key_pat = re.compile(r"<key>(NS[A-Za-z0-9]+UsageDescription)</key>")
    val_pat = re.compile(r"<string>([^<]*)</string>")

    findings: list[Finding] = []
    measured = 0

    for pf in plists:
        for idx, line in enumerate(pf.lines):
            km = key_pat.search(line)
            if not km:
                continue
            key_name = km.group(1)
            measured += 1

            # Nächste Zeile nach <string> absuchen
            for off in range(idx + 1, min(len(pf.lines), idx + 4)):
                nxt = pf.lines[off]
                vm = val_pat.search(nxt)
                if vm:
                    val_str = vm.group(1).strip()
                    if not val_str:
                        findings.append(Finding(
                            check_id="apple.empty_usage_description",
                            severity=Severity.ERROR,
                            message=f"'{key_name}' ist leer — Xcode bricht mit 'must be a non-empty string' ab.",
                            file=pf.rel,
                            line=off + 1,
                            evidence=snippet(nxt),
                            fix=f"Einen aussagekräftigen Text in <string> eintragen oder den Key '{key_name}' ganz entfernen, wenn die Berechtigung nicht benötigt wird.",
                            guideline="IOS_DEBUGGING_GUIDELINES.md § Privacy Keys",
                        ))
                    break

    if measured == 0:
        return unmeasured("apple.empty_usage_description", title,
                          "Keine Usage-Descriptions in Plist-Dateien gefunden.", PLATFORM)
    return result_for("apple.empty_usage_description", title, findings, measured,
                      "Usage-Descriptions", PLATFORM)


@register(
    "apple.automatic_signing_distribution_conflict",
    "Automatisches Signing mit festem 'Apple Distribution' (bricht lokalen Xcode-Build ab)",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="IOS_DEBUGGING_GUIDELINES.md § Signing",
    self_tests=[
        SelfTestCase(
            name="Konflikt Automatic Signing mit Apple Distribution",
            files={
                "App.xcodeproj/project.pbxproj": (
                    "buildSettings = {\n"
                    '    CODE_SIGN_IDENTITY = "Apple Distribution";\n'
                    '    CODE_SIGN_STYLE = Automatic;\n'
                    "};\n"
                )
            },
            expect=Status.FAIL,
            expect_finding_contains="Apple Distribution",
        ),
        SelfTestCase(
            name="Sauberes Automatic Signing",
            files={
                "App.xcodeproj/project.pbxproj": (
                    "buildSettings = {\n"
                    '    CODE_SIGN_IDENTITY = "Apple Development";\n'
                    '    CODE_SIGN_STYLE = Automatic;\n'
                    "};\n"
                )
            },
            expect=Status.PASS,
        ),
    ],
)
def check_automatic_signing_distribution(ctx: Context) -> CheckResult:
    """Wenn CODE_SIGN_STYLE auf Automatic steht, bricht Xcode bei hartem CODE_SIGN_IDENTITY = 'Apple Distribution'
    mit 'conflicting provisioning settings' ab. Für automatisches Signing gehört 'Apple Development' (oder kein manueller Override) hinein."""
    title = "Automatisches Signing mit festem 'Apple Distribution'"
    pbx_files = ctx.files_named("project.pbxproj")
    if not pbx_files:
        return unmeasured("apple.automatic_signing_distribution_conflict", title,
                          "Keine project.pbxproj-Dateien gefunden.", PLATFORM)

    findings: list[Finding] = []
    measured = 0

    for pf in pbx_files:
        text = pf.text
        # Abschnitte suchen mit buildSettings
        blocks = re.findall(r"buildSettings\s*=\s*\{([^}]+)\};", text)
        for b_idx, block in enumerate(blocks):
            if "CODE_SIGN_STYLE" in block and "CODE_SIGN_IDENTITY" in block:
                measured += 1
                is_auto = bool(re.search(r'CODE_SIGN_STYLE\s*=\s*"?Automatic"?', block))
                is_dist = bool(re.search(r'CODE_SIGN_IDENTITY\s*=\s*"Apple Distribution"', block))
                if is_auto and is_dist:
                    # Zeilennummer im Original suchen
                    line_num = 1
                    for l_idx, l_raw in enumerate(pf.lines, start=1):
                        if 'CODE_SIGN_IDENTITY = "Apple Distribution"' in l_raw:
                            line_num = l_idx
                            break
                    findings.append(Finding(
                        check_id="apple.automatic_signing_distribution_conflict",
                        severity=Severity.ERROR,
                        message="CODE_SIGN_STYLE ist 'Automatic', aber CODE_SIGN_IDENTITY steht manuell auf 'Apple Distribution' — erzeugt Signatur-Konflikt in Xcode.",
                        file=pf.rel,
                        line=line_num,
                        evidence='CODE_SIGN_STYLE = Automatic; CODE_SIGN_IDENTITY = "Apple Distribution";',
                        fix="CODE_SIGN_IDENTITY auf 'Apple Development' setzen. Xcode wechselt bei automatischem Signing beim Archivieren selbstständig auf Distribution.",
                        guideline="IOS_DEBUGGING_GUIDELINES.md § Signing",
                    ))

    if measured == 0:
        return unmeasured("apple.automatic_signing_distribution_conflict", title,
                          "Keine Build-Konfigurationen mit Code-Signing-Einstellungen gefunden.", PLATFORM)
    return result_for("apple.automatic_signing_distribution_conflict", title, findings, measured,
                      "Build-Konfigurationen", PLATFORM)


@register(
    "apple.gitignore_xcode_user_data",
    "Xcode-Benutzerdaten (xcuserdata / *.xcuserstate) nicht in .gitignore ignoriert",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="IOS_DEBUGGING_GUIDELINES.md § Version Control",
    self_tests=[
        SelfTestCase(
            name="Xcode-Projekt ohne xcuserdata in gitignore",
            files={
                "App.xcodeproj/project.pbxproj": "// Xcode project\n",
                ".gitignore": "build/\n.DS_Store\n",
            },
            expect=Status.FAIL,
            expect_finding_contains="xcuserdata",
        ),
        SelfTestCase(
            name="Xcode-Projekt mit xcuserdata in gitignore",
            files={
                "App.xcodeproj/project.pbxproj": "// Xcode project\n",
                ".gitignore": "build/\nxcuserdata/\n*.xcuserstate\n",
            },
            expect=Status.PASS,
        ),
    ],
)
def check_gitignore_xcode_user_data(ctx: Context) -> CheckResult:
    """In jedem Apple-/Xcode-Projekt müssen xcuserdata und *.xcuserstate zwingend
    in .gitignore ignoriert werden, um Merge-Konflikte, lokale IDE-Zustände und
    Pfad-Leaks im Git-Repository zu verhindern."""
    title = "Xcode-Benutzerdaten nicht in .gitignore ignoriert"
    pbx_files = ctx.files_named("project.pbxproj")
    if not pbx_files:
        return unmeasured("apple.gitignore_xcode_user_data", title,
                          "Keine Xcode-Projekte im Arbeitsbereich gefunden.", PLATFORM)

    gitignore_files = ctx.files_named(".gitignore")
    gi_text = ""
    gi_path = ".gitignore"
    if gitignore_files:
        gi_text = gitignore_files[0].text
        gi_path = gitignore_files[0].rel
    else:
        full_gi = os.path.join(ctx.root, ".gitignore")
        if os.path.isfile(full_gi):
            try:
                with open(full_gi, "r", encoding="utf-8", errors="replace") as fh:
                    gi_text = fh.read()
            except Exception:
                pass

    findings: list[Finding] = []
    has_xcuserdata = "xcuserdata" in gi_text
    has_xcuserstate = "xcuserstate" in gi_text

    if not has_xcuserdata or not has_xcuserstate:
        missing = []
        if not has_xcuserdata:
            missing.append("xcuserdata/")
        if not has_xcuserstate:
            missing.append("*.xcuserstate")
        findings.append(Finding(
            check_id="apple.gitignore_xcode_user_data",
            severity=Severity.ERROR,
            message=f"In .gitignore fehlen Pflicht-Einträge für Xcode: {', '.join(missing)}.",
            file=gi_path,
            line=1,
            evidence=snippet(gi_text.splitlines()[0] if gi_text else "(keine oder leere .gitignore)"),
            fix="Füge 'xcuserdata/' und '*.xcuserstate' zu .gitignore hinzu.",
            guideline="IOS_DEBUGGING_GUIDELINES.md § Version Control",
        ))

    return result_for("apple.gitignore_xcode_user_data", title, findings,
                      len(pbx_files), "Xcode-Projekte", PLATFORM)
