#!/usr/bin/env python3
"""
Universelle Checks — Grundsätze A–E aus CLAUDE.md, plattformunabhängig.

A · Branding ist NIE hardcoded
B · Labor-Modus: statisch auswertbares Flag
C · Kein sichtbarer Text im Code (Katalogpflicht)
D · Zustand getrennt vom Laufzeitkram
E · Veröffentlichtes Protokoll ist ein Vertrag

Dazu: Secrets, Gate-Hygiene (Pipe-Falle, tail vor $?), Existenz-vs-Wirkung.
"""

from __future__ import annotations

import os
import re

from core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, ok, failed, unmeasured, result_for, iter_matches, snippet,
    strip_comments,
)

SOURCE_EXTS = (
    ".swift", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".cs",
    ".gd", ".kt", ".java", ".go", ".rs", ".vue", ".svelte",
)
MARKUP_EXTS = (".html", ".xaml", ".xml", ".tscn", ".vue", ".svelte")


def _is_git_ignored(ctx: Context, rel: str) -> bool:
    """True, wenn .gitignore den Pfad erfasst. Konservativ: nur exakte Namen
    und Verzeichnispräfixe, keine volle Glob-Semantik."""
    gi = os.path.join(ctx.root, ".gitignore")
    if not os.path.isfile(gi):
        return False
    try:
        with open(gi, "r", encoding="utf-8", errors="replace") as fh:
            entries = [ln.strip() for ln in fh
                       if ln.strip() and not ln.strip().startswith(("#", "!"))]
    except OSError:
        return False
    base = os.path.basename(rel)
    for e in entries:
        e = e.strip("/")
        if e in (base, rel) or rel.startswith(e + "/"):
            return True
        if e.startswith("*") and base.endswith(e.lstrip("*")):
            return True
        if e.endswith("*") and base.startswith(e.rstrip("*")):
            return True
    return False


# ===========================================================================
# A · Branding
# ===========================================================================

def _brand_candidates(ctx: Context) -> list[str]:
    """Markennamen aus dem Profil, sonst aus Projektmetadaten abgeleitet."""
    if ctx.config.brand_names:
        return ctx.config.brand_names
    names: set[str] = set()
    for sf in ctx.files_named("package.json"):
        m = re.search(r'"name"\s*:\s*"([^"]+)"', sf.text)
        if m:
            raw = m.group(1).split("/")[-1]
            for part in re.split(r"[-_.\s]+", raw):
                if len(part) >= 4 and part.isalpha():
                    names.add(part)
    for sf in ctx.files_named("project.godot"):
        m = re.search(r'config/name\s*=\s*"([^"]+)"', sf.text)
        if m:
            for part in re.split(r"[-_.\s]+", m.group(1)):
                if len(part) >= 4 and part.isalpha():
                    names.add(part)
    # Generische Wörter taugen nicht als Markenanker.
    generic = {
        "main", "test", "demo", "core", "util", "utils", "common", "shared",
        "client", "server", "front", "back", "site", "root", "base", "lib",
        "project", "sample", "template", "example", "index", "source",
        # Aus echten Projekten nachgetragen: package.json-Namen, die ein
        # Fachwort tragen statt einer Marke.
        "asset", "assets", "studio", "game", "games", "tool", "tools", "app",
        "apps", "web", "site", "data", "code", "next", "node", "view", "views",
        "page", "pages", "type", "types", "model", "models", "store", "state",
        "auth", "user", "users", "admin", "image", "images", "media", "file",
        "files", "text", "task", "tasks", "item", "items", "list", "form",
        "chat", "note", "notes", "docs", "build", "public", "static", "style",
    }
    return sorted(n for n in names if n.lower() not in generic)


@register(
    "brand.hardcoded_in_display",
    "Markenname steht fest im Anzeigepfad",
    severity=Severity.ERROR,
    guideline="CLAUDE.md § Architektur-Grundsatz A",
    self_tests=[
        SelfTestCase(
            name="Markenname im JSX",
            files={
                "package.json": '{"name": "tellunia-web"}',
                "src/App.tsx": 'export const A = () => <h1>Willkommen bei Tellunia</h1>;\n',
            },
            expect=Status.FAIL,
            expect_finding_contains="Tellunia",
        ),
        SelfTestCase(
            name="Markenname nur in der Quelle",
            files={
                "package.json": '{"name": "tellunia-web"}',
                "src/brand.ts": 'export const BRAND = { name: "Tellunia" };\n',
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
            "Kein Markenname ermittelbar. In .qualitygate.toml unter "
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
            files={"package.json": '{"name": "tellunia-web"}', "public/tellunia-logo.png": "x"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="generisch benannt",
            files={"package.json": '{"name": "tellunia-web"}', "public/wordmark.png": "x"},
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


# ===========================================================================
# B · Labor-Modus
# ===========================================================================

@register(
    "lab.flag_not_statically_evaluable",
    "Labor-Flag ist ein Funktionsaufruf statt einer Konstante",
    severity=Severity.ERROR,
    guideline="CLAUDE.md § Grundsatz B",
    self_tests=[
        SelfTestCase(
            name="Flag als Funktion",
            files={"src/lab.ts": "export function isLabEnabled() { return import.meta.env.VITE_ENABLE_LAB !== 'false'; }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Flag als Konstante",
            files={"src/lab.ts": "export const isLabEnabled = import.meta.env.VITE_ENABLE_LAB !== 'false';\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_lab_flag(ctx: Context) -> CheckResult:
    """Nur ein statisch auswertbares Flag kann der Bundler wegoptimieren.
    Ein `if (getLabFlag())` bleibt im ausgelieferten Bundle stehen."""
    title = "Labor-Flag ist ein Funktionsaufruf statt einer Konstante"
    # 'Label', 'Laboratory', 'collaborate' enthalten alle 'lab' als Fragment.
    # Gemessen gehört ein Flag-Bezeichner, keine Teilzeichenkette: das Wort
    # 'lab' muss an einer Wortgrenze oder camelCase-Grenze enden. Belegt an
    # SchnitzeljagdAI: 'buildCheckerLabel' und 'mirrorLabel' wurden als
    # Labor-Flags gemeldet.
    name_pat = re.compile(
        r"(?:^|_|\b)(?:is|enable|use|with)?_?"
        r"(?:lab|labor|playground|sandbox|experimental)"
        r"(?:_?(?:enabled|mode|flag|only)|(?=[A-Z_]|$))",
        re.IGNORECASE,
    )
    fn_decl = re.compile(
        r"^\s*(export\s+)?(async\s+)?function\s+(\w*(?:[Ll]ab|[Ll]abor|[Pp]layground|[Ss]andbox)\w*)\s*\(",
    )
    arrow_fn = re.compile(
        r"^\s*(export\s+)?const\s+(\w*(?:[Ll]ab|[Ll]abor|[Pp]layground|[Ss]andbox)\w*)\s*[:=][^=]*=>\s*",
    )
    findings: list[Finding] = []
    units = 0
    found_any_lab = False
    # Ein Flag-Bezeichner in IRGENDEINER Form heißt: hier gibt es ein Labor,
    # also ist der Check anwendbar. Ohne diese Erkennung meldete der gesunde
    # Fall "nicht gemessen" statt "bestanden" — die Gegenprobe hat das gefunden.
    flag_present = re.compile(
        r"\b(?:is|enable|use|with|VITE_ENABLE|ENABLE)?_?"
        r"(?:[Ll]ab|LAB|[Ll]abor|[Pp]layground|[Ss]andbox)"
        r"(?:_?(?:[Ee]nabled|ENABLED|[Mm]ode|MODE|[Ff]lag|FLAG)|\b)"
    )
    for sf in ctx.files(".ts", ".tsx", ".js", ".jsx", ".mjs", ".swift"):
        units += 1
        body = strip_comments(sf.text, sf.ext)
        if flag_present.search(body):
            found_any_lab = True
        for idx, raw in enumerate(body.splitlines(), start=1):
            for pat in (fn_decl, arrow_fn):
                m = pat.match(raw)
                if not m:
                    continue
                name = m.group(m.lastindex or 1)
                if not name_pat.search(name):
                    continue
                found_any_lab = True
                orig = sf.lines[idx - 1] if idx <= len(sf.lines) else raw
                findings.append(Finding(
                    check_id="lab.flag_not_statically_evaluable",
                    severity=Severity.ERROR,
                    message=f"'{name}' ist eine Funktion — der Bundler kann den Zweig nicht entfernen.",
                    file=sf.rel, line=idx, evidence=snippet(orig),
                    fix="Als Konstante schreiben (`export const isLabEnabled = "
                        "import.meta.env.VITE_ENABLE_LAB !== 'false'`), damit "
                        "Tree-Shaking greift.",
                    guideline="CLAUDE.md § Grundsatz B",
                ))
    if not found_any_lab and not findings:
        return unmeasured("lab.flag_not_statically_evaluable", title,
                          "Kein Labor-Flag im Projekt gefunden — nichts zu messen.")
    return result_for("lab.flag_not_statically_evaluable", title, findings, units)


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


# ===========================================================================
# Secrets
# ===========================================================================

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
        # Name einen WERT zugewiesen bekommt. Belegt an SchnitzeljagdAI:
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


# ===========================================================================
# Gate-Hygiene: die Pipe-Falle
# ===========================================================================

@register(
    "gate.pipe_swallows_exit_status",
    "Exit-Status wird durch eine Pipe verfälscht",
    severity=Severity.ERROR,
    guideline="CLAUDE.md § Gates — 'Ein tail vor der Statusprüfung verschluckt die Gegenprobe'",
    safe_by_default=True,
    self_tests=[
        SelfTestCase(
            name="Pipe vor Statusprüfung",
            files={"run.sh": '#!/bin/bash\npython3 gate.py 2>&1 | head -3\necho "EXIT: $?"\n'},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Status aus Variable",
            files={"run.sh": '#!/bin/bash\nout=$(python3 gate.py 2>&1)\nstatus=$?\necho "$out" | head -3\n'},
            expect=Status.PASS,
        ),
    ],
)
def check_pipe_exit(ctx: Context) -> CheckResult:
    """Der Status einer Pipeline ist der des LETZTEN Glieds.

    Belegt am 13.09.2026: drei Sabotage-Läufe meldeten alle EXIT: 0, auch die
    mit sichtbarem FEHLER — der Status war der von `head`.

    Warnzeichen laut Guideline: in einer Prüfzeile stehen `|` und `$?` beide.
    """
    title = "Exit-Status wird durch eine Pipe verfälscht"
    findings: list[Finding] = []
    units = 0
    swallowing = re.compile(r"\|\s*(head|tail|grep|awk|sed|cut|sort|uniq|jq|tee|wc)\b")
    for sf in ctx.all_files():
        base = os.path.basename(sf.rel)
        if sf.ext not in (".sh", ".bash", ".zsh") and not base.endswith(("Makefile", "makefile")):
            if sf.ext not in (".yml", ".yaml") or "workflow" not in sf.rel.lower():
                continue
        units += 1
        lines = sf.lines
        for idx, raw in enumerate(lines, start=1):
            code = raw.split("#", 1)[0]
            if "pipefail" in raw:
                continue
            # Fall 1: | und $? in derselben Zeile
            if swallowing.search(code) and "$?" in code:
                findings.append(Finding(
                    check_id="gate.pipe_swallows_exit_status",
                    severity=Severity.ERROR,
                    message="Pipe und $? in derselben Zeile — $? ist der Status des letzten Glieds.",
                    file=sf.rel, line=idx, evidence=snippet(raw),
                    fix="Ausgabe in eine Variable, Status sofort danach lesen, "
                        "dann erst filtern.",
                    guideline="CLAUDE.md § Gates",
                ))
                continue
            # Fall 2: gepipete Zeile, direkt danach wird $? gelesen
            if swallowing.search(code) and idx < len(lines):
                nxt = lines[idx].split("#", 1)[0]
                if "$?" in nxt:
                    findings.append(Finding(
                        check_id="gate.pipe_swallows_exit_status",
                        severity=Severity.ERROR,
                        message="$? unmittelbar nach einer Pipe gelesen — "
                                "das ist der Status des Filters, nicht des Gates.",
                        file=sf.rel, line=idx + 1, evidence=snippet(nxt),
                        fix="Ausgabe in eine Variable, Status sofort danach, "
                            "dann filtern. Oder `set -o pipefail` setzen.",
                        guideline="CLAUDE.md § Gates",
                    ))
    if units == 0:
        return unmeasured("gate.pipe_swallows_exit_status", title,
                          "Keine Shell-Skripte, Makefiles oder Workflows gefunden.")
    return result_for("gate.pipe_swallows_exit_status", title, findings, units,
                      "Skripte")


@register(
    "gate.runner_accepts_zero_tests",
    "Test-Runner wertet 'null Tests gefunden' nicht als Fehler",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Gates — \"'Null Tests gefunden' ist rot, nicht grün\"",
    self_tests=[
        SelfTestCase(
            name="nur Exit-Code",
            files={"run_tests.sh": "#!/bin/bash\npytest tests/\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Testzahl geprueft",
            files={"run_tests.sh": "#!/bin/bash\nout=$(pytest tests/)\nif echo \"$out\" | grep -q 'no tests ran'; then\n  echo 'nicht gemessen'; exit 2\nfi\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_zero_tests(ctx: Context) -> CheckResult:
    """Jeder Sammel-Runner braucht einen dritten Ausgang. Ein Runner, der nur
    den Exit-Code liest, verbucht einen Abbruch als Erfolg."""
    title = "Test-Runner wertet 'null Tests gefunden' nicht als Fehler"
    runners: list[tuple[str, int, str]] = []
    test_cmd = re.compile(
        r"\b(pytest|deno\s+test|npm\s+(run\s+)?test|jest|vitest|swift\s+test"
        r"|dotnet\s+test|go\s+test|cargo\s+test|gdunit|gut)\b"
    )
    for sf in ctx.all_files():
        base = os.path.basename(sf.rel)
        is_runner = (
            sf.ext in (".sh", ".bash", ".zsh")
            or base in ("Makefile", "makefile")
            or (sf.ext in (".yml", ".yaml") and "workflow" in sf.rel.lower())
        )
        if not is_runner:
            continue
        for idx, raw in enumerate(sf.lines, start=1):
            if test_cmd.search(raw) and not raw.strip().startswith("#"):
                runners.append((sf.rel, idx, raw.strip()))
    if not runners:
        return unmeasured("gate.runner_accepts_zero_tests", title,
                          "Kein Test-Runner-Aufruf in Skripten/Workflows gefunden.")

    guard = re.compile(
        r"(?i)(0\s+(tests?|passed|collected|Dateien|gates?)"
        r"|no\s+tests?\s+(ran|found|collected)"
        r"|null\s+(tests?|gates?)"
        r"|keine\s+(tests?|gates?)"
        r"|collected\s+0"
        r"|test_count|tests_run|--?fail-?under|\bcount\b\s*[-=]eq\s*0"
        r"|nicht\s+gemessen|unmeasured)"
    )
    findings: list[Finding] = []
    for rel, line, evidence in runners:
        sf = next((f for f in ctx.all_files() if f.rel == rel), None)
        if sf and guard.search(sf.text):
            continue
        findings.append(Finding(
            check_id="gate.runner_accepts_zero_tests",
            severity=Severity.WARNING,
            message="Runner liest nur den Exit-Code — 'null Tests' sieht aus wie Erfolg.",
            file=rel, line=line, evidence=snippet(evidence),
            fix="Testzahl aus der Ausgabe lesen und 0 ausdrücklich als Fehler "
                "werten. Drei Ausgänge: bestanden / durchgefallen / nicht gelaufen.",
            guideline="CLAUDE.md § Gates",
        ))
    return result_for("gate.runner_accepts_zero_tests", title, findings,
                      len(runners), "Runner-Aufrufe")


@register(
    "gate.reads_from_gitignored_artifact",
    "Gate liest aus einem Verzeichnis, das in .gitignore steht",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § 'Ein Gate, das aus einem Artefakt liest, prüft den Stand des Artefakts'",
    self_tests=[
        SelfTestCase(
            name="Gate liest ignoriertes Artefakt",
            files={".gitignore": ".build/\n", "gates/check_x.mjs": "import { render } from '../.build/renderer.js';\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Gate liest die Quelle",
            files={".gitignore": ".build/\n", "gates/check_x.mjs": "import { render } from '../src/renderer.ts';\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_gate_artifact(ctx: Context) -> CheckResult:
    """Auf einem frischen Checkout existiert das Artefakt gar nicht — dann ist
    'nicht gemessen' der einzige ehrliche Ausgang."""
    title = "Gate liest aus einem Verzeichnis, das in .gitignore steht"
    gitignore = os.path.join(ctx.root, ".gitignore")
    if not os.path.isfile(gitignore):
        return unmeasured("gate.reads_from_gitignored_artifact", title,
                          "Keine .gitignore vorhanden.")
    try:
        with open(gitignore, "r", encoding="utf-8", errors="replace") as fh:
            ignored = [
                ln.strip().strip("/") for ln in fh
                if ln.strip() and not ln.strip().startswith("#")
                and not ln.strip().startswith("!")
            ]
    except OSError:
        return unmeasured("gate.reads_from_gitignored_artifact", title,
                          ".gitignore nicht lesbar.")
    ignored = [i for i in ignored if i and "*" not in i and "." != i and len(i) > 1]
    if not ignored:
        return unmeasured("gate.reads_from_gitignored_artifact", title,
                          "Keine konkreten Verzeichnisse in .gitignore.")

    gate_files = [
        # Hier ist die Gate-Datei der Prüfgegenstand — also ausdrücklich
        # die Fassung, die Regeldefinitionen einschließt.
        sf for sf in ctx.all_files()
        if re.search(r"(gate|check|verify|pruef|prüf|audit)", sf.rel, re.IGNORECASE)
        and sf.ext in (".py", ".js", ".mjs", ".ts", ".sh")
    ]
    if not gate_files:
        return unmeasured("gate.reads_from_gitignored_artifact", title,
                          "Keine Gate-/Prüfskripte im Projekt gefunden.")
    findings: list[Finding] = []
    for sf in gate_files:
        body = strip_comments(sf.text, sf.ext)
        for entry in ignored:
            pat = re.compile(r"[\"'`(\s/]" + re.escape(entry) + r"/")
            for m in pat.finditer(body):
                line_no = body.count("\n", 0, m.start()) + 1
                raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
                findings.append(Finding(
                    check_id="gate.reads_from_gitignored_artifact",
                    severity=Severity.WARNING,
                    message=f"Gate greift auf '{entry}/' zu, das in .gitignore steht.",
                    file=sf.rel, line=line_no, evidence=snippet(raw),
                    fix="Den Bau-Schritt in den Runner legen, unmittelbar vor das "
                        "Gate. Ein Befehl in der README ist Text zum Lesen, kein "
                        "Schritt zum Durchlaufen.",
                    guideline="CLAUDE.md § Gates",
                ))
                break
    return result_for("gate.reads_from_gitignored_artifact", title, findings,
                      len(gate_files), "Gate-Skripte")


@register(
    "quality.display_text_as_anchor",
    "Position/Logik hängt an einem Anzeigetext statt an einem Bezeichner",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § 'Ein Anzeigetext ist nie ein Anker'",
    self_tests=[
        SelfTestCase(
            name="Anker auf Anzeigetext",
            files={"gate.ts": 'const pos = src.indexOf("Storyboard generieren");\n'},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Anker auf Bezeichner",
            files={"gate.ts": 'const pos = src.indexOf("data-testid=\"generate\"");\n'},
            expect=Status.PASS,
        ),
    ],
)
def check_display_anchor(ctx: Context) -> CheckResult:
    """indexOf gegen einen sichtbaren String misst die Formulierung mit — beim
    nächsten Wording-Fix liefert es -1 und jeder Größenvergleich kippt still."""
    title = "Position/Logik hängt an einem Anzeigetext statt an einem Bezeichner"
    pat = re.compile(
        r"\.(indexOf|lastIndexOf|search|find|firstIndex\s*\(\s*of:)\s*\(\s*"
        r"[\"']([^\"']{8,})[\"']"
    )
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(*SOURCE_EXTS):
        units += 1
        for line_no, m, raw in iter_matches(sf, pat):
            needle = m.group(2)
            # Ein Bezeichner ist kein Anzeigetext: keine Leerzeichen, oder
            # erkennbar technisch (Punkt-Pfad, camelCase ohne Leerzeichen).
            if " " not in needle:
                continue
            if not re.search(r"[A-Za-zÄÖÜäöüß]{3,}\s+[A-Za-zÄÖÜäöüß]{3,}", needle):
                continue
            findings.append(Finding(
                check_id="quality.display_text_as_anchor",
                severity=Severity.WARNING,
                message=f"Suche gegen Anzeigetext \"{snippet(needle, 40)}\".",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Gegen den stabilen Bezeichner ankern (Katalogschlüssel, "
                    "testid, Funktionsname) und vor jedem Positionsvergleich die "
                    "Existenz des Ankers prüfen.",
                guideline="CLAUDE.md § Anker",
            ))
    return result_for("quality.display_text_as_anchor", title, findings, units)


@register(
    "quality.assistant_trace",
    "Spur eines KI-Assistenten im Quelltext",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Kommunikationsstil — keine Claude-Erwähnungen in Code/Git",
    self_tests=[
        SelfTestCase(
            name="Generierungshinweis im Kommentar",
            files={"src/a.ts": "// Generated with Claude Code\nexport const a = 1;\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Legitime API-Nutzung",
            files={"src/a.ts": 'import Anthropic from "@anthropic-ai/sdk";\nconst c = new Anthropic();\n'},
            expect=Status.PASS,
        ),
    ],
)
def check_assistant_traces(ctx: Context) -> CheckResult:
    """Unterscheidet SPUR von NUTZUNG.

    Ein Import des Anthropic-SDK oder ein Modellname in einem API-Aufruf ist
    legitimer Code, keine Spur — wer schon das Lesen verbietet, verbietet auch
    legitimes Weiterreichen.
    """
    title = "Spur eines KI-Assistenten im Quelltext"
    trace = re.compile(
        r"(?i)("
        r"generated\s+(with|by)\s+(claude|chatgpt|codex|copilot|gemini|cursor)"
        r"|(erstellt|generiert)\s+(mit|von)\s+(claude|chatgpt|codex|copilot|gemini)"
        r"|co-?authored-?by:\s*(claude|chatgpt|codex|copilot)"
        r"|🤖\s*generated"
        r"|\b(claude|chatgpt|codex)\s+(hat|sagt|meint|schlägt vor|suggests|says)"
        r"|as\s+an\s+ai\s+(language\s+)?model"
        r"|\bTODO\s*[:\-]?\s*(claude|chatgpt|codex)"
        r")"
    )
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(*SOURCE_EXTS, *MARKUP_EXTS, ".css", ".scss", ".sh"):
        units += 1
        for idx, raw in enumerate(sf.lines, start=1):
            m = trace.search(raw)
            if not m:
                continue
            findings.append(Finding(
                check_id="quality.assistant_trace",
                severity=Severity.WARNING,
                message="Hinweis auf einen KI-Assistenten im Quelltext.",
                file=sf.rel, line=idx, evidence=snippet(raw),
                fix="Zeile neutral formulieren oder entfernen.",
                guideline="CLAUDE.md § Kommunikationsstil",
            ))
    return result_for("quality.assistant_trace", title, findings, units)


@register(
    "protocol.version_bump_without_fallback",
    "Enum eines veröffentlichten Formats ohne Unknown-Fallback",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Grundsatz E",
    self_tests=[
        SelfTestCase(
            name="Enum ohne Fallback",
            files={"src/api/types.ts": 'import { z } from "zod";\nexport enum Kind { Text, Image }\nexport const S = z.enum(["a"]);\n'},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Enum mit Unknown",
            files={"src/api/types.ts": 'import { z } from "zod";\nexport enum Kind { Text, Image, Unknown }\nexport const S = z.enum(["a"]);\n'},
            expect=Status.PASS,
        ),
    ],
)
def check_protocol_enum(ctx: Context) -> CheckResult:
    """Ein alter Client muss einen neuen Enum-Wert ignorieren können, statt
    daran zu sterben. Gemessen wird an Enums, die von Serialisierung erreicht
    werden — nicht an jedem Enum im Projekt."""
    title = "Enum eines veröffentlichten Formats ohne Unknown-Fallback"
    serde_hint = re.compile(
        r"(?i)(Codable|Decodable|@Serializable|serde|JsonConverter|"
        r"JSONDecoder|json\.loads|JSON\.parse|z\.enum|Protobuf|from_json|to_json)"
    )
    enum_decl = re.compile(
        r"^\s*(public\s+|export\s+|internal\s+)?enum\s+(\w+)", re.MULTILINE
    )
    fallback = re.compile(r"(?i)\b(unknown|unrecognized|other|default|fallback|future)\b")
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(".swift", ".ts", ".kt", ".cs", ".rs"):
        if not serde_hint.search(sf.text):
            continue
        body = strip_comments(sf.text, sf.ext)
        for m in enum_decl.finditer(body):
            units += 1
            start = m.end()
            depth = 0
            end = start
            for i in range(start, min(len(body), start + 4000)):
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            block = body[start:end]
            if fallback.search(block):
                continue
            line_no = body.count("\n", 0, m.start()) + 1
            findings.append(Finding(
                check_id="protocol.version_bump_without_fallback",
                severity=Severity.WARNING,
                message=f"Enum '{m.group(2)}' wird serialisiert, hat aber keinen "
                        "Unknown-Fallback.",
                file=sf.rel, line=line_no, evidence=snippet(m.group(0)),
                fix="Einen Unknown-Fall ergänzen, damit ein alter Client einen "
                    "neuen Wert ignoriert statt daran zu sterben.",
                guideline="CLAUDE.md § Grundsatz E",
            ))
    if units == 0:
        return unmeasured("protocol.version_bump_without_fallback", title,
                          "Keine serialisierten Enums gefunden.")
    return result_for("protocol.version_bump_without_fallback", title, findings,
                      units, "Enums")


@register(
    "protocol.ui_named_runtime_term",
    "Geteilter Laufzeitbegriff ist nach der Oberfläche benannt",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Grundsatz E — Namensregel",
    self_tests=[
        SelfTestCase(
            name="Feld nach Oberflaeche benannt",
            files={"src/api/dto.ts": 'export interface Msg {\n  sidebarState: string;\n}\n'},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Feld nach der Sache benannt",
            files={"src/api/dto.ts": 'export interface Msg {\n  workspaceState: string;\n}\n'},
            expect=Status.PASS,
        ),
    ],
)
def check_ui_naming(ctx: Context) -> CheckResult:
    """Ein zweiter Client hat diese Oberfläche nicht — der Name lügt ab dem Tag,
    an dem er existiert."""
    title = "Geteilter Laufzeitbegriff ist nach der Oberfläche benannt"
    ui_words = r"(sidebar|widget|card|row|panel|tooltip|popup|modal|badge|tile|drawer)"
    # Gemessen wird am Protokoll-/API-Bereich, nicht an Komponenten.
    api_hint = re.compile(r"(?i)(api|rpc|proto|schema|dto|payload|message|event|command|server)")
    field_decl = re.compile(
        r"(?i)^\s*(\"?\w*" + ui_words + r"\w*\"?)\s*[:?]\s*\w", re.MULTILINE
    )
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(".ts", ".swift", ".kt", ".cs", ".proto", ".rs", ".py"):
        if not api_hint.search(sf.rel):
            continue
        units += 1
        body = strip_comments(sf.text, sf.ext)
        for m in field_decl.finditer(body):
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="protocol.ui_named_runtime_term",
                severity=Severity.WARNING,
                message=f"Feld '{m.group(1).strip()}' in einer Schnittstellendatei "
                        "ist nach einer Oberfläche benannt.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Nach der Sache benennen, nicht nach der Anzeige, die sie "
                    "gerade darstellt.",
                guideline="CLAUDE.md § Grundsatz E",
            ))
    if units == 0:
        return unmeasured("protocol.ui_named_runtime_term", title,
                          "Keine Schnittstellendateien (api/proto/dto/...) gefunden.")
    return result_for("protocol.ui_named_runtime_term", title, findings, units)


@register(
    "quality.duplicate_literal_list",
    "Dieselbe Werteliste steht an mehreren Stellen (zweite Liste)",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § 'Die zweite Liste ist fast nie die letzte'",
    self_tests=[
        SelfTestCase(
            name="Liste doppelt",
            files={"src/a.ts": 'const MODES = ["easy", "normal", "hard", "insane"];\n',
                   "src/b.ts": 'const LEVELS = ["easy", "normal", "hard", "insane"];\n'},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="eine Quelle",
            files={"src/a.ts": 'export const MODES = ["easy", "normal", "hard", "insane"];\n',
                   "src/b.ts": 'import { MODES } from "./a";\nconst LEVELS = MODES;\n'},
            expect=Status.PASS,
        ),
    ],
)
def check_duplicate_lists(ctx: Context) -> CheckResult:
    """Sucht nach den WERTEN, nicht nach dem Variablennamen — die versteckte
    Kopie heißt meist anders."""
    title = "Dieselbe Werteliste steht an mehreren Stellen (zweite Liste)"
    array_lit = re.compile(r"\[\s*((?:[\"'][^\"'\n]{2,40}[\"']\s*,\s*){2,}[\"'][^\"'\n]{2,40}[\"']\s*,?)\s*\]")
    seen: dict[str, list[tuple[str, int, str]]] = {}
    units = 0
    for sf in ctx.files(*SOURCE_EXTS):
        units += 1
        body = strip_comments(sf.text, sf.ext)
        for m in array_lit.finditer(body):
            values = tuple(sorted(re.findall(r"[\"']([^\"']+)[\"']", m.group(1))))
            if len(values) < 3:
                continue
            key = "|".join(values)
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            seen.setdefault(key, []).append((sf.rel, line_no, snippet(raw)))
    findings: list[Finding] = []
    for key, places in seen.items():
        uniq = {(p[0], p[1]) for p in places}
        if len(uniq) < 2:
            continue
        where = ", ".join(f"{r}:{l}" for r, l in sorted(uniq))
        first = sorted(uniq)[0]
        findings.append(Finding(
            check_id="quality.duplicate_literal_list",
            severity=Severity.WARNING,
            message=f"Identische Werteliste ({len(key.split('|'))} Einträge) an "
                    f"{len(uniq)} Stellen: {where}",
            file=first[0], line=first[1], evidence=snippet(key.replace("|", ", ")),
            fix="Zusammenlegen — eine Quelle, aus der sich Ansichten ableiten. "
                "Und nach der dritten Kopie suchen, nach den Werten, nicht nach "
                "dem Variablennamen.",
            guideline="CLAUDE.md § Konsistenz",
        ))
    return result_for("quality.duplicate_literal_list", title, findings, units)
