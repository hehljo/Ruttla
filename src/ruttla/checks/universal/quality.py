"""Universal: anchors, duplicated lists and assistant traces.

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
)

from ._common import MARKUP_EXTS, SOURCE_EXTS


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
