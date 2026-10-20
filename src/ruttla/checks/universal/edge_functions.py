"""Universal: Supabase Edge Functions ohne Gateway-Prüfung.

Python statt Regel-Datei: die Prüfung verbindet zwei Dateien (config.toml und den
Quelltext der Funktion) — das kann ein Muster über eine Datei nicht.
"""

from __future__ import annotations

import re

from ruttla.core import (
    CheckResult,
    Context,
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

CHECK_ID = "supabase.verify_jwt_off_without_signature_check"
TITLE = "Edge Function ohne verify_jwt prüft keine Signatur"

ABSCHNITT = re.compile(r"^\[functions\.([A-Za-z0-9_-]+)\]\s*$")
AUS = re.compile(r"^\s*verify_jwt\s*=\s*false\b")
# Eigene Echtheitsprüfung in der Funktion: Apple-JWS, JWT/OIDC über JWKS, Webhook-HMAC.
PRUEFUNG = re.compile(
    r"SignedDataVerifier|verifyAndDecode|jwtVerify\s*\(|createRemoteJWKSet\s*\(|"
    r"crypto\.subtle\.verify\s*\(|timingSafeEqual\s*\(|constructEvent(?:Async)?\s*\(|"
    r"verifySignature\s*\(|verifyWebhook\w*\s*\("
)

_GUT_CONFIG = "[functions.apple-webhook]\nverify_jwt = false\n"
_GUT_FN = ("import { SignedDataVerifier } from 'npm:@apple/app-store-server-library';\n"
           "const v = new SignedDataVerifier(roots, true, env, bundleId);\n"
           "const n = await v.verifyAndDecodeNotification(body.signedPayload);\n")


@register(
    CHECK_ID,
    TITLE,
    severity=Severity.ERROR,
    guideline="~/.claude/guides/supabase-deploy.md § Edge Function als Webhook fremder Dienste",
    self_tests=[
        SelfTestCase(
            name="verify_jwt aus, Funktion prüft den Absender nicht",
            files={"supabase/config.toml": "[functions.play-rtdn]\nverify_jwt = false\n",
                   "supabase/functions/play-rtdn/index.ts":
                       "Deno.serve(async (req) => { const msg = await req.json(); return new Response('ok'); });\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="verify_jwt aus, Funktion prüft die Apple-Signatur",
            files={"supabase/config.toml": _GUT_CONFIG,
                   "supabase/functions/apple-webhook/index.ts": _GUT_FN},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Prüfaufruf nur im Kommentar zählt nicht",
            files={"supabase/config.toml": _GUT_CONFIG,
                   "supabase/functions/apple-webhook/index.ts":
                       "// TODO: SignedDataVerifier einbauen\nDeno.serve(() => new Response('ok'));\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Funktion ohne Quelltext ist ein Befund, kein Grün",
            files={"supabase/config.toml": "[functions.fehlt]\nverify_jwt = false\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="verify_jwt an braucht keine eigene Prüfung",
            files={"supabase/config.toml": "[functions.intern]\nverify_jwt = true\n",
                   "supabase/functions/intern/index.ts": "Deno.serve(() => new Response('ok'));\n"},
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_verify_jwt_off(ctx: Context) -> CheckResult:
    """Belegt am 20.10.2026 (Vylea): `handle-play-rtdn` sollte wie der Apple-Webhook
    ohne verify_jwt laufen, prüfte aber das OIDC-Token des Pub/Sub-Push nicht — jeder
    hätte die Funktion anonym auslösen können. Gezählt wird jede Funktion mit
    verify_jwt = false (der Kandidat), nicht nur die durchgefallenen."""
    alle = {sf.rel: sf for sf in ctx.files(".ts", ".js", ".mjs", ".toml")}
    findings: list[Finding] = []
    units = 0
    for sf in alle.values():
        if not sf.rel.endswith("config.toml"):
            continue
        basis = sf.rel[: -len("config.toml")]
        name = None
        for idx, zeile in enumerate(sf.lines, start=1):
            kopf = ABSCHNITT.match(zeile)
            if kopf:
                name = kopf.group(1)
                continue
            if zeile.lstrip().startswith("["):
                name = None
            if not (name and AUS.match(zeile)):
                continue
            units += 1
            quellen = [alle[p] for p in (f"{basis}functions/{name}/index.{e}" for e in ("ts", "js", "mjs")) if p in alle]
            geprueft = any(PRUEFUNG.search(strip_comments(q.text, q.ext)) for q in quellen)
            if geprueft:
                continue
            grund = ("prüft weder Signatur noch Token des Absenders" if quellen
                     else "Quelltext der Funktion nicht gefunden")
            findings.append(Finding(
                check_id=CHECK_ID,
                severity=Severity.ERROR,
                message=f"Funktion '{name}' läuft ohne verify_jwt und {grund} — anonym auslösbar.",
                file=sf.rel, line=idx, evidence=snippet(zeile.strip()),
                fix="verify_jwt = true lassen, bis die Funktion die Echtheit selbst prüft "
                    "(signierter JWS, OIDC-Token über JWKS oder Webhook-HMAC).",
                guideline="~/.claude/guides/supabase-deploy.md § Edge Function als Webhook fremder Dienste",
            ))
    if units == 0:
        return unmeasured(CHECK_ID, TITLE, "Keine Edge Function mit verify_jwt = false gefunden.")
    return result_for(CHECK_ID, TITLE, findings, units)
