"""
Dokumentations- und Playtest-Checks.

Fängt typische Fehler in Anleitungen und Vorlagen:
- Unquotierte Angle-Bracket-Platzhalter in Shell-Snippets (<HOST_IP> bricht die Shell)
- Trailing Whitespace in Markdown-Dateien (lässt git diff --check scheitern)
"""

from __future__ import annotations

import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, result_for, snippet,
)

SHELL_LANGS = {"bash", "sh", "zsh", "shell", "powershell", "pwsh", "cmd", "console"}


@register(
    "docs.unquoted_shell_placeholder",
    "Unquotierter Angle-Bracket-Platzhalter in Shell-Codeblock",
    platform="universal",
    severity=Severity.ERROR,
    guideline="GUIDELINES.md § Documentation — copy-paste-safe shell snippets",
    self_tests=[
        SelfTestCase(
            name="Unquotierter Platzhalter im Shell-Block",
            files={
                "docs/test.md": "```bash\n./app --join=<HOST_IP>\n```\n",
            },
            expect=Status.FAIL,
            expect_finding_contains="<HOST_IP>",
        ),
        SelfTestCase(
            name="Gequoteter oder sicherer Platzhalter",
            files={
                "docs/test.md": "```bash\n./app --join=\"<HOST_IP>\"\n```\n",
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="HTML-Block ignoriert",
            files={
                "docs/test.md": "```html\n<div><HOST_IP></div>\n```\n",
            },
            expect=Status.PASS,
        ),
    ],
)
def check_unquoted_shell_placeholders(ctx: Context) -> CheckResult:
    """Findet <PLATZHALTER> in ausführbaren Shell-Snippets, die nicht in Quotes
    stehen und bei direkter Shell-Eingabe als I/O-Redirection fehlinterpretiert werden."""
    title = "Unquotierter Angle-Bracket-Platzhalter in Shell-Codeblock"
    fenced_re = re.compile(r"^```([a-zA-Z0-9_-]+)?\s*$", re.MULTILINE)
    placeholder_re = re.compile(r"(?<![\"'])<([A-Z0-9_]{2,})>(?![\"'])")

    findings: list[Finding] = []
    units = 0

    for sf in ctx.files(".md"):
        units += 1
        lines = sf.lines
        in_shell_block = False
        block_lang = ""

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            fence_match = fenced_re.match(stripped)
            if fence_match:
                if in_shell_block:
                    in_shell_block = False
                    block_lang = ""
                else:
                    block_lang = (fence_match.group(1) or "").lower()
                    if block_lang in SHELL_LANGS:
                        in_shell_block = True
                continue

            if not in_shell_block:
                continue

            for match in placeholder_re.finditer(line):
                # Prüfen, ob der Treffer innerhalb von Anführungszeichen liegt
                prefix = line[:match.start()]
                double_quotes = prefix.count('"') - prefix.count(r'\"')
                single_quotes = prefix.count("'") - prefix.count(r"\'")
                if double_quotes % 2 == 1 or single_quotes % 2 == 1:
                    continue  # inner-string

                raw_token = match.group(0)
                findings.append(Finding(
                    check_id="docs.unquoted_shell_placeholder",
                    severity=Severity.ERROR,
                    message=f"Unquotierter Platzhalter {raw_token} im ```{block_lang}-Block bricht Shell/I/O-Redirection.",
                    file=sf.rel,
                    line=idx,
                    evidence=snippet(line),
                    fix=f"Platzhalter in Anführungszeichen setzen (z. B. \"{raw_token}\") oder konkretes Zahlenbeispiel verwenden.",
                    guideline="GUIDELINES.md § Documentation — copy-paste-safe shell snippets",
                ))

    return result_for("docs.unquoted_shell_placeholder", title, findings, units, "Markdown-Dateien")


@register(
    "docs.trailing_whitespace",
    "Trailing Whitespace in Markdown-Dateien",
    platform="universal",
    severity=Severity.WARNING,
    guideline="GUIDELINES.md § Documentation — git diff --check clean",
    self_tests=[
        SelfTestCase(
            name="Trailing Whitespace in Liste",
            files={
                "docs/test.md": "- [ ] Punkt\n-  \n- [ ] Weiterer Punkt\n",
            },
            expect=Status.FAIL,
            expect_finding_contains="Trailing Whitespace",
        ),
        SelfTestCase(
            name="Saubere Markdown-Datei",
            files={
                "docs/test.md": "- [ ] Punkt\n-\n- [ ] Weiterer Punkt\n",
            },
            expect=Status.PASS,
        ),
    ],
)
def check_trailing_whitespace(ctx: Context) -> CheckResult:
    """Findet Zeilen mit überflüssigem Whitespace am Zeilenende in Markdown-Dateien,
    die `git diff --check` fehlschlagen lassen."""
    title = "Trailing Whitespace in Markdown-Dateien"
    trailing_re = re.compile(r"[ \t]+$")
    findings: list[Finding] = []
    units = 0

    for sf in ctx.files(".md"):
        units += 1
        for idx, line in enumerate(sf.lines, start=1):
            if trailing_re.search(line):
                findings.append(Finding(
                    check_id="docs.trailing_whitespace",
                    severity=Severity.WARNING,
                    message="Trailing Whitespace am Zeilenende (bricht git diff --check).",
                    file=sf.rel,
                    line=idx,
                    evidence=snippet(line),
                    fix="Leerzeichen am Zeilenende entfernen.",
                    guideline="GUIDELINES.md § Documentation — git diff --check clean",
                ))

    return result_for("docs.trailing_whitespace", title, findings, units, "Markdown-Dateien")
