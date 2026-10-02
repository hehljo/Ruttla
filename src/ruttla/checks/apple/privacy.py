"""SwiftUI: a visual blur does not remove sensitive text from a renderer."""

from __future__ import annotations

import re

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status,
    register, result_for, snippet, strip_comments, unmeasured,
)

from ._common import PLATFORM


def _alias_bindings(code: str, ends: dict[int, int], field: re.Pattern):
    """Lexical bindings for the narrow direct-field pattern, not type/dataflow.

    Comments/string contents are already masked. A literal or parameter with
    the same name must shadow an outer story alias, rather than inheriting it.
    """
    scopes = [0] * (len(code) + 1)
    paths = {0: (0,)}
    stack = [0]
    for offset, char in enumerate(code):
        scopes[offset] = stack[-1]
        if char == "{":
            scope = offset + 1
            paths[scope] = paths[stack[-1]] + (scope,)
            stack.append(scope)
        elif char == "}" and len(stack) > 1:
            stack.pop()
    bindings: dict[str, list[tuple[int, int, bool]]] = {}

    def add(name, position, scope, sensitive):
        bindings.setdefault(name, []).append((position, scope, sensitive))

    declaration = re.compile(r"\b(?:let|var)\s+(\w+)(?:\s*:[^=\n{}]+)?\s*=")
    for match in declaration.finditer(code):
        scope = scopes[match.start()]
        stop = re.search(r"[;,\n{}]", code[match.end():])
        end = match.end() + stop.start() if stop else len(code)
        sensitive = bool(field.fullmatch(code[match.end():end].strip()))
        # A simple if/while-let introduces a binding only in its body.
        if re.search(r"\b(?:if|while)\s*$", code[:match.start()]):
            body = code.find("{", match.end())
            if body >= 0:
                scope = body + 1
        add(match.group(1), match.start(), scope, sensitive)

    # Parameters are unknown input, not aliases of an identically named member.
    # Generic signatures/capture lists/helper dataflow stay outside this pattern.
    for match in re.finditer(r"\b(?:func\s+\w+|init)\s*\(", code):
        opening = match.end() - 1
        if opening not in ends:
            continue
        body = code.find("{", ends[opening] + 1)
        if body < 0 or scopes[body] != scopes[match.start()]:
            continue
        parameters = code[opening + 1:ends[opening]]
        for param in re.finditer(r"(?:^|,)\s*(?:(?:_|\w+)\s+)?(\w+)\s*:", parameters):
            add(param.group(1), body, body + 1, False)
    for match in re.finditer(r"\{\s*((?:\w+\s*,\s*)*\w+)\s+in\b", code):
        for name in re.findall(r"\w+", match.group(1)):
            add(name, match.start(), match.start() + 1, False)
    return scopes, paths, bindings


def _is_story_alias(name: str, position: int, scopes, paths, bindings) -> bool:
    visible = [binding for binding in bindings.get(name, ())
               if binding[0] < position and binding[1] in paths[scopes[position]]]
    if not visible:
        return False
    nearest = max(visible, key=lambda binding: (len(paths[binding[1]]), binding[0]))
    return nearest[2]


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
        "andere Metadatenpfade und Datenfluss über Helper bleiben ungemessen. "
        "Einfache lokale Aliasse werden nach Block, Reihenfolge und Schattenbindung "
        "zugeordnet; das ist keine vollständige Swift-Namens-/Typauflösung."
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
        SelfTestCase(name="gesund: gleichnamige Bindung in anderer View", files={
            "App/Episodes.swift": 'struct A { let summary = item.summary }\n'
            'struct B { let summary = "Neutral"; var body: some View { Text(summary).blur(radius: spoilerShield ? 8 : 0) } }\n',
        }, expect=Status.PASS),
        SelfTestCase(name="gesund: lokaler Literal-Schatten", files={
            "App/Episodes.swift": 'func view() { let title = item.title; do { let title = "Neutral"; Text(title).blur(radius: spoilerShield ? 8 : 0) } }\n',
        }, expect=Status.PASS),
        SelfTestCase(name="gesund: if-let gilt nur im eigenen Block", files={
            "App/Episodes.swift": 'func view(summary: String) { if let summary = item.summary { Image("cover") }; Text(summary).blur(radius: spoilerShield ? 8 : 0) }\n',
        }, expect=Status.PASS),
        SelfTestCase(name="gesund: spätere Bindung ist nicht die Textquelle", files={
            "App/Episodes.swift": 'func view(title: String) { Text(title).blur(radius: spoilerShield ? 8 : 0) }\nlet title = item.title\n',
        }, expect=Status.PASS),
        SelfTestCase(name="gesund: Funktionsparameter überschattet Member", files={
            "App/Episodes.swift": 'struct A { let title = item.title; func view(title: String) { Text(title).blur(radius: spoilerShield ? 8 : 0) } }\n',
        }, expect=Status.PASS),
        SelfTestCase(name="gesund: Closureparameter überschattet Member", files={
            "App/Episodes.swift": 'struct A { let title = item.title; func view() { items.map { title in Text(title).blur(radius: spoilerShield ? 8 : 0) } } }\n',
        }, expect=Status.PASS),
        SelfTestCase(name="defekt: äußerer Alias im verschachtelten Block", files={
            "App/Episodes.swift": 'func view() { let summary = item.summary; VStack { Text(summary).blur(radius: spoilerShield ? 8 : 0) } }\n',
        }, expect=Status.FAIL),
        SelfTestCase(name="defekt: if-let im verschachtelten Renderer", files={
            "App/Episodes.swift": 'if let summary = item.summary { VStack { Text(summary).blur(radius: spoilerShield ? 8 : 0) } }\n',
        }, expect=Status.FAIL),
        SelfTestCase(name="defekt: Protokollparameter ist kein Schatten im Folgetyp", files={
            "App/Episodes.swift": 'protocol P { func view(title: String) }\nlet title = item.title\n'
            'struct B { var body: some View { Text(title).blur(radius: spoilerShield ? 8 : 0) } }\n',
        }, expect=Status.FAIL),
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
        scopes, paths, bindings = _alias_bindings(code, ends, field)
        for text in re.finditer(r"\bText\s*\(", code):
            opening = text.end() - 1
            if opening not in ends:
                continue
            measured += 1
            argument = code[opening + 1:ends[opening]].strip()
            if not field.fullmatch(argument) and not _is_story_alias(argument, text.start(), scopes, paths, bindings):
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
