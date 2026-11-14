"""Web-Check: :checked-Input mit Akzent-Hintergrund ohne Vordergrundfarbe.

Aus `rules.py` ausgelagert (Modulgröße); ID, Meldung und Proben unverändert.
"""

from __future__ import annotations

import re

from ruttla.checks.web.rules import PLATFORM, WEB_STYLE
from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, unmeasured, result_for, snippet, strip_comments,
)

@register(
    "web.checked_input_accent_without_foreground",
    ":checked-Input mit Akzent-Hintergrund ohne passende Vordergrundfarbe (color)",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5",
    self_tests=[
        SelfTestCase(
            name="checked ohne color",
            files={
                "src/a.css": (
                    ".checkbox-label input:checked {\n"
                    "  background-color: var(--accent);\n"
                    "  border-color: var(--accent);\n"
                    "}\n"
                )
            },
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="checked mit color",
            files={
                "src/a.css": (
                    ".checkbox-label input:checked {\n"
                    "  background-color: var(--accent);\n"
                    "  border-color: var(--accent);\n"
                    "  color: var(--accent-ink);\n"
                    "}\n"
                )
            },
            expect=Status.PASS,
        ),
    ],
)
def check_checked_input_accent_without_foreground(ctx: Context) -> CheckResult:
    """Setzt ein eigenes Checkbox-/Radio-Input (`appearance: none`) bei `:checked`
    `background-color: var(--accent)`, ohne `color` auf die Kontrastfarbe
    (`var(--accent-ink)` / `#fff`) umzustellen, messen Laufzeit-Kontrastprüfer
    (`getComputedStyle(input)`) `var(--ink)` gegen `var(--accent)` (z. B. 2,56:1)."""
    title = ":checked-Input mit Akzent-Hintergrund ohne passende Vordergrundfarbe (color)"
    files = ctx.files(*WEB_STYLE)
    if not files:
        return unmeasured("web.checked_input_accent_without_foreground", title,
                          "Keine Stylesheet-Dateien gefunden.", PLATFORM)

    rule_re = re.compile(r"([^{};]+:checked(?![\w:-])\s*)\{([^}]*)\}", re.M)
    bg_re = re.compile(r"\bbackground(?:-color)?\s*:\s*([^;}\n]+)")
    fg_re = re.compile(r"(?<![-\w])color\s*:\s*([^;}\n]+)")

    findings: list[Finding] = []
    measured = 0
    for sf in files:
        body = strip_comments(sf.text, sf.ext)
        for m in rule_re.finditer(body):
            selector = m.group(1).strip()
            if "::before" in selector or "::after" in selector:
                continue
            block = m.group(2)
            bg_match = bg_re.search(block)
            if not bg_match:
                continue
            bg_val = bg_match.group(1).strip().lower()
            if bg_val in ("transparent", "none", "inherit", "initial", "unset"):
                continue
            measured += 1
            if fg_re.search(block):
                continue
            line_no = body.count("\n", 0, m.start()) + 1
            raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else selector
            findings.append(Finding(
                check_id="web.checked_input_accent_without_foreground",
                severity=Severity.WARNING,
                message=f"'{selector}' setzt Hintergrund '{bg_val}', aber keine "
                        "kontrastreiche Vordergrundfarbe (color) — bricht WCAG-Messung am <input>.",
                file=sf.rel,
                line=line_no,
                evidence=snippet(raw),
                fix="Im :checked-Block explizit `color: var(--accent-ink)` (bzw. passende "
                    "Kontrastfarbe zum Akzent-Hintergrund) ergänzen.",
                guideline="CODE_QUALITY_GUIDELINES_WEB.md § 5",
            ))

    if measured == 0:
        return unmeasured("web.checked_input_accent_without_foreground", title,
                          "Keine :checked-Regel mit Hintergrundfarbe gefunden.", PLATFORM)
    return result_for("web.checked_input_accent_without_foreground", title, findings,
                      measured, ":checked-Hintergrundregeln", PLATFORM)
