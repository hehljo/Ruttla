"""
Dokumentations- und Playtest-Checks.

Fängt typische Fehler in Anleitungen und Vorlagen:
- Unquotierte Angle-Bracket-Platzhalter in Shell-Snippets (<HOST_IP> bricht die Shell)
- Trailing Whitespace in Markdown-Dateien (lässt git diff --check scheitern)
- Dokumentierte Ergebniswerte, die der Code nirgends als Literal erzeugt
"""

from __future__ import annotations

import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, result_for, snippet, strip_comments, unmeasured,
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


# --- Dokumentierte Ergebniswerte gegen erzeugte Literale ---------------------
RESULT_ID = "docs.result_value_not_emitted"
RESULT_TITLE = "Dokumentierter Ergebniswert kommt im Code nicht als Literal vor"
SOURCE_EXTS = (".gd", ".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".cs", ".swift", ".rs", ".go", ".kt", ".java", ".dart")
# Eine Werteliste in einer Tabellenzelle, in Klammern hinter einem Ergebniswort:
# `Grund (`a` / `b`)`. Ohne das Ergebniswort trafen im Sweep über 40 lokale
# Repos fast nur Modul-, Befehls- und Funktionslisten (`add` / `sync`).
_VALUE_LIST = re.compile(
    r"(?i:\b(?:ergebnis|grund|ursache|result|reason|outcome|status|zustand|ausgang)\w*)[ \t]*\("
    r"[ \t]*(`[a-z][a-z0-9_]*`(?:[ \t]*/[ \t]*`[a-z][a-z0-9_]*`)+)")
_LITERAL = re.compile(r"""["']([a-z][a-z0-9_]*)["']""")

_RESULT_DOC = (
    "| Rd. | Ergebnis (`hunter` / `drunks` / `aborted`) | Grund (`last_catch` / `timeout` / `hunter_disconnect`) |\n"
    "|---|---|---|\n| 1 | | |\n"
)
_RESULT_CODE = (
    "func _finish(reason: String) -> void:\n"
    "\tvar winner := \"hunter\" if reason == \"last_catch\" else \"drunks\"\n"
    "\tif reason in [\"timeout\", \"hunter_disconnect\"]:\n"
    "\t\t_emit(\"aborted\")\n"
)


@register(
    RESULT_ID, RESULT_TITLE,
    platform="universal",
    severity=Severity.WARNING,
    guideline="GUIDELINES.md § Documentation — Enum- & Literal-Abgleich",
    rationale="Belegt (Drink-and-Hide DH003-LL-023): die Playtest-Tabelle nannte `disconnect`, der Code "
              "erzeugt hunter_disconnect und last_drunk_disconnect. Gemessen werden nur Wertelisten in "
              "Tabellenzellen (`a` / `b`); berechnete Werte (Formatstrings) sieht die Regel nicht.",
    self_tests=[
        SelfTestCase("gesund: alle Werte als Literal im Code",
                     {"docs/playtest.md": _RESULT_DOC, "scripts/match.gd": _RESULT_CODE}, Status.PASS),
        SelfTestCase("defekt: zusammengefasster Wert",
                     {"docs/playtest.md": _RESULT_DOC.replace("hunter_disconnect", "disconnect"),
                      "scripts/match.gd": _RESULT_CODE},
                     Status.FAIL, expect_finding_contains="disconnect"),
        SelfTestCase("gesund: Wert nur als Teil eines Bezeichners zählt nicht als Treffer, Literal schon",
                     {"docs/playtest.md": "| Status (`ready` / `idle`) |\n|---|\n",
                      "src/a.py": "STATE = 'ready'\nother = \"idle\"\n"}, Status.PASS),
        SelfTestCase("defekt: Wert steht nur im Kommentar",
                     {"docs/playtest.md": "| Status (`ready` / `idle`) |\n|---|\n",
                      "src/a.py": "STATE = 'ready'\n# früher: 'idle'\n"},
                     Status.FAIL, expect_finding_contains="idle"),
        SelfTestCase("ungemessen: Bezeichnerliste ohne Ergebniswort",
                     {"docs/arch.md": "| Modul | `handlers` / `polling` |\n|---|---|\n", "scripts/match.gd": _RESULT_CODE},
                     Status.UNMEASURED),
        SelfTestCase("ungemessen: kein Quellcode", {"docs/playtest.md": _RESULT_DOC}, Status.UNMEASURED),
        SelfTestCase("ungemessen: keine Werteliste",
                     {"docs/playtest.md": "| Rd. | Notiz |\n|---|---|\n", "scripts/match.gd": _RESULT_CODE},
                     Status.UNMEASURED),
    ],
)
def check_result_value_not_emitted(ctx: Context) -> CheckResult:
    literals: set[str] = set()
    sources = ctx.files(*SOURCE_EXTS)
    for sf in sources:
        literals.update(_LITERAL.findall(strip_comments(sf.text, sf.ext)))
    if not sources:
        return unmeasured(RESULT_ID, RESULT_TITLE, "Kein Quellcode, gegen den dokumentierte Werte geprüft werden könnten.")
    findings, units = [], 0
    for sf in ctx.files(".md"):
        for no, line in enumerate(sf.lines, 1):
            if not line.lstrip().startswith("|"):
                continue
            for m in _VALUE_LIST.finditer(line):
                for value in re.findall(r"`([a-z][a-z0-9_]*)`", m.group(1)):
                    units += 1
                    if value in literals:
                        continue
                    findings.append(Finding(RESULT_ID, Severity.WARNING,
                        f"Dokumentierter Wert `{value}` kommt in keinem Quelltext als String-Literal vor — "
                        "Log oder Protokoll zeigen dann einen anderen Text als die Anleitung.",
                        file=sf.rel, line=no, evidence=snippet(m.group(1)),
                        fix="Den tatsächlich erzeugten Wert aus Produzent/Serializer übernehmen; zusammengefasste "
                            "Werte als mehrere exakte Werte auflisten.",
                        guideline="GUIDELINES.md § Documentation — Enum- & Literal-Abgleich"))
    if units == 0:
        return unmeasured(RESULT_ID, RESULT_TITLE, "Keine Werteliste Ergebnis (`a` / `b`) in einer Markdown-Tabelle gefunden.")
    return result_for(RESULT_ID, RESULT_TITLE, findings, units, "dokumentierte Tabellenwerte")
