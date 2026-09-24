"""Apple: SwiftUI navigation, typography and container traps.

Split from the original checks/apple.py; background and
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

from ._common import PLATFORM


# ===========================================================================
# SwiftUI Multiplattform
# ===========================================================================

@register(
    "apple.navigationdestination_not_at_root",
    ".navigationDestination steht nicht am NavigationStack-Root",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="swiftui_multiplatform_guideline.md § 3",
    self_tests=[
        SelfTestCase(
            name="Ziel ohne Stack",
            files={"App/Sub.swift": "import SwiftUI\nstruct Sub: View { var body: some View { List {}.navigationDestination(for: Int.self) { _ in Text(\"d\") } } }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Ziel am Stack-Root",
            files={"App/Root.swift": "import SwiftUI\nstruct Root: View { var body: some View { NavigationStack { List {}.navigationDestination(for: Int.self) { _ in Text(\"d\") } } } }\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_navdest(ctx: Context) -> CheckResult:
    """Laut Guideline CRITICAL: ein .navigationDestination in einer Unteransicht
    wird auf macOS nicht gefunden und der Push passiert nicht."""
    title = ".navigationDestination steht nicht am NavigationStack-Root"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.navigationdestination_not_at_root", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    findings: list[Finding] = []
    measured = 0
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        if ".navigationDestination" not in body:
            continue
        measured += 1
        has_stack = "NavigationStack" in body or "NavigationSplitView" in body
        for m in re.finditer(r"\.navigationDestination", body):
            line_no = body.count("\n", 0, m.start()) + 1
            if has_stack:
                continue
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="apple.navigationdestination_not_at_root",
                severity=Severity.ERROR,
                message=".navigationDestination ohne NavigationStack in derselben Datei.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="An den NavigationStack-Root verschieben — in einer "
                    "Unteransicht findet macOS das Ziel nicht.",
                guideline="swiftui_multiplatform_guideline.md § 3",
            ))
    if measured == 0:
        return unmeasured("apple.navigationdestination_not_at_root", title,
                          "Kein .navigationDestination im Projekt.", PLATFORM)
    return result_for("apple.navigationdestination_not_at_root", title, findings,
                      measured, "Swift-Dateien mit navigationDestination", PLATFORM)


@register(
    "apple.system_font_relative_to",
    "Font.system mit nicht existentem relativeTo",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="swiftui_multiplatform_guideline.md",
    # Hart, auch ohne Profil: das ist kein Stilurteil, sondern ein
    # Compilerfehler — der Code uebersetzt nachweislich nicht. Ein
    # falsch-positiver Fall ist ausgeschlossen, weil die API nicht existiert.
    safe_by_default=True,
    self_tests=[
        SelfTestCase(
            name="system mit relativeTo bricht den Build",
            files={"App/V.swift": "import SwiftUI\nstruct V: View { var body: some View { Image(systemName: \"x\").font(.system(size: 48, relativeTo: .largeTitle)) } }\n"},
            expect=Status.FAIL,
            expect_finding_contains="relativeTo",
        ),
        SelfTestCase(
            name="system ueber mehrere Zeilen",
            files={"App/V.swift": "import SwiftUI\nstruct V: View { var body: some View { Text(\"x\").font(\n  .system(\n    size: 20,\n    relativeTo: .body\n  )\n) } }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="custom mit relativeTo ist gueltig",
            files={"App/V.swift": "import SwiftUI\nstruct V: View { var body: some View { Text(\"x\").font(.custom(\"Inter\", size: 20, relativeTo: .body)) } }\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="system ohne relativeTo ist gueltig",
            files={"App/V.swift": "import SwiftUI\nstruct V: View { var body: some View { Text(\"x\").font(.system(size: 20, weight: .bold)) } }\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="beide Formen in einer Datei",
            files={"App/V.swift": "import SwiftUI\nstruct V: View { var body: some View {\n  Text(\"a\").font(.custom(\"Inter\", size: 12, relativeTo: .body))\n  Text(\"b\").font(.system(size: 12, relativeTo: .body))\n} }\n"},
            expect=Status.FAIL,
        ),
    ],
)
def check_system_font_relative_to(ctx: Context) -> CheckResult:
    """'Font.system(size:relativeTo:)' gibt es nicht — der Compiler meldet
    "Extra argument 'relativeTo' in call".

    'relativeTo:' traegt nur 'Font.custom(_:size:relativeTo:)'. Fuer System-
    Schriften ist die Skalierung ein offener Feature-Request (FB9772279), kein
    vorhandener Parameter.

    Warum das ein eigener Check ist und nicht der Dynamic-Type-Check: der
    Compiler bricht bei der ERSTEN fehlerhaften Stelle je Datei ab, meldet also
    nie die uebrigen. Und weil der falsche Aufruf den Basistyp des Arguments
    unbestimmt laesst, kommt als Folgefehler ein irrefuehrendes "Cannot infer
    contextual base in reference to member 'largeTitle'" dazu — zwei Meldungen
    fuer eine Ursache. Gemessen wird deshalb die Eigenschaft ueber alle
    Fundstellen hinweg, nicht die eine, die Xcode gerade zeigt.
    """
    title = "Font.system mit nicht existentem relativeTo"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.system_font_relative_to", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)

    findings: list[Finding] = []
    for sf in swift:
        text = strip_comments(sf.text, sf.ext)
        # Auf die Verwendung ankern, nicht auf den Namen: gesucht ist der
        # Aufruf '.system(' und dann sein EIGENER Argumentbereich bis zur
        # passenden schliessenden Klammer. Ein Suchfenster fester Zeichenzahl
        # waere eine Vermutung ueber Formatierung — '.custom(...)' in der
        # Zeile davor oder danach wuerde sonst mitgelesen.
        for m in re.finditer(r"\.system\s*\(", text):
            depth, i, end = 0, m.end() - 1, None
            while i < len(text):
                c = text[i]
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
                i += 1
            if end is None:
                continue  # unbalanciert — keine Aussage moeglich
            args = text[m.end():end]
            # Verschachtelte Aufrufe ausblenden, damit ein '.custom(..,
            # relativeTo:)' INNERHALB der system-Argumente nicht faelschlich
            # als dessen eigenes Argument zaehlt.
            flat, d = [], 0
            for c in args:
                if c == "(":
                    d += 1
                elif c == ")":
                    d -= 1
                elif d == 0:
                    flat.append(c)
            if "relativeTo:" not in "".join(flat):
                continue
            line_no = text.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if 0 < line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="apple.system_font_relative_to", severity=Severity.ERROR,
                message="Font.system(size:relativeTo:) existiert nicht — "
                        "Compiler: \"Extra argument 'relativeTo' in call\".",
                file=sf.rel, line=line_no, evidence=snippet(raw.strip()),
                fix="relativeTo entfernen und einen Text-Style nehmen "
                    "(.largeTitle, .title2), oder fuer eine eigene Schrift auf "
                    "'.custom(_:size:relativeTo:)' wechseln. Fuer skalierende "
                    "SF-Symbols: '.font(.largeTitle)' plus '.imageScale(.large)'.",
            ))
    return result_for("apple.system_font_relative_to", title, findings,
                      len(swift), "Swift-Dateien", PLATFORM)


@register(
    "apple.hardcoded_font_size",
    "Feste Schriftgröße statt Text-Style",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="swiftui_multiplatform_guideline.md / IOS_DEBUGGING_GUIDELINES.md",
    self_tests=[
        SelfTestCase(
            name="feste Punktgroesse",
            files={"App/V.swift": "import SwiftUI\nstruct V: View { var body: some View { Text(\"x\").font(.system(size: 13)) } }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Text-Style statt Punktgroesse",
            files={"App/V.swift": "import SwiftUI\nstruct V: View { var body: some View { Text(\"x\").font(.body) } }\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="custom mit relativeTo skaliert mit",
            files={"App/V.swift": "import SwiftUI\nstruct V: View { var body: some View { Text(\"x\").font(.custom(\"Inter\", size: 13, relativeTo: .body)) } }\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_font_sizes(ctx: Context) -> CheckResult:
    """Eine feste Punktgröße ignoriert Dynamic Type — die Anzeige skaliert für
    sehbehinderte Nutzer nicht mit."""
    title = "Feste Schriftgröße statt Text-Style"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.hardcoded_font_size", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    pat = re.compile(r"\.font\(\s*\.system\(\s*size:\s*(\d+)")
    findings: list[Finding] = []
    for sf in swift:
        for line_no, m, raw in iter_matches(sf, pat):
            if "relativeTo:" in raw and ".custom(" in raw:
                continue  # .custom(_:size:relativeTo:) skaliert mit, ist richtig
            findings.append(Finding(
                check_id="apple.hardcoded_font_size", severity=Severity.WARNING,
                message=f"Feste Schriftgröße {m.group(1)}pt ohne relativeTo.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Text-Style verwenden (.body, .headline), oder fuer eine "
                    "eigene Schrift '.custom(_:size:relativeTo:)'. Es gibt "
                    "KEIN '.system(size:relativeTo:)' — siehe "
                    "apple.system_font_relative_to.",
            ))
    return result_for("apple.hardcoded_font_size", title, findings, len(swift),
                      "Swift-Dateien", PLATFORM)


# ===========================================================================
# macOS: NavigationSplitView Detail-Bereich ohne .navigationTitle
# ===========================================================================

# In macOS SwiftUI reserviert eine NavigationSplitView für die Detail-Pane
# automatisch einen leeren grauen Toolbar-/Header-Platzhalter, wenn an der
# Detailansicht kein .navigationTitle(...) gebunden ist. Dieser leere Balken
# überlagert den oberen Inhalt (Forms, ScrollViews, Eingabefelder).
# Belegt: reale macOS-App, 19.09.2026 — Ein grauer Balken verdeckte Textfelder im Formular,
# bis .navigationTitle(...) an der Detailansicht gesetzt wurde.

@register(
    "apple.splitview_detail_without_navigation_title",
    "NavigationSplitView Detail-Ansicht ohne .navigationTitle erzeugt grauen Header-Überlagerungsstreifen",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="IOS_DEBUGGING_GUIDELINES.md § SwiftUI-Container-Fallen",
    self_tests=[
        SelfTestCase(
            name="Detail ohne navigationTitle",
            files={"Sources/App/SettingsView.swift":
                   "import SwiftUI\n"
                   "struct SettingsView: View {\n"
                   "  var body: some View {\n"
                   "    NavigationSplitView {\n"
                   "      Text(\"Sidebar\")\n"
                   "    } detail: {\n"
                   "      Form { Text(\"Inhalt\") }\n"
                   "    }\n"
                   "  }\n"
                   "}\n"},
            expect=Status.FAIL,
            expect_finding_contains="NavigationSplitView",
        ),
        SelfTestCase(
            name="Detail mit navigationTitle",
            files={"Sources/App/SettingsView.swift":
                   "import SwiftUI\n"
                   "struct SettingsView: View {\n"
                   "  var body: some View {\n"
                   "    NavigationSplitView {\n"
                   "      Text(\"Sidebar\")\n"
                   "    } detail: {\n"
                   "      Form { Text(\"Inhalt\") }\n"
                   "        .navigationTitle(\"Detail\")\n"
                   "    }\n"
                   "  }\n"
                   "}\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_splitview_detail_title(ctx: Context) -> CheckResult:
    title = "NavigationSplitView Detail-Ansicht ohne .navigationTitle erzeugt grauen Header-Überlagerungsstreifen"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.splitview_detail_without_navigation_title", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)

    callers = 0
    findings: list[Finding] = []
    pat = re.compile(r"\bNavigationSplitView\b\s*\{")
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        if not pat.search(body):
            continue
        # Suche detail: { ... }
        for m in re.finditer(r"\bdetail\s*:\s*\{", body):
            callers += 1
            # Finde zugehörige schließende Klammer
            depth, i = 1, m.end()
            while i < len(body) and depth:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                i += 1
            block = body[m.end(): i - 1]
            if ".navigationTitle(" not in block:
                line_no = body.count("\n", 0, m.start()) + 1
                raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
                findings.append(Finding(
                    check_id="apple.splitview_detail_without_navigation_title",
                    severity=Severity.WARNING,
                    message="NavigationSplitView Detail-Ansicht ohne .navigationTitle(...): "
                            "macOS reserviert einen leeren grauen Toolbar-Header, der "
                            "den oberen Inhalt (Text/Formulare) überlagert.",
                    file=sf.rel, line=line_no, evidence=snippet(raw),
                    fix="An der Detail-View '.navigationTitle(...)' setzen, damit macOS "
                        "die Toolbar-Integration sauber abschließt.",
                    guideline="IOS_DEBUGGING_GUIDELINES.md § SwiftUI-Container-Fallen",
                ))
    if not callers:
        return unmeasured("apple.splitview_detail_without_navigation_title", title,
                          "Keine NavigationSplitView mit detail:-Block gefunden.", PLATFORM)
    return result_for("apple.splitview_detail_without_navigation_title", title, findings,
                      callers, "NavigationSplitView-Detail-Blöcke", PLATFORM)
