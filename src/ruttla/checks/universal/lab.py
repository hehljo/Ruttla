"""Universal: experimental flags are statically evaluable.

Split from the original checks/universal.py; background and
shared helpers in _common.py.
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
    # einer realen Web-App: 'buildCheckerLabel' und 'mirrorLabel' wurden als
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
