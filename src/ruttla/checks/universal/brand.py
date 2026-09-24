"""Universal: brand names stay in their single source.

Split from the original checks/universal.py; background and
shared helpers in _common.py.
"""

from __future__ import annotations

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
    strip_comments,
    unmeasured,
)

from ._common import _brand_candidates, MARKUP_EXTS, SOURCE_EXTS


@register(
    "brand.hardcoded_in_display",
    "Markenname steht fest im Anzeigepfad",
    severity=Severity.ERROR,
    guideline="CLAUDE.md § Architektur-Grundsatz A",
    self_tests=[
        SelfTestCase(
            name="Markenname im JSX",
            files={
                "package.json": '{"name": "acme-web"}',
                "src/App.tsx": 'export const A = () => <h1>Willkommen bei Acme</h1>;\n',
            },
            expect=Status.FAIL,
            expect_finding_contains="Acme",
        ),
        SelfTestCase(
            name="Markenname nur in der Quelle",
            files={
                "package.json": '{"name": "acme-web"}',
                "src/brand.ts": 'export const BRAND = { name: "Acme" };\n',
                "src/App.tsx": 'import { BRAND } from "./brand";\nexport const A = () => <h1>{BRAND.name}</h1>;\n',
            },
            expect=Status.PASS,
        ),
    ],
)
def check_brand_hardcoded(ctx: Context) -> CheckResult:
    """Misst die EIGENSCHAFT "kein fester Markentext im Anzeigepfad".

    Bewusst NICHT geprüft wird, ob ein bestimmter Import vorliegt — das wäre
    eine Bauform-Vorschrift und verböte die bessere Lösung.

    Die Brand-Quelldateien selbst sind ausgenommen: dort GEHÖRT der Name hin.
    Technische Bezeichner (Bundle-IDs, Tabellen, Storage-Keys) sind Verträge,
    keine Textänderung — sie werden nicht gemeldet.
    """
    title = "Markenname steht fest im Anzeigepfad"
    brands = _brand_candidates(ctx)
    if not brands:
        return unmeasured(
            "brand.hardcoded_in_display", title,
            "Kein Markenname ermittelbar. In .ruttla.toml unter "
            "[brand] names = [\"...\"] eintragen, damit dieser Check misst.",
        )

    source_globs = ctx.config.brand_source_globs or [
        "*brand*", "*Brand*", "*config*", "*Config*", "*constants*",
        "*Constants*", "*strings*", "*Strings*", "*i18n*", "*locale*",
        "*theme*", "*Theme*", "*.json", "*.plist", "*.pbxproj", "*.md",
        "*.lock", "*.toml", "*.cfg", "*.godot", "*.csproj", "*.podspec",
    ]

    def is_brand_source(rel: str) -> bool:
        base = os.path.basename(rel)
        import fnmatch
        return any(fnmatch.fnmatch(base, g) or fnmatch.fnmatch(rel, g)
                   for g in source_globs)

    # Technische Verträge — Umbenennen dort ist eine Migration, kein Textfix.
    contract_ctx = re.compile(
        r"(bundleIdentifier|PRODUCT_BUNDLE_IDENTIFIER|localStorage|sessionStorage"
        r"|from\s*\(|\.from\(|table\s*[:=]|bucket|schema"
        r"|package\s|namespace\s|^\s*import\s|require\s*\(|#include"
        r"|url\s*[:=]|href\s*=|src\s*=|\bpath\b|\bclassName\b|data-testid"
        r")",
        re.IGNORECASE,
    )
    decl_before = re.compile(
        r"\b(?:interface|type|class|struct|enum|extends|implements|func|"
        r"function|def|const|let|var|protocol|actor|new|instanceof|as)\s+$"
        r"|[:<]\s*$|\.\s*$"
    )
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(*SOURCE_EXTS, *MARKUP_EXTS):
        if is_brand_source(sf.rel):
            continue
        units += 1
        body = strip_comments(sf.text, sf.ext)
        for brand in brands:
            # Case-insensitiv: package.json liefert oft klein, das JSX groß.
            # Gemeldet wird die TATSÄCHLICHE Schreibweise im Code, nicht die
            # gesuchte — sonst zeigt der Befund auf einen Text, der so nicht
            # dasteht.
            pat = re.compile(r"\b" + re.escape(brand) + r"\b", re.IGNORECASE)
            for m in pat.finditer(body):
                line_no = body.count("\n", 0, m.start()) + 1
                raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
                if contract_ctx.search(raw):
                    continue
                # Der Prüfbereich ist die FUNDSTELLE, nicht die Zeile: direkt
                # vor dem Treffer ein Deklarations-Schlüsselwort heißt, dass
                # der Name ein Bezeichner ist und kein Anzeigetext.
                before = body[max(0, m.start() - 40): m.start()]
                if decl_before.search(before):
                    continue
                # Ein Bezeichner geht unmittelbar in einen Typ-/Aufrufkontext
                # über (Asset[], Asset.foo, Asset(...), Asset<T>). Ein '</'
                # dagegen ist ein SCHLIESSENDES Tag — also gerade der Beweis,
                # dass der Name Anzeigetext ist. Die Gegenprobe hat genau das
                # gefunden: '</h1>' blockte den echten Befund weg.
                after = body[m.end(): m.end() + 2]
                if re.match(r"[\w.\[(]", after) or re.match(r"<[^/]", after):
                    continue
                findings.append(Finding(
                    check_id="brand.hardcoded_in_display",
                    severity=Severity.ERROR,
                    message=f"Markenname '{m.group(0)}' steht wörtlich im Anzeigepfad.",
                    file=sf.rel, line=line_no, evidence=snippet(raw),
                    fix="Aus der Brand-Einzelquelle beziehen (Modul ohne "
                        "Umgebungsabhängigkeiten) oder als Platzhalter {brand} "
                        "in den Textkatalog legen.",
                    guideline="CLAUDE.md § Grundsatz A",
                ))
    return result_for("brand.hardcoded_in_display", title, findings, units)


@register(
    "brand.derived_asset_named_after_brand",
    "Abgeleitete Datei trägt den Markennamen im Dateinamen",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Grundsatz A — abgeleitete Dateien generisch benennen",
    self_tests=[
        SelfTestCase(
            name="Asset traegt Markennamen",
            files={"package.json": '{"name": "acme-web"}', "public/acme-logo.png": "x"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="generisch benannt",
            files={"package.json": '{"name": "acme-web"}', "public/wordmark.png": "x"},
            expect=Status.PASS,
        ),
    ],
)
def check_brand_asset_names(ctx: Context) -> CheckResult:
    title = "Abgeleitete Datei trägt den Markennamen im Dateinamen"
    brands = _brand_candidates(ctx)
    if not brands:
        return unmeasured("brand.derived_asset_named_after_brand", title,
                          "Kein Markenname ermittelbar.")
    asset_exts = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".ico", ".icns", ".pdf"}
    findings: list[Finding] = []
    units = 0
    for sf in ctx.all_files():
        if sf.ext not in asset_exts:
            continue
        units += 1
        base = os.path.basename(sf.rel)
        for brand in brands:
            if re.search(r"\b" + re.escape(brand) + r"\b", base, re.IGNORECASE):
                findings.append(Finding(
                    check_id="brand.derived_asset_named_after_brand",
                    severity=Severity.WARNING,
                    message=f"'{base}' trägt den Markennamen im Dateinamen.",
                    file=sf.rel,
                    fix="Generisch benennen (wordmark.png, icon-512.png), damit "
                        "beim Rebranding nur die Vorlage getauscht wird.",
                    guideline="CLAUDE.md § Grundsatz A",
                ))
                break
    return result_for("brand.derived_asset_named_after_brand", title, findings,
                      units, "Asset-Dateien")


@register(
    "brand.manual_derivation_comment",
    "Kommentar kündigt eine von Hand nachgebaute Ableitung an",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Grundsatz A — 'Der Kommentar ist die Warnung, dass die Kopplung fehlt'",
    self_tests=[
        SelfTestCase(
            name="Kopplungskommentar vorhanden",
            files={"src/gen.ts": "// ändert sich der Zuschnitt dort, muss er hier mit\nconst R = 4.25;\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Normaler Kommentar",
            files={"src/gen.ts": "// Seitenverhältnis aus der Vorlage berechnet\nconst R = ratioFromTemplate();\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_manual_derivation(ctx: Context) -> CheckResult:
    """Wo im Code steht "muss mitgeändert werden", ist eine Ableitung von Hand
    nachgebaut. Genau dort muss der Generator schreiben, nicht der Mensch."""
    title = "Kommentar kündigt eine von Hand nachgebaute Ableitung an"
    pat = re.compile(
        r"(muss(\s+\w+){0,3}\s+(hier\s+)?mit(geändert|gepflegt|gezogen)?\b"
        r"|hier\s+(auch\s+)?(mit)?ändern"
        r"|keep\s+in\s+sync|must\s+match|remember\s+to\s+update"
        r"|synchron\s+halten|gleichzeitig\s+ändern"
        r"|dann\s+(auch\s+)?hier\s+anpassen)",
        re.IGNORECASE,
    )
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(*SOURCE_EXTS, *MARKUP_EXTS, ".css", ".scss"):
        units += 1
        # Hier wollen wir GERADE die Kommentare sehen.
        for idx, raw in enumerate(sf.lines, start=1):
            stripped = raw.strip()
            if not re.match(r"^\s*(//|#|/\*|\*|<!--)", stripped):
                continue
            if pat.search(stripped):
                findings.append(Finding(
                    check_id="brand.manual_derivation_comment",
                    severity=Severity.WARNING,
                    message="Kommentar verlangt manuelles Mitpflegen — die Kopplung fehlt.",
                    file=sf.rel, line=idx, evidence=snippet(stripped),
                    fix="Den Wert generieren oder aus der Quelle ableiten, statt "
                        "ihn zu tippen. Und prüfen, dass der Verbraucher ihn benutzt.",
                    guideline="CLAUDE.md § Grundsatz A",
                ))
    return result_for("brand.manual_derivation_comment", title, findings, units)
