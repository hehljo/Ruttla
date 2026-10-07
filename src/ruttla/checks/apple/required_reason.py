"""Apple: Swift-Code nutzt eine Required-Reason-API, kein Datenschutz-Manifest nennt sie.

Belegt am 07.10.2026 (Merkma, Capacitor-Hülle): `@capacitor/preferences` 8.0.1
speichert über `UserDefaults` und bringt **kein** eigenes `PrivacyInfo.xcprivacy`
mit. Die App hatte auch keins. App Store Connect lehnt so einen Upload mit
ITMS-91053 („Missing API declaration") ab — sichtbar erst nach dem Hochladen,
nicht im Xcode-Build. Gefunden hat es nur, wer den Quelltext des Plugins las.

Ein Python-Check statt einer TOML-Regel: die Aussage hängt an mehreren
Dateien (Package.swift → lokales Paket → dessen Swift-Quellen → Manifest im
Paket oder in der App → Verweis im Xcode-Projekt), und die Pakete liegen
meist unter `node_modules`, das der Dateiblick des Kerns auslässt.

Gemessen wird je Quellgruppe: die App selbst und jedes lokale Swift-Paket
(`.package(…, path: "…")`). Ein Paket darf die API im eigenen Manifest
erklären, sonst muss es das der App tun. Pakete per URL sind nicht gemessen
(ihr Quelltext liegt nicht im Repository). Fehlt ein lokales Paket auf der
Platte (kein `npm ci`), ist es nicht gemessen — nie bestanden.
"""

from __future__ import annotations

import os
import re

from ruttla.core import (
    DEFAULT_EXCLUDE_DIRS,
    CheckResult,
    Context,
    Finding,
    SelfTestCase,
    Severity,
    Status,
    register,
    result_for,
    strip_comments,
    unmeasured,
)

_ID = "apple.required_reason_api_undeclared"
_TITLE = "Required-Reason-API im Swift-Code, aber in keinem Datenschutz-Manifest erklärt"
_GUIDELINE = "CODE_QUALITY_GUIDELINES_WEB_TO_NATIVE.md § Store-Pflichten"

# Apples Kategorien mit Mustern, die nur die API treffen, nicht ein
# gleichnamiges Modellfeld: Zeitstempel nur mit URLResourceKey/FileAttributeKey.
_CATEGORIES = (
    ("NSPrivacyAccessedAPICategoryUserDefaults",
     re.compile(r"\b(?:NS)?UserDefaults\b")),
    ("NSPrivacyAccessedAPICategoryFileTimestamp",
     re.compile(r"\.(?:creationDate|contentModificationDate|contentAccessDate)Key\b"
                r"|FileAttributeKey\.(?:creationDate|modificationDate)\b"
                r"|\bgetattrlist\s*\(")),
    ("NSPrivacyAccessedAPICategorySystemBootTime",
     re.compile(r"\bsystemUptime\b|\bmach_absolute_time\s*\(")),
    ("NSPrivacyAccessedAPICategoryDiskSpace",
     re.compile(r"\bvolume(?:Available|Total)Capacity\w*Key\b|FileAttributeKey\.system(?:Free)?Size\b"
                r"|\bstatv?fs\s*\(")),
)
_LOCAL_PACKAGE = re.compile(r"""\.package\s*\(\s*(?:name\s*:\s*"[^"]*"\s*,\s*)?path\s*:\s*"([^"]+)"\s*\)""")
_SKIP = set(DEFAULT_EXCLUDE_DIRS) | {"node_modules", "Tests", "build", "DerivedData"}


def _rel(ctx: Context, path: str) -> str:
    return os.path.relpath(path, ctx.root).replace(os.sep, "/")


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _inside(path: str, root: str) -> bool:
    """Liegt der aufgelöste Pfad unter der Prüfwurzel? Eine fremde
    Package.swift oder ein Link darf den Check nicht aus dem Repository
    führen — weder zum Lesen noch zu einem Lauf über das halbe Dateisystem."""
    real, base = os.path.realpath(path), os.path.realpath(root)
    try:
        return os.path.commonpath([real, base]) == base
    except ValueError:  # anderes Laufwerk unter Windows
        return False


def _walk(top: str, suffix: str, root: str) -> list[str]:
    if not _inside(top, root):
        return []
    out = []
    for base, dirs, files in os.walk(top):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP and not d.startswith("."))
        out += [os.path.join(base, f) for f in sorted(files)
                if f.endswith(suffix) and _inside(os.path.join(base, f), root)]
    return out


def _uses(files: list[str]) -> dict[str, tuple[str, int]]:
    """Kategorie → erste Fundstelle (Pfad, Zeile)."""
    used: dict[str, tuple[str, int]] = {}
    for path in files:
        code = strip_comments(_read(path), ".swift")
        for category, pattern in _CATEGORIES:
            if category in used:
                continue
            m = pattern.search(code)
            if m:
                used[category] = (path, code.count("\n", 0, m.start()) + 1)
    return used


_SDKROOT = re.compile(r"\bSDKROOT\s*=\s*\"?(\w+)")
_SPM_PLATFORM = re.compile(r"\.(iOS|macOS|tvOS|watchOS|visionOS|macCatalyst)\s*\(")


def _mac_only(ctx: Context) -> bool:
    """Nur macOS? Gemessen am SDK, gegen das gebaut wird, nicht an einem
    MACOSX_DEPLOYMENT_TARGET, das jedes iOS-Projekt mit Catalyst auch trägt.
    Ohne Xcode-Projekt zählen die Plattformen der Package.swift."""
    sdks = {m.group(1) for p in _walk(ctx.root, "project.pbxproj", ctx.root)
            for m in _SDKROOT.finditer(_read(p))}
    if sdks:
        return sdks == {"macosx"}
    platforms = {m.group(1) for p in _walk(ctx.root, "Package.swift", ctx.root)
                 for m in _SPM_PLATFORM.finditer(strip_comments(_read(p), ".swift"))}
    return platforms == {"macOS"}


def _declared(manifests: list[str]) -> set[str]:
    text = "".join(_read(p) for p in manifests)
    return {c for c, _ in _CATEGORIES if c in text}


@register(
    _ID, _TITLE, platform="apple", severity=Severity.ERROR,
    guideline=_GUIDELINE,
    references=("https://developer.apple.com/documentation/bundleresources/describing-use-of-required-reason-api",
                "https://developer.apple.com/documentation/bundleresources/privacy-manifest-files",
                "https://capacitorjs.com/docs/ios/privacy-manifest"),
    self_tests=[
        SelfTestCase("Lokales Paket nutzt UserDefaults, kein Manifest", {
            "ios/App/CapApp-SPM/Package.swift":
                'let p = Package(dependencies: [\n'
                '  .package(name: "Prefs", path: "../../../node_modules/prefs")\n])\n',
            "node_modules/prefs/ios/Sources/Prefs/Store.swift":
                "let d = UserDefaults(suiteName: \"x\")\n",
            "ios/App/App/AppDelegate.swift": "import UIKit\n",
        }, Status.FAIL, expect_finding_contains="NSPrivacyAccessedAPICategoryUserDefaults"),
        SelfTestCase("App-Manifest erklärt es, ist aber nicht im Xcode-Projekt", {
            "ios/App/CapApp-SPM/Package.swift":
                '.package(name: "Prefs", path: "../../../node_modules/prefs")\n',
            "node_modules/prefs/Sources/Store.swift": "UserDefaults.standard\n",
            "ios/App/App/PrivacyInfo.xcprivacy":
                "<string>NSPrivacyAccessedAPICategoryUserDefaults</string>\n",
            "ios/App/App.xcodeproj/project.pbxproj": "/* AppDelegate.swift */\n",
        }, Status.FAIL, expect_finding_contains="nicht im Xcode-Projekt"),
        SelfTestCase("App-Manifest erklärt es und steht im Projekt", {
            "ios/App/CapApp-SPM/Package.swift":
                '.package(name: "Prefs", path: "../../../node_modules/prefs")\n',
            "node_modules/prefs/Sources/Store.swift": "UserDefaults.standard\n",
            "ios/App/App/PrivacyInfo.xcprivacy":
                "<string>NSPrivacyAccessedAPICategoryUserDefaults</string>\n",
            "ios/App/App.xcodeproj/project.pbxproj": "/* PrivacyInfo.xcprivacy in Resources */\n",
        }, Status.PASS),
        SelfTestCase("Paket bringt eigenes Manifest mit", {
            "ios/App/CapApp-SPM/Package.swift":
                '.package(name: "Prefs", path: "../../../node_modules/prefs")\n',
            "node_modules/prefs/Sources/Store.swift": "UserDefaults.standard\n",
            "node_modules/prefs/Sources/PrivacyInfo.xcprivacy":
                "<string>NSPrivacyAccessedAPICategoryUserDefaults</string>\n",
        }, Status.PASS),
        SelfTestCase("App-Code: Modellfeld creationDate ist keine API", {
            "ios/App/App/Item.swift": "struct Item { var creationDate: Date }\n// UserDefaults\n",
        }, Status.PASS),
        SelfTestCase("App-Code nutzt UserDefaults selbst", {
            "ios/App/App/Settings.swift": "let x = UserDefaults.standard.bool(forKey: \"a\")\n",
        }, Status.FAIL, expect_finding_contains="Settings.swift"),
        SelfTestCase("Reine macOS-App: nicht gemessen", {
            "App/Settings.swift": "let x = UserDefaults.standard\n",
            "App.xcodeproj/project.pbxproj": "SDKROOT = macosx;\nMACOSX_DEPLOYMENT_TARGET = 14.0;\n",
        }, Status.UNMEASURED),
        SelfTestCase("iOS mit Mac-Beiwerk bleibt Fehler", {
            "App/Settings.swift": "let x = UserDefaults.standard\n",
            "App.xcodeproj/project.pbxproj": "SDKROOT = iphoneos;\nMACOSX_DEPLOYMENT_TARGET = 14.0;\n",
        }, Status.FAIL, expect_finding_contains="UserDefaults"),
        SelfTestCase("Lokales Paket fehlt auf der Platte", {
            "ios/App/CapApp-SPM/Package.swift":
                '.package(name: "Prefs", path: "../../../node_modules/prefs")\n',
        }, Status.UNMEASURED),
    ],
)
def check_required_reason(ctx: Context) -> CheckResult:
    """Prüfgegenstand ist jede Quellgruppe, die ins App-Binary kommt: der
    eigene Swift-Code und jedes lokale Swift-Paket. Jede benutzte Kategorie
    braucht eine Erklärung im Manifest des Pakets oder der App — und das
    App-Manifest wirkt nur, wenn das Xcode-Projekt es mitnimmt."""
    packages: dict[str, str] = {}   # Paketordner → Package.swift, das ihn nennt
    missing: list[str] = []
    for spm in _walk(ctx.root, "Package.swift", ctx.root):
        for m in _LOCAL_PACKAGE.finditer(strip_comments(_read(spm), ".swift")):
            target = os.path.realpath(os.path.join(os.path.dirname(spm), m.group(1)))
            if not _inside(target, ctx.root):
                missing.append(f"{_rel(ctx, spm)} → {m.group(1)} (außerhalb des Repositorys)")
            elif os.path.isdir(target):
                packages.setdefault(target, spm)
            else:
                missing.append(f"{_rel(ctx, spm)} → {m.group(1)}")

    package_files = {t: _walk(t, ".swift", ctx.root) for t in packages}
    in_package = {os.path.realpath(f) for files in package_files.values() for f in files}
    app_files = [os.path.join(ctx.root, sf.rel) for sf in ctx.files(".swift")
                 if os.path.basename(sf.rel) != "Package.swift"
                 and os.path.realpath(os.path.join(ctx.root, sf.rel)) not in in_package]
    in_package_dirs = tuple(t + os.sep for t in packages)
    app_manifests = [p for p in _walk(ctx.root, ".xcprivacy", ctx.root)
                     if not os.path.realpath(p).startswith(in_package_dirs)]
    app_declared = _declared(app_manifests)

    groups = [(None, app_files)] if app_files else []
    groups += [(t, package_files[t]) for t in sorted(packages) if package_files[t]]
    if not groups:
        reason = "Kein Swift-Code und kein lokales Swift-Paket gefunden."
        if missing:
            reason = ("Lokale Swift-Pakete fehlen auf der Platte (npm ci?) oder liegen "
                      "außerhalb des Repositorys: "
                      + ", ".join(missing[:3]) + " — ihr Code ist nicht gemessen.")
        return unmeasured(_ID, _TITLE, reason, "apple")

    # App Store Connect weist fehlende Erklärungen bei iOS, iPadOS, tvOS,
    # visionOS und watchOS ab, bei macOS (Stand der Quellen: 2024) nicht. Eine
    # Abstufung je Befund gibt es nicht (die Engine setzt die Schwere des
    # Checks) — also nicht gemessen statt eines Fehlers, der keiner ist.
    if _mac_only(ctx):
        return unmeasured(_ID, _TITLE, "Reine macOS-App: Apple verlangt die Erklärung beim "
                          "Upload nicht. Empfohlen bleibt ein PrivacyInfo.xcprivacy trotzdem.",
                          "apple")
    severity = Severity.ERROR
    findings: list[Finding] = []
    app_needs = False
    for target, files in groups:
        own = _declared(_walk(target, ".xcprivacy", ctx.root)) if target else set()
        for category, (path, line) in sorted(_uses(files).items()):
            if category in own:
                continue
            if category in app_declared:
                app_needs = True
                continue
            where = _rel(ctx, path)
            if target:
                name = os.path.basename(target)
                message = (f"Paket {name} nutzt {category} ({where}:{line}) und bringt kein "
                           "Manifest dafür mit; die App erklärt es auch nicht. App Store "
                           "Connect lehnt den Upload mit ITMS-91053 ab.")
                file, at = _rel(ctx, packages[target]), 1
            else:
                message = (f"Der App-Code nutzt {category} ({where}:{line}), kein "
                           "PrivacyInfo.xcprivacy der App erklärt es (ITMS-91053).")
                file, at = where, line
            findings.append(Finding(
                check_id=_ID, severity=severity, message=message,
                file=file, line=at, evidence=category,
                fix=(f"PrivacyInfo.xcprivacy im App-Target anlegen (Build Phase Copy Bundle "
                     f"Resources) und unter NSPrivacyAccessedAPITypes {category} mit dem "
                     "passenden Grund eintragen (UserDefaults nur für die eigene App: CA92.1)."),
                guideline=_GUIDELINE,
            ))

    if app_needs and app_manifests:
        projects = [_read(p) for p in _walk(ctx.root, "project.pbxproj", ctx.root)]
        names = {os.path.basename(p) for p in app_manifests}
        if projects and not any(n in text for n in names for text in projects):
            findings.append(Finding(
                check_id=_ID, severity=Severity.ERROR,
                message=("Das App-Manifest erklärt die APIs, ist aber nicht im Xcode-Projekt "
                         "— es landet nicht im Bundle und zählt bei Apple nicht."),
                file=_rel(ctx, app_manifests[0]), line=1, evidence=", ".join(sorted(names)),
                fix="Die Datei in Xcode dem App-Target hinzufügen (Copy Bundle Resources).",
                guideline=_GUIDELINE,
            ))

    return result_for(_ID, _TITLE, findings, len(groups), "Swift-Quellgruppen", "apple")
