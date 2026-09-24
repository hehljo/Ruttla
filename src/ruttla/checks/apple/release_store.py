"""Apple release: App Store requirements per app target.

Split from the original checks/apple_release.py; background and
shared helpers in _release_common.py.
"""

from __future__ import annotations

import json
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

from ._release_common import (
    _app_target_projects,
    _BROKEN_IDENTITY_PLIST,
    _BROKEN_SIGNING,
    _CATALOG_PROJECT,
    _COMPLETE_CATALOG,
    _HEALTHY_IDENTITY_PLIST,
    _HEALTHY_SIGNING,
    _IDENTITY_PROJECT,
    _INCOMPLETE_CATALOG,
    _IOS_SANDBOX_PROJECT,
    _plist_for_configuration,
    _project_fixture,
    _read_plist,
    _SANDBOX_MISSING,
    _SANDBOX_ON,
    _SANDBOX_PROJECT,
    _setting,
    _walk_files,
    PLATFORM,
)


@register(
    "apple.release.app_category_missing",
    "App-Target ohne LSApplicationCategoryType",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="Apple: LSApplicationCategoryType (Information Property List)",
    # Hart ohne Profil: App Store Connect lehnt den Upload ohne Kategorie ab.
    # Ein falsch-positiver Fall ist ausgeschlossen, weil beide zulässigen
    # Bauformen (Plist-Key und INFOPLIST_KEY_*) geprüft werden und ein nicht
    # auflösbares Target UNMEASURED statt FAIL liefert.
    safe_by_default=True,
    self_tests=[
        SelfTestCase(
            name="gesund: Kategorie in der Info.plist",
            files={"P.xcodeproj/project.pbxproj": _IDENTITY_PROJECT,
                   "App/Info.plist": _HEALTHY_IDENTITY_PLIST},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="gesund: Kategorie als INFOPLIST_KEY im Target",
            files={"P.xcodeproj/project.pbxproj": _project_fixture(
                INFOPLIST_KEY_LSApplicationCategoryType="public.app-category.utilities",
                PRODUCT_BUNDLE_IDENTIFIER="com.example.App")},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: weder Plist-Key noch Build-Setting",
            files={"P.xcodeproj/project.pbxproj": _IDENTITY_PROJECT,
                   "App/Info.plist": _BROKEN_IDENTITY_PLIST},
            expect=Status.FAIL,
            expect_finding_contains="LSApplicationCategoryType",
        ),
        SelfTestCase(
            # Xcode erzeugt die Info.plist erst beim Build. Die Quelle kann
            # die Angabe nicht enthalten, also ist sie nicht gemessen — ein
            # PASS wäre hier eine falsch grüne Zusage.
            name="nicht gemessen: Info.plist wird generiert",
            files={"P.xcodeproj/project.pbxproj": _project_fixture(
                GENERATE_INFOPLIST_FILE="YES",
                INFOPLIST_FILE="App/Info.plist",
                PRODUCT_BUNDLE_IDENTIFIER="com.example.App")},
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_app_category(ctx: Context) -> CheckResult:
    """App Store Connect lehnt einen Upload ohne App-Kategorie ab.

    Gemessen wird die Eigenschaft 'die Kategorie erreicht das gebaute Bundle',
    nicht eine bestimmte Bauform: Xcode erlaubt sie als Schlüssel in der
    Info.plist ODER als INFOPLIST_KEY_* im Target. Beide Wege sind gültig,
    ein Gate, das nur einen verlangt, verbietet den anderen.

    Belegt am 2026-09-22 (reale macOS-App): Im Target unter Identity war 'App Category'
    leer und der Schlüssel fehlte im Custom macOS Application Target
    Properties. Der lokale Build war grün, Apple meldete den Fehler erst
    nach dem Upload.
    """
    check_id = "apple.release.app_category_missing"
    title = "App-Target ohne LSApplicationCategoryType"
    projects = _app_target_projects(ctx)
    if not projects:
        return unmeasured(check_id, title, "Kein .xcodeproj gefunden.", PLATFORM)

    findings: list[Finding] = []
    examined = 0
    unresolved = 0
    for project, rel, configs in projects:
        if not configs:
            continue
        for config in configs:
            if not config["resolved"]:
                unresolved += 1
                continue
            examined += 1
            setting = _setting(config["block"],
                               "INFOPLIST_KEY_LSApplicationCategoryType")
            if setting:
                continue
            plist_entry = _plist_for_configuration(ctx, project, config)
            if plist_entry is None:
                # Kein lesbarer Anzeigeort: bei GENERATE_INFOPLIST_FILE = YES
                # erzeugt Xcode die Datei erst beim Build, die Quelle enthält
                # sie nicht. Das ist NICHT GEMESSEN, nie bestanden — sonst
                # meldet der Check für genau die Projekte grün, deren Angabe
                # er gar nicht sehen kann (belegt an einer veröffentlichten iOS-App, 2026-09-22).
                unresolved += 1
                examined -= 1
                continue
            data = _read_plist(plist_entry[0])
            if data is None:
                unresolved += 1
                examined -= 1
                continue
            if str(data.get("LSApplicationCategoryType") or "").strip():
                continue
            findings.append(Finding(
                check_id=check_id, severity=Severity.ERROR,
                message=f"LSApplicationCategoryType fehlt für Target "
                        f"'{config['target']}' ({config['config']}).",
                file=plist_entry[1] if plist_entry else rel,
                fix="In Xcode unter Target > General > Identity eine App "
                    "Category wählen, oder LSApplicationCategoryType "
                    "(z. B. public.app-category.utilities) in die Info.plist "
                    "schreiben. App Store Connect lehnt den Upload sonst ab.",
                guideline="Apple: LSApplicationCategoryType",
            ))
    if examined == 0:
        return unmeasured(
            check_id, title,
            f"Keine auflösbare App-Target-Konfiguration gefunden "
            f"({unresolved} nicht auflösbar).", PLATFORM)
    return result_for(check_id, title, findings, examined,
                      "App-Target-Konfigurationen", PLATFORM)


@register(
    "apple.release.display_name_missing",
    "App-Target ohne CFBundleDisplayName",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="Apple: CFBundleDisplayName (Information Property List)",
    self_tests=[
        SelfTestCase(
            name="gesund: Anzeigename in der Info.plist",
            files={"P.xcodeproj/project.pbxproj": _IDENTITY_PROJECT,
                   "App/Info.plist": _HEALTHY_IDENTITY_PLIST},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: nur CFBundleName, kein Anzeigename",
            files={"P.xcodeproj/project.pbxproj": _IDENTITY_PROJECT,
                   "App/Info.plist": _BROKEN_IDENTITY_PLIST},
            expect=Status.FAIL,
            expect_finding_contains="CFBundleDisplayName",
        ),
    ],
)
def check_display_name(ctx: Context) -> CheckResult:
    """Ohne CFBundleDisplayName zeigt der Finder den Dateinamen.

    Belegt am 2026-09-22 (reale macOS-App): Display Name war im Target unter Identity
    leer. Das bricht keinen Build — es fällt erst auf, wenn die App unter
    ihrem Produktnamen statt ihrem Markennamen im Dock steht.
    """
    check_id = "apple.release.display_name_missing"
    title = "App-Target ohne CFBundleDisplayName"
    projects = _app_target_projects(ctx)
    if not projects:
        return unmeasured(check_id, title, "Kein .xcodeproj gefunden.", PLATFORM)

    findings: list[Finding] = []
    examined = 0
    unresolved = 0
    for project, rel, configs in projects:
        for config in configs:
            if not config["resolved"]:
                unresolved += 1
                continue
            setting = _setting(config["block"],
                               "INFOPLIST_KEY_CFBundleDisplayName")
            if setting:
                examined += 1
                continue
            plist_entry = _plist_for_configuration(ctx, project, config)
            if plist_entry is None:
                unresolved += 1
                continue
            data = _read_plist(plist_entry[0])
            if data is None:
                unresolved += 1
                continue
            examined += 1
            value = str(data.get("CFBundleDisplayName") or "").strip()
            if value:
                continue
            findings.append(Finding(
                check_id=check_id, severity=Severity.WARNING,
                message=f"CFBundleDisplayName fehlt für Target "
                        f"'{config['target']}' ({config['config']}).",
                file=plist_entry[1],
                fix="CFBundleDisplayName in die Info.plist schreiben oder in "
                    "Xcode unter Target > General > Identity > Display Name "
                    "setzen. Ohne den Schlüssel zeigt macOS CFBundleName.",
                guideline="Apple: CFBundleDisplayName",
            ))
    if examined == 0:
        return unmeasured(
            check_id, title,
            f"Keine App-Target-Konfiguration mit auflösbarer Info.plist "
            f"({unresolved} nicht auflösbar).", PLATFORM)
    return result_for(check_id, title, findings, examined,
                      "App-Target-Konfigurationen", PLATFORM)


@register(
    "apple.release.signing_team_missing",
    "App-Target ohne DEVELOPMENT_TEAM",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="Apple: Distributing your app for beta testing and releases",
    self_tests=[
        SelfTestCase(
            name="gesund: Team im App-Target gesetzt",
            files={"P.xcodeproj/project.pbxproj": _HEALTHY_SIGNING},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: Team leer im App-Target",
            files={"P.xcodeproj/project.pbxproj": _BROKEN_SIGNING},
            expect=Status.FAIL,
            expect_finding_contains="DEVELOPMENT_TEAM",
        ),
    ],
)
def check_signing_team(ctx: Context) -> CheckResult:
    """DEVELOPMENT_TEAM muss im App-Target stehen, nicht irgendwo in der Datei.

    Der Prüfbereich ist die einzelne Target-Konfiguration. Das bestehende
    `apple.project_settings` sucht denselben Schlüssel mit einem dateiweiten
    re.search — bei einer realen macOS-App blieb es dadurch grün, obwohl das App-Target kein
    Team trug und die Signierung bei Apple scheiterte (2026-09-22).
    """
    check_id = "apple.release.signing_team_missing"
    title = "App-Target ohne DEVELOPMENT_TEAM"
    projects = _app_target_projects(ctx)
    if not projects:
        return unmeasured(check_id, title, "Kein .xcodeproj gefunden.", PLATFORM)

    findings: list[Finding] = []
    examined = 0
    unresolved = 0
    for _project, rel, configs in projects:
        for config in configs:
            if not config["resolved"]:
                unresolved += 1
                continue
            examined += 1
            team = _setting(config["block"], "DEVELOPMENT_TEAM")
            if team:
                continue
            reason = ("ist leer" if team == "" else "fehlt")
            findings.append(Finding(
                check_id=check_id, severity=Severity.WARNING,
                message=f"DEVELOPMENT_TEAM {reason} in Target "
                        f"'{config['target']}' ({config['config']}).",
                file=rel,
                fix="In Xcode unter Target > Signing & Capabilities das Team "
                    "wählen. Ohne Team schlägt die Distributionssignierung "
                    "fehl; ein lokaler Debug-Build bleibt davon unberührt.",
                guideline="Apple: Distributing your app",
            ))
    if examined == 0:
        return unmeasured(
            check_id, title,
            f"Keine auflösbare App-Target-Konfiguration gefunden "
            f"({unresolved} nicht auflösbar).", PLATFORM)
    return result_for(check_id, title, findings, examined,
                      "App-Target-Konfigurationen", PLATFORM)


@register(
    "apple.release.app_sandbox_missing",
    "macOS-App ohne App-Sandbox-Entitlement",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="Apple: com.apple.security.app-sandbox (App Sandbox Entitlement)",
    # Hart ohne Profil: App Review verlangt die Sandbox für jede
    # Mac-App-Store-App. Der Check läuft nur auf macOS-Projekten mit
    # auflösbarer Entitlements-Datei, sonst UNMEASURED.
    safe_by_default=True,
    self_tests=[
        SelfTestCase(
            name="gesund: Sandbox aktiviert",
            files={"P.xcodeproj/project.pbxproj": _SANDBOX_PROJECT,
                   "App/App.entitlements": _SANDBOX_ON},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: Entitlements ohne app-sandbox",
            files={"P.xcodeproj/project.pbxproj": _SANDBOX_PROJECT,
                   "App/App.entitlements": _SANDBOX_MISSING},
            expect=Status.FAIL,
            expect_finding_contains="app-sandbox",
        ),
        SelfTestCase(
            name="gesund: iOS-Target ohne Sandbox-Schlüssel",
            files={"P.xcodeproj/project.pbxproj": _IOS_SANDBOX_PROJECT,
                   "App/App.entitlements": _SANDBOX_MISSING},
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_app_sandbox(ctx: Context) -> CheckResult:
    """App Review verlangt com.apple.security.app-sandbox für jede Mac-App.

    Gemessen wird der Wert im Entitlement, nicht die Existenz der Datei: eine
    Entitlements-Datei mit Sandbox-Unterschlüsseln, aber ohne den
    Sandbox-Schalter selbst, sieht vollständig aus und ist es nicht.

    Belegt am 2026-09-22 (reale macOS-App): Die Datei trug
    com.apple.security.network.client und files.user-selected.read-write,
    aber nicht com.apple.security.app-sandbox. Unter Signing & Capabilities
    fehlte die Capability 'App Sandbox' deshalb ganz.
    """
    check_id = "apple.release.app_sandbox_missing"
    title = "macOS-App ohne App-Sandbox-Entitlement"
    projects = _app_target_projects(ctx)
    if not projects:
        return unmeasured(check_id, title, "Kein .xcodeproj gefunden.", PLATFORM)

    findings: list[Finding] = []
    examined = 0
    unresolved = 0
    seen: set[str] = set()
    for project, rel, configs in projects:
        for config in configs:
            if not config["resolved"]:
                unresolved += 1
                continue
            # Die Regel gilt für macOS. Ein iOS-Target sandboxt implizit und
            # trägt den Schlüssel nicht — dort wäre der Befund falsch positiv.
            if not config.get("macos"):
                continue
            raw = _setting(config["block"], "CODE_SIGN_ENTITLEMENTS")
            if not raw or "$(" in raw:
                unresolved += 1
                continue
            path = os.path.normpath(os.path.join(os.path.dirname(project), raw))
            if not os.path.isfile(path):
                findings.append(Finding(
                    check_id=check_id, severity=Severity.ERROR,
                    message=f"CODE_SIGN_ENTITLEMENTS zeigt auf '{raw}', "
                            f"die Datei fehlt.",
                    file=rel,
                    fix="Pfad korrigieren oder die Entitlements-Datei anlegen.",
                ))
                examined += 1
                continue
            entitlements_rel = to_posix(os.path.relpath(path, ctx.root))
            if entitlements_rel in seen:
                continue
            seen.add(entitlements_rel)
            data = _read_plist(path)
            if data is None:
                unresolved += 1
                continue
            examined += 1
            if data.get("com.apple.security.app-sandbox") is True:
                continue
            present = "com.apple.security.app-sandbox" in data
            message = ("com.apple.security.app-sandbox steht auf "
                       f"{data.get('com.apple.security.app-sandbox')!r}."
                       if present else
                       "com.apple.security.app-sandbox fehlt im Entitlement.")
            findings.append(Finding(
                check_id=check_id, severity=Severity.ERROR,
                message=message,
                file=entitlements_rel,
                fix="In Xcode unter Signing & Capabilities die Capability "
                    "'App Sandbox' hinzufügen, oder "
                    "com.apple.security.app-sandbox = true in die "
                    "Entitlements schreiben. App Review verlangt sie für "
                    "jede Mac-App-Store-App.",
                guideline="Apple: App Sandbox Entitlement",
            ))
    if examined == 0:
        return unmeasured(
            check_id, title,
            f"Keine macOS-App-Konfiguration mit auflösbarer "
            f"Entitlements-Datei ({unresolved} nicht auflösbar).", PLATFORM)
    return result_for(check_id, title, findings, examined,
                      "Entitlements-Dateien", PLATFORM)


@register(
    "apple.release.xcstrings_incomplete",
    "String Catalog hat unübersetzte Schlüssel",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="Apple: Localizing and varying text with a string catalog",
    self_tests=[
        SelfTestCase(
            name="gesund: alle Sprachen vollständig",
            files={"P.xcodeproj/project.pbxproj": _CATALOG_PROJECT,
                   "App/Localizable.xcstrings": _COMPLETE_CATALOG},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: ein Schlüssel ohne englische Übersetzung",
            files={"P.xcodeproj/project.pbxproj": _CATALOG_PROJECT,
                   "App/Localizable.xcstrings": _INCOMPLETE_CATALOG},
            expect=Status.FAIL,
            expect_finding_contains="en",
        ),
    ],
)
def check_xcstrings_complete(ctx: Context) -> CheckResult:
    """Ein halb gepflegter Katalog sieht aus wie eine Quelle und ist keine.

    Der Prüfgegenstand ist der Kandidat: gezählt werden alle Schlüssel des
    Katalogs, nicht nur die Lücken. Die erwarteten Sprachen werden aus dem
    Katalog selbst abgeleitet (jede Sprache, die irgendein Schlüssel trägt) —
    eine gepflegte Sprachliste im Gate wäre die zweite Liste.

    Belegt am 2026-09-22 (reale macOS-App): Der Katalog wuchs von 27 auf 52 Schlüssel,
    47 davon blieben in mindestens einer Sprache unübersetzt. In der App war
    die Oberfläche dadurch nur teilweise lokalisiert.
    """
    check_id = "apple.release.xcstrings_incomplete"
    title = "String Catalog hat unübersetzte Schlüssel"
    candidates = [(path, rel) for path, rel in _walk_files(ctx)
                  if rel.endswith(".xcstrings")]
    if not candidates:
        return unmeasured(check_id, title,
                          "Kein .xcstrings-Katalog gefunden.", PLATFORM)

    findings: list[Finding] = []
    examined = 0
    unreadable = 0
    for path, rel in candidates:
        try:
            with open(path, "rb") as handle:
                data = json.load(handle)
        except Exception:
            # Syntaxfehler meldet apple.release.xcstrings_json; hier wäre er
            # ein zweiter Befund für dieselbe Ursache.
            unreadable += 1
            continue
        if not isinstance(data, dict):
            unreadable += 1
            continue
        strings = data.get("strings")
        if not isinstance(strings, dict) or not strings:
            continue

        expected: set[str] = set()
        source = str(data.get("sourceLanguage") or "").strip()
        if source:
            expected.add(source)
        for entry in strings.values():
            if isinstance(entry, dict):
                localizations = entry.get("localizations")
                if isinstance(localizations, dict):
                    expected |= set(localizations.keys())
        if len(expected) < 2:
            # Einsprachiger Katalog: es gibt keine Lücke zu messen.
            continue

        incomplete: list[tuple[str, list[str]]] = []
        for key, entry in strings.items():
            if not isinstance(entry, dict):
                continue
            examined += 1
            # Ein Schlüssel, der ausdrücklich nicht übersetzt werden soll,
            # ist kein Befund — das ist Apples eigener Schalter dafür.
            if entry.get("shouldTranslate") is False:
                continue
            localizations = entry.get("localizations")
            localizations = localizations if isinstance(localizations, dict) else {}
            missing: list[str] = []
            for language in sorted(expected):
                unit = localizations.get(language)
                if not isinstance(unit, dict):
                    # Der Quellsprache darf der Eintrag fehlen: dann ist der
                    # Schlüssel selbst der Text.
                    if language != source:
                        missing.append(language)
                    continue
                state = str(
                    (unit.get("stringUnit") or {}).get("state") or ""
                ).strip()
                if state in {"needs_review", "new", "stale"}:
                    missing.append(language)
            if missing:
                incomplete.append((key, missing))

        if incomplete:
            languages = sorted({lang for _key, langs in incomplete
                                for lang in langs})
            preview = ", ".join(repr(key[:40]) for key, _ in incomplete[:3])
            findings.append(Finding(
                check_id=check_id, severity=Severity.WARNING,
                message=f"{len(incomplete)} von {len(strings)} Schlüsseln "
                        f"unvollständig ({', '.join(languages)}): {preview}"
                        f"{' …' if len(incomplete) > 3 else ''}.",
                file=rel,
                fix="Katalog in Xcode öffnen und die offenen Sprachen füllen, "
                    "oder shouldTranslate=false setzen, wo Absicht. Eine "
                    "halb gefüllte Sprache wirkt im UI wie ein Bug.",
                guideline="Apple: String Catalogs",
            ))
    if examined == 0:
        return unmeasured(
            check_id, title,
            f"Kein mehrsprachiger Katalog mit Schlüsseln gefunden "
            f"({unreadable} nicht lesbar).", PLATFORM)
    return result_for(check_id, title, findings, examined,
                      "Katalogschlüssel", PLATFORM)
