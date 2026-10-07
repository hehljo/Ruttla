"""Web → App: Anmeldung per Anbieter (Supabase OAuth) in einer Capacitor-Hülle.

Belegt am 07.10.2026 (Merkma, erster Gerätetest): die Web-App rief
`signInWithOAuth` mit `redirectTo` aus `location.origin` auf. In der Hülle ist
das `capacitor://localhost/…` — Supabase kennt die Adresse nicht und fällt
**still** auf die Site URL zurück. Der Nutzer landete nach der Google-Anmeldung
in Safari auf der Webseite (nach einer Umbenennung sogar der alten), mit
`#access_token=…` in der Adresse, statt angemeldet in der App.

Ein Python-Check statt einer TOML-Regel: die Aussage hängt am Zustand mehrerer
Dateien (Capacitor-Projekt? nativer Rücksprung irgendwo im Code? URL-Schema in
der Info.plist?), kein einzelnes Muster trägt sie.

Nicht offline messbar: ob die Rücksprungadresse in Supabase unter *Redirect
URLs* steht. Fehlt sie, passiert dasselbe — der Fix-Text sagt es deshalb dazu.
"""

from __future__ import annotations

import json
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

_ID = "web.capacitor_oauth_without_native_return"
_TITLE = "Anbieter-Anmeldung in der Capacitor-App springt nicht in die App zurück"
_GUIDELINE = "docs/GUIDELINES.md § Anbieter-Anmeldung in der Capacitor-Hülle"
_CODE_EXTS = (".js", ".mjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte")
_OAUTH = re.compile(r"\bsignInWithOAuth\s*\(")
_NATIVE = re.compile(r"\bskipBrowserRedirect\b")
_SCHEMES = re.compile(r"<key>CFBundleURLSchemes</key>\s*<array>\s*<string>[^<\s]+</string>")
_CAP_CONFIGS = ("capacitor.config.json", "capacitor.config.ts", "capacitor.config.js")
_CAP_PACKAGES = ("@capacitor/ios", "@capacitor/android")
_SKIP = set(DEFAULT_EXCLUDE_DIRS) | {"node_modules"}
# Die Hüllen tragen eine Kopie des Web-Stands (ios/App/App/public): wer dort
# sucht, findet jede Fundstelle doppelt — und einen veralteten Stand.
_SHELLS = ("ios", "android")

_CAP_CONFIG = '{"appId": "com.example.app", "webDir": "dist"}\n'
_PACKAGE = '{"devDependencies": {"@capacitor/ios": "^8.5.2"}}\n'
_WEB_ONLY = (
    "export const signIn = () => db.auth.signInWithOAuth({\n"
    "  provider: 'google', options: { redirectTo: location.origin + '/app/' } });\n"
)
_NATIVE_CODE = (
    "export const signIn = (redirectTo) => db.auth.signInWithOAuth({\n"
    "  provider: 'google', options: { redirectTo, skipBrowserRedirect: true } });\n"
)
_PLIST_WITH = (
    "<dict>\n\t<key>CFBundleURLTypes</key>\n\t<array>\n\t\t<dict>\n"
    "\t\t\t<key>CFBundleURLSchemes</key>\n\t\t\t<array>\n"
    "\t\t\t\t<string>com.example.app</string>\n\t\t\t</array>\n\t\t</dict>\n\t</array>\n</dict>\n"
)
_PLIST_WITHOUT = "<dict>\n\t<key>CFBundleDisplayName</key>\n\t<string>App</string>\n</dict>\n"


def _is_capacitor(root: str) -> bool:
    if any(os.path.isfile(os.path.join(root, name)) for name in _CAP_CONFIGS):
        return True
    try:
        with open(os.path.join(root, "package.json"), "r", encoding="utf-8") as fh:
            pkg = json.load(fh)
    except (OSError, ValueError):
        return False
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    return any(name in deps for name in _CAP_PACKAGES)


def _ios_plists(root: str) -> list[str]:
    """Info.plist-Dateien unter ios/ — nur dort liegt die Hülle."""
    base = os.path.join(root, "ios")
    found = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _SKIP]
        if "Info.plist" in filenames:
            found.append(os.path.join(dirpath, "Info.plist"))
    return found


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


@register(
    _ID, _TITLE, platform="web", severity=Severity.ERROR,
    guideline=_GUIDELINE,
    references=("https://supabase.com/docs/guides/auth/native-mobile-deep-linking",
                "https://capacitorjs.com/docs/apis/app#addlistenerappurlopen-"),
    self_tests=[
        SelfTestCase("Capacitor, Anmeldung nur mit Web-Rücksprung", {
            "capacitor.config.json": _CAP_CONFIG,
            "package.json": _PACKAGE,
            "src/auth.js": _WEB_ONLY,
        }, Status.FAIL, expect_finding_contains="Site URL"),
        SelfTestCase("Capacitor, nativer Rücksprung steht nur im Kommentar", {
            "package.json": _PACKAGE,
            "src/auth.js": "// TODO: skipBrowserRedirect für die App\n" + _WEB_ONLY,
        }, Status.FAIL, expect_finding_contains="Site URL"),
        SelfTestCase("Capacitor, nativer Rücksprung ohne URL-Schema in der Info.plist", {
            "capacitor.config.json": _CAP_CONFIG,
            "src/auth.js": _NATIVE_CODE,
            "ios/App/App/Info.plist": _PLIST_WITHOUT,
        }, Status.FAIL, expect_finding_contains="CFBundleURLSchemes"),
        SelfTestCase("Capacitor, nativer Rücksprung mit URL-Schema", {
            "capacitor.config.json": _CAP_CONFIG,
            "src/auth.js": _NATIVE_CODE,
            "ios/App/App/Info.plist": _PLIST_WITH,
        }, Status.PASS),
        SelfTestCase("Capacitor, alte Web-Kopie in der Hülle zählt nicht", {
            "capacitor.config.json": _CAP_CONFIG,
            "public/scripts/data.js": _NATIVE_CODE,
            "ios/App/App/public/scripts/data.js": _WEB_ONLY,
            "ios/App/App/Info.plist": _PLIST_WITH,
        }, Status.PASS),
        SelfTestCase("Capacitor ohne iOS-Hülle, nativer Rücksprung", {
            "package.json": _PACKAGE,
            "src/auth.js": _NATIVE_CODE,
        }, Status.PASS),
        SelfTestCase("Reine Web-App mit Anbieter-Anmeldung", {
            "package.json": '{"dependencies": {"@supabase/supabase-js": "^2"}}\n',
            "src/auth.js": _WEB_ONLY,
        }, Status.UNMEASURED),
        SelfTestCase("Capacitor ohne Anbieter-Anmeldung", {
            "capacitor.config.json": _CAP_CONFIG,
            "src/main.js": "export const x = 1;\n",
        }, Status.UNMEASURED),
    ],
)
def check_capacitor_oauth(ctx: Context) -> CheckResult:
    """Prüfgegenstand ist jede Anbieter-Anmeldung in einem Capacitor-Projekt.
    Gebraucht wird ein nativer Weg (`skipBrowserRedirect`, danach Browser-
    Fenster und `appUrlOpen`) und, wo eine iOS-Hülle existiert, ein URL-Schema,
    über das iOS den Rücksprung an die App gibt."""
    if not _is_capacitor(ctx.root):
        return unmeasured(_ID, _TITLE, "Kein Capacitor-Projekt (capacitor.config.* oder "
                          "@capacitor/ios|android in package.json).", "web")

    calls: list[tuple[str, int]] = []
    native = False
    for sf in ctx.files(*_CODE_EXTS):
        if sf.rel.split("/", 1)[0] in _SHELLS:
            continue
        code = strip_comments(sf.text, sf.ext)
        for m in _OAUTH.finditer(code):
            calls.append((sf.rel, _line_of(code, m.start())))
        if _NATIVE.search(code):
            native = True
    if not calls:
        return unmeasured(_ID, _TITLE, "Capacitor-Projekt ohne signInWithOAuth-Aufruf.", "web")

    findings: list[Finding] = []
    if not native:
        rel, line = calls[0]
        findings.append(Finding(
            check_id=_ID, severity=Severity.ERROR,
            message=("signInWithOAuth ohne nativen Rücksprung: in der Hülle ist die Seite "
                     "capacitor://localhost, Supabase kennt die Adresse nicht und fällt still "
                     "auf die Site URL zurück — der Nutzer landet angemeldet in Safari auf der "
                     "Webseite statt in der App."),
            file=rel, line=line, evidence="signInWithOAuth(",
            fix=("In der App: skipBrowserRedirect: true, data.url in @capacitor/browser öffnen, "
                 "Rücksprung <appId>://<host> per @capacitor/app (appUrlOpen + getLaunchUrl) "
                 "mit flowType 'pkce' einlösen; die Adresse in Supabase unter Redirect URLs "
                 "eintragen (offline nicht messbar)."),
            guideline=_GUIDELINE,
        ))

    plists = _ios_plists(ctx.root)
    if native and plists:
        with_scheme = []
        for path in plists:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    if _SCHEMES.search(fh.read()):
                        with_scheme.append(path)
            except OSError:
                continue
        if not with_scheme:
            rel = os.path.relpath(plists[0], ctx.root).replace(os.sep, "/")
            findings.append(Finding(
                check_id=_ID, severity=Severity.ERROR,
                message=("Nativer Rücksprung im Code, aber keine Info.plist der iOS-Hülle trägt "
                         "CFBundleURLSchemes: iOS reicht <appId>://… nicht an die App weiter, der "
                         "Rücksprung bleibt im Browserfenster hängen."),
                file=rel, line=1, evidence="CFBundleURLSchemes fehlt",
                fix=("CFBundleURLTypes mit dem Schema der Rücksprungadresse eintragen — "
                     "generiert aus der appId, nicht von Hand."),
                guideline=_GUIDELINE,
            ))

    return result_for(_ID, _TITLE, findings, len(calls), "Anbieter-Anmeldungen", "web")
