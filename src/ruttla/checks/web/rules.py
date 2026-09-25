"""
Web-Checks aus CODE_QUALITY_GUIDELINES_WEB.md.

Schwerpunkte:
* § -0  Nichts hardcoden (Endpunkte, Marke, Texte)
* § 0   Intrinsic Layout — minmax(0,1fr) statt 1fr, min-width:0
* § 4   Mobile-Fallen — 100vh, safe-area, Trefferflächen
* § 5   Barrierefreiheit (BFSG seit 28.06.2025)
* § 5b  API-Schlüssel erreichen den Browser NIE
* § 5e  OAuth/HTTPS, verschluckte Fehler bei if(res.ok) ohne else
* § 5h  Laden vs. Prüfen — null als dritter Zustand
* § 5i  StrictMode + Canvas/WebGL/Audio
"""

from __future__ import annotations

import os
import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, unmeasured, result_for, iter_matches, snippet, strip_comments,
)

PLATFORM = "web"
WEB_CODE = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")
WEB_STYLE = (".css", ".scss", ".sass", ".less")


@register(
    "web.secret_reaches_browser",
    "API-Schlüssel erreicht den Browser",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5b Regel 1",
    safe_by_default=True,
    self_tests=[
        SelfTestCase(
            name="Gemini-Key im Client",
            files={
                "package.json": '{"name":"app","dependencies":{"vite":"^5"}}',
                "src/ai.ts": "const key = import.meta.env.VITE_GEMINI_API_KEY;\n",
            },
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Aufruf über die eigene Funktion",
            files={
                "package.json": '{"name":"app","dependencies":{"vite":"^5"}}',
                "src/ai.ts": "const r = await fetch('/api/generate', { method: 'POST' });\n",
            },
            expect=Status.PASS,
        ),
    ],
)
def check_client_secret(ctx: Context) -> CheckResult:
    """VITE_/NEXT_PUBLIC_/REACT_APP_-Variablen landen im ausgelieferten Bundle.

    Gemessen wird der NAME der Variablen — wer einen KI-Schlüssel über ein
    client-sichtbares Präfix bezieht, hat ihn veröffentlicht, ganz gleich wie
    die Umgebung konfiguriert ist.
    """
    title = "API-Schlüssel erreicht den Browser"
    code = ctx.files(*WEB_CODE)
    if not code:
        return unmeasured("web.secret_reaches_browser", title,
                          "Keine Web-Quelldateien gefunden.", PLATFORM)
    pat = re.compile(
        r"\b(?:import\.meta\.env|process\.env)\.("
        r"(?:VITE_|NEXT_PUBLIC_|REACT_APP_|PUBLIC_|NUXT_PUBLIC_|EXPO_PUBLIC_)"
        r"\w*(?:API_?KEY|SECRET|TOKEN|PASSWORD|SERVICE_ROLE|PRIVATE)\w*)"
    )
    findings: list[Finding] = []
    for sf in code:
        for line_no, m, raw in iter_matches(sf, pat):
            name = m.group(1)
            # Der Supabase-anon-Key DARF öffentlich sein (RLS sichert ab).
            if re.search(r"(?i)anon", name):
                continue
            findings.append(Finding(
                check_id="web.secret_reaches_browser", severity=Severity.ERROR,
                message=f"'{name}' ist client-sichtbar und trägt ein Geheimnis im Namen.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Den Aufruf über eine eigene Serverfunktion leiten. Der Key "
                    "erreicht den Browser nie — als Header, nicht im Query-String.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5b",
            ))
    return result_for("web.secret_reaches_browser", title, findings, len(code),
                      "Web-Dateien", PLATFORM)


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
    "web.swallowed_fetch_error",
    "if (res.ok) ohne else — der Fehlerfall wird verschluckt",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5e",
    self_tests=[
        SelfTestCase(
            name="ok ohne else",
            files={"src/a.ts": "const res = await fetch(u);\nif (res.ok) {\n  setData(await res.json());\n}\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="ok mit else",
            files={"src/a.ts": "const res = await fetch(u);\nif (res.ok) {\n  setData(await res.json());\n} else {\n  setError(res.statusText);\n}\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_swallowed_error(ctx: Context) -> CheckResult:
    """Ohne else-Zweig geht ein 403 lautlos vorbei — der Nutzer sieht nichts."""
    title = "if (res.ok) ohne else — der Fehlerfall wird verschluckt"
    code = ctx.files(*WEB_CODE)
    if not code:
        return unmeasured("web.swallowed_fetch_error", title,
                          "Keine Web-Quelldateien gefunden.", PLATFORM)
    pat = re.compile(r"if\s*\(\s*(?:!\s*)?(\w+)\.ok\s*\)\s*\{")
    findings: list[Finding] = []
    measured = 0
    for sf in code:
        body = strip_comments(sf.text, sf.ext)
        for m in pat.finditer(body):
            measured += 1
            if m.group(0).lstrip("if (").startswith("!"):
                continue
            # Klammern zählen bis zum Blockende, dann auf else prüfen.
            depth, i = 0, m.end() - 1
            end = len(body)
            while i < len(body):
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
                i += 1
            tail = body[end: end + 40].lstrip()
            if tail.startswith("else"):
                continue
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="web.swallowed_fetch_error", severity=Severity.WARNING,
                message=f"'if ({m.group(1)}.ok)' ohne else — ein 4xx/5xx passiert lautlos.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="else-Zweig ergänzen, der den Status liest und sichtbar macht. "
                    "Und prüfen, dass die Ansicht, die die Meldung zeigt, im "
                    "Fehlerfall auch eingenommen wird.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5e",
            ))
    if measured == 0:
        return unmeasured("web.swallowed_fetch_error", title,
                          "Kein 'if (res.ok)'-Muster im Projekt.", PLATFORM)
    return result_for("web.swallowed_fetch_error", title, findings, measured,
                      "ok-Prüfungen", PLATFORM)


@register(
    "web.empty_catch_block",
    "Leerer catch-Block verschluckt den Fehler vollständig",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § Fehlerbehandlung",
    references=(
        "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Statements/try...catch",
    ),
    rationale=(
        "Ein leerer catch-Block verwirft die gefangene Exception ohne sichtbare "
        "Behandlung. Das erschwert Diagnose und kann Fehlerzustände als Erfolg "
        "erscheinen lassen. Absichtlich ignorierte Fehler (z. B. optionale "
        "Best-Effort-Arbeit) sind eine mögliche legitime Ausnahme; deshalb ist "
        "der Check advisory und nicht safe-by-default. Er prüft nur syntaktisch "
        "leere JavaScript/TypeScript-catch-Blöcke, keine allgemeine Qualität "
        "der Fehlerbehandlung oder DB-RLS-Rechte."
    ),
    self_tests=[
        SelfTestCase(
            name="Exception wird lautlos verworfen",
            files={"src/api.ts": "try { await save(); } catch {}\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Fehler wird protokolliert und Stringliteral ist kein Treffer",
            files={
                "src/api.ts": (
                    'const example = "catch {}";\n'
                    "try { await save(); } catch (error) { console.error(error); }\n"
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_empty_catch_block(ctx: Context) -> CheckResult:
    """Ein leeres catch verwirft den Fehler und verschleiert den Laufzeitstatus."""
    title = "Leerer catch-Block verschluckt den Fehler vollständig"
    files = ctx.files(*WEB_CODE)
    if not files:
        return unmeasured("web.empty_catch_block", title,
                          "Keine Web-Quelldateien gefunden.", PLATFORM)

    catch_start = re.compile(r"\bcatch\s*(?:\([^)]*\)\s*)?\{")
    empty_catch = re.compile(r"\bcatch\s*(?:\([^)]*\)\s*)?\{\s*\}")
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = _mask_js_strings(strip_comments(sf.text, sf.ext))
        matches = list(catch_start.finditer(body))
        measured += len(matches)
        for match in empty_catch.finditer(body):
            line_no = body.count("\n", 0, match.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="web.empty_catch_block", severity=Severity.WARNING,
                message="Leerer catch-Block verwirft den Fehler ohne Meldung oder Fallback.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Fehler sichtbar behandeln (z. B. protokollieren, dem Aufrufer "
                    "melden oder erneut werfen). Absichtliches Ignorieren begründen "
                    "und den Fehlerfall anderweitig abdecken.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § Fehlerbehandlung",
            ))
    if measured == 0:
        return unmeasured("web.empty_catch_block", title,
                          "Keine JavaScript/TypeScript-catch-Blöcke gefunden.", PLATFORM)
    return result_for("web.empty_catch_block", title, findings, measured,
                      "catch-Blöcke", PLATFORM)


def _mask_js_strings(source: str) -> str:
    """Maskiert String- und Template-Literale, erhält Zeilen- und Offset-Bezug."""
    out = list(source)
    quote: str | None = None
    i = 0
    while i < len(source):
        char = source[i]
        if quote is not None:
            if char == "\\":
                if char != "\n":
                    out[i] = " "
                if i + 1 < len(source) and source[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if char == quote:
                quote = None
            elif char != "\n":
                out[i] = " "
            i += 1
            continue
        if char in ('"', "'", "`"):
            quote = char
            out[i] = " "
        i += 1
    return "".join(out)


@register(
    "web.loading_without_null_state",
    "Ladezustand kennt kein 'noch nicht geprüft' (null als dritter Zustand)",
    platform=PLATFORM,
    severity=Severity.INFO,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5h",
    self_tests=[
        SelfTestCase(
            name="boolescher Ladezustand",
            files={"src/a.tsx": "const [isChecked, setIsChecked] = useState(false);\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="mit null als drittem Zustand",
            files={"src/a.tsx": "const [isChecked, setIsChecked] = useState<boolean | null>(null);\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_null_state(ctx: Context) -> CheckResult:
    """Ein boolescher Ladezustand hat zwei Werte für drei Zustände: noch nicht
    geladen, geladen-und-leer, geladen-mit-Daten. Der mittlere wird dann als
    Fehler angezeigt."""
    title = "Ladezustand kennt kein 'noch nicht geprüft' (null als dritter Zustand)"
    code = ctx.files(*WEB_CODE)
    if not code:
        return unmeasured("web.loading_without_null_state", title,
                          "Keine Web-Quelldateien gefunden.", PLATFORM)
    pat = re.compile(
        r"useState\s*(?:<[^>]*>)?\s*\(\s*(?:false|true)\s*\)\s*;?\s*"
    )
    state_name = re.compile(
        r"const\s*\[\s*(\w*(?:[Ll]oaded|[Cc]hecked|[Vv]alid|[Aa]llowed|[Ee]xists|"
        r"[Hh]as\w+|[Ii]s\w+))\s*,"
    )
    findings: list[Finding] = []
    measured = 0
    for sf in code:
        body = strip_comments(sf.text, sf.ext)
        for m in state_name.finditer(body):
            # Prüfgegenstand ist jede solche Zustandsvariable — erst danach
            # entscheidet der Startwert über den Befund. Nur die Verstöße zu
            # zählen machte aus dem gesunden Fall ein "nicht gemessen".
            measured += 1
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            if not pat.search(raw):
                continue
            findings.append(Finding(
                check_id="web.loading_without_null_state", severity=Severity.INFO,
                message=f"'{m.group(1)}' ist boolesch — 'noch nicht geprüft' ist "
                        "nicht unterscheidbar von 'geprüft und negativ'.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Als `boolean | null` führen und mit null starten; erst nach "
                    "der Prüfung setzen.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5h",
            ))
    if measured == 0:
        return unmeasured("web.loading_without_null_state", title,
                          "Keine passenden Zustandsvariablen gefunden.", PLATFORM)
    return result_for("web.loading_without_null_state", title, findings, measured,
                      "Zustandsvariablen", PLATFORM)


@register(
    "web.a11y_missing_label",
    "Bedienelement ohne zugängliche Beschriftung",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5 (BFSG seit 28.06.2025)",
    self_tests=[
        SelfTestCase(
            name="Icon-Knopf ohne Label",
            files={"src/a.tsx": "export const A = () => <button><Icon /></button>;\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="mit aria-label",
            files={"src/a.tsx": "export const A = () => <button aria-label=\"Schliessen\"><Icon /></button>;\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_a11y_labels(ctx: Context) -> CheckResult:
    """Ein Label, das nur danebensteht, ist kein Label. Gemessen wird am Code,
    nicht am ausgelieferten HTML — bei SPAs ist das HTML leer."""
    title = "Bedienelement ohne zugängliche Beschriftung"
    files = ctx.files(".tsx", ".jsx", ".vue", ".svelte", ".html")
    if not files:
        return unmeasured("web.a11y_missing_label", title,
                          "Keine Markup-Dateien gefunden.", PLATFORM)
    el = re.compile(r"<(button|input|select|textarea|a)\b([^>]*)>", re.IGNORECASE | re.DOTALL)
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        for m in el.finditer(body):
            tag, attrs = m.group(1).lower(), m.group(2)
            measured += 1
            if re.search(r"(aria-label|aria-labelledby|title\s*=|alt\s*=)", attrs, re.I):
                continue
            if tag == "input" and re.search(r'type\s*=\s*["\']?(hidden|submit|button)', attrs, re.I):
                continue
            if tag == "a" and re.search(r"(aria-hidden)", attrs, re.I):
                continue
            # Text zwischen den Tags zählt als Beschriftung.
            after = body[m.end(): m.end() + 200]
            if re.search(r"^\s*[^<>{}\s][^<>]{1,}", after):
                continue
            if re.search(r"^\s*\{[^}]*\}", after):
                continue  # Interpolation, vermutlich Katalogtext
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="web.a11y_missing_label", severity=Severity.WARNING,
                message=f"<{tag}> ohne sichtbare oder zugängliche Beschriftung.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="aria-label ergänzen oder ein <label for=…> verbinden. Ein "
                    "Label, das nur danebensteht, ist kein Label.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5",
            ))
    if measured == 0:
        return unmeasured("web.a11y_missing_label", title,
                          "Keine Bedienelemente gefunden.", PLATFORM)
    return result_for("web.a11y_missing_label", title, findings, measured,
                      "Bedienelemente", PLATFORM)


@register(
    "web.strictmode_resource_leak",
    "Canvas/WebGL/Audio-Ressource ohne Cleanup (StrictMode-Doppelmount)",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5i",
    self_tests=[
        SelfTestCase(
            name="ohne Cleanup",
            files={"src/a.tsx": "export const A = () => { useEffect(() => { const ctx = ref.current.getContext('2d'); draw(ctx); }, []); return null; };\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="mit Cleanup",
            files={"src/a.tsx": "export const A = () => { useEffect(() => { const ctx = ref.current.getContext('2d'); draw(ctx); return () => ctx.reset(); }, []); return null; };\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_strictmode(ctx: Context) -> CheckResult:
    """Das Ref überlebt den Doppelmount, die Ressource nicht. Ein useEffect, der
    einen Kontext anlegt, braucht eine Rückgabefunktion, die ihn freigibt."""
    title = "Canvas/WebGL/Audio-Ressource ohne Cleanup (StrictMode-Doppelmount)"
    code = ctx.files(".tsx", ".jsx", ".ts", ".js")
    if not code:
        return unmeasured("web.strictmode_resource_leak", title,
                          "Keine React-Dateien gefunden.", PLATFORM)
    resource = re.compile(
        r"(getContext\s*\(|new\s+AudioContext|new\s+(Three\.)?WebGLRenderer"
        r"|requestAnimationFrame\s*\(|new\s+ResizeObserver|new\s+IntersectionObserver"
        r"|addEventListener\s*\(|setInterval\s*\()"
    )
    findings: list[Finding] = []
    measured = 0
    for sf in code:
        body = strip_comments(sf.text, sf.ext)
        for m in re.finditer(r"useEffect\s*\(\s*\(\s*\)\s*=>\s*\{", body):
            depth, i = 0, m.end() - 1
            end = len(body)
            while i < len(body):
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
                i += 1
            block = body[m.end(): end]
            if not resource.search(block):
                continue
            measured += 1
            if re.search(r"\breturn\s*(\(\s*\)\s*=>|function)", block):
                continue
            line_no = body.count("\n", 0, m.start()) + 1
            findings.append(Finding(
                check_id="web.strictmode_resource_leak", severity=Severity.WARNING,
                message="useEffect legt eine Ressource an, gibt aber keine "
                        "Cleanup-Funktion zurück.",
                file=sf.rel, line=line_no,
                evidence=snippet(resource.search(block).group(0)),
                fix="Eine Aufräumfunktion zurückgeben. Im StrictMode läuft der "
                    "Effekt doppelt — das Ref überlebt, die Ressource nicht.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5i",
            ))
    if measured == 0:
        return unmeasured("web.strictmode_resource_leak", title,
                          "Kein useEffect mit Ressourcenanlage gefunden.", PLATFORM)
    return result_for("web.strictmode_resource_leak", title, findings, measured,
                      "Effekte mit Ressourcen", PLATFORM)


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
    "web.hardcoded_endpoint",
    "Adresse steht fest im Code statt in einer Endpunktliste",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § -0",
    self_tests=[
        SelfTestCase(
            name="feste Adresse",
            files={"src/api.ts": "const r = await fetch('https://api.meinedomain.de/v1/items');\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="aus der Endpunktliste",
            files={"src/api.ts": "import { ENDPOINTS } from './config';\nconst r = await fetch(ENDPOINTS.items);\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_endpoints(ctx: Context) -> CheckResult:
    title = "Adresse steht fest im Code statt in einer Endpunktliste"
    code = ctx.files(*WEB_CODE)
    if not code:
        return unmeasured("web.hardcoded_endpoint", title,
                          "Keine Web-Quelldateien gefunden.", PLATFORM)
    pat = re.compile(r"[\"'`](https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)[^\"'`\s]{6,})[\"'`]")
    # Dokumentations-, Schema- und Standardadressen sind keine Endpunkte.
    ignore = re.compile(
        r"(?i)(w3\.org|schema\.org|json-schema|xmlns|example\.(com|org)|"
        r"github\.com|npmjs|mozilla\.org|creativecommons|purl\.org|"
        r"fonts\.googleapis|fonts\.gstatic|\.svg$|\.png$|\.md$)"
    )
    findings: list[Finding] = []
    for sf in code:
        if re.search(r"(?i)(config|constants|endpoints|env)\.(ts|js)$", sf.rel):
            continue
        for line_no, m, raw in iter_matches(sf, pat):
            url = m.group(1)
            if ignore.search(url):
                continue
            findings.append(Finding(
                check_id="web.hardcoded_endpoint", severity=Severity.WARNING,
                message=f"Feste Adresse '{snippet(url, 60)}' im Code.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="In die Endpunktliste (config.ts) legen — eine Liste, alles "
                    "andere abgeleitet.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § -0",
            ))
    return result_for("web.hardcoded_endpoint", title, findings, len(code),
                      "Web-Dateien", PLATFORM)


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
    corpus = "\n".join(
        sf.rel + "\n" + sf.text
        for sf in ctx.files(*WEB_CODE, ".html", ".md", ".json")
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
    ],
)
def check_touch_targets(ctx: Context) -> CheckResult:
    """Statische Annäherung: explizit gesetzte Höhen/Breiten unter 44px an
    Interaktions-Selektoren. Die echte Messung gehört in einen Browser-Lauf
    (z. B. Playwright) — das hier fängt die offensichtlichen Fälle früher ab."""
    title = "Trefferfläche unter 44px"
    styles = ctx.files(*WEB_STYLE)
    if not styles:
        return unmeasured("web.touch_target_too_small", title,
                          "Keine Stylesheets gefunden. Die verlässliche Messung "
                          "läuft im Browser (gerenderte Messung).", PLATFORM)
    rule = re.compile(r"([^{}]+)\{([^}]*)\}", re.DOTALL)
    size = re.compile(r"(?:min-)?(?:height|width)\s*:\s*(\d+(?:\.\d+)?)px")
    interactive = re.compile(r"(?i)(button|\.btn|\[role=\"?button|a[:\s.,{]|input|"
                             r"\.link|\.tab|\.chip|\.icon-button|select)")
    findings: list[Finding] = []
    measured = 0
    for sf in styles:
        body = strip_comments(sf.text, sf.ext)
        for m in rule.finditer(body):
            selector, decls = m.group(1), m.group(2)
            if not interactive.search(selector):
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


@register(
    "web.search_selection_resets_category",
    "Suchtreffer-Auswahl leert Suchfeld ohne Kategorie-Sync (UI springt weg)",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 3b",
    self_tests=[
        SelfTestCase(
            name="Auswahl leert Suche ohne Kategorie",
            files={
                "src/Modal.jsx": (
                    "export function Modal() {\n"
                    "  return (\n"
                    "    <button onClick={() => { handleTypeChange(val); setSearchQuery(''); }}>\n"
                    "      Select\n"
                    "    </button>\n"
                    "  );\n"
                    "}\n"
                ),
            },
            expect=Status.FAIL,
            expect_finding_contains="setSearchQuery",
        ),
        SelfTestCase(
            name="Auswahl synchronisiert Kategorie mit",
            files={
                "src/Modal.jsx": (
                    "export function Modal() {\n"
                    "  return (\n"
                    "    <button onClick={() => { handleTypeChange(val); setSelectedCategory(cat); setSearchQuery(''); }}>\n"
                    "      Select\n"
                    "    </button>\n"
                    "  );\n"
                    "}\n"
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_search_selection_resets_category(ctx: Context) -> CheckResult:
    """Wenn in einer gefilterten oder kategorisierten Liste ein Treffer ausgewählt
    wird und der Click-Handler die Suche leert (''), aber die aktive Kategorie/Gruppe
    nicht synchronisiert, springt die Ansicht nach dem Leeren der Suche sofort auf
    die alte vorherige Kategorie zurück und das gewählte Element wird unsichtbar."""
    title = "Suchtreffer-Auswahl leert Suchfeld ohne Kategorie-Sync"
    code = ctx.files(".tsx", ".jsx", ".vue", ".svelte", ".js", ".ts")
    if not code:
        return unmeasured("web.search_selection_resets_category", title,
                          "Keine Frontend-Dateien gefunden.", PLATFORM)

    inline_pattern = re.compile(
        r'(?:onClick|onSelect)\s*=\s*\{(?:\(\s*\)\s*=>\s*\{?|\bfunction\s*\(\)\s*\{?)([^}]+)\}?',
        re.DOTALL
    )
    fn_pattern = re.compile(
        r'(?:const|let|function)\s+(\w+)\s*=\s*(?:\([^)]*\)|[a-zA-Z0-9_]+)\s*=>\s*\{([^}]+)\}',
        re.DOTALL
    )

    findings: list[Finding] = []
    measured = 0

    def check_body(body_str: str, file_rel: str, line_no: int, raw_snippet: str, sf_full_text: str):
        nonlocal measured
        has_clear = bool(re.search(r'setSearch(?:Query)?\s*\(\s*[\'"]\s*[\'"]\s*\)', body_str))
        if not has_clear:
            return

        select_match = re.search(
            r'(\b(?:handle(?:Type|Item|Source|Option)(?:Change)?|set(?:Selected)?(?:Type|Item|Source|Option)))\s*\(',
            body_str
        )
        if not select_match:
            return

        measured += 1
        has_cat = bool(re.search(
            r'(?:setSelected(?:Category|Tab|Group|Filter|Section)|handle(?:Category|Tab|Group)Change|setCategory)\s*\(',
            body_str
        ))
        if has_cat:
            return

        # Prüfen, ob die aufgerufene Handler-Funktion in derselben Datei selbst die Kategorie synchronisiert
        handler_name = select_match.group(1)
        handler_def = re.search(
            r'(?:const|let|function)\s+' + re.escape(handler_name) + r'\b[^=]*=\s*(?:\([^)]*\)|[a-zA-Z0-9_]+)\s*=>\s*\{([^}]+)\}',
            sf_full_text,
            re.DOTALL
        )
        if handler_def and re.search(
            r'(?:setSelected(?:Category|Tab|Group|Filter|Section)|handle(?:Category|Tab|Group)Change|setCategory)\s*\(',
            handler_def.group(1)
        ):
            return

        findings.append(Finding(
            check_id="web.search_selection_resets_category",
            severity=Severity.WARNING,
            message="Auswahl-Handler leert das Suchfeld, ohne die zugehörige Kategorie/den Tab zu aktualisieren.",
            file=file_rel,
            line=line_no,
            evidence=snippet(raw_snippet),
            fix="Kategorie des gewählten Eintrags mitsynchronisieren (z. B. setSelectedCategory(item.category)), "
                "damit die UI nach Leeren der Suche nicht auf die alte Kategorie zurückspringt.",
            guideline="CODE_QUALITY_GUIDELINES_WEB.md § 3b",
        ))

    for sf in code:
        body = strip_comments(sf.text, sf.ext)
        for m in inline_pattern.finditer(body):
            content = m.group(1)
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else m.group(0)
            check_body(content, sf.rel, line_no, raw, body)

        for m in fn_pattern.finditer(body):
            content = m.group(2)
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else m.group(0)
            check_body(content, sf.rel, line_no, raw, body)

    if measured == 0:
        return unmeasured("web.search_selection_resets_category", title,
                          "Keine Auswahl-Handler mit Suchfeld-Bereinigung gefunden.", PLATFORM)
    return result_for("web.search_selection_resets_category", title, findings, measured,
                      "Suchauswahl-Handler", PLATFORM)

