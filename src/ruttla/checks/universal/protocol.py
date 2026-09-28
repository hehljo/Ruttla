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
        SelfTestCase(
            name="Swift lokale Enums neben fremdem Decoder",
            files={"App/Screen.swift": 'enum Selection: String { case session, persistent }\n'
                   'enum SelectionKind { case movies, shows }\n'
                   'enum SelectionStore { static let decoder = JSONDecoder() }\n'
                   'struct Payload: Codable { let name: String }\n'},
            expect=Status.UNMEASURED,
        ),
        SelfTestCase(
            name="Swift CodingKeys sind keine offenen Protokollwerte",
            files={"App/Models.swift": 'struct Payload: Codable {\n'
                   '  let title: String\n'
                   '  enum CodingKeys: String, CodingKey { case title }\n}\n'},
            expect=Status.UNMEASURED,
        ),
        SelfTestCase(
            name="Swift expliziter Decoder mit Fallback",
            files={"App/Models.swift": 'import Foundation\n'
                   'enum Kind: String, Decodable {\n'
                   '  case text, unknown\n'
                   '  init(from decoder: Decoder) throws {\n'
                   '    let value = try decoder.singleValueContainer().decode(String.self)\n'
                   '    self = Kind(rawValue: value) ?? .unknown\n  }\n}\n'},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Swift serialisierter Wert ohne Fallback",
            files={"App/Models.swift": 'private enum Kind: String, Codable { case text, image }\n'},
            expect=Status.FAIL,
            expect_finding_contains="Kind",
        ),
        SelfTestCase(
            name="Swift Konformitaet in Extension",
            files={"App/Models.swift": 'enum Kind: String { case text, image }\n'
                   'extension Kind: Swift.Decodable {}\n'},
            expect=Status.FAIL,
            expect_finding_contains="Kind",
        ),
        SelfTestCase(
            name="Swift Kommentar ist keine Konformitaet",
            files={"App/Models.swift": '// enum Kind: Codable\n'
                   'enum Kind: String { case text, image }\n'
                   '// extension Kind: Decodable {}\n'},
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_protocol_enum(ctx: Context) -> CheckResult:
    """Ein alter Client muss einen neuen Enum-Wert ignorieren können, statt
    daran zu sterben. Gemessen wird an Enums, die von Serialisierung erreicht
    werden — nicht an jedem Enum im Projekt. Swift benötigt eine explizite
    Codable-/Decodable-Konformität am Enum oder in einer gleichnamigen
    Extension derselben Datei. Ein fremder JSONDecoder oder Codable-Struct
    ist kein Beleg; CodingKey-Enums sind keine offenen Protokollwerte.
    Cross-file Extensions und die tatsächliche Ausführung eines Decoders
    werden nicht bewiesen. Ein benannter Unknown-Fall allein garantiert
    keine tolerante Decodierung; dafür ist ein Laufzeittest erforderlich."""
    title = "Enum eines veröffentlichten Formats ohne Unknown-Fallback"
    serde_hint = re.compile(
        r"(?i)(Codable|Decodable|@Serializable|serde|JsonConverter|"
        r"JSONDecoder|json\.loads|JSON\.parse|z\.enum|Protobuf|from_json|to_json)"
    )
    enum_decl = re.compile(
        r"^[ \t]*((?:(?:public|export|internal|private|fileprivate|package)\s+)*)enum\s+(\w+)",
        re.MULTILINE,
    )
    fallback = re.compile(r"(?i)\b(unknown|unrecognized|other|default|fallback|future)\b")
    findings: list[Finding] = []
    units = 0
    for sf in ctx.files(".swift", ".ts", ".kt", ".cs", ".rs"):
        body = strip_comments(sf.text, sf.ext)
        if not serde_hint.search(body):
            continue
        for m in enum_decl.finditer(body):
            if sf.ext == ".swift":
                brace = body.find("{", m.end())
                if brace < 0:
                    continue
                header = body[m.end():brace]
                if re.search(r"\bCodingKey\b", header):
                    continue
                conforms = r":[^{}]*\b(?:Codable|Decodable)\b"
                extension = re.compile(
                    r"\bextension\s+" + re.escape(m.group(2)) + conforms)
                if not re.search(conforms, header) and not extension.search(body):
                    continue
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
                fix="Fallback an der Decodiergrenze implementieren und einen "
                    "unbekannten Eingabewert testen. In Swift reicht ein "
                    "Unknown-Case allein bei synthetisiertem Decodable nicht.",
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
