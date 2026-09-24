"""Universal: visible text lives in a catalog.

Split from the original checks/universal.py; background and
shared helpers in _common.py.
"""

from __future__ import annotations

import re

from ruttla.core import (
    CheckResult,
    Context,
    Finding,
    iter_matches,
    register,
    result_for,
    SelfTestCase,
    Severity,
    snippet,
    Status,
    strip_comments,
    unmeasured,
)

from ._common import MARKUP_EXTS, SOURCE_EXTS


# ===========================================================================
# C · Textkatalog
# ===========================================================================

@register(
    "i18n.orphan_catalog_keys",
    "Katalogschlüssel, die niemand aufruft (Karteileichen)",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Grundsatz C — 'Ein halb gepflegter Katalog ist schlimmer als keiner'",
    self_tests=[
        SelfTestCase(
            name="Karteileiche im Katalog",
            files={"src/locales/de.json": '{"studio.save": "Speichern", "studio.veraltet": "Alt"}',
                   "src/App.tsx": 'export const A = () => <button>{t("studio.save")}</button>;\n'},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="alle Schluessel benutzt",
            files={"src/locales/de.json": '{"studio.save": "Speichern"}',
                   "src/App.tsx": 'export const A = () => <button>{t("studio.save")}</button>;\n'},
            expect=Status.PASS,
        ),
    ],
)
def check_orphan_keys(ctx: Context) -> CheckResult:
    """Misst die eine Richtung, die maschinell sicher geht: Schlüssel, die im
    Katalog stehen und nirgends aufgerufen werden.

    Die Gegenrichtung (Text im Anzeigepfad ohne Katalog) prüft
    `i18n.literal_in_markup` — beide Richtungen sind nötig, sonst ist ein
    falsch-positives Gate nicht ausgeschlossen.
    """
    title = "Katalogschlüssel, die niemand aufruft (Karteileichen)"
    catalogs = [
        sf for sf in ctx.all_files()
        if sf.ext in (".json", ".ts", ".js", ".csv", ".po")
        and re.search(r"(^|/)(locales?|i18n|lang|translations?|strings)(/|\.|$)",
                      sf.rel, re.IGNORECASE)
    ]
    if not catalogs:
        return unmeasured("i18n.orphan_catalog_keys", title,
                          "Kein Textkatalog gefunden (locales/, i18n/, strings.*).")

    keys: dict[str, tuple[str, int]] = {}
    for sf in catalogs:
        if sf.ext == ".json":
            # Ein einzeiliges JSON hat alle Schlüssel in EINER Zeile — eine
            # zeilenweise Suche findet dort höchstens den ersten. Über den
            # ganzen Text suchen und die Zeile aus dem Offset ableiten.
            for m in re.finditer(r'["\']([A-Za-z][\w.]{2,})["\']\s*:\s*["\']',
                                 sf.text):
                keys.setdefault(m.group(1), (sf.rel, sf.line_of(m.start())))
            continue
        for idx, raw in enumerate(sf.lines, start=1):
            m = re.match(r'^\s*["\']?([A-Za-z][\w.]{2,})["\']?\s*:\s*["\']', raw)
            if m:
                keys.setdefault(m.group(1), (sf.rel, idx))
    if not keys:
        return unmeasured("i18n.orphan_catalog_keys", title,
                          f"{len(catalogs)} Katalogdatei(en) gefunden, aber keine "
                          "Schlüssel im erwarteten Format erkannt.")

    catalog_paths = {sf.path for sf in catalogs}
    consumers = "\n".join(
        sf.text for sf in ctx.files(*SOURCE_EXTS, *MARKUP_EXTS)
        if sf.path not in catalog_paths
    )
    findings: list[Finding] = []
    for key, (rel, line) in sorted(keys.items()):
        leaf = key.split(".")[-1]
        if key in consumers or (len(leaf) > 3 and leaf in consumers):
            continue
        findings.append(Finding(
            check_id="i18n.orphan_catalog_keys",
            severity=Severity.WARNING,
            message=f"Katalogschlüssel '{key}' wird nirgends aufgerufen.",
            file=rel, line=line,
            fix="Schlüssel löschen oder die Verwendungsstelle nachziehen. Ein "
                "Katalog mit Karteileichen sieht aus wie eine Quelle und ist keine.",
            guideline="CLAUDE.md § Grundsatz C",
        ))
    return result_for("i18n.orphan_catalog_keys", title, findings, len(keys),
                      "Katalogschlüssel")


@register(
    "i18n.literal_in_markup",
    "Sichtbarer Text steht fest im Markup statt im Katalog",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Grundsatz C",
    self_tests=[
        SelfTestCase(
            name="Literal im JSX",
            files={
                "src/locales/de.json": '{"studio.title": "Studio"}',
                "src/App.tsx": 'export const A = () => <button>Jetzt alle Figuren speichern</button>;\n',
            },
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Aus dem Katalog bezogen",
            files={
                "src/locales/de.json": '{"studio.save": "Speichern"}',
                "src/App.tsx": 'export const A = () => <button>{t("studio.save")}</button>;\n',
            },
            expect=Status.PASS,
        ),
    ],
)
def check_literal_text(ctx: Context) -> CheckResult:
    """Die Gegenrichtung zu `i18n.orphan_catalog_keys`.

    Läuft NUR, wenn ein Katalog existiert — sonst wäre in einem Projekt ohne
    i18n jede Zeile rot, und ein Gate, das beim ersten Lauf über funktionierende
    Dinge rot wird, ist die Bauform-Falle.
    """
    title = "Sichtbarer Text steht fest im Markup statt im Katalog"
    has_catalog = any(
        re.search(r"(^|/)(locales?|i18n|lang|translations?|strings)(/|\.|$)",
                  sf.rel, re.IGNORECASE)
        for sf in ctx.all_files()
    )
    if not has_catalog:
        return unmeasured(
            "i18n.literal_in_markup", title,
            "Kein Textkatalog im Projekt — die Katalogpflicht ist hier nicht "
            "etabliert. Grundsatz C verlangt einen, auch einsprachig.",
        )

    # Anzeigetext zwischen Tags. Bewusst konservativ: mindestens zwei Wörter,
    # Buchstaben, kein reines Symbol/Zahl — sonst trifft es Icons und Zähler.
    jsx_text = re.compile(r">\s*([A-ZÄÖÜ][^<>{}\n]{6,120}?)\s*<")
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(".tsx", ".jsx", ".vue", ".svelte", ".html"):
        if re.search(r"(^|/)(locales?|i18n|lang|translations?)(/|$)", sf.rel, re.IGNORECASE):
            continue
        units += 1
        body = strip_comments(sf.text, sf.ext)
        for m in jsx_text.finditer(body):
            text = m.group(1).strip()
            if len(text.split()) < 2:
                continue
            if not re.search(r"[A-Za-zÄÖÜäöüß]{3,}", text):
                continue
            # Interpolation/Ausdruck → kommt vermutlich aus dem Katalog
            if "{" in text or "}" in text:
                continue
            line_no = body.count("\n", 0, m.start()) + 1
            findings.append(Finding(
                check_id="i18n.literal_in_markup",
                severity=Severity.WARNING,
                message=f"Sichtbarer Text im Markup: \"{snippet(text, 60)}\"",
                file=sf.rel, line=line_no, evidence=snippet(text),
                fix="In den Textkatalog verschieben und über den Schlüssel "
                    "beziehen. Marke/Zahlen als Platzhalter {brand}, {count}.",
                guideline="CLAUDE.md § Grundsatz C",
            ))
    return result_for("i18n.literal_in_markup", title, findings, units)


@register(
    "i18n.string_concatenation",
    "Sichtbarer Text wird zusammengeklebt statt über Platzhalter gebildet",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Grundsatz C — 'Nie Zeichenketten zusammenkleben'",
    self_tests=[
        SelfTestCase(
            name="Text zusammengeklebt",
            files={"src/a.ts": 'const msg = "Es wurden " + count + " Eintraege gespeichert";\n'},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Platzhalter",
            files={"src/a.ts": 'const msg = t("items.saved", { count });\n'},
            expect=Status.PASS,
        ),
    ],
)
def check_string_concat(ctx: Context) -> CheckResult:
    title = "Sichtbarer Text wird zusammengeklebt statt über Platzhalter gebildet"
    # Literal mit Satzzeichen/Leerzeichen am Rand + '+' + Variable
    pat = re.compile(r'["\'][^"\']*[A-Za-zÄÖÜäöüß]{3,}[^"\']*\s["\']\s*\+\s*\w')
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(*SOURCE_EXTS):
        units += 1
        for line_no, m, raw in iter_matches(sf, pat):
            if re.search(r"(console\.|print\(|log\w*\(|logger|throw |Error\(|assert)", raw, re.I):
                continue  # Entwicklertext, gehört nicht in den Katalog
            findings.append(Finding(
                check_id="i18n.string_concatenation",
                severity=Severity.WARNING,
                message="Anzeigetext wird per '+' zusammengesetzt.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Platzhalter im Katalog nutzen ({name}, {count}) — die "
                    "Wortstellung ist sprachabhängig.",
                guideline="CLAUDE.md § Grundsatz C",
            ))
    return result_for("i18n.string_concatenation", title, findings, units)
