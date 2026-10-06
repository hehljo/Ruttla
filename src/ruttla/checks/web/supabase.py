"""Offline check for browser-visible Supabase loopback URLs on remote Vite hosts."""

from __future__ import annotations

import re
import tomllib
from urllib.parse import urlsplit

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status,
    register, result_for, strip_comments, unmeasured,
)


_ID = "web.supabase_loopback_on_remote_dev_host"
_TITLE = "Supabase-Loopback im extern erreichbaren Vite-Frontend"
_ENV_NAMES = (".env", ".env.development", ".env.local", ".env.development.local")
_ASSIGNMENT = re.compile(r"^[ \t]*VITE_SUPABASE_URL\s*=\s*(.*?)\s*$", re.MULTILINE)
_HOST_LIST = re.compile(r"\ballowedHosts\s*:\s*\[([^\]]*)\]", re.DOTALL)
_QUOTED = re.compile(r"['\"]([^'\"]+)['\"]")
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


@register(
    _ID, _TITLE, platform="web", severity=Severity.WARNING,
    guideline="docs/GUIDELINES.md § Browser-Supabase im Remote-Dev-Modus",
    references=("https://supabase.com/docs/guides/auth/redirect-urls",
                "https://vite.dev/config/server-options.html#server-allowedhosts"),
    self_tests=[
        SelfTestCase("Remote-Host und Cloud-Supabase", {
            "vite.config.ts": "export default {server:{allowedHosts:['dev.example.test']}};",
            ".env": "VITE_SUPABASE_URL=https://project.supabase.co\n",
        }, Status.PASS),
        SelfTestCase("Nur lokaler Dev-Host mit Loopback", {
            "vite.config.ts": "export default {server:{allowedHosts:['localhost']}};",
            ".env": "VITE_SUPABASE_URL=http://127.0.0.1:54321\n",
        }, Status.PASS),
        SelfTestCase("Remote-Host mit Browser-Loopback", {
            "vite.config.ts": "export default {server:{allowedHosts:['dev.example.test']}};",
            ".env": "VITE_SUPABASE_URL=http://127.0.0.1:54321\n",
        }, Status.FAIL),
        SelfTestCase("Remote-Host mit localhost", {
            "vite.config.ts": "export default {server:{allowedHosts:['dev.example.test']}};",
            ".env.local": "VITE_SUPABASE_URL='http://localhost:54321'\n",
        }, Status.FAIL),
        SelfTestCase("Dev-Override auf Cloud gewinnt", {
            "vite.config.ts": "export default {server:{allowedHosts:['dev.example.test']}};",
            ".env": "VITE_SUPABASE_URL=http://127.0.0.1:54321\n",
            ".env.development.local": "VITE_SUPABASE_URL=https://project.supabase.co\n",
        }, Status.PASS),
        SelfTestCase("Dokumentierte Loopback-URL ohne aktive Konfiguration", {
            "vite.config.ts": "// allowedHosts: ['dev.example.test']\nexport default {};",
            ".env": "VITE_SUPABASE_URL=http://127.0.0.1:54321\n",
        }, Status.UNMEASURED),
    ],
)
def check_supabase_loopback(ctx: Context) -> CheckResult:
    """Eine Browser-App auf einem fremden Host erreicht 127.0.0.1/localhost
    auf dem *Client*, nicht auf dem Dev-Server. Dadurch kann OAuth auf den
    falschen lokalen Supabase-Stack zeigen. Der Check misst nur explizite
    allowedHosts-Listen und statische Dev-Env-Dateien; Prozess-Overrides,
    Reverse-Proxys und den tatsächlich laufenden Supabase-Stack nicht.
    """
    configs = [sf for sf in ctx.all_files() if sf.rel in ("vite.config.ts", "vite.config.js", "vite.config.mts", "vite.config.mjs")]
    env_files = {sf.rel: sf for sf in ctx.all_files() if sf.rel in _ENV_NAMES}
    if not configs or not env_files:
        return unmeasured(_ID, _TITLE, "Vite-Konfiguration oder Dev-Env-Datei fehlt.", "web")

    effective = None
    for name in _ENV_NAMES:
        sf = env_files.get(name)
        if not sf:
            continue
        values = list(_ASSIGNMENT.finditer(sf.text))
        if values:
            effective = (sf, values[-1])
    if effective is None:
        return unmeasured(_ID, _TITLE, "Keine statische VITE_SUPABASE_URL in Dev-Env-Dateien.", "web")

    env_sf, assignment = effective
    value = assignment.group(1).strip().strip("'\"")
    try:
        host = urlsplit(value).hostname
    except ValueError:
        host = None
    findings: list[Finding] = []
    measured = 0
    for config in configs:
        body = strip_comments(config.text, config.ext)
        for hosts in _HOST_LIST.finditer(body):
            measured += 1
            has_remote = any(h not in _LOOPBACK and h != ".localhost"
                             for h in _QUOTED.findall(hosts.group(1)))
            if has_remote and host in _LOOPBACK:
                findings.append(Finding(
                    check_id=_ID, severity=Severity.WARNING,
                    message="Extern erreichbarer Vite-Host mit Browser-Supabase auf Loopback.",
                    file=env_sf.rel, line=env_sf.line_of(assignment.start()),
                    evidence="VITE_SUPABASE_URL verweist auf Browser-Loopback (Wert ausgeblendet).",
                    fix="Für Remote-Dev eine erreichbare Supabase-URL verwenden und OAuth-Redirects separat prüfen.",
                    guideline="docs/GUIDELINES.md § Browser-Supabase im Remote-Dev-Modus",
                ))
    if measured == 0:
        return unmeasured(_ID, _TITLE, "Keine statische Vite-allowedHosts-Liste gefunden.", "web")
    return result_for(_ID, _TITLE, findings, measured, "Vite-Hostlisten", "web")


_SMTP_ID = "web.supabase_email_login_without_smtp"
_SMTP_TITLE = "Mail-Anmeldung über den Supabase-Standardversand"
_SMTP_GUIDE = "docs/GUIDELINES.md § Mail-Anmeldung ohne eigenen SMTP"
_OTP_EMAIL = re.compile(r"\bsignInWithOtp\s*\(\s*\{[^}]*\bemail\b", re.DOTALL)
_CODE_EXT = (".js", ".mjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte")


def _smtp_configured(toml: str) -> bool | None:
    """Steht in [auth.email.smtp] ein eigener Versand? `enabled = false`
    zählt nicht; ältere CLI-Fassungen kennen kein `enabled`, dort reicht
    ein gesetzter Host."""
    try:
        values = tomllib.loads(toml).get("auth", {}).get("email", {}).get("smtp", {})
    except (tomllib.TOMLDecodeError, AttributeError):
        return None
    if not isinstance(values, dict):
        return None
    enabled = values.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        return None
    if enabled is False:
        return False
    host = values.get("host", "")
    if not isinstance(host, str):
        return None
    return bool(host.strip())


@register(
    _SMTP_ID, _SMTP_TITLE, platform="web", severity=Severity.WARNING,
    guideline=_SMTP_GUIDE,
    references=("https://supabase.com/docs/guides/auth/auth-smtp",),
    self_tests=[
        SelfTestCase("Mail-Login mit eigenem SMTP", {
            "src/auth.ts": "await sb.auth.signInWithOtp({ email, options: {} });",
            "supabase/config.toml": "[auth.email.smtp]\nenabled = true\nhost = \"smtp.resend.com\"\n",
        }, Status.PASS),
        SelfTestCase("Ältere CLI: Host ohne enabled", {
            "src/auth.ts": "await sb.auth.signInWithOtp({ email });",
            "supabase/config.toml": "[auth.email.smtp]\nhost = \"smtp.resend.com\"\nport = 587\n",
        }, Status.PASS),
        SelfTestCase("SMTP mit TOML-Kommentaren und Tabellenkommentar", {
            "src/auth.ts": "await sb.auth.signInWithOtp({ email });",
            "supabase/config.toml": "[auth.email.smtp] # Versand\nenabled = true # aktiv\nhost = \"smtp.example.test\" # Host\n",
        }, Status.PASS),
        SelfTestCase("Aktiv ohne SMTP-Host", {
            "src/auth.ts": "await sb.auth.signInWithOtp({ email });",
            "supabase/config.toml": "[auth.email.smtp]\nenabled = true\n",
        }, Status.FAIL),
        SelfTestCase("Aktiv mit leerem SMTP-Host", {
            "src/auth.ts": "await sb.auth.signInWithOtp({ email });",
            "supabase/config.toml": "[auth.email.smtp]\nenabled = true\nhost = \"  \"\n",
        }, Status.FAIL),
        SelfTestCase("SMTP aus mit Inline-Kommentar", {
            "src/auth.ts": "await sb.auth.signInWithOtp({ email });",
            "supabase/config.toml": "[auth.email.smtp]\nenabled = false # deaktiviert\nhost = \"smtp.example.test\"\n",
        }, Status.FAIL),
        SelfTestCase("Ungültiges TOML ist kein SMTP-Nachweis", {
            "src/auth.ts": "await sb.auth.signInWithOtp({ email });",
            "supabase/config.toml": "[auth.email.smtp]\nenabled = true\nhost = \"smtp.example.test\n",
        }, Status.UNMEASURED),
        SelfTestCase("SMTP-Flag mit falschem Typ", {
            "src/auth.ts": "await sb.auth.signInWithOtp({ email });",
            "supabase/config.toml": "[auth.email.smtp]\nenabled = \"false\"\nhost = \"smtp.example.test\"\n",
        }, Status.UNMEASURED),
        SelfTestCase("Mail-Login ohne SMTP-Abschnitt", {
            "src/auth.ts": "await sb.auth.signInWithOtp({\n  email,\n});",
            "supabase/config.toml": "[auth]\nsite_url = \"http://localhost:5173\"\n",
        }, Status.FAIL),
        SelfTestCase("SMTP ausdrücklich aus", {
            "src/auth.ts": "await sb.auth.signInWithOtp({ email });",
            "supabase/config.toml": "[auth.email.smtp]\nenabled = false\nhost = \"smtp.resend.com\"\n",
        }, Status.FAIL),
        SelfTestCase("Nur Telefon-OTP", {
            "src/auth.ts": "await sb.auth.signInWithOtp({ phone });",
            "supabase/config.toml": "[auth]\n",
        }, Status.UNMEASURED),
        SelfTestCase("Mail-Login nur im Kommentar", {
            "src/auth.ts": "// await sb.auth.signInWithOtp({ email });\nexport {};",
            "supabase/config.toml": "[auth]\n",
        }, Status.UNMEASURED),
        SelfTestCase("Kein Supabase-Projekt im Repo", {
            "src/auth.ts": "await sb.auth.signInWithOtp({ email });",
        }, Status.UNMEASURED),
    ],
)
def check_supabase_email_login_without_smtp(ctx: Context) -> CheckResult:
    """Ohne eigenen SMTP verschickt Supabase Anmeldemails selbst: laut Doku
    2 Mails pro Stunde und nur an Adressen aus dem eigenen Team, „not meant
    for production use". Ein Mail-Login-Formular für Fremde ist dann ein
    Versprechen ohne Zustellung.

    Gemessen wird nur `supabase/config.toml` im Repo. Ein im Dashboard
    gesetzter SMTP ist offline unsichtbar; deshalb WARNING, nie FAIL-hart,
    und die Meldung sagt es. TOML-Kommentare werden geparst; aktiviert ohne
    gesetzten Host ist kein SMTP-Nachweis. Ungültiges TOML bleibt ungemessen.
    Hostpräsenz belegt weder DNS, Credentials, Limits noch Zustellung.
    """
    tomls = [sf for sf in ctx.all_files() if sf.rel.endswith("supabase/config.toml")]
    if not tomls:
        return unmeasured(_SMTP_ID, _SMTP_TITLE, "Keine supabase/config.toml im Repo.", "web")

    calls = []
    for sf in ctx.all_files():
        if not sf.rel.endswith(_CODE_EXT) or "/node_modules/" in f"/{sf.rel}":
            continue
        body = strip_comments(sf.text, sf.ext)
        calls += [(sf, m) for m in _OTP_EMAIL.finditer(body)]
    if not calls:
        return unmeasured(_SMTP_ID, _SMTP_TITLE, "Kein Mail-Login (signInWithOtp mit email) gefunden.", "web")

    configured = [_smtp_configured(sf.text) for sf in tomls]
    if any(state is None for state in configured):
        return unmeasured(_SMTP_ID, _SMTP_TITLE, "SMTP-Konfiguration ist kein gültiges statisches TOML.", "web")
    if any(configured):
        return result_for(_SMTP_ID, _SMTP_TITLE, [], len(calls), "Mail-Login-Aufrufe", "web")

    sf, match = calls[0]
    finding = Finding(
        check_id=_SMTP_ID, severity=Severity.WARNING,
        message=("Mail-Login ohne lokalen SMTP-Host in supabase/config.toml. "
                 "Remote-SMTP-Konfiguration ist offline nicht gemessen."),
        file=sf.rel, line=sf.line_of(match.start()),
        evidence=f"{len(calls)} Aufruf(e) von signInWithOtp mit email; kein aktiver [auth.email.smtp]. "
                 "Ein im Dashboard gesetzter SMTP ist hier nicht gemessen.",
        fix=("Remote-SMTP lesend prüfen. Falls dort kein eigener Versand steht, SMTP einrichten. "
             "Bei lokaler Nutzung auch [auth.email.smtp] konfigurieren; Credentials nicht committen."),
        guideline=_SMTP_GUIDE,
    )
    return result_for(_SMTP_ID, _SMTP_TITLE, [finding], len(calls), "Mail-Login-Aufrufe", "web")


_MOCK_ID = "web.rest_mock_ignores_select"
_MOCK_TITLE = "REST-Attrappe im Prüfstand liefert mehr Spalten als angefragt"
_MOCK_GUIDE = "docs/GUIDELINES.md § REST-Attrappe ohne select-Projektion"
_REST_PATH = re.compile(r"/rest/v1/")
_FULFILL = re.compile(r"\.fulfill\s*\(")
_SELECT_PARAM = re.compile(r"['\"`]select['\"`]")


@register(
    _MOCK_ID, _MOCK_TITLE, platform="web", severity=Severity.WARNING,
    guideline=_MOCK_GUIDE,
    references=("https://postgrest.org/en/stable/references/api/tables_views.html#vertical-filtering",
                "https://playwright.dev/docs/api/class-route#route-fulfill"),
    self_tests=[
        SelfTestCase("Attrappe beantwortet REST mit vollen Zeilen", {
            "setup-pruef.mjs": (
                "await page.route('**/*', async (route) => {\n"
                "  const pfad = new URL(route.request().url()).pathname;\n"
                "  if (pfad.startsWith('/rest/v1/')) return route.fulfill({ body: JSON.stringify(zeilen(pfad)) });\n"
                "});\n"),
        }, Status.FAIL),
        SelfTestCase("Attrappe projiziert auf select=", {
            "setup-pruef.mjs": (
                "await page.route('**/*', async (route) => {\n"
                "  const url = new URL(route.request().url());\n"
                "  if (url.pathname.startsWith('/rest/v1/')) {\n"
                "    const daten = projiziere(zeilen(url.pathname), url.searchParams.get('select'));\n"
                "    return route.fulfill({ body: JSON.stringify(daten) });\n"
                "  }\n"
                "});\n"),
        }, Status.PASS),
        SelfTestCase("Nur im Kommentar erwähnte Attrappe", {
            "setup-pruef.mjs": "// route.fulfill fuer /rest/v1/ waere hier moeglich\nexport default 1;\n",
        }, Status.UNMEASURED),
    ],
)
def check_rest_mock_ignores_select(ctx: Context) -> CheckResult:
    """Ein Prüfstand, der PostgREST-Aufrufe abfängt und immer volle Zeilen
    zurückgibt, ist großzügiger als der echte Server: eine Seite, die Spalten
    liest, die ihre Abfrage gar nicht selektiert, sieht dort gesund aus und
    bekommt in Produktion `undefined`. Gemessen wird jede Datei, die
    `/rest/v1/` mit einem Playwright-`fulfill` beantwortet; ein Befund, wenn
    sie den `select`-Parameter nirgends ausliest. Ob die Projektion richtig
    rechnet (Aliasse, Einbettungen), misst der Check nicht.

    Python statt TOML-Regel: der Befund ist die ABWESENHEIT von `select` in
    einer Datei, die zwei andere Merkmale trägt — das braucht eine
    Negativbedingung über die ganze Datei, die die linearzeitige Regex der
    Engine (ohne Lookaround) nicht ausdrücken kann.
    """
    findings: list[Finding] = []
    measured = 0
    for sf in ctx.files_including_rules(*_CODE_EXT):
        body = strip_comments(sf.text, sf.ext)
        rest = _REST_PATH.search(body)
        if not rest or not _FULFILL.search(body):
            continue
        measured += 1
        if _SELECT_PARAM.search(body):
            continue
        findings.append(Finding(
            check_id=_MOCK_ID, severity=Severity.WARNING,
            message="REST-Attrappe beantwortet /rest/v1/ ohne den select-Parameter auszuwerten.",
            file=sf.rel, line=sf.line_of(rest.start()),
            evidence=sf.text.splitlines()[sf.line_of(rest.start()) - 1].strip()[:160],
            fix="Antwortzeilen auf die Spalten aus `select=` beschränken, wie PostgREST es tut.",
            guideline=_MOCK_GUIDE,
        ))
    if measured == 0:
        return unmeasured(_MOCK_ID, _MOCK_TITLE, "Keine REST-Attrappe (fulfill auf /rest/v1/) gefunden.", "web")
    return result_for(_MOCK_ID, _MOCK_TITLE, findings, measured, "REST-Attrappen", "web")
