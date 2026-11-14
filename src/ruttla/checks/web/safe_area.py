"""Source advisory for adding one physical safe-area inset twice in a CSS box.

Observed in a tablet dock: margin shorthand already owned the bottom inset,
while padding-bottom added it again. This checks declaration-local ownership,
not computed geometry, native scroll insets or device safety.
"""
from __future__ import annotations

import re

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status,
    register, result_for, strip_comments,
)

ID = "web.safe_area_margin_padding_doubled"
TITLE = "Dasselbe Safe-Area-Inset in Außen- und Innenabstand"
GUIDELINE = "docs/GUIDELINES.md § Safe-area ownership"
EDGES = ("top", "right", "bottom", "left")
ENV = re.compile(r"env\(\s*safe-area-inset-(top|right|bottom|left)\s*(?:,\s*\d+(?:\.\d+)?(?:px|pt|rem|em)?)?\s*\)", re.I)
PROPERTY = re.compile(r"(margin|padding)(?:-(top|right|bottom|left))?", re.I)
STRINGS = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*' ''', re.X)
HEALTHY = ".dock { margin: 0 0 max(12px, env(safe-area-inset-bottom, 0px)); padding-bottom: 6px; }"


def _tokens(value: str) -> list[str]:
    """Split shorthand values without splitting whitespace inside CSS functions."""
    depth, start, values = 0, 0, []
    for index, char in enumerate(value):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char.isspace() and depth == 0:
            if value[start:index].strip():
                values.append(value[start:index].strip())
            start = index + 1
        if depth < 0:
            return []
    if depth:
        return []
    if value[start:].strip():
        values.append(value[start:].strip())
    return values


def _full_inset(value: str, edge: str) -> bool | None:
    """Only direct env, positive calc sums and max wrappers have known ownership.

    Variable expansion, subtraction, multiplication and clamp/min are deliberately
    unknown; this advisory does not implement CSS math or choose safe inset sizes.
    """
    matches = list(ENV.finditer(value))
    if not matches:
        return None if re.search(r"\b(?:var|env)\s*\(", value, re.I) else False
    rest = ENV.sub("0px", value)
    if (len(matches) != 1 or matches[0][1].lower() != edge or
            re.search(r"[-*/]|\b(?:var|min|clamp|env)\s*\(", rest, re.I) or
            re.search(r"\b(?!calc\b|max\b)[a-z]+\s*\(", rest, re.I)):
        return None
    return True


@register(
    ID, TITLE, platform="web", severity=Severity.WARNING, guideline=GUIDELINE,
    references=("https://www.w3.org/TR/css-env-1/#safe-area-insets",
                "https://www.w3.org/TR/css-box-3/#box-model"),
    self_tests=[
        SelfTestCase("Single inset owner", {"src/a.css": HEALTHY}, Status.PASS),
        SelfTestCase("Bottom inset added in padding too", {"src/a.css": HEALTHY.replace(
            "padding-bottom: 6px", "padding-bottom: env(safe-area-inset-bottom, 0px)")}, Status.FAIL),
        SelfTestCase("Top inset added twice", {"src/a.css": ".bar { margin-top: env(safe-area-inset-top); padding-top: env(safe-area-inset-top); }"}, Status.FAIL),
        SelfTestCase("Separate boxes", {"src/a.css": ".a { margin-bottom: env(safe-area-inset-bottom); } .b { padding-bottom: env(safe-area-inset-bottom); }"}, Status.PASS),
        SelfTestCase("Later padding override", {"src/a.css": HEALTHY.replace(
            "padding-bottom: 6px", "padding-bottom: env(safe-area-inset-bottom); padding: 6px")}, Status.PASS),
        SelfTestCase("No inset subject", {"src/a.css": ".bar { padding: 6px; }"}, Status.UNMEASURED),
        SelfTestCase("Only unresolved variables", {"src/a.css": ".bar { margin: var(--spacing); padding: var(--safe-area-inset-bottom); }"}, Status.UNMEASURED),
    ],
)
def check_safe_area(ctx: Context) -> CheckResult:
    findings, measured = [], 0
    for source in ctx.files(".css"):
        code = strip_comments(source.text, source.ext)
        code = STRINGS.sub(lambda match: re.sub(r"[^\n]", " ", match[0]), code)
        for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", code):
            selector, body = block[1].strip(), block[2]
            if selector.startswith("@") or re.search(r"(?:^|;)\s*(?:all|(?:margin|padding)-(?:block|inline)(?:-start|-end)?)\s*:", body, re.I):
                continue  # Logical properties/cross-cascade ownership need computed style.
            state = {}
            for declaration in re.finditer(r"(?:^|;)\s*([\w-]+)\s*:\s*([^;]*)", body):
                prop = PROPERTY.fullmatch(declaration[1])
                if not prop:
                    continue
                important = bool(re.search(r"!\s*important\s*$", declaration[2], re.I))
                value = re.sub(r"!\s*important\s*$", "", declaration[2], flags=re.I).strip()
                tokens = _tokens(value)
                expanded = ([tokens[0], tokens[0], tokens[0], tokens[0]] if len(tokens) == 1 else
                            [tokens[0], tokens[1], tokens[0], tokens[1]] if len(tokens) == 2 else
                            [tokens[0], tokens[1], tokens[2], tokens[1]] if len(tokens) == 3 else tokens)
                if not prop[2] and (len(expanded) != 4 or "var(" in value.lower()):
                    expanded = ["var(--unknown)"] * 4
                entries = [(prop[2].lower(), value)] if prop[2] else list(zip(EDGES, expanded))
                for edge, expression in entries:
                    key = (prop[1].lower(), edge)
                    if key not in state or important or not state[key][1]:
                        state[key] = (_full_inset(expression, edge), important, declaration.start(1))
            for edge in EDGES:
                margin, padding = state.get(("margin", edge)), state.get(("padding", edge))
                if not any(item and item[0] is True for item in (margin, padding)):
                    continue
                measured += 1
                if not (margin and padding and margin[0] is True and padding[0] is True):
                    continue
                position = block.start(2) + padding[2]
                findings.append(Finding(
                    check_id=ID, severity=Severity.WARNING, file=source.rel,
                    line=code.count("\n", 0, position) + 1,
                    message=f"{selector[:80]}: safe-area-inset-{edge} steckt in margin und padding derselben Seite.",
                    evidence=f"margin-{edge} + padding-{edge}: env(safe-area-inset-{edge})",
                    fix="Safe-Area-Inset einem Abstand zuweisen; zweiten Zuschlag entfernen. Native Inset-Automatik und tatsächliche Gerätegeometrie separat prüfen.",
                    guideline=GUIDELINE,
                ))
    return result_for(ID, TITLE, findings, measured, "lokal auflösbare Safe-Area-Seiten", "web")
