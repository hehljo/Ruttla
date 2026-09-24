"""Universal: published formats evolve safely.

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
        r"^[ \t]*(public\s+|export\s+|internal\s+)?enum\s+(\w+)", re.MULTILINE
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
        r"(?i)^[ \t]*(\"?\w*" + ui_words + r"\w*\"?)\s*[:?]\s*\w", re.MULTILINE
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
