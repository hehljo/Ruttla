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


_CATALOG_PATH = re.compile(
    r"(^|/)(locales?|i18n|lang|translations?|strings)(/|\.|$)", re.IGNORECASE)
# Apple-Stringskatalog: "schluessel" = "Wert"; — je Sprache in <lang>.lproj/.
_APPLE_STRINGS_KEY = re.compile(r'^\s*"((?:[^"\\\n]|\\.)+)"\s*=\s*"', re.MULTILINE)


def _is_apple_catalog(sf) -> bool:
    return sf.ext == ".strings" and ".lproj/" in sf.rel


def _catalog_files(ctx: Context) -> list:
    return [
        sf for sf in ctx.all_files()
        if (sf.ext in (".json", ".ts", ".js", ".csv", ".po")
            and _CATALOG_PATH.search(sf.rel))
        or _is_apple_catalog(sf)
    ]


def _apple_keys(sf) -> list[tuple[str, int]]:
    return [(m.group(1), sf.line_of(m.start()))
            for m in _APPLE_STRINGS_KEY.finditer(sf.text)]


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
    catalogs = _catalog_files(ctx)
    if not catalogs:
        return unmeasured("i18n.orphan_catalog_keys", title,
                          "Kein Textkatalog gefunden (locales/, i18n/, strings.*).")

    keys: dict[str, tuple[str, int]] = {}
    for sf in catalogs:
        if _is_apple_catalog(sf):
            for key, line in _apple_keys(sf):
                keys.setdefault(key, (sf.rel, line))
            continue
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
        ),        SelfTestCase(
            name="SwiftUI-Literal ohne Katalogschluessel",
            files={
                "App/en.lproj/Localizable.strings": '"tab.home" = "Home";\n',
                "App/HomeView.swift": 'struct H: View { var body: some View { Text("Continue watching now") } }\n',
            },
            expect=Status.FAIL,
            expect_finding_contains="Continue watching",
        ),
        SelfTestCase(
            name="SwiftUI-Schluessel, Kuerzel, verbatim und Preview",
            files={
                "App/en.lproj/Localizable.strings": '"tab.home" = "Home";\n',
                "App/HomeView.swift": 'struct H: View { var body: some View { VStack {\n'
                    '  Text("tab.home"); Text("HDR"); Text(verbatim: "Plex Media Server")\n'
                    '  Text(L10n.home); Text("\\(count) items") } } }\n'
                    '#Preview { Text("Preview only text") }\n',
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
    has_catalog = any(_CATALOG_PATH.search(sf.rel) or _is_apple_catalog(sf)
                      for sf in ctx.all_files())
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

    # SwiftUI: ein String-Literal in Text/Button/Label/... ist ein
    # LocalizedStringKey. Er kommt nur dann aus dem Katalog, wenn der Katalog
    # genau diesen Schlüssel kennt — sonst zeigt die App das Literal selbst.
    apple_keys = {key for sf in ctx.all_files() if _is_apple_catalog(sf)
                  for key, _ in _apple_keys(sf)}
    swift_ui = re.compile(
        r"(?:\b(?:Text|Button|Label|Toggle|Section|Picker|TextField|SecureField"
        r"|Link|Menu|LabeledContent)|\.(?:navigationTitle|alert|confirmationDialog"
        r"|help|accessibilityLabel|accessibilityHint))"
        r'\s*\(\s*"((?:[^"\\\n]|\\.)*)"')
    for sf in ctx.files(".swift"):
        units += 1
        body = strip_comments(sf.text, sf.ext)
        # Vorschauen sind Entwicklerfläche, keine ausgelieferte Oberfläche.
        preview = re.search(r"^\s*#Preview\b|PreviewProvider\b", body, re.MULTILINE)
        end = preview.start() if preview else len(body)
        for m in swift_ui.finditer(body, 0, end):
            text = m.group(1)
            if text in apple_keys or "\\(" in text:
                continue
            words = re.findall(r"[A-Za-zÄÖÜäöüß]{2,}", text)
            if not words:
                continue
            # Ein einzelnes Kürzel (HDR, 4K, OK) ist kein Satz; ein einzelnes
            # Wort mit Kleinbuchstaben ("Settings") dagegen schon.
            if len(words) < 2 and (len(words[0]) < 4 or words[0].isupper()):
                continue
            line_no = body.count("\n", 0, m.start()) + 1
            findings.append(Finding(
                check_id="i18n.literal_in_markup",
                severity=Severity.WARNING,
                message=f"SwiftUI-Literal ohne Katalogschlüssel: \"{snippet(text, 60)}\"",
                file=sf.rel, line=line_no, evidence=snippet(text),
                fix="Schlüssel im Stringskatalog anlegen und über die "
                    "Katalogschicht beziehen; bewusst unübersetzte Werte als "
                    "Text(verbatim:) kennzeichnen.",
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


@register(
    "i18n.catalog_key_parity",
    "Sprachkataloge haben nicht dieselben Schlüssel",
    severity=Severity.WARNING,
    guideline="CLAUDE.md § Grundsatz C — 'Fehlender Schlüssel ist sichtbar, nicht still leer'",
    self_tests=[
        SelfTestCase(
            name="Schluessel fehlt in einer Sprache",
            files={
                "App/en.lproj/Localizable.strings": '"tab.home" = "Home";\n"tab.search" = "Search";\n',
                "App/de.lproj/Localizable.strings": '"tab.home" = "Start";\n',
            },
            expect=Status.FAIL,
            expect_finding_contains="tab.search",
        ),
        SelfTestCase(
            name="alle Sprachen deckungsgleich",
            files={
                "App/en.lproj/Localizable.strings": '"tab.home" = "Home";\n',
                "App/de.lproj/Localizable.strings": '/* Start */\n"tab.home" = "Start";\n',
                "App/de.lproj/InfoPlist.strings": '"CFBundleDisplayName" = "Acme";\n',
            },
            expect=Status.PASS,
        ),
    ],
)
def check_catalog_key_parity(ctx: Context) -> CheckResult:
    """Apple fällt bei einem fehlenden Schlüssel still auf den Schlüssel selbst
    zurück — der Nutzer liest dann `tab.search` statt eines Worts. Gemessen
    wird je Katalogdatei (gleicher Dateiname in mehreren `<lang>.lproj/`),
    dass jede Sprache die Vereinigung aller Schlüssel trägt.

    Eine Katalogdatei, die nur in EINER Sprache existiert (z. B.
    InfoPlist.strings), hat nichts zum Vergleichen und zählt nicht als
    geprüft — null verglichene Kataloge sind nicht gemessen, nicht bestanden.
    """
    title = "Sprachkataloge haben nicht dieselben Schlüssel"
    groups: dict[str, dict[str, dict[str, int]]] = {}
    for sf in ctx.all_files():
        if not _is_apple_catalog(sf):
            continue
        m = re.search(r"(?:^|/)([^/]+)\.lproj/(.+)$", sf.rel)
        if not m:
            continue
        name = m.group(2)
        groups.setdefault(name, {})[sf.rel] = dict(reversed(_apple_keys(sf)))
    compared = {name: langs for name, langs in groups.items() if len(langs) >= 2}
    if not compared:
        return unmeasured(
            "i18n.catalog_key_parity", title,
            "Keine Apple-Stringskataloge in mindestens zwei Sprachen gefunden "
            "(<lang>.lproj/<Name>.strings). JSON-Kataloge misst dieser Check "
            "noch nicht.")
    findings: list[Finding] = []
    units = 0
    for name, langs in sorted(compared.items()):
        union = set().union(*(set(k) for k in langs.values()))
        for rel, keys in sorted(langs.items()):
            units += 1
            for key in sorted(union - set(keys)):
                findings.append(Finding(
                    check_id="i18n.catalog_key_parity",
                    severity=Severity.WARNING,
                    message=f"Schlüssel '{key}' fehlt in {rel} (andere Sprachen "
                            f"von {name} haben ihn).",
                    file=rel,
                    fix="Übersetzung ergänzen. Apple zeigt sonst den rohen "
                        "Schlüssel an.",
                    guideline="CLAUDE.md § Grundsatz C",
                ))
    return result_for("i18n.catalog_key_parity", title, findings, units,
                      "Katalogdateien")
