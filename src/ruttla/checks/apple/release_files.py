"""Apple release: plist, String Catalog and asset catalog syntax.

Split from the original checks/apple_release.py; background and
shared helpers in _release_common.py.
"""

from __future__ import annotations

import json
import os
import plistlib

from ruttla.core import (
    CheckResult,
    Context,
    Finding,
    register,
    result_for,
    SelfTestCase,
    Severity,
    Status,
    unmeasured,
)

from ._release_common import (
    _HEALTHY_CONTENTS,
    _HEALTHY_PLIST,
    _HEALTHY_XCSTRINGS,
    _walk_files,
    PLATFORM,
)


@register(
    "apple.release.plist_syntax",
    "Apple-Property-List ist nicht lesbar",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="Apple: About Info.plist Keys and Values",
    self_tests=[
        SelfTestCase(
            name="gesund: verschachtelte Property List",
            files={"App/Info.plist": _HEALTHY_PLIST},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: beschädigte Property List",
            files={"App/Info.plist": "<?xml version=\"1.0\"?><plist><dict><key>Name</key><string>x</dict></plist>\n"},
            expect=Status.FAIL,
        ),
    ],
)
def check_plist_syntax(ctx: Context) -> CheckResult:
    title = "Apple-Property-List ist nicht lesbar"
    candidates = [(path, rel) for path, rel in _walk_files(ctx)
                  if rel.endswith((".plist", ".entitlements", ".xcprivacy"))]
    if not candidates:
        return unmeasured("apple.release.plist_syntax", title,
                          "Keine Property-List-Datei gefunden.", PLATFORM)
    findings: list[Finding] = []
    for path, rel in candidates:
        try:
            with open(path, "rb") as handle:
                plistlib.load(handle)
        except Exception as exc:
            findings.append(Finding(
                check_id="apple.release.plist_syntax",
                severity=Severity.ERROR,
                message=f"Property List kann nicht gelesen werden ({type(exc).__name__}).",
                file=rel,
                fix="Datei als gültige XML- oder Binär-Property-List neu speichern.",
            ))
    return result_for("apple.release.plist_syntax", title, findings,
                      len(candidates), "Property-List-Dateien", PLATFORM)


@register(
    "apple.release.xcstrings_json",
    "String Catalog enthält ungültiges JSON",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="Apple: Localizing and varying text with a string catalog",
    self_tests=[
        SelfTestCase(
            name="gesund: gültiger String Catalog",
            files={"App/Localizable.xcstrings": _HEALTHY_XCSTRINGS},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: JSON mit nachlaufendem Komma",
            files={"App/Localizable.xcstrings": '{"sourceLanguage":"en","strings":{},}\n'},
            expect=Status.FAIL,
        ),
    ],
)
def check_xcstrings_json(ctx: Context) -> CheckResult:
    title = "String Catalog enthält ungültiges JSON"
    candidates = [(path, rel) for path, rel in _walk_files(ctx)
                  if rel.endswith(".xcstrings")]
    if not candidates:
        return unmeasured("apple.release.xcstrings_json", title,
                          "Kein .xcstrings-Katalog gefunden.", PLATFORM)
    findings: list[Finding] = []
    for path, rel in candidates:
        try:
            with open(path, "rb") as handle:
                json.load(handle)
        except json.JSONDecodeError as exc:
            findings.append(Finding(
                check_id="apple.release.xcstrings_json",
                severity=Severity.ERROR,
                message=f"String Catalog ist kein gültiges JSON: {exc.msg}.",
                file=rel,
                line=exc.lineno,
                fix="JSON-Syntax korrigieren oder den Katalog in Xcode neu speichern.",
            ))
        except (OSError, UnicodeError) as exc:
            findings.append(Finding(
                check_id="apple.release.xcstrings_json",
                severity=Severity.ERROR,
                message=f"String Catalog ist nicht lesbar ({type(exc).__name__}).",
                file=rel,
                fix="Kodierung, Dateirechte und Checkout prüfen.",
            ))
    return result_for("apple.release.xcstrings_json", title, findings,
                      len(candidates), "String-Kataloge", PLATFORM)


@register(
    "apple.release.asset_contents_json",
    "Asset-Catalog Contents.json enthält ungültiges JSON",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="Apple Asset Catalog Format Reference § Contents.json File",
    self_tests=[
        SelfTestCase(
            name="gesund: gültiges Asset Contents.json",
            files={"App/Assets.xcassets/AppIcon.appiconset/Contents.json": _HEALTHY_CONTENTS},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: abgeschnittenes Asset-JSON",
            files={"App/Assets.xcassets/AppIcon.appiconset/Contents.json": '{"images":[\n'},
            expect=Status.FAIL,
        ),
    ],
)
def check_asset_contents_json(ctx: Context) -> CheckResult:
    title = "Asset-Catalog Contents.json enthält ungültiges JSON"
    candidates: list[tuple[str, str]] = []
    for path, rel in _walk_files(ctx):
        parts = rel.replace(os.sep, "/").split("/")
        if (os.path.basename(path) == "Contents.json"
                and any(part.endswith(".xcassets") for part in parts[:-1])):
            candidates.append((path, rel))
    if not candidates:
        return unmeasured("apple.release.asset_contents_json", title,
                          "Kein Contents.json in einem .xcassets-Katalog gefunden.",
                          PLATFORM)
    findings: list[Finding] = []
    for path, rel in candidates:
        try:
            with open(path, "rb") as handle:
                json.load(handle)
        except json.JSONDecodeError as exc:
            findings.append(Finding(
                check_id="apple.release.asset_contents_json",
                severity=Severity.ERROR,
                message=f"Asset Contents.json ist kein gültiges JSON: {exc.msg}.",
                file=rel,
                line=exc.lineno,
                fix="JSON-Syntax korrigieren oder den Asset-Katalog in Xcode neu speichern.",
            ))
        except (OSError, UnicodeError) as exc:
            findings.append(Finding(
                check_id="apple.release.asset_contents_json",
                severity=Severity.ERROR,
                message=f"Asset Contents.json ist nicht lesbar ({type(exc).__name__}).",
                file=rel,
                fix="Kodierung, Dateirechte und Checkout prüfen.",
            ))
    return result_for("apple.release.asset_contents_json", title, findings,
                      len(candidates), "Asset-Contents-Dateien", PLATFORM)
