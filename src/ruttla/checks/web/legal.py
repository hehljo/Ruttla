"""Rechtstexte: fehlende Pflichtseiten und unausgefüllte Platzhalter."""
from __future__ import annotations

import os
import re

from ruttla.checks.web.rules import WEB_CODE
from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, result_for, snippet, strip_comments, unmeasured,
)

PLATFORM = "web"


@register(
    "web.legal_pages_missing",
    "Impressum oder Datenschutzerklärung fehlt",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 6c / CLAUDE.md § Rechtliche Blocker",
    self_tests=[
        SelfTestCase(
            name="Impressum fehlt",
            files={"package.json": '{"name":"shop"}', "src/App.tsx": "export const A = () => <main>Shop</main>;\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="beide vorhanden",
            files={"package.json": '{"name":"shop"}',
                   "src/App.tsx": "export const A = () => <main><a href=\"/impressum\">Impressum</a><a href=\"/datenschutz\">Datenschutz</a></main>;\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Roadmap-Nennung ist keine Pflichtseite",
            files={"package.json": '{"name":"shop"}', "src/App.tsx": "export const A = () => <main>Shop</main>;\n", "README.md": "Impressum und Datenschutz fehlen noch.\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Quelltextkommentar ist keine Pflichtseite",
            files={"package.json": '{"name":"shop"}', "src/App.tsx": "// TODO: Impressum und Datenschutz\nexport const A = () => <main>Shop</main>;\n"},
            expect=Status.FAIL,
        ),
    ],
)
def check_legal(ctx: Context) -> CheckResult:
    """Rechtlicher Blocker vor jedem Deploy. Gemessen an Routen/Dateien, nicht
    an einem Haken in einer ROADMAP — ein Haken belegt nichts."""
    title = "Impressum oder Datenschutzerklärung fehlt"
    is_site = any(
        os.path.basename(sf.rel) in ("index.html", "App.tsx", "app.tsx", "+layout.svelte")
        for sf in ctx.all_files()
    ) or bool(ctx.files_named("package.json"))
    if not is_site:
        return unmeasured("web.legal_pages_missing", title,
                          "Kein Web-Frontend erkannt.", PLATFORM)
    # Documentation and comments can explicitly describe missing pages. Their
    # keywords must never turn a release blocker green. This is still a source
    # presence check, not a legal assessment or proof of reachable routes.
    corpus = "\n".join(
        sf.rel + "\n" + strip_comments(sf.text, sf.ext)
        for sf in ctx.files(*WEB_CODE, ".html")
    )
    findings: list[Finding] = []
    for label, pat in (
        ("Impressum", r"(?i)(impressum|legal[_-]?notice|/imprint)"),
        ("Datenschutzerklärung", r"(?i)(datenschutz|privacy[_-]?policy|/privacy)"),
    ):
        if not re.search(pat, corpus):
            findings.append(Finding(
                check_id="web.legal_pages_missing", severity=Severity.ERROR,
                message=f"{label} nirgends im Projekt gefunden.",
                fix=f"{label} anlegen und aus dem Fuß jeder Seite verlinken. "
                    "Pflichtangabe vor dem Deploy — und eine Fassung, auf die "
                    "alle Plattformen verweisen, statt drei synchron zu haltender.",
                guideline="CLAUDE.md § Rechtliche Blocker",
            ))
    return result_for("web.legal_pages_missing", title, findings, 2,
                      "geprüfte Pflichtangaben", PLATFORM)

# Erkannt wird die Seite an ihrer Überschrift, nicht am Pfad: ein Pfad ist
# eine Bauform-Annahme, die Überschrift ist die Eigenschaft.
_LEGAL_HEADING = re.compile(
    r"<(?:title|h1)\b[^>]*>[^<]*(?:Impressum|Datenschutz|Nutzungsbedingungen|"
    r"AGB|Allgemeine Geschäftsbedingungen|Widerruf|Privacy Policy|Imprint|"
    r"Legal Notice|Terms of (?:Service|Use)|Terms and Conditions)",
    re.IGNORECASE,
)
_HIDDEN = re.compile(
    r"<(script|style|code|pre|template)\b.*?</\1\s*>|<!--.*?-->",
    re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r"<[^>]*>", re.DOTALL)
# Ein Platzhalter enthält Buchstaben oder die Auslassung — "[1]" ist eine
# Fußnote. Markdown-Links "[Text](url)" sind keine Platzhalter.
_PLACEHOLDER = re.compile(r"\[(?=[^\]\n]*[A-Za-zÄÖÜäöüß…])[^\]\n]{1,60}\](?!\()")
_LOREM = re.compile(r"\blorem ipsum\b", re.IGNORECASE)
# Ein Entwurfsvermerk an die Leserin: das Wort, direkt gefolgt von einem
# Satzzeichen ("Entwurf." / "Noch auszufüllen:"). Im Fließtext steht so
# etwas praktisch nie, als Hinweiskasten über einem Gerüst immer.
_DRAFT = re.compile(r"\b(?:Entwurf|Noch auszufüllen|Draft|TODO|FIXME)[.:!]")


def _blank(text: str, pattern: re.Pattern) -> str:
    return pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


@register(
    "web.legal_placeholder",
    "Pflichtseite mit unausgefülltem Platzhalter",
    platform=PLATFORM,
    severity=Severity.ERROR,
    safe_by_default=True,
    guideline="CLAUDE.md § Rechtliche Blocker und Pflichtangaben",
    rationale=(
        "`web.legal_pages_missing` misst, ob Impressum und Datenschutz "
        "existieren — nicht, ob sie ausgefüllt sind. Ein Gerüst mit [Name], "
        "[Region bestätigen] oder [Datum] besteht diese Prüfung und geht bei "
        "jedem Push live. Belegt am 30.09.2026: die Datenschutzerklärung trug "
        "sieben Platzhalter, darunter den Verantwortlichen und die "
        "Aufsichtsbehörde, während die Seite bereits ausgeliefert wurde."
    ),
    self_tests=[
        SelfTestCase(
            name="defekt: Verantwortlicher als Platzhalter",
            files={"public/datenschutz/index.html":
                   "<title>Datenschutz</title><h1>Datenschutzerklärung</h1>\n"
                   "<p>[Name]<br>[PLZ, Ort]</p>\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="defekt: Region nicht bestätigt, in einer Tabelle",
            files={"legal/privacy.html":
                   "<h1>Privacy Policy</h1>\n<table><tr><td>Netlify</td>"
                   "<td>[Region bestätigen]</td></tr></table>\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="defekt: Entwurfsvermerk ohne Klammer",
            files={"public/agb/index.html":
                   "<h1>Nutzungsbedingungen</h1>\n<p><strong>Entwurf.</strong> "
                   "Vor dem Start prüfen lassen.</p>\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="gesund: Entwürfe als Funktion der App",
            files={"public/datenschutz/index.html":
                   "<h1>Datenschutz</h1>\n<p>Entwürfe werden nur auf deinem Gerät "
                   "gespeichert; ein Entwurf verlässt es nie.</p>\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="gesund: ausgefüllt, Script-Array und Fußnote",
            files={"public/impressum/index.html":
                   "<title>Impressum</title><script>var l=[\"atlas\",\"vitrine\"];</script>\n"
                   "<h1>Impressum</h1><p>Max Muster, Hauptstraße 1, 80331 München [1]</p>\n"
                   "<p>Beispiel: <code>[Name]</code></p>\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Klammern auf einer normalen Seite zählen nicht",
            files={"public/index.html": "<h1>Willkommen</h1><p>[Beta]</p>\n",
                   "public/impressum/index.html": "<h1>Impressum</h1><p>Max Muster</p>\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_legal_placeholder(ctx: Context) -> CheckResult:
    title = "Pflichtseite mit unausgefülltem Platzhalter"
    pages = [sf for sf in ctx.files(".html", ".htm")
             if _LEGAL_HEADING.search(sf.text)]
    if not pages:
        return unmeasured("web.legal_placeholder", title,
                          "Keine Pflichtseite (Impressum, Datenschutz, AGB …) "
                          "als HTML gefunden.", PLATFORM)
    findings: list[Finding] = []
    for sf in pages:
        visible = _blank(_blank(sf.text, _HIDDEN), _TAG)
        for pattern in (_PLACEHOLDER, _LOREM, _DRAFT):
            for m in pattern.finditer(visible):
                line = sf.line_of(m.start())
                findings.append(Finding(
                    check_id="web.legal_placeholder", severity=Severity.ERROR,
                    message=f"Unfertige Stelle '{m.group(0)}' in einer Pflichtseite.",
                    file=sf.rel, line=line, evidence=snippet(sf.lines[line - 1]),
                    fix="Angabe ausfüllen, bevor die Seite ausgeliefert wird. "
                        "Ist sie noch nicht bekannt, die Seite aus dem Build "
                        "nehmen statt ein Gerüst zu veröffentlichen.",
                    guideline="CLAUDE.md § Rechtliche Blocker",
                ))
    return result_for("web.legal_placeholder", title, findings, len(pages),
                      "Pflichtseiten", PLATFORM)
