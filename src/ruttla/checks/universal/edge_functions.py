"""Universal: Supabase Edge Functions ohne Gateway-Prüfung.

Python statt Regel-Datei: die Prüfung verbindet zwei Dateien (config.toml und den
Quelltext der Funktion) — das kann ein Muster über eine Datei nicht.
"""

from __future__ import annotations

import posixpath
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

# Lokale Importe (Adapter → `_shared/...`). Verfolgt werden nur die importierten
# NAMEN bis zu ihrer Deklaration — ein Prüfaufruf in einem fremden Export desselben
# Moduls zählt nicht. Linear statt eines Musters mit Klausel-Quantor: erst jedes
# `from "./…"` suchen, dann rückwärts in einem begrenzten Fenster bis zum letzten
# Trenner (; oder Anführungszeichen) das Schlüsselwort. Ein Muster
# `import\s+…*?from` war über langem Leerraum quadratisch (18 s bei 200 KB).
VON = re.compile(r"\bfrom[ \t\r\n]*([\"'])(\.\.?/[^\"'\n]{1,300})\1")
SCHLUESSEL = re.compile(r"\b(import|export)\b")
FENSTER = 3000


def _anweisungen(modul: str):
    """(Schlüsselwort, nur Typ?, Klausel, Pfad) je lokaler import/export-from-Anweisung."""
    for m in VON.finditer(modul):
        anfang = max(0, m.start() - FENSTER)
        trenner = max(modul.rfind(z, anfang, m.start()) for z in ";\"'`")
        fenster = modul[max(anfang, trenner + 1): m.start()]
        kopf = None
        for k in SCHLUESSEL.finditer(fenster):
            kopf = k
        if kopf is None:
            continue
        rest = fenster[kopf.end():].strip()
        nur_typ = rest.startswith("type ") or rest.startswith("type{")
        if nur_typ:
            rest = rest[4:].strip()
        yield kopf.group(1), nur_typ, rest, m.group(2)
DEKL = re.compile(r"^(?:export[ \t]+)?(?:default[ \t]+)?(?:async[ \t]+)?(?:function\*?|const|let|var|class)[ \t]+([A-Za-z_$][\w$]*)", re.M)
OBEN = re.compile(r"^(?:export|function|async|const|let|var|class)\b", re.M)


def _namen(klausel: str) -> list[tuple[str, str]]:
    """Import-/Export-Klausel → (Originalname, lokaler Name); Typ-Spezifizierer fallen weg."""
    paare: list[tuple[str, str]] = []
    rest = klausel
    if "{" in klausel:
        vorne, _, innen = klausel.partition("{")
        innen = innen.partition("}")[0]
        rest = vorne
        for teil in innen.split(","):
            teil = teil.strip()
            if not teil or teil.startswith("type "):
                continue
            orig, _, lokal = teil.partition(" as ")
            paare.append((orig.strip(), (lokal or orig).strip()))
    for teil in rest.split(","):
        teil = teil.strip()
        if teil.startswith("* as "):
            paare.append(("*", teil[5:].strip()))
        elif re.fullmatch(r"[A-Za-z_$][\w$]*", teil):
            paare.append(("default", teil))
    return paare


BEZEICHNER = re.compile(r"(?<![\w$.])[A-Za-z_$][\w$]*")


def _modul(sf) -> dict:
    """Einmal je Datei: Text ohne Kommentare, Anweisungen, Top-Level-Deklarationen."""
    text = strip_comments(sf.text, sf.ext)
    dekl: dict[str, str] = {}
    for m in DEKL.finditer(text):
        ende = OBEN.search(text, m.end())
        stueck = text[m.start(): ende.start() if ende else len(text)]
        dekl.setdefault(m.group(1), stueck)
        if m.group(0).startswith("export default"):
            dekl.setdefault("default", stueck)
    return {"text": text, "anw": list(_anweisungen(text)), "dekl": dekl}


def _ziel(rel: str, spez: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(rel), spez))


def _geprueft(einstieg, alle: dict) -> bool:
    """Erreicht der Einstieg über benutzte Namen einen Prüfaufruf?"""
    module: dict[str, dict] = {}
    gesehen: set[tuple[str, str]] = set()
    offen = [(einstieg.rel, "*")]
    while offen:
        rel, name = offen.pop()
        if (rel, name) in gesehen or rel not in alle:
            continue
        gesehen.add((rel, name))
        if rel not in module:
            module[rel] = _modul(alle[rel])
        mod = module[rel]
        stueck = mod["text"] if name == "*" else mod["dekl"].get(name)
        if stueck is None:
            for wort, nur_typ, klausel, spez in mod["anw"]:
                if wort == "export" and not nur_typ and klausel.startswith("{"):
                    offen.extend((_ziel(rel, spez), orig) for orig, lokal in _namen(klausel) if lokal == name)
            continue
        if PRUEFUNG.search(stueck):
            return True
        benutzt = set(BEZEICHNER.findall(stueck))
        for wort, nur_typ, klausel, spez in mod["anw"]:
            if wort == "import" and not nur_typ:
                offen.extend((_ziel(rel, spez), orig) for orig, lokal in _namen(klausel) if lokal in benutzt)
        offen.extend((rel, n) for n in benutzt & mod["dekl"].keys() if n != name)
    return False


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
            name="Prüfung im importierten Shared-Handler zählt (belegt Warteheld seven-dlr)",
            files={"supabase/config.toml": "[functions.seven-dlr]\nverify_jwt = false\n",
                   "supabase/functions/seven-dlr/index.ts":
                       "import { handle } from \"../_shared/handler.ts\";\nDeno.serve((r) => handle(r));\n",
                   "supabase/functions/_shared/handler.ts":
                       "import {\n  verifySig,\n} from \"./sig.ts\";\n"
                       "export const handle = (r) => verifySig(r) ? ok() : deny();\n",
                   "supabase/functions/_shared/sig.ts":
                       "import { timingSafeEqual } from \"node:crypto\";\n"
                       "export const verifySig = (r) => timingSafeEqual(a(r), b(r));\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Importierter Shared-Handler ohne Prüfung bleibt ein Befund",
            files={"supabase/config.toml": "[functions.seven-dlr]\nverify_jwt = false\n",
                   "supabase/functions/seven-dlr/index.ts":
                       "import { handle } from \"../_shared/handler.ts\";\nDeno.serve((r) => handle(r));\n",
                   "supabase/functions/_shared/handler.ts":
                       "export const handle = async (r) => apply(await r.json());\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Reiner Typ-Import aus dem Prüfmodul zählt nicht",
            files={"supabase/config.toml": "[functions.seven-dlr]\nverify_jwt = false\n",
                   "supabase/functions/seven-dlr/index.ts":
                       "import type { Sig } from \"../_shared/sig.ts\";\nDeno.serve(() => new Response('ok'));\n",
                   "supabase/functions/_shared/sig.ts":
                       "export type Sig = string;\nexport const v = (a, b) => timingSafeEqual(a, b);\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Prüfung nur in einem fremden Export des importierten Moduls zählt nicht",
            files={"supabase/config.toml": "[functions.seven-dlr]\nverify_jwt = false\n",
                   "supabase/functions/seven-dlr/index.ts":
                       "import { handle } from \"../_shared/util.ts\";\nDeno.serve((r) => handle(r));\n",
                   "supabase/functions/_shared/util.ts":
                       "export const handle = async (r) => apply(await r.json());\n"
                       "export const verifyOther = (a, b) => timingSafeEqual(a, b);\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Ohne Semikolon, Prüfung im lokalen Helfer des Shared-Moduls",
            files={"supabase/config.toml": "[functions.hook]\nverify_jwt = false\n",
                   "supabase/functions/hook/index.ts":
                       "import type { Cfg } from \"npm:x\"\nimport { handle } from \"../_shared/h.ts\"\n"
                       "Deno.serve((r) => handle(r))\n",
                   "supabase/functions/_shared/h.ts":
                       "function check(r) {\n  return timingSafeEqual(a(r), b(r))\n}\n"
                       "export function handle(r) {\n  return check(r) ? ok() : deny()\n}\n"},
            expect=Status.PASS,
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
    verify_jwt = false (der Kandidat), nicht nur die durchgefallenen.
    Belegt am 23.10.2026 (Warteheld): ein dünner Adapter importiert den geteilten
    Handler aus `_shared/`; die Prüfung liegt dort. Lokale Importe werden deshalb
    über die benutzten Namen bis zu ihrer Deklaration verfolgt — Typ-Importe nicht,
    und ein Prüfaufruf in einem anderen Export desselben Moduls zählt nicht."""
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
            geprueft = any(_geprueft(q, alle) for q in quellen)
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
