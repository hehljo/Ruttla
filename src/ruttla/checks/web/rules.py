"""
Web-Checks aus CODE_QUALITY_GUIDELINES_WEB.md (Fehlerbehandlung, Zustand, A11y,
StrictMode, Suchauswahl).

Layout/CSS liegt in `layout.py`, Rechtstexte in `legal.py`, PWA in `pwa.py`,
Buchung/Zahlung/SMS in `booking.py`.
"""

from __future__ import annotations

import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, unmeasured, result_for, snippet, strip_comments,
)

PLATFORM = "web"
WEB_CODE = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")
WEB_STYLE = (".css", ".scss", ".sass", ".less")


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


_JS_COMMENT = re.compile(r"//|/\*")


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
        SelfTestCase(
            name="Begründet leer: Kommentar im Block",
            files={"src/build.js": (
                "try {\n  await stat(path);\n} catch {\n"
                "  // Nicht vorhanden — genau so soll es sein.\n}\n")},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Kommentar vor dem try entschuldigt nichts",
            files={"src/build.js": (
                "// Datei lesen\ntry {\n  await stat(path);\n} catch {\n}\n")},
            expect=Status.FAIL,
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
            end_no = body.count("\n", 0, match.end()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            # Ein Kommentar im Block IST die Begründung, die der fix-Text
            # verlangt. Belegt am 08.10.2026 (Merkma, build.js): `catch {
            # // Nicht vorhanden — genau so soll es sein. }` wurde gemeldet,
            # weil die Prüfung auf kommentarfreiem Text lief.
            if any(_JS_COMMENT.search(l) for l in sf.lines[line_no - 1:end_no]):
                continue
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
            name="gesund: UI-Schalter ohne Nullable-Typ ist nicht gemessen",
            files={"src/a.tsx": "const [isOpen, setIsOpen] = useState(false);\n"},
            expect=Status.UNMEASURED,
        ),
        SelfTestCase(
            name="gesund: boolean | null startet mit null",
            files={"src/a.tsx": "const [isChecked, setIsChecked] = useState<boolean | null>(null);\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="defekt: boolean | null startet mit false",
            files={"src/a.tsx": "const [isChecked, setIsChecked] = useState<boolean | null>(false);\n"},
            expect=Status.FAIL,
        ),
    ],
)
def check_null_state(ctx: Context) -> CheckResult:
    """Ein als `boolean | null` geführter Zustand trägt „noch nicht geprüft“ als
    null. Startet er trotzdem mit true/false, ist der dritte Zustand vom ersten
    Render an verloren. Gemessen werden nur ausdrückliche Nullable-Boolean-Typen
    mit Literal-Startwert: aus Namen wie isOpen/isSaving folgt keine Fachbedeutung,
    Aliase und berechnete Startwerte bleiben nicht gemessen."""
    title = "Ladezustand kennt kein 'noch nicht geprüft' (null als dritter Zustand)"
    code = ctx.files(*WEB_CODE)
    if not code:
        return unmeasured("web.loading_without_null_state", title,
                          "Keine Web-Quelldateien gefunden.", PLATFORM)
    decl = re.compile(
        r"\bconst\s*\[\s*(\w+)\s*,\s*\w+\s*\]\s*=\s*(?:React\s*\.\s*)?useState\s*"
        r"<\s*(?:boolean\s*\|\s*null|null\s*\|\s*boolean)\s*>\s*\(\s*(null|false|true)\s*\)"
    )
    findings: list[Finding] = []
    measured = 0
    for sf in code:
        body = _mask_js_strings(strip_comments(sf.text, sf.ext))
        for m in decl.finditer(body):
            # Prüfgegenstand ist jede Nullable-Boolean-Deklaration mit Literal-
            # Startwert; erst der Startwert entscheidet über den Befund.
            measured += 1
            if m.group(2) == "null":
                continue
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else ""
            findings.append(Finding(
                check_id="web.loading_without_null_state", severity=Severity.INFO,
                message=f"'{m.group(1)}' ist als boolean | null deklariert, startet "
                        f"aber mit {m.group(2)} — 'noch nicht geprüft' ist nicht "
                        "unterscheidbar von 'geprüft'.",
                file=sf.rel, line=line_no, evidence=snippet(raw),
                fix="Mit null starten und erst nach der Prüfung setzen; ist das "
                    "Ergebnis beim Start bekannt (Cache), den Typ auf boolean "
                    "verengen.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5h",
            ))
    if measured == 0:
        return unmeasured("web.loading_without_null_state", title,
                          "Keine boolean | null-Zustände mit Literal-Startwert gefunden.",
                          PLATFORM)
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
        SelfTestCase(
            name="Katalogtext per data-i18n und verbundenes label",
            files={"public/index.html":
                   '<button type="submit" data-i18n="auth.send"></button>\n'
                   '<label for="f-brand" data-i18n="filter.brand"></label>\n'
                   '<select id="f-brand"></select>\n'
                   '<label><span>Name</span> <input name="n"></label>\n'
                   '<button type="button" id="f"><span data-i18n="app.filter"></span></button>\n'},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="data-i18n beschriftet kein Eingabefeld",
            files={"public/index.html": '<select id="x" data-i18n="filter.brand"></select>\n'},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="data-i18n-label mit Katalogcode, der aria-label setzt",
            files={"index.html": '<button data-i18n-label="kopf.menue"><svg aria-hidden="true"></svg></button>\n'
                                 '<input type="range" id="r" data-i18n-label="schritt.regler" />\n',
                   "src/i18n/katalog.ts":
                   'document.querySelectorAll<HTMLElement>("[data-i18n-label]").forEach((el) =>\n'
                   '  el.setAttribute("aria-label", t(el.dataset.i18nLabel!)));\n'},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="data-i18n-label ohne Code, der es in aria-label übersetzt",
            files={"index.html": '<button data-i18n-label="kopf.menue"><svg aria-hidden="true"></svg></button>\n'},
            expect=Status.FAIL,
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
    # data-i18n-label ist eine Katalog-Konvention: das Attribut selbst beschriftet
    # nichts. Es zählt nur, wenn Projektcode daraus ein aria-label setzt — sonst
    # wäre es eine Existenz-, keine Wirkungsprüfung.
    label_wired = any(
        re.search(r"i18n-label|i18nLabel", cf.text) and re.search(r"aria-label", cf.text)
        for cf in ctx.files(".ts", ".js", ".mjs", ".tsx", ".jsx")
    )
    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        # Ein <label for=…> ist eine Beschriftung — die Fix-Empfehlung nennt
        # es selbst; ohne diese Zeile widersprach der Check seinem Rat.
        labelled = set(re.findall(r"<label\b[^>]*\b(?:for|htmlFor)\s*=\s*[\"']([^\"']+)", body, re.I))
        for m in el.finditer(body):
            tag, attrs = m.group(1).lower(), m.group(2)
            measured += 1
            if re.search(r"(aria-label|aria-labelledby|title\s*=|alt\s*=)", attrs, re.I):
                continue
            if label_wired and re.search(r"\bdata-i18n-label\s*=", attrs):
                continue
            ident = re.search(r"\bid\s*=\s*[\"']([^\"']+)", attrs)
            if ident and ident.group(1) in labelled:
                continue
            # Umschließendes <label>: das letzte offene label vor dem Element.
            before = body[:m.start()]
            if before.rfind("<label") > before.rfind("</label"):
                continue
            # data-i18n setzt den Textinhalt — bei Knopf und Link ist das
            # die Beschriftung, bei einem Eingabefeld nicht.
            if tag in ("button", "a") and re.search(r"\bdata-i18n\s*=", attrs):
                continue
            # …auch wenn er in einem Kind-Element steht: <button><span data-i18n>.
            if tag in ("button", "a"):
                close = body.find(f"</{tag}", m.end())
                inner = body[m.end(): close] if close != -1 else ""
                if re.search(r"\bdata-i18n\s*=", inner):
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
