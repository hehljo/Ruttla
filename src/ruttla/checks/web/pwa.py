"""Web-Check: PWA-Workbox ohne API-Ausnahme.

Aus `rules.py` ausgelagert (Modulgröße); ID, Meldung und Proben unverändert.
"""

from __future__ import annotations

import os
import re

from ruttla.checks.web.rules import PLATFORM, WEB_CODE
from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, unmeasured, result_for, snippet, strip_comments,
)


def _strip_config_comments(text: str) -> str:
    """Entfernt Block- und reine Zeilenkommentare, ohne Regex-Literale wie /^\\/api\\// zu zerschneiden."""
    ohne_block = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"(?m)^[ \t]*//.*$", "", ohne_block)


@register(
    "web.pwa_workbox_api_bypass",
    "PWA-Workbox ohne API-Ausnahme fängt /api/-Aufrufe ab",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § PWA",
    self_tests=[
        SelfTestCase(
            name="gesund: Denylist und NetworkOnly gesetzt",
            files={
                "vite.config.ts": (
                    'VitePWA({ workbox: { navigateFallbackDenylist: [/^\\/api\\//], '
                    'runtimeCaching: [{ urlPattern: /^\\/api\\//, handler: "NetworkOnly" }] } })'
                ),
                "src/api.ts": 'export const load = () => fetch("/api/items");\n',
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="gesund: navigateFallback null plus NetworkOnly",
            files={
                "vite.config.ts": (
                    'VitePWA({ workbox: { navigateFallback: null, '
                    'runtimeCaching: [{ urlPattern: /^\\/api\\//, handler: "NetworkOnly" }] } })'
                ),
                "src/api.ts": "export const load = () => fetch('/api/items');\n",
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="defekt: navigateFallbackDenylist fehlt",
            files={
                "vite.config.ts": (
                    'VitePWA({ workbox: { runtimeCaching: [{ urlPattern: /^\\/api\\//, handler: "NetworkOnly" }] } })'
                ),
                "src/api.ts": 'export const load = () => fetch("/api/items");\n',
            },
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="defekt: NetworkOnly für /api/ fehlt",
            files={
                "vite.config.ts": (
                    'VitePWA({ workbox: { navigateFallbackDenylist: [/^\\/api\\//] } })'
                ),
                "src/api.ts": 'export const load = () => fetch("/api/items");\n',
            },
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="defekt: auskommentierte Ausnahme zählt nicht",
            files={
                "vite.config.ts": (
                    'VitePWA({ workbox: {\n'
                    '  // navigateFallbackDenylist: [/^\\/api\\//],\n'
                    '  // runtimeCaching: [{ urlPattern: /^\\/api\\//, handler: "NetworkOnly" }],\n'
                    '} })\n'
                ),
                "src/api.ts": 'export const load = () => fetch("/api/items");\n',
            },
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="ungemessen: keine /api/-Aufrufe im Frontend",
            files={
                "vite.config.ts": "VitePWA({ workbox: {} })\n",
                "src/main.ts": "console.log('offline-only');\n",
            },
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_pwa_workbox_api_bypass(ctx: Context) -> CheckResult:
    """Eine VitePWA-App mit generateSW fängt Navigations- und GET-Routen über Workbox ab.
    Ohne explizite Denylist und NetworkOnly-Regel für /api/ landet statt JSON/Blob
    schnell die gecachte index.html beim Client."""
    title = "PWA-Workbox ohne API-Ausnahme fängt /api/-Aufrufe ab"
    configs = [
        sf for sf in ctx.files(".ts", ".js", ".mjs", ".mts")
        if os.path.basename(sf.rel).startswith("vite.config.")
    ]
    pwa_configs = []
    for sf in configs:
        body = _strip_config_comments(sf.text)
        if "VitePWA" in body and "workbox" in body:
            pwa_configs.append((sf, body))
    if not pwa_configs:
        return unmeasured("web.pwa_workbox_api_bypass", title,
                          "Keine VitePWA-Workbox-Konfiguration gefunden.", PLATFORM)

    has_api_calls = any(
        not os.path.basename(sf.rel).startswith("vite.config.")
        and not sf.rel.startswith("server/")
        and re.search(r"['\"`]/api/", strip_comments(sf.text, sf.ext))
        for sf in ctx.files(*WEB_CODE)
    )
    if not has_api_calls:
        return unmeasured("web.pwa_workbox_api_bypass", title,
                          "Keine /api/-Endpunktaufrufe im Frontend gefunden.", PLATFORM)

    findings: list[Finding] = []
    for sf, body in pwa_configs:
        has_denylist = bool(re.search(
            r"navigateFallbackDenylist\s*:[^\]]*api|navigateFallback\s*:\s*null\b",
            body,
        ))
        has_network_only = bool(re.search(
            r"runtimeCaching\s*:[\s\S]*?(?:\\?/api\\?/|['\"`]/api/)[\s\S]*?NetworkOnly",
            body,
        ))
        if has_denylist and has_network_only:
            continue
        fehlt: list[str] = []
        if not has_denylist:
            fehlt.append("navigateFallbackDenylist (oder navigateFallback: null)")
        if not has_network_only:
            fehlt.append("runtimeCaching mit handler: 'NetworkOnly' für /api/")
        m = re.search(r"\bworkbox\s*:", body)
        line_no = body.count("\n", 0, m.start()) + 1 if m else 1
        raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
        findings.append(Finding(
            check_id="web.pwa_workbox_api_bypass",
            severity=Severity.WARNING,
            message=f"Workbox-Konfiguration lässt /api/-Pfade ungeschützt ({', '.join(fehlt)} fehlt).",
            file=sf.rel,
            line=line_no,
            evidence=snippet(raw),
            fix="In workbox sowohl navigateFallbackDenylist: [/^\\/api\\//] als auch "
                "runtimeCaching: [{ urlPattern: /^\\/api\\//, handler: 'NetworkOnly' }] eintragen.",
            guideline="CODE_QUALITY_GUIDELINES_WEB.md § PWA",
        ))
    return result_for("web.pwa_workbox_api_bypass", title, findings,
                      len(pwa_configs), "VitePWA-Konfigurationen", PLATFORM)
