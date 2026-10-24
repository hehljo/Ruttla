"""Netlify deploy target selection in executable command contexts.

Python is needed for the *structure*, not negative matching: ruttla-rule/0
supports match.exclude, but cannot select JSON scripts (excluding description,
config and dependency values), parse shell argument boundaries or inventory
extensionless Makefiles. A text-only approximation caused false positives on
quoted examples. No target shell, package script or Netlify CLI is executed.
"""
from __future__ import annotations

import json
from pathlib import PurePosixPath
import re
import shlex

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status,
    register, result_for,
)
from ruttla.discovery import is_rule_definition_file

CHECK_ID = "web.netlify_cli_deploy_without_site"
TITLE = "Netlify-Deploy ohne explizites Site-Ziel"
GUIDELINE = "CODE_QUALITY_GUIDELINES_WEB.md § Deploy-Ziel ausdrücklich festlegen"
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_NPX = re.compile(r"^netlify(?:-cli)?(?:@[A-Za-z0-9_.^~+\-]+)?$")
_SHELL_EXTS = {".sh", ".bash", ".zsh", ".ksh"}
_MAKE_NAMES = {"Makefile", "makefile", "GNUmakefile"}


def _tokens(line: str) -> list[list[str]]:
    lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    commands: list[list[str]] = [[]]
    for token in lexer:
        if token and all(c in ";&|()" for c in token):
            commands.append([])
        else:
            commands[-1].append(token)
    return commands


def _deploy(tokens: list[str]) -> bool:
    index = 0
    while index < len(tokens):
        token = tokens[index].lstrip("@") if index == 0 else tokens[index]
        if _ASSIGN.match(token) or token in ("env", "command", "exec", "then", "do"):
            index += 1
            continue
        if token == "npx":
            index += 1
            if index < len(tokens) and tokens[index] in ("-y", "--yes"):
                index += 1
            if index >= len(tokens) or not _NPX.fullmatch(tokens[index]):
                return False
        elif token != "netlify":
            return False
        return index + 1 < len(tokens) and tokens[index + 1] == "deploy"
    return False


def _has_site(tokens: list[str]) -> bool:
    # A quoted --message='use --site next time' must not become an option.
    for index, token in enumerate(tokens):
        if token.startswith("--site=") and token[len("--site="):]:
            return True
        if token == "--site" and index + 1 < len(tokens):
            value = tokens[index + 1]
            if value and not value.startswith("-"):
                return True
    return False


def _site_assignment(tokens: list[str]) -> bool:
    for token in tokens:
        token = token.lstrip("@")
        if token in ("env", "export"):
            continue
        if not _ASSIGN.match(token):
            return False
        if token.startswith("NETLIFY_SITE_ID=") and token[len("NETLIFY_SITE_ID="):]:
            return True
    return False


def _logical_lines(text: str):
    pending = ""
    first = 1
    heredoc = None
    for number, line in enumerate(text.splitlines(), 1):
        if heredoc is not None:
            if line.lstrip("\t") == heredoc:
                heredoc = None
            continue
        if not pending:
            first = number
        # Backslash continuation is a single command, still reported at its start.
        if line.endswith("\\") and not line.endswith("\\\\"):
            pending += line[:-1] + " "
            continue
        complete = pending + line
        # Literal, single heredocs are data. Complex shell expansion is outside
        # this bounded command parser, and never executed by the check.
        heredoc = _heredoc_marker(complete)
        yield first, complete
        pending = ""
    if pending:
        yield first, pending


def _heredoc_marker(line: str) -> str | None:
    quote = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            continue
        if char == "#" and (index == 0 or line[index - 1].isspace()):
            return None
        if line.startswith("<<", index):
            # Only a literal delimiter in unquoted shell syntax counts.
            match = re.match(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", line[index:])
            if match:
                return match.group(2)
    return None


def _members(text: str, start: int = 0):
    """Locations of object values in already validated JSON, without guessing keys."""
    decoder = json.JSONDecoder()
    position = start + 1
    while True:
        while text[position].isspace():
            position += 1
        if text[position] == "}":
            return
        key, position = decoder.raw_decode(text, position)
        while text[position].isspace():
            position += 1
        position += 1  # colon
        while text[position].isspace():
            position += 1
        value_start = position
        value, position = decoder.raw_decode(text, position)
        yield key, value, value_start
        while text[position].isspace():
            position += 1
        if text[position] == "}":
            return
        position += 1  # comma


def _script_sources(text: str):
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("scripts"), dict):
        return
    start = len(text) - len(text.lstrip())
    offset = {key: pos for key, _, pos in _members(text, start)}["scripts"]
    scripts = {key: (value, pos) for key, value, pos in _members(text, offset)}
    for value, position in scripts.values():
        if isinstance(value, str):
            yield text.count("\n", 0, position) + 1, value


@register(
    CHECK_ID, TITLE, platform="web", severity=Severity.WARNING,
    guideline=GUIDELINE, tags=("netlify", "deploy", "site-selection"),
    references=("https://cli.netlify.com/commands/deploy/",
                "https://docs.netlify.com/cli/get-started/#link-and-unlink-sites"),
    rationale=(
        "Reproduced on 23.10.2026: a CLI deploy without an explicit target "
        "created an unintended new site. --site or an inline NETLIFY_SITE_ID "
        "assignment makes the target visible in the command. Warning only: "
        ".netlify/state.json or inherited environment may already select a "
        "site; their absence is not proven. Measures direct shell/Make recipes "
        "and package.json scripts, including npx [-y] netlify-cli@version. "
        "Dynamic commands, heredoc bodies and general shell data flow are not "
        "a complete shell execution analysis. No deploy is performed."
    ),
    self_tests=[
        SelfTestCase("gesund: Site-Option", {"deploy.sh": "netlify deploy --site sample\n"}, Status.PASS),
        SelfTestCase("gesund: Site-Umgebung", {"deploy.sh": "NETLIFY_SITE_ID=sample npx -y netlify-cli@23.0.0 deploy\n"}, Status.PASS),
        SelfTestCase("defekt: direkt", {"deploy.sh": "netlify deploy --prod\n"}, Status.FAIL),
        SelfTestCase("defekt: npx", {"package.json": '{"scripts":{"ship":"npx -y netlify-cli@23.0.0 deploy"}}'}, Status.FAIL),
        SelfTestCase("defekt: Makefile", {"Makefile": "ship:\n\tnetlify deploy\n"}, Status.FAIL),
        SelfTestCase("gesund: JSON-Beschreibung ist kein Script", {"package.json": '{"description":"netlify deploy", "scripts":{"ship":"netlify deploy --site sample"}}'}, Status.PASS),
        SelfTestCase("ungemessen: keine Aufrufe", {"deploy.sh": '# netlify deploy\necho "netlify deploy"\n'}, Status.UNMEASURED),
        SelfTestCase("defekt: Site nur in anderer Zeile", {"deploy.sh": "export NETLIFY_SITE_ID=sample\nnetlify deploy\n"}, Status.FAIL),
    ],
)
def check_netlify_deploy(ctx: Context) -> CheckResult:
    findings = []
    units = 0
    incomplete = []
    for source in ctx.all_files():
        path = PurePosixPath(source.rel)
        if is_rule_definition_file(source):
            continue
        shell_shebang = (not source.ext and source.text.startswith("#!")
                         and re.search(r"(?:^|[/\s])(?:ba|z|k)?sh(?:\s|$)", source.lines[0]))
        if source.ext in _SHELL_EXTS or shell_shebang or path.name in _MAKE_NAMES or source.ext == ".mk":
            sources = [(0, source.text)]
        elif path.name == "package.json":
            try:
                sources = list(_script_sources(source.text))
            except (ValueError, RecursionError):
                incomplete.append(source.rel)
                continue
        else:
            continue
        for offset, text in sources:
            for number, line in _logical_lines(text):
                if "netlify" not in line:
                    continue
                try:
                    commands = _tokens(line)
                except ValueError:
                    incomplete.append(source.rel)
                    continue
                site_env = any(_site_assignment(command) for command in commands)
                for command in commands:
                    if not _deploy(command):
                        continue
                    units += 1
                    if site_env or _has_site(command):
                        continue
                    findings.append(Finding(
                        CHECK_ID, Severity.WARNING,
                        "netlify deploy ohne --site oder NETLIFY_SITE_ID in derselben Befehlszeile; CLI könnte eine andere oder neue Site wählen.",
                        file=source.rel, line=offset or number, evidence="netlify deploy (Ziel nicht explizit)",
                        fix="Die bestehende Site mit --site auswählen oder NETLIFY_SITE_ID in derselben Befehlszeile setzen. Eine lokale .netlify/state.json kann bereits verknüpfen; Ziel vor dem Deploy prüfen.",
                        guideline=GUIDELINE,
                    ))
    if incomplete and not findings:
        return CheckResult(CHECK_ID, Status.UNMEASURED, TITLE,
                           reason="JSON/Befehlszeile nicht vollständig auswertbar: " + ", ".join(sorted(set(incomplete))),
                           units_examined=units, unit_label="Netlify-Deploy-Aufrufe", platform="web")
    return result_for(CHECK_ID, TITLE, findings, units, "Netlify-Deploy-Aufrufe", platform="web")
