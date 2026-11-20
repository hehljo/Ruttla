"""Web-Checks: Layout, CSS-Tokens, Viewport-Einheiten und Trefferflächen.

Aus `rules.py` ausgelagert (Modulgröße); IDs, Meldungen und Proben unverändert.
"""

from __future__ import annotations

import re

from ruttla.checks.web.rules import PLATFORM, WEB_CODE, WEB_STYLE
from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, unmeasured, result_for, snippet, strip_comments,
)


@register(
    "web.grid_fr_without_minmax",
    "Grid-Spalte mit 1fr statt minmax(0, 1fr)",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 0",
    self_tests=[
        SelfTestCase(
            name="nacktes 1fr",
            files={"src/a.css": ".grid { display: grid; grid-template-columns: 1fr 1fr 1fr; }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="minmax(0,1fr)",
            files={"src/a.css": ".grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_grid_minmax(ctx: Context) -> CheckResult:
    """`1fr` heißt nicht "gleich breit", sondern "mindestens so breit wie der
    Inhalt". Belegt: drei Spalten wurden 285,5 / 251,2 / 251,2 px, weil in der
    ersten ein Knopf mit längerer Beschriftung saß."""
    title = "Grid-Spalte mit 1fr statt minmax(0, 1fr)"
    files = ctx.files(*WEB_STYLE, *WEB_CODE, ".html")
    if not files:
        return unmeasured("web.grid_fr_without_minmax", title,
                          "Keine Style- oder Web-Dateien gefunden.", PLATFORM)
    decl = re.compile(
        r"grid-template-(?:columns|rows)\s*:\s*([^;}\n\"']+)"
    )
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        for m in decl.finditer(body):
            measured += 1
            value = m.group(1)
            if "minmax(" in value:
                continue
            if not re.search(r"\b\d*\.?\d*fr\b", value):
                continue
            # auto-fit/auto-fill mit minmax ist die richtige Bauform und oben
            # schon abgefangen; hier bleibt nacktes fr übrig.
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="web.grid_fr_without_minmax", severity=Severity.WARNING,
                message=f"'{value.strip()}' — fr ohne minmax(0, …): die Spalte "
                        "wächst mit ihrem längsten Inhalt.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="minmax(0, 1fr) verwenden, damit die Spaltenbreite vom Inhalt "
                    "gelöst ist.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § 0",
            ))
    if measured == 0:
        return unmeasured("web.grid_fr_without_minmax", title,
                          "Keine grid-template-Deklaration gefunden.", PLATFORM)
    return result_for("web.grid_fr_without_minmax", title, findings, measured,
                      "Grid-Deklarationen", PLATFORM)


@register(
    "web.viewport_height_unit",
    "100vh statt 100dvh — auf Mobilgeräten bricht das Layout",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 4",
    self_tests=[
        SelfTestCase(
            name="100vh",
            files={"src/a.css": ".page { height: 100vh; }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="100dvh",
            files={"src/a.css": ".page { height: 100dvh; }\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_vh(ctx: Context) -> CheckResult:
    title = "100vh statt 100dvh — auf Mobilgeräten bricht das Layout"
    files = ctx.files(*WEB_STYLE, *WEB_CODE, ".html")
    if not files:
        return unmeasured("web.viewport_height_unit", title,
                          "Keine Style- oder Web-Dateien gefunden.", PLATFORM)
    pat = re.compile(r"(?<![\w.-])(\d{1,3})vh\b")
    findings: list[Finding] = []
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        for m in pat.finditer(body):
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            if "dvh" in raw or "svh" in raw or "lvh" in raw:
                continue
            findings.append(Finding(
                check_id="web.viewport_height_unit", severity=Severity.WARNING,
                message=f"{m.group(1)}vh berücksichtigt die Browserleiste auf "
                        "Mobilgeräten nicht.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="dvh verwenden (dynamic viewport height) oder svh, wo die "
                    "kleinste Höhe gemeint ist.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § 4",
            ))
    return result_for("web.viewport_height_unit", title, findings, len(files),
                      "Dateien", PLATFORM)


@register(
    "web.undefined_css_token",
    "CSS-Variable wird benutzt, aber nirgends definiert",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5l",
    self_tests=[
        SelfTestCase(
            name="Token fehlt",
            files={"src/a.css": ":root { --bg: #fff; }\n.card { color: var(--text-primary); }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Token definiert",
            files={"src/a.css": ":root { --bg: #fff; --text-primary: #111; }\n.card { color: var(--text-primary); }\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_css_tokens(ctx: Context) -> CheckResult:
    """Ein CSS-Token, das es nicht gibt, meldet sich nicht — die Regel fällt
    still aus, und die Farbe ist die geerbte."""
    title = "CSS-Variable wird benutzt, aber nirgends definiert"
    files = ctx.files(*WEB_STYLE, ".html", ".tsx", ".jsx", ".vue", ".svelte")
    if not files:
        return unmeasured("web.undefined_css_token", title,
                          "Keine Style- oder Markup-Dateien gefunden.", PLATFORM)
    defined: set[str] = set()
    used: list[tuple[str, int, str, str]] = []
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        defined |= set(re.findall(r"(--[\w-]+)\s*:", body))
        for m in re.finditer(r"var\(\s*(--[\w-]+)\s*([,)])", body):
            if m.group(2) == ",":
                continue  # Fallback vorhanden
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            used.append((sf.rel, line_no, m.group(1), snippet(raw)))
    if not used:
        return unmeasured("web.undefined_css_token", title,
                          "Keine var(--…)-Nutzung ohne Fallback gefunden.", PLATFORM)
    findings: list[Finding] = []
    for rel, line, name, ev in used:
        if name in defined:
            continue
        findings.append(Finding(
            check_id="web.undefined_css_token", severity=Severity.WARNING,
            message=f"'{name}' wird benutzt, ist aber nirgends definiert.",
            file=rel, line=line, evidence=ev,
            fix="Token definieren oder einen Fallback angeben: var(--x, #fallback). "
                "Sonst fällt die Regel still aus.",
            guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5l",
        ))
    return result_for("web.undefined_css_token", title, findings, len(used),
                      "Token-Nutzungen", PLATFORM)


@register(
    "web.touch_target_too_small",
    "Trefferfläche unter 44px",
    platform=PLATFORM,
    severity=Severity.INFO,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 4",
    self_tests=[
        SelfTestCase(
            name="zu kleine Flaeche",
            files={"src/a.css": ".btn { height: 28px; width: 28px; }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="ausreichend gross",
            files={"src/a.css": ".btn { height: 48px; width: 48px; }\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="kleines Symbol in grosser echter Klickflaeche",
            files={"src/a.css": "input[type=checkbox] { width: 44px; height: 44px; }\ninput[type=checkbox]::before { width: 22px; height: 22px; }\ninput[type=checkbox]:checked::before { line-height: 20px; }\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Symbol verdeckt keine zu kleine echte Klickflaeche",
            files={"src/a.css": "input[type=checkbox] { width: 22px; height: 22px; }\ninput[type=checkbox]::before { width: 44px; height: 44px; }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="gemischter Selektor behaelt echten Button",
            files={"src/a.css": ".btn::before, button { width: 22px; height: 22px; }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="reiner dekorativer Pseudoselektor nicht gemessen",
            files={"src/a.css": "input::before { width: 22px; height: 22px; }\n"},
            expect=Status.UNMEASURED,
        ),
        SelfTestCase(
            name="Zeilenhoehe ist nicht die Klickflaeche",
            files={"src/a.css": "button { width: 44px; height: 44px; line-height: 20px; }\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_touch_targets(ctx: Context) -> CheckResult:
    """Statische Annäherung: explizit gesetzte Höhen/Breiten unter 44px an
    Interaktions-Selektoren. Die echte Messung gehört in einen Browser-Lauf
    (z. B. Playwright) — das hier fängt die offensichtlichen Fälle früher ab.
    Dekorative ::before/::after-Symbole sind keine eigenen Klickflächen;
    echte Selektoren einer gemischten Liste bleiben messbar."""
    title = "Trefferfläche unter 44px"
    styles = ctx.files(*WEB_STYLE)
    if not styles:
        return unmeasured("web.touch_target_too_small", title,
                          "Keine Stylesheets gefunden. Die verlässliche Messung "
                          "läuft im Browser (gerenderte Messung).", PLATFORM)
    rule = re.compile(r"([^{}]+)\{([^}]*)\}", re.DOTALL)
    size = re.compile(r"(?<![\w-])(?:min-)?(?:height|width)\s*:\s*(\d+(?:\.\d+)?)px")
    interactive = re.compile(r"(?i)(button|\.btn|\[role=\"?button|a[:\s.,{]|input|"
                             r"\.link|\.tab|\.chip|\.icon-button|select)")
    findings: list[Finding] = []
    measured = 0
    for sf in styles:
        body = strip_comments(sf.text, sf.ext)
        for m in rule.finditer(body):
            selector, decls = m.group(1), m.group(2)
            targets = [part for part in selector.split(',')
                       if not re.search(r"(?i)::?(?:before|after|marker|placeholder)\b", part)]
            if not any(interactive.search(part) for part in targets):
                continue
            measured += 1
            for sm in size.finditer(decls):
                val = float(sm.group(1))
                if val >= 44 or val < 8:
                    continue
                line_no = body.count("\n", 0, m.start(2) + sm.start()) + 1
                findings.append(Finding(
                    check_id="web.touch_target_too_small", severity=Severity.INFO,
                    message=f"'{snippet(selector.strip(), 40)}' hat {val}px — "
                            "unter der 44px-Mindestfläche.",
                    file=sf.rel, line=line_no, evidence=snippet(sm.group(0)),
                    fix="Mindestens 44×44px, notfalls über padding oder ein "
                        "::after-Pseudoelement vergrößern.",
                    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 4",
                ))
    if measured == 0:
        return unmeasured("web.touch_target_too_small", title,
                          "Keine Regeln an Interaktions-Selektoren gefunden.",
                          PLATFORM)
    return result_for("web.touch_target_too_small", title, findings, measured,
                      "Interaktionsregeln", PLATFORM)
