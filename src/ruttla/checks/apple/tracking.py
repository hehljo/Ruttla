"""App Tracking Transparency: Info.plist, Privacy-Manifest und Werbe-SDK
müssen dieselbe Tracking-Aussage machen.

Python statt TOML-Regel: die Aussage entsteht erst aus mehreren Dateien
(App-Plist, App-Manifest, Build-Settings in der project.pbxproj).

Belegt 14.10.2026 (Wiesn Survivors, Apple-Ablehnung 5.1.2(i)): AdMob mit
SKAdNetwork-Liste im Binary, ASC-Label „Tracking", aber kein
NSUserTrackingUsageDescription — ohne den Begründungstext zeigt iOS keinen
ATT-Dialog, Apple lehnt ab.

Korrigiert 03.11.2026 (Hopfenhölle Build 49, ITMS-91064): Die frühere Regel
„ATT-Text verlangt NSPrivacyTracking=true im App-Manifest" erzwang genau die
Ablehnung. Das App-Manifest beschreibt nur den eigenen Code; trackt allein das
Werbe-SDK, deklariert das dessen Manifest. true ohne NSPrivacyTrackingDomains
weist Apple als ungültige Binärdatei zurück, und eingetragene Domains sperrt
iOS ohne ATT-Zustimmung (auch für nicht-personalisierte Werbung).
"""

from __future__ import annotations

import os
import plistlib
import re

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status,
    register, result_for, unmeasured,
)

from ._common import PLATFORM

GUIDELINE = "CODE_QUALITY_GUIDELINES_GAMEDEV.md § iOS: Werbung und App Tracking Transparency"
TRACKING_KEY = "NSUserTrackingUsageDescription"
# Mitgelieferte SDK-Dateien beschreiben das SDK, nicht die App.
_VENDOR = re.compile(r"\.(?:xcframework|framework|bundle)$|^(?:Pods|node_modules|SourcePackages|\.build|Carthage|DerivedData)$")
_APP_PLIST = re.compile(r"<key>CFBundleExecutable</key>")
# Eigenschaft „App nimmt an Werbe-Attribution teil": SKAdNetwork-Liste oder AdMob-App-ID.
_AD_MARKER = re.compile(r"<key>(SKAdNetworkItems|GADApplicationIdentifier)</key>")
_USAGE_PLIST = re.compile(r"<key>%s</key>[ \t\r\n]*<string>([^<]*)</string>" % TRACKING_KEY)
_USAGE_SETTING = re.compile(r"INFOPLIST_KEY_%s = (\"[^\"\n]*\"|[^;\n]*);" % TRACKING_KEY)
_USAGE_STRINGS = re.compile(r'^[ \t]*"?%s"?[ \t]*=[ \t]*"((?:[^"\\\n]|\\.)*)"' % TRACKING_KEY, re.MULTILINE)
_MANIFEST_TRACKING = re.compile(r"<key>NSPrivacyTracking</key>[ \t\r\n]*<(true|false)/>")


def _vendored(rel: str) -> bool:
    return any(_VENDOR.search(part) for part in rel.split("/")[:-1])


def _has_text(value: str) -> bool:
    return value.strip().strip('"').strip() != ""


def _tracking_state(ctx: Context):
    """(App-Plists, ATT-Text vorhanden, App-Manifeste mit Wert)."""
    plists = [sf for sf in ctx.all_files()
              if sf.rel.endswith("Info.plist") and not _vendored(sf.rel) and _APP_PLIST.search(sf.text)]
    usage = any(_has_text(m.group(1)) for sf in plists for m in _USAGE_PLIST.finditer(sf.text))
    usage = usage or any(_has_text(m.group(1)) for sf in ctx.files_named("project.pbxproj")
                         for m in _USAGE_SETTING.finditer(sf.text))
    usage = usage or any(_has_text(m.group(1)) for sf in ctx.files_named("InfoPlist.strings")
                         if not _vendored(sf.rel) for m in _USAGE_STRINGS.finditer(sf.text))
    manifests = [(sf, m.group(1) == "true" if (m := _MANIFEST_TRACKING.search(sf.text)) else False)
                 for sf in ctx.files_named("PrivacyInfo.xcprivacy") if not _vendored(sf.rel)]
    return plists, usage, manifests


_PLIST_HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0">\n<dict>\n'
_APP = _PLIST_HEAD + "\t<key>CFBundleExecutable</key>\n\t<string>$(EXECUTABLE_NAME)</string>\n"
_ADS = "\t<key>GADApplicationIdentifier</key>\n\t<string>ca-app-pub-1~2</string>\n\t<key>SKAdNetworkItems</key>\n\t<array/>\n"
_ATT = "\t<key>NSUserTrackingUsageDescription</key>\n\t<string>Werbung personalisieren</string>\n"
_END = "</dict>\n</plist>\n"
_MANIFEST = _PLIST_HEAD + "\t<key>NSPrivacyTracking</key>\n\t<%s/>\n" + _END
_PBX = "// !$*UTF8*$!\n{ objects = { }; }\n"


@register(
    "apple.ad_sdk_without_att",
    "Werbe-SDK eingebaut, aber kein ATT-Begründungstext",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline=GUIDELINE,
    rationale=("Belegt 14.10.2026 (Wiesn Survivors): AdMob + SKAdNetwork im Binary, ASC-Label „Tracking“, "
               "kein NSUserTrackingUsageDescription → Ablehnung 5.1.2(i). Warnung statt Fehler: wer nur "
               "nicht-personalisierte Werbung ausliefert und in ASC kein Tracking angibt, braucht keinen Dialog."),
    references=["https://developer.apple.com/app-store/user-privacy-and-data-use/",
                "https://developers.google.com/admob/ios/privacy/idfa"],
    self_tests=[
        SelfTestCase(name="AdMob ohne ATT-Text", expect=Status.FAIL, expect_finding_contains="ATT",
                     files={"ios/game.xcodeproj/project.pbxproj": _PBX, "ios/game/game-Info.plist": _APP + _ADS + _END}),
        SelfTestCase(name="AdMob mit ATT-Text", expect=Status.PASS,
                     files={"ios/game.xcodeproj/project.pbxproj": _PBX, "ios/game/game-Info.plist": _APP + _ADS + _ATT + _END}),
        SelfTestCase(name="AdMob, ATT-Text nur lokalisiert", expect=Status.PASS,
                     files={"ios/game.xcodeproj/project.pbxproj": _PBX, "ios/game/game-Info.plist": _APP + _ADS + _END,
                            "ios/game/de.lproj/InfoPlist.strings": '"NSUserTrackingUsageDescription" = "Werbung";\n'}),
        SelfTestCase(name="AdMob, ATT-Text als Build-Setting", expect=Status.PASS,
                     files={"ios/game.xcodeproj/project.pbxproj": _PBX.replace("objects = { };", "objects = { INFOPLIST_KEY_NSUserTrackingUsageDescription = \"Werbung\"; };"),
                            "ios/game/game-Info.plist": _APP + _ADS + _END}),
        SelfTestCase(name="SDK-Plist im xcframework zählt nicht als App", expect=Status.PASS,
                     files={"ios/game.xcodeproj/project.pbxproj": _PBX, "ios/game/game-Info.plist": _APP + _END,
                            "ios/libs/Ads.xcframework/ios-arm64/Ads.framework/Info.plist": _APP + _ADS + _END}),
        SelfTestCase(name="keine App-Plist", expect=Status.UNMEASURED,
                     files={"ios/game.xcodeproj/project.pbxproj": _PBX}),
    ],
)
def check_ad_sdk_without_att(ctx: Context) -> CheckResult:
    check_id = "apple.ad_sdk_without_att"
    title = "Werbe-SDK eingebaut, aber kein ATT-Begründungstext"
    plists, usage, _ = _tracking_state(ctx)
    if not plists:
        return unmeasured(check_id, title, "Keine App-Info.plist gefunden.", PLATFORM)
    findings: list[Finding] = []
    if not usage:
        for sf in plists:
            marker = _AD_MARKER.search(sf.text)
            if marker:
                findings.append(Finding(
                    check_id=check_id, severity=Severity.WARNING,
                    message=(f"{marker.group(1)} zeigt ein Werbe-SDK, aber {TRACKING_KEY} fehlt — iOS kann keinen "
                             "ATT-Dialog zeigen. Mit ASC-Label „Tracking“ lehnt Apple nach 5.1.2(i) ab."),
                    file=sf.rel, line=sf.text.count("\n", 0, marker.start()) + 1,
                    evidence=marker.group(0),
                    fix=("Entweder ATT einbauen (Begründung in Info.plist/InfoPlist.strings; bei Google UMP die "
                         "IDFA-Erklärung im AdMob-Konto veröffentlichen) oder nur nicht-personalisierte Werbung "
                         "und in ASC kein Tracking angeben."),
                    guideline=GUIDELINE,
                ))
    return result_for(check_id, title, findings, len(plists), "App-Info.plists", PLATFORM)


@register(
    "apple.tracking_manifest_contradicts_att",
    "Privacy-Manifest und ATT-Begründung widersprechen sich",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline=GUIDELINE,
    safe_by_default=True,
    rationale=("Meldet das App-Manifest Tracking, braucht die App den ATT-Text. Die Gegenrichtung (ATT-Text "
               "verlangt Manifest true) war falsch: AdMob deklariert sein Tracking im SDK-Manifest, true ohne "
               "Domains lehnte Apple ab (ITMS-91064, 03.11.2026)."),
    references=["https://developer.apple.com/documentation/bundleresources/privacy-manifest-files"],
    self_tests=[
        SelfTestCase(name="ATT-Text, Manifest false (Tracking nur im SDK)", expect=Status.PASS,
                     files={"ios/game.xcodeproj/project.pbxproj": _PBX, "ios/game/game-Info.plist": _APP + _ATT + _END,
                            "ios/PrivacyInfo.xcprivacy": _MANIFEST % "false"}),
        SelfTestCase(name="Manifest true, kein ATT-Text", expect=Status.FAIL, expect_finding_contains=TRACKING_KEY,
                     files={"ios/game.xcodeproj/project.pbxproj": _PBX, "ios/game/game-Info.plist": _APP + _END,
                            "ios/PrivacyInfo.xcprivacy": _MANIFEST % "true"}),
        SelfTestCase(name="beides Tracking", expect=Status.PASS,
                     files={"ios/game.xcodeproj/project.pbxproj": _PBX, "ios/game/game-Info.plist": _APP + _ATT + _END,
                            "ios/PrivacyInfo.xcprivacy": _MANIFEST % "true"}),
        SelfTestCase(name="beides ohne Tracking, SDK-Manifest true", expect=Status.PASS,
                     files={"ios/game.xcodeproj/project.pbxproj": _PBX, "ios/game/game-Info.plist": _APP + _END,
                            "ios/PrivacyInfo.xcprivacy": _MANIFEST % "false",
                            "ios/libs/Ads.xcframework/ios-arm64/PrivacyInfo.xcprivacy": _MANIFEST % "true"}),
        SelfTestCase(name="kein App-Manifest", expect=Status.UNMEASURED,
                     files={"ios/game.xcodeproj/project.pbxproj": _PBX, "ios/game/game-Info.plist": _APP + _ATT + _END}),
    ],
)
def check_tracking_manifest_contradicts_att(ctx: Context) -> CheckResult:
    check_id = "apple.tracking_manifest_contradicts_att"
    title = "Privacy-Manifest und ATT-Begründung widersprechen sich"
    plists, usage, manifests = _tracking_state(ctx)
    if not plists or not manifests:
        return unmeasured(check_id, title, "Keine App-Info.plist mit App-eigenem PrivacyInfo.xcprivacy gefunden.", PLATFORM)
    findings: list[Finding] = []
    declared = any(tracking for _, tracking in manifests)
    if declared and not usage:
        for sf, tracking in manifests:
            if tracking:
                findings.append(Finding(
                    check_id=check_id, severity=Severity.ERROR,
                    message=f"Das Manifest meldet Tracking, aber {TRACKING_KEY} fehlt — ohne ihn gibt es keinen ATT-Dialog.",
                    file=sf.rel, line=1, evidence=os.path.basename(sf.rel),
                    fix="ATT-Begründung in Info.plist/InfoPlist.strings ergänzen oder, wenn die App nicht trackt, NSPrivacyTracking=false.",
                    guideline=GUIDELINE,
                ))
    return result_for(check_id, title, findings, len(manifests), "App-Privacy-Manifeste", PLATFORM)


_DOMAINS = "\t<key>NSPrivacyTrackingDomains</key>\n\t<array>\n\t\t<string>ads.example.com</string>\n\t</array>\n"


@register(
    "apple.privacy_manifest_tracking_domains",
    "Privacy-Manifest: NSPrivacyTracking und Tracking-Domains passen nicht zusammen",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline=GUIDELINE,
    rationale=("Belegt 03.11.2026 (Hopfenhölle Build 49): App-Manifest NSPrivacyTracking=true ohne "
               "NSPrivacyTrackingDomains, Apple: ITMS-91064 „Invalid tracking information“, Version auf "
               "INVALID_BINARY. Dieselbe Meldung für Domains ohne true (Braze, Unity). Gilt auch für "
               "mitgelieferte SDK-Manifeste — Apple prüft jedes im Bundle."),
    references=["https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacytrackingdomains",
                "https://github.com/opendocument-app/OpenDocument.ios/pull/107"],
    self_tests=[
        SelfTestCase(name="true ohne Domains (Build 49)", expect=Status.FAIL, expect_finding_contains="ITMS-91064",
                     files={"ios/PrivacyInfo.xcprivacy": _MANIFEST % "true"}),
        SelfTestCase(name="Domains ohne true", expect=Status.FAIL, expect_finding_contains="ITMS-91064",
                     files={"ios/PrivacyInfo.xcprivacy": _PLIST_HEAD + _DOMAINS + "\t<key>NSPrivacyTracking</key>\n\t<false/>\n" + _END}),
        SelfTestCase(name="SDK-Manifest true ohne Domains", expect=Status.FAIL, expect_finding_contains="SDK",
                     files={"ios/PrivacyInfo.xcprivacy": _MANIFEST % "false",
                            "ios/libs/Ads.xcframework/ios-arm64/PrivacyInfo.xcprivacy": _MANIFEST % "true"}),
        SelfTestCase(name="true mit Domains", expect=Status.PASS,
                     files={"ios/PrivacyInfo.xcprivacy": _PLIST_HEAD + _DOMAINS + "\t<key>NSPrivacyTracking</key>\n\t<true/>\n" + _END}),
        SelfTestCase(name="false ohne Domains", expect=Status.PASS,
                     files={"ios/PrivacyInfo.xcprivacy": _MANIFEST % "false"}),
        SelfTestCase(name="kein Manifest", expect=Status.UNMEASURED, files={"ios/game.xcodeproj/project.pbxproj": _PBX}),
    ],
)
def check_privacy_manifest_tracking_domains(ctx: Context) -> CheckResult:
    check_id = "apple.privacy_manifest_tracking_domains"
    title = "Privacy-Manifest: NSPrivacyTracking und Tracking-Domains passen nicht zusammen"
    manifests = list(ctx.files_named("PrivacyInfo.xcprivacy"))
    if not manifests:
        return unmeasured(check_id, title, "Kein PrivacyInfo.xcprivacy gefunden.", PLATFORM)
    findings: list[Finding] = []
    unreadable = 0
    for sf in manifests:
        try:
            data = plistlib.loads(sf.text.encode("utf-8"))
        except Exception:
            unreadable += 1
            continue
        tracking = data.get("NSPrivacyTracking") is True
        domains = [d for d in data.get("NSPrivacyTrackingDomains") or [] if isinstance(d, str) and d.strip()]
        if tracking == bool(domains):
            continue
        owner = "SDK-Manifest (Update des Anbieters nötig)" if _vendored(sf.rel) else "App-Manifest"
        problem = "NSPrivacyTracking=true ohne NSPrivacyTrackingDomains" if tracking else \
            f"{len(domains)} NSPrivacyTrackingDomains ohne NSPrivacyTracking=true"
        findings.append(Finding(
            check_id=check_id, severity=Severity.ERROR,
            message=f"{owner}: {problem} — Apple weist das Binary zurück (ITMS-91064).",
            file=sf.rel, line=1, evidence=os.path.basename(sf.rel),
            fix=("Trackt nur ein eingebautes SDK, im App-Manifest NSPrivacyTracking=false (Godot: "
                 "`privacy/tracking_enabled=false`); das SDK-Manifest deklariert sein Tracking selbst. Eigene "
                 "Tracking-Domains nur mit true eintragen — iOS sperrt sie ohne ATT-Zustimmung."),
            guideline=GUIDELINE,
        ))
    if unreadable == len(manifests):
        return unmeasured(check_id, title, f"{unreadable} Privacy-Manifeste nicht als Plist lesbar.", PLATFORM)
    return result_for(check_id, title, findings, len(manifests) - unreadable, "Privacy-Manifeste", PLATFORM)
