"""SwiftUI: a visual blur does not remove sensitive text from a renderer."""

from __future__ import annotations

import re

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status,
    register, result_for, snippet, strip_comments, unmeasured,
)

from ._common import PLATFORM


@register(
    "apple.swiftui_sensitive_text_blur",
    "Story-Metadaten werden für Spoilerschutz nur geblurrt",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="Apple: SwiftUI blur und Accessibility",
    references=[
        "https://developer.apple.com/documentation/swiftui/view/blur(radius:opaque:)",
        "https://developer.apple.com/documentation/swiftui/view/accessibilityhidden(_:)",
    ],
    rationale=(
        "blur verändert laut Apple die Darstellung der View, nicht den Textwert. "
        "Eine an spoiler/shield/redact gekoppelte Blur-Kette an title/summary/tagline "
        "behält damit Story-Metadaten im Renderer. Gemessen wird dieses konkrete "
        "Quellcode-Muster, kein tatsächlicher VoiceOver- oder Übergangs-Leak. "
        "Advisory: Herkunft bereits projizierter Felder und übergeordnete "
        "Accessibility-Modifier müssen manuell geprüft werden. Dekorative Blurs, "
        "andere Metadatenpfade und Datenfluss über Helper bleiben ungemessen."
    ),
    self_tests=[
        SelfTestCase(name="gesund: projizierter Titel ohne Blur", files={
            "App/Episodes.swift": "Text(presentation.title.localized).font(.headline)\n",
        }, expect=Status.PASS),
        SelfTestCase(name="gesund: neutrale Ersatzanzeige", files={
            "App/Episodes.swift": 'Text("Episode").blur(radius: spoilerShield ? 0 : 0)\n',
        }, expect=Status.PASS),
        SelfTestCase(name="gesund: dekorativer Titelblur", files={
            "App/Episodes.swift": "Text(item.title).blur(radius: ambientBlur)\n",
        }, expect=Status.PASS),
        SelfTestCase(name="gesund: Kommentar und String sind kein Code", files={
            "App/Episodes.swift": '// Text(item.title).blur(radius: spoilerShield ? 8 : 0)\n'
            'let example = "Text(item.title).blur(radius: spoilerShield ? 8 : 0)"\n',
        }, expect=Status.UNMEASURED),
        SelfTestCase(name="gesund: benachbarter Blur gehört nicht zum Text", files={
            "App/Episodes.swift": "Text(item.title).font(.headline)\nImage(\"cover\").blur(radius: spoilerShield ? 8 : 0)\n",
        }, expect=Status.PASS),
        SelfTestCase(name="defekt: Titel trotz Spoilerschutz im Text", files={
            "App/Episodes.swift": "Text(item.title).font(.headline).blur(radius: shouldHideSpoilers ? 8 : 0)\n",
        }, expect=Status.FAIL, expect_finding_contains="Textwert"),
        SelfTestCase(name="defekt: Summary nach lokaler Bindung", files={
            "App/Episodes.swift": "if let summary = item.summary { Text(summary).lineLimit(2).blur(radius: spoilerShield ? 6 : 0) }\n",
        }, expect=Status.FAIL),
        SelfTestCase(name="defekt: verschachtelte Modifierargumente", files={
            "App/Episodes.swift": "Text(item.tagline).foregroundColor(Color.white.opacity(0.5)).blur(radius: max(0, redactStory ? 8 : 0))\n",
        }, expect=Status.FAIL),
        SelfTestCase(name="defekt: multiline Text und Blur", files={
            "App/Episodes.swift": "Text(\n item.displayTitle\n)\n.font(.headline)\n.blur(\n radius: shieldActive ? 8 : 0\n)\n",
        }, expect=Status.FAIL),
        SelfTestCase(name="gesund: keine Swift-Datei", files={}, expect=Status.UNMEASURED),
        SelfTestCase(name="gesund: Datei ohne Text-Prüfgegenstand", files={
            "App/Episodes.swift": "struct Episode {}\n",
        }, expect=Status.UNMEASURED),
    ],
)
def check_sensitive_text_blur(ctx: Context) -> CheckResult:
    check_id = "apple.swiftui_sensitive_text_blur"
    title = "Story-Metadaten werden für Spoilerschutz nur geblurrt"
    findings: list[Finding] = []
    measured = 0
    literal = re.compile(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"')
    field = re.compile(r"\b\w+(?:\s*\.\s*\w+)*\s*\.\s*(?:title|displayTitle|summary|tagline)\s*$")
    sensitive = re.compile(r"\b\w*(?:spoiler|shield|redact)\w*\b", re.I)

    for sf in ctx.files(".swift"):
        code = strip_comments(sf.text, sf.ext)
        code = literal.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), code)
        ends: dict[int, int] = {}
        stack: list[int] = []
        for offset, char in enumerate(code):
            if char == "(":
                stack.append(offset)
            elif char == ")" and stack:
                ends[stack.pop()] = offset
        aliases = {
            m.group(1) for m in re.finditer(
                r"\b(?:let|var)\s+(\w+)\s*=\s*\w+(?:\s*\.\s*\w+)*\s*\.\s*(?:title|displayTitle|summary|tagline)\b", code,
            )
        }
        for text in re.finditer(r"\bText\s*\(", code):
            opening = text.end() - 1
            if opening not in ends:
                continue
            measured += 1
            argument = code[opening + 1:ends[opening]].strip()
            if not field.fullmatch(argument) and argument not in aliases:
                continue
            cursor = ends[opening] + 1
            while modifier := re.match(r"\s*\.\s*(\w+)\s*\(", code[cursor:]):
                call = cursor + modifier.end() - 1
                if call not in ends:
                    break
                arguments = code[call + 1:ends[call]]
                if modifier.group(1) == "blur" and sensitive.search(arguments):
                    line = code.count("\n", 0, text.start()) + 1
                    findings.append(Finding(
                        check_id=check_id, severity=Severity.WARNING,
                        message="Spoiler-/Textschutz steuert nur Blur; der ursprüngliche Textwert bleibt im Renderer.",
                        file=sf.rel, line=line, evidence=snippet(sf.lines[line - 1]),
                        fix="Sensible Storyfelder vor Text/Placeholder/Accessibility durch sichere Labels ersetzen; VoiceOver und Übergänge am Gerät prüfen.",
                    ))
                    break
                cursor = ends[call] + 1
    if not measured:
        return unmeasured(check_id, title, "Keine direkt auswertbare SwiftUI-Text-View gefunden.", PLATFORM)
    return result_for(check_id, title, findings, measured, "SwiftUI-Text-Views", PLATFORM)
