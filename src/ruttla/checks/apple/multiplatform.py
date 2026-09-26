"""Apple: Typen, die nur unter einer Plattformbedingung existieren.

Belegt am 26.09.2026 (tvOS/iOS-Mediaplayer, ein Target für beide
Plattformen): ein umbrechendes Layout stand innerhalb des
`#if os(tvOS)`-Blocks einer tvOS-Filteransicht. Eine iOS-Ansicht benutzte
es ohne Bedingung. tvOS baute grün, der iPhone-Build brach mit fünfmal
`Cannot find 'FlowLayout' in scope` ab. Lokal fiel das nicht auf, weil nur
für das Apple TV gebaut wurde.
"""

from __future__ import annotations

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

from ._common import PLATFORM


# SUPPORTED_PLATFORMS-Werte -> Name in `os(...)`. Simulatoren zählen zur
# Geräteplattform, weil `os(...)` dort denselben Wert liefert.
_SDK_TO_OS = {
    "iphoneos": "iOS", "iphonesimulator": "iOS",
    "appletvos": "tvOS", "appletvsimulator": "tvOS",
    "macosx": "macOS",
    "xros": "visionOS", "xrsimulator": "visionOS",
    "watchos": "watchOS", "watchsimulator": "watchOS",
}
_OS_ALIASES = {"OSX": "macOS", "xrOS": "visionOS"}

_CONFIG_BLOCK = re.compile(r"isa\s*=\s*XCBuildConfiguration;.*?buildSettings\s*=\s*\{(.*?)\n\t*\};",
                           re.S)
_SUPPORTED = re.compile(r'SUPPORTED_PLATFORMS\s*=\s*"?([^";]+)"?;')
_CATALYST = re.compile(r"SUPPORTS_MACCATALYST\s*=\s*YES;")

_DECL = re.compile(
    r"^\s*(?:(?:@\w+(?:\([^)]*\))?|public|internal|private|fileprivate|open|final|"
    r"indirect|nonisolated)\s+)*(?:struct|class|enum|protocol|actor|typealias)\s+([A-Z]\w*)")
_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
_DIRECTIVE = re.compile(r"^\s*#(if|elseif|else|endif)\b(.*)$")


def _multi_platform_sets(pbx: str) -> set[str]:
    """Plattformen aller Build-Konfigurationen, die MEHR als eine Plattform
    tragen. Ein Projekt mit getrennten Einzel-Plattform-Targets (App +
    Watch-Erweiterung) kompiliert jede Datei nur für eine Plattform — dort
    ist eine Bedingung kein Befund."""
    out: set[str] = set()
    for block in _CONFIG_BLOCK.findall(pbx):
        plats: set[str] = set()
        m = _SUPPORTED.search(block)
        if m:
            plats = {_SDK_TO_OS[t] for t in m.group(1).split() if t in _SDK_TO_OS}
        if _CATALYST.search(block) and "iOS" in plats:
            plats.add("macCatalyst")
        if len(plats) > 1:
            out |= plats
    return out


# --- Auswertung von #if-Bedingungen, dreiwertig je Plattform ---------------
# True/False = sicher, None = hängt an etwas anderem (DEBUG, canImport, ...).

def _tokens(expr: str) -> list[str]:
    return re.findall(r"&&|\|\||!|\(|\)|\w+\s*\([^()]*\)|[\w.]+", expr)


def _eval(expr: str, plat: str) -> bool | None:
    toks = _tokens(expr)
    pos = 0

    def atom() -> bool | None:
        nonlocal pos
        if pos >= len(toks):
            return None
        tok = toks[pos]
        pos += 1
        if tok == "!":
            v = atom()
            return None if v is None else not v
        if tok == "(":
            v = disj()
            if pos < len(toks) and toks[pos] == ")":
                pos += 1
            return v
        m = re.fullmatch(r"os\s*\(\s*(\w+)\s*\)", tok)
        if m:
            name = _OS_ALIASES.get(m.group(1), m.group(1))
            effective = "iOS" if plat == "macCatalyst" else plat
            return name == effective
        m = re.fullmatch(r"targetEnvironment\s*\(\s*macCatalyst\s*\)", tok)
        if m:
            return plat == "macCatalyst"
        return None

    def conj() -> bool | None:
        nonlocal pos
        v = atom()
        while pos < len(toks) and toks[pos] == "&&":
            pos += 1
            w = atom()
            if v is False or w is False:
                v = False
            elif v is None or w is None:
                v = None
        return v

    def disj() -> bool | None:
        nonlocal pos
        v = conj()
        while pos < len(toks) and toks[pos] == "||":
            pos += 1
            w = conj()
            if v is True or w is True:
                v = True
            elif v is None or w is None:
                v = None
        return v

    return disj()


def _and(values: list[bool | None]) -> bool | None:
    if any(v is False for v in values):
        return False
    if any(v is None for v in values):
        return None
    return True


def _line_conditions(lines: list[str]) -> list[list[tuple[str, bool]]]:
    """Je Zeile die aktiven Bedingungen als (Ausdruck, muss_wahr_sein)."""
    stack: list[list[tuple[str, bool]]] = []   # je #if: Liste der Terme
    branches: list[list[str]] = []             # je #if: bisherige Zweigbedingungen
    out: list[list[tuple[str, bool]]] = []
    for raw in lines:
        m = _DIRECTIVE.match(raw)
        if m:
            kind, rest = m.group(1), m.group(2).strip()
            if kind == "if":
                branches.append([rest])
                stack.append([(rest, True)])
            elif kind == "elseif" and stack:
                prev = branches[-1]
                stack[-1] = [(c, False) for c in prev] + [(rest, True)]
                prev.append(rest)
            elif kind == "else" and stack:
                stack[-1] = [(c, False) for c in branches[-1]]
            elif kind == "endif" and stack:
                stack.pop()
                branches.pop()
            out.append([])
            continue
        out.append([t for frame in stack for t in frame])
    return out


def _compiled(conds: list[tuple[str, bool]], plat: str) -> bool | None:
    vals: list[bool | None] = []
    for expr, want in conds:
        v = _eval(expr, plat)
        vals.append(None if v is None else (v if want else not v))
    return _and(vals)


@register(
    "apple.platform_conditional_type_used_unguarded",
    "Typ existiert nur unter #if os(...), wird aber auf einer anderen Plattform benutzt",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="swiftui_multiplatform_guideline.md",
    self_tests=[
        SelfTestCase(
            name="Layout nur unter tvOS deklariert, iOS-Ansicht benutzt es",
            files={
                "P.xcodeproj/project.pbxproj":
                    "isa = XCBuildConfiguration;\n\t\t\tbuildSettings = {\n"
                    "\t\t\t\tSUPPORTED_PLATFORMS = \"appletvos appletvsimulator iphoneos iphonesimulator\";\n"
                    "\t\t\t};\n",
                "App/Panel.swift": "import SwiftUI\n#if os(tvOS)\nstruct Panel: View { var body: some View { EmptyView() } }\n"
                                   "struct FlowLayout: Layout {}\n#endif\n",
                "App/Sheet.swift": "import SwiftUI\n#if os(iOS)\nstruct Sheet: View {\n"
                                   "  var body: some View { FlowLayout { Text(\"a\") } }\n}\n#endif\n",
            },
            expect=Status.FAIL,
            expect_finding_contains="FlowLayout",
        ),
        SelfTestCase(
            name="Layout plattformneutral deklariert",
            files={
                "P.xcodeproj/project.pbxproj":
                    "isa = XCBuildConfiguration;\n\t\t\tbuildSettings = {\n"
                    "\t\t\t\tSUPPORTED_PLATFORMS = \"appletvos appletvsimulator iphoneos iphonesimulator\";\n"
                    "\t\t\t};\n",
                "App/FlowLayout.swift": "import SwiftUI\nstruct FlowLayout: Layout {}\n",
                "App/Panel.swift": "import SwiftUI\n#if os(tvOS)\nstruct Panel: View { var body: some View { FlowLayout { } } }\n#endif\n",
                "App/Sheet.swift": "import SwiftUI\n#if os(iOS)\nstruct Sheet: View {\n"
                                   "  var body: some View { FlowLayout { Text(\"a\") } }\n}\n#endif\n",
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Benutzung liegt selbst unter #if os(tvOS)",
            files={
                "P.xcodeproj/project.pbxproj":
                    "isa = XCBuildConfiguration;\n\t\t\tbuildSettings = {\n"
                    "\t\t\t\tSUPPORTED_PLATFORMS = \"appletvos iphoneos\";\n"
                    "\t\t\t};\n",
                "App/Panel.swift": "#if os(tvOS)\nstruct FlowLayout {}\n#endif\n",
                "App/Use.swift": "#if os(tvOS) || DEBUG && os(tvOS)\nlet l = FlowLayout()\n#else\nlet l = 0\n#endif\n",
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Einzelplattform-Projekt: Bedingung ist kein Befund",
            files={
                "P.xcodeproj/project.pbxproj":
                    "isa = XCBuildConfiguration;\n\t\t\tbuildSettings = {\n"
                    "\t\t\t\tSUPPORTED_PLATFORMS = \"appletvos appletvsimulator\";\n"
                    "\t\t\t};\n",
                "App/Panel.swift": "#if os(tvOS)\nstruct FlowLayout {}\n#endif\n",
                "App/Use.swift": "let l = FlowLayout()\n",
            },
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_platform_conditional_type(ctx: Context) -> CheckResult:
    """Ein Typ, dessen sämtliche Deklarationen auf Plattform P sicher
    wegfallen, darf auf P nicht benutzt werden. Gemeldet wird nur, wenn die
    Benutzung auf P SICHER kompiliert wird — unbekannte Bedingungen (DEBUG,
    canImport, ...) zählen für die Deklaration als vorhanden und für die
    Benutzung als nicht sicher. Dadurch bleibt der Check im Zweifel still."""
    cid = "apple.platform_conditional_type_used_unguarded"
    title = "Plattformbedingter Typ ungeschützt benutzt"
    pbx_files = ctx.files_named("project.pbxproj")
    if not pbx_files:
        return unmeasured(cid, title, "Kein Xcode-Projekt gefunden.", PLATFORM)
    plats: set[str] = set()
    for pf in pbx_files:
        plats |= _multi_platform_sets(pf.text)
    if not plats:
        return unmeasured(cid, title,
                          "Kein Target baut für mehr als eine Plattform — eine "
                          "#if os(...)-Bedingung kann dort keinen Typ verstecken.",
                          PLATFORM)
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured(cid, title, "Keine Swift-Dateien gefunden.", PLATFORM)

    # Pro Datei: bereinigte Zeilen und Bedingungen je Zeile.
    parsed = []
    for sf in swift:
        clean = strip_comments(sf.text, ".swift").splitlines()
        parsed.append((sf, clean, _line_conditions(clean)))

    # Deklarationen: Name -> Plattformen, auf denen sie VIELLEICHT existiert.
    maybe_declared: dict[str, set[str]] = {}
    decl_lines: set[tuple[str, int]] = set()
    for sf, clean, conds in parsed:
        for idx, line in enumerate(clean):
            m = _DECL.match(line)
            if not m:
                continue
            decl_lines.add((sf.rel, idx))
            avail = maybe_declared.setdefault(m.group(1), set())
            for p in plats:
                if _compiled(conds[idx], p) is not False:
                    avail.add(p)

    hidden = {name: plats - avail for name, avail in maybe_declared.items() if plats - avail}
    findings: list[Finding] = []
    if hidden:
        use = re.compile(r"(?<![.\w])(" + "|".join(map(re.escape, sorted(hidden))) + r")\b")
        for sf, clean, conds in parsed:
            for idx, line in enumerate(clean):
                if (sf.rel, idx) in decl_lines or _DIRECTIVE.match(line):
                    continue
                for m in use.finditer(_STRING.sub('""', line)):
                    name = m.group(1)
                    missing = sorted(p for p in hidden[name] if _compiled(conds[idx], p) is True)
                    if not missing:
                        continue
                    findings.append(Finding(
                        check_id=cid, severity=Severity.ERROR,
                        message=(f"'{name}' ist auf {', '.join(missing)} nicht deklariert "
                                 f"(nur innerhalb einer #if os(...)-Bedingung), wird hier aber "
                                 f"für {', '.join(missing)} kompiliert — Build-Fehler "
                                 f"\"Cannot find '{name}' in scope\"."),
                        file=sf.rel, line=idx + 1, evidence=snippet(sf.lines[idx]),
                        fix=(f"Die Deklaration von '{name}' aus dem #if-Block in eine eigene, "
                             "plattformneutrale Datei ziehen — oder die Benutzung unter "
                             "dieselbe Bedingung stellen."),
                        guideline="swiftui_multiplatform_guideline.md",
                    ))
                    break
    return result_for(cid, title, findings, len(swift), "Swift-Dateien", PLATFORM)
