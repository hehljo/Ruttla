"""Statische Web-Dateien: Verweise auf Bilder, Symbole und Schriften, die es
nicht gibt, und Übersetzungsziele, die ihre Kinder überschreiben."""
from __future__ import annotations

import os
import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, result_for, snippet, strip_comments, unmeasured,
)

PLATFORM = "web"

# Nur Medien, Symbole, Schriften und Manifeste: Skripte und Stylesheets
# entstehen oft erst im Build (Bundler, mitgelieferte Bibliotheken) und
# wären hier Fehlalarm.
_STATIC_EXT = (".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg",
               ".ico", ".webmanifest", ".woff", ".woff2", ".ttf", ".otf")
_HTML_REF = re.compile(r"""\b(?:href|src|content)\s*=\s*["']([^"'\s>]+)["']""", re.I)
_CSS_REF = re.compile(r"""url\(\s*["']?([^"')\s]+)["']?\s*\)""", re.I)
_JSON_REF = re.compile(r'"src"\s*:\s*"([^"]+)"')
_WEB_ROOTS = ("public", "static", "www", "site", "wwwroot")


def _is_local_static(ref: str) -> bool:
    if re.match(r"^(?:[a-z][\w+.-]*:|//|#)", ref, re.I):
        return False
    if "{" in ref or "$" in ref or "<" in ref:
        return False  # Vorlage, wird erst beim Ausliefern gefüllt
    path = ref.split("?")[0].split("#")[0]
    return path.lower().endswith(_STATIC_EXT)


def _candidates(root: str, file_rel: str, ref: str) -> list[str]:
    """Wo die Datei liegen darf. Ein Pfad mit / beginnt an der Web-Wurzel;
    die ist je nach Bauart public/, static/ oder das Projekt selbst —
    Vite legt index.html ins Projekt und bedient /logo.png aus public/."""
    path = ref.split("?")[0].split("#")[0]
    here = os.path.dirname(file_rel)
    if not path.startswith("/"):
        return [os.path.normpath(os.path.join(root, here, path))]
    rel = path.lstrip("/")
    # Jede Ebene zwischen Projekt und Datei kann die Wurzel sein — ein
    # Vite-Teilprojekt in dashboard/ bedient /favicon.svg aus
    # dashboard/public/, nicht aus dem public/ des Repos.
    parts = here.split("/") if here else []
    roots = set()
    for i in range(len(parts) + 1):
        level = os.path.join(root, *parts[:i])
        roots.add(level)
        for name in _WEB_ROOTS:
            roots.add(os.path.join(level, name))
    return [os.path.join(r, rel) for r in roots]


@register(
    "web.local_asset_missing",
    "Verweis auf ein Bild, Symbol oder eine Schrift, die es nicht gibt",
    platform=PLATFORM,
    severity=Severity.ERROR,
    safe_by_default=True,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 6n — Symbole aus einer Quelle",
    rationale=(
        "Wer ein Symbol ersetzt oder eine Datei löscht, lässt leicht einen Verweis "
        "stehen: ein <link rel=icon>, ein Manifest-Eintrag, ein url() im CSS. Der "
        "Browser meldet nichts, der Tab zeigt ein leeres Blatt oder das alte "
        "Symbol aus dem Cache. Belegt am 30.09.2026: beim Wechsel auf ein neues "
        "Zeichen entfiel favicon.svg; fünf Seiten verwiesen noch darauf, drei "
        "davon ausschließlich. Gemessen werden nur Medien, Symbole, Schriften und "
        "Manifeste — Skripte und Stylesheets entstehen oft erst im Build."
    ),
    self_tests=[
        SelfTestCase(
            name="defekt: Favicon gelöscht, Verweis steht noch",
            files={"public/impressum/index.html":
                   '<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">\n'
                   "<h1>Impressum</h1>\n",
                   "public/assets/icon-32.png": "x"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="defekt: Manifest-Symbol fehlt",
            files={"public/index.html": '<link rel="manifest" href="/manifest.webmanifest">\n',
                   "public/manifest.webmanifest": '{"icons":[{"src":"/assets/icon-512.png"}]}'},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="gesund: Wurzel public/, Vite-Stil, relativ, extern und Vorlage",
            files={"public/index.html":
                   '<link rel="icon" href="/assets/icon-32.png">\n'
                   '<img src="../logo.webp"><img src="https://cdn.example/x.png">\n'
                   '<img src="data:image/png;base64,AAA="><img src="/img/{{slug}}.png">\n'
                   '<script src="/vendor/lib.js"></script>\n',
                   "public/assets/icon-32.png": "x",
                   "logo.webp": "x",
                   "index.html": '<link rel="icon" href="/favicon.ico">\n',
                   "public/favicon.ico": "x",
                   "public/styles/a.css": "@font-face{src:url(../fonts/a.woff2)}\n",
                   "public/fonts/a.woff2": "x"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="gesund: Vite-Teilprojekt mit eigenem public/",
            files={"dashboard/index.html": '<link rel="icon" href="/favicon.svg">\n',
                   "dashboard/public/favicon.svg": "<svg/>"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="defekt: Schrift im CSS fehlt",
            files={"public/styles/a.css": "@font-face{src:url('../fonts/weg.woff2')}\n"},
            expect=Status.FAIL,
        ),
    ],
)
def check_local_asset_missing(ctx: Context) -> CheckResult:
    title = "Verweis auf ein Bild, Symbol oder eine Schrift, die es nicht gibt"
    sources = ctx.files(".html", ".htm", ".css", ".webmanifest")
    if not sources:
        return unmeasured("web.local_asset_missing", title,
                          "Keine HTML-, CSS- oder Manifest-Dateien gefunden.", PLATFORM)
    findings: list[Finding] = []
    refs = 0
    for sf in sources:
        if sf.ext == ".css":
            text, pattern = strip_comments(sf.text, sf.ext), _CSS_REF
        elif sf.ext == ".webmanifest":
            text, pattern = sf.text, _JSON_REF
        else:
            text = re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                          sf.text, flags=re.S)
            pattern = _HTML_REF
        for m in pattern.finditer(text):
            ref = m.group(1)
            if not _is_local_static(ref):
                continue
            refs += 1
            if any(os.path.isfile(p) for p in _candidates(ctx.root, sf.rel, ref)):
                continue
            line = sf.line_of(m.start())
            findings.append(Finding(
                check_id="web.local_asset_missing", severity=Severity.ERROR,
                message=f"'{ref}' verweist auf eine Datei, die es nicht gibt.",
                file=sf.rel, line=line, evidence=snippet(sf.lines[line - 1]),
                fix="Verweis auf die neue Datei umstellen oder entfernen. Nach "
                    "jedem Symbolwechsel alle Verweise aus der Quelle suchen, "
                    "nicht aus einer Liste.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § 6n",
            ))
    if refs == 0:
        return unmeasured("web.local_asset_missing", title,
                          "Keine Verweise auf lokale Bilder, Symbole oder Schriften.",
                          PLATFORM)
    return result_for("web.local_asset_missing", title, findings, refs,
                      "Verweise", PLATFORM)


_TARGET = re.compile(
    r"<([a-zA-Z][\w-]*)\b([^>]*\bdata-(?:i18n|brand-name)(?![\w-])[^>]*)>", re.S)
_VOID = {"img", "input", "meta", "link", "br", "hr", "source", "area", "col",
         "embed", "track", "wbr"}


@register(
    "web.i18n_target_has_children",
    "Übersetzungsziel mit Kind-Elementen — der Text überschreibt sie",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § -0 — Markenname als Platzhalter",
    rationale=(
        "Wer den Text eines [data-i18n]- oder [data-brand-name]-Elements setzt "
        "(textContent oder innerHTML), ersetzt alles darin — auch ein Symbol "
        "neben dem Schriftzug. Im Markup steht es, im Browser ist es weg; ein "
        "DOM-Test, der die Übersetzung nicht laufen lässt, sieht es weiter. "
        "Aufgefallen am 30.09.2026 beim Einbau des Markenzeichens in "
        "<a class=wordmark data-brand-name>: der Name gehört in ein eigenes "
        "<span>. Hinweis statt Fehler — ein Rückfalltext mit <strong> darf "
        "absichtlich ersetzt werden."
    ),
    self_tests=[
        SelfTestCase(
            name="defekt: Zeichen im Markenelement",
            files={"public/index.html":
                   '<a class="wordmark" href="/" data-brand-name><img src="/m.webp" alt="">Marke</a>\n'},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="gesund: Name in eigenem span, Attribut-Übersetzung mit Kindern",
            files={"public/index.html":
                   '<a class="wordmark" href="/"><img src="/m.webp" alt=""><span data-brand-name>Marke</span></a>\n'
                   '<button data-i18n-attr="aria-label:app.close"><svg></svg></button>\n'
                   '<input data-i18n-placeholder="a.b">\n<p data-i18n="a.c"></p>\n'},
            expect=Status.PASS,
        ),
    ],
)
def check_i18n_target_has_children(ctx: Context) -> CheckResult:
    title = "Übersetzungsziel mit Kind-Elementen — der Text überschreibt sie"
    files = ctx.files(".html", ".htm")
    findings: list[Finding] = []
    targets = 0
    for sf in files:
        for m in _TARGET.finditer(sf.text):
            tag = m.group(1).lower()
            if tag in _VOID:
                continue
            targets += 1
            close = sf.text.find(f"</{tag}", m.end())
            inner = sf.text[m.end(): close] if close != -1 else ""
            if not re.search(r"<[a-zA-Z]", re.sub(r"<!--.*?-->", "", inner, flags=re.S)):
                continue
            line = sf.line_of(m.start())
            findings.append(Finding(
                check_id="web.i18n_target_has_children", severity=Severity.WARNING,
                message=f"<{tag}> bekommt seinen Text zur Laufzeit gesetzt und "
                        "enthält Elemente, die dabei verschwinden.",
                file=sf.rel, line=line, evidence=snippet(sf.lines[line - 1]),
                fix="Den übersetzten Text in ein eigenes <span data-i18n> legen; "
                    "Symbole und Bilder daneben, nicht darin.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § -0",
            ))
    if targets == 0:
        return unmeasured("web.i18n_target_has_children", title,
                          "Keine Elemente mit data-i18n oder data-brand-name.", PLATFORM)
    return result_for("web.i18n_target_has_children", title, findings, targets,
                      "Übersetzungsziele", PLATFORM)
