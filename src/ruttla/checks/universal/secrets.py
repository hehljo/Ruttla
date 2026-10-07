"""Universal: credentials never live in source.

Split from the original checks/universal.py; background and
shared helpers in _common.py.
"""

from __future__ import annotations

import base64
import json
import os
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
)

from ._common import _is_git_ignored, SOURCE_EXTS


# ===========================================================================
# Secrets
# ===========================================================================

def _demo_jwt(role: str, iss: str) -> str:
    """Prüf-Token für die Selbsttests, erst zur Laufzeit gebaut — als Literal
    im Quelltext meldet dieser Check seine eigenen Testdaten."""
    def enc(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return (enc({"alg": "HS256", "typ": "JWT"}) + "."
            + enc({"iss": iss, "ref": "abcdefghijklmnop", "role": role, "iat": 1700000000})
            + ".c2lnbmF0dXJlLWRlci1rZXk")


def _is_public_supabase_key(token: str) -> bool:
    """Öffentlicher Supabase-anon-Key: Rolle anon UND Aussteller Supabase.
    Jeder Fehler beim Lesen heißt: kein anon-Key — also Befund (fail closed)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return (isinstance(data, dict) and data.get("role") == "anon"
                and str(data.get("iss", "")).startswith("supabase"))
    except Exception:  # noqa: BLE001 — auch RecursionError: im Zweifel melden
        return False


@register(
    "secrets.hardcoded_credential",
    "Geheimnis oder Schlüssel steht im Quelltext",
    severity=Severity.ERROR,
    guideline="CLAUDE.md § Supabase / WEB § 5b",
    safe_by_default=True,
    self_tests=[
        SelfTestCase(
            name="GitHub-Token im Code",
            files={"src/a.ts": 'const t = "ghp_' + "a" * 36 + '";\n'},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Supabase-anon-Key ist öffentlich",
            files={"supabase.public.env": "SUPABASE_ANON_KEY=" + _demo_jwt('anon', 'supabase') + "\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="service_role-JWT bleibt ein Befund",
            files={"supabase.public.env": "SUPABASE_KEY=" + _demo_jwt('service_role', 'supabase') + "\n"},
            expect=Status.FAIL,
            expect_finding_contains="JWT",
        ),
        SelfTestCase(
            name="anon-Key verdeckt keinen service_role-Key in derselben Zeile",
            files={"keys.env": "KEYS=" + _demo_jwt('anon', 'supabase') + "," + _demo_jwt('service_role', 'supabase') + "\n"},
            expect=Status.FAIL,
            expect_finding_contains="JWT",
        ),
        SelfTestCase(
            name="Rolle anon eines fremden Ausstellers bleibt ein Befund",
            files={"keys.env": "TOKEN_X=" + _demo_jwt('anon', 'auth.example-dienst.de') + "\n"},
            expect=Status.FAIL,
            expect_finding_contains="JWT",
        ),
        SelfTestCase(
            name="Key aus der Umgebung",
            files={"src/a.ts": 'const t = process.env.GITHUB_TOKEN;\n'},
            expect=Status.PASS,
        ),
    ],
)
def check_secrets(ctx: Context) -> CheckResult:
    """Erkennt Geheimnisse an ihrer FORM (Präfix, Entropie, Struktur), nicht am
    Variablennamen — ein Name ist eine Existenzprüfung, kein Wert."""
    title = "Geheimnis oder Schlüssel steht im Quelltext"
    patterns: list[tuple[re.Pattern, str, Severity]] = [
        (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub Personal Access Token", Severity.ERROR),
        (re.compile(r"github_pat_[A-Za-z0-9_]{50,}"), "GitHub Fine-grained Token", Severity.ERROR),
        (re.compile(r"sk-(proj-)?[A-Za-z0-9_\-]{32,}"), "OpenAI API-Key", Severity.ERROR),
        (re.compile(r"sk-ant-[A-Za-z0-9_\-]{30,}"), "Anthropic API-Key", Severity.ERROR),
        (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "Google API-Key", Severity.ERROR),
        (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID", Severity.ERROR),
        (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "Slack Token", Severity.ERROR),
        (re.compile(r"-----BEGIN (RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"),
         "Privater Schlüssel", Severity.ERROR),
        (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}"),
         "JWT mit Nutzdaten", Severity.WARNING),
        # Der blosse Rollenname ist ein SQL-Bezeichner und kommt in jedem
        # Grant/Policy vor — ein Signal, das im legitimen Normalfall anschlägt,
        # ist eine Warnung, nie allein ein Befund. Gemeldet wird nur, wo der
        # Name einen WERT zugewiesen bekommt. Belegt an einer realen Web-App:
        # 1042 von 1045 Treffern kamen aus generierten Katalog-Dumps.
        (re.compile(r"(?i)service_role[\w]*\s*[:=]\s*[\"'][A-Za-z0-9._\-]{20,}[\"']"),
         "Supabase service_role-Schlüssel", Severity.ERROR),
        (re.compile(r"(?i)(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*"
                    r"[\"'][A-Za-z0-9+/=_\-]{16,}[\"']"),
         "Zugangsdaten im Klartext", Severity.ERROR),
    ]
    # Platzhalter und Beispiele sind keine Geheimnisse.
    placeholder = re.compile(
        r"(?i)(your[_-]?|example|placeholder|dummy|sample|xxx+|\.\.\.|<[^>]+>"
        r"|changeme|redacted|\*{4,}|test[_-]?key|fake|process\.env|import\.meta\.env"
        r"|os\.environ|getenv|System\.getenv|ProcessInfo)"
    )
    env_example = re.compile(r"(?i)(\.env\.example|\.env\.sample|\.env\.template)")

    findings: list[Finding] = []
    units = 0
    scan_exts = (*SOURCE_EXTS, ".json", ".yaml", ".yml", ".toml", ".xml",
                 ".plist", ".env", ".sh", ".properties", ".cfg", ".ini")
    for sf in ctx.all_files():
        base = os.path.basename(sf.rel)
        if sf.ext not in scan_exts and not base.startswith(".env"):
            continue
        if env_example.search(sf.rel):
            continue
        # .env liegt per Konvention in .gitignore und IST der richtige Ort für
        # ein Geheimnis. Gemeldet wird nur, wenn sie nicht ignoriert ist —
        # dann ist sie im Verlauf und das Geheimnis kompromittiert.
        if base.startswith(".env") and _is_git_ignored(ctx, sf.rel):
            continue
        # Testskripte und lokale Werkzeuge sind kein ausgelieferter Code. Der
        # Befund bleibt, wird aber zur Warnung herabgestuft.
        is_aux = bool(re.search(
            r"(?i)(^|/)(test|tests|scripts?|tools?|bench|examples?|fixtures?)(/|$)"
            r"|\.(test|spec)\.", sf.rel))
        units += 1
        for idx, raw in enumerate(sf.lines, start=1):
            if placeholder.search(raw):
                continue
            for pat, label, sev in patterns:
                m = pat.search(raw)
                if not m:
                    continue
                # Ein Supabase-anon-Key ist öffentlich (Schutz über RLS) und
                # gehört in jeden Client. Belegt am 08.10.2026 (Merkma): die
                # eingecheckten öffentlichen Werte für Xcode-Builds wurden
                # blockierend gemeldet. Entschieden wird an der Rolle im
                # Token, nicht am Dateinamen — ein service_role-JWT bleibt rot.
                if label == "JWT mit Nutzdaten":
                    # Jeder JWT der Zeile zählt, nicht nur der erste: ein
                    # anon-Key davor darf keinen service_role-Key verdecken.
                    offen = [t for t in pat.finditer(raw)
                             if not _is_public_supabase_key(t.group(0))]
                    if not offen:
                        continue
                    m = offen[0]
                # service_role nur melden, wenn es ein Wert ist, kein Kommentar
                # über die Regel oder eine Server-seitige Umgebungsvariable.
                if label.startswith("Supabase") and re.search(
                    r"(?i)(process\.env|import\.meta\.env|os\.environ|Deno\.env|//|#)", raw
                ):
                    continue
                findings.append(Finding(
                    check_id="secrets.hardcoded_credential",
                    severity=Severity.WARNING if is_aux else sev,
                    message=f"{label} im Quelltext gefunden.",
                    file=sf.rel, line=idx,
                    evidence=snippet(re.sub(re.escape(m.group(0)), "«…»", raw)),
                    fix="Aus einer Umgebungsvariablen beziehen und als Geheimnis "
                        "markieren, nicht nur setzen. Danach den Schlüssel rotieren "
                        "— was im Verlauf steht, ist kompromittiert.",
                    guideline="CLAUDE.md § Supabase / WEB § 5b",
                ))
                break
    return result_for("secrets.hardcoded_credential", title, findings, units)
