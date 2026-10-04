"""Quadratische Regex-Laufzeit durch ``^\\s*`` im MULTILINE-Modus.

Mit ``re.M`` ist jeder Zeilenanfang ein Startpunkt. ``\\s`` frisst auch
Zeilenumbrüche: an jedem Zeilenanfang einer Leerzeilenstrecke läuft ``\\s*``
bis an deren Ende, scheitert und versucht es am nächsten Zeilenanfang erneut.
Das ist quadratisch in der Länge der Strecke.

Belegt am 2026-10-04 an Ruttla selbst: 40 KB Leerzeilen → 2,0 s je Muster,
80 KB → 8,1 s; mit ``[ \\t]*`` 0,00 s. Ein Gate, das fremde Repos liest, hängt
damit an einer Datei voller Leerzeilen.
"""
from __future__ import annotations

import ast
import re

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status,
    register, result_for, unmeasured,
)

_CHECK_ID = "python.regex_quadratic_line_start"
_TITLE = "Zeilenanfang + \\s* am Musteranfang läuft quadratisch über Leerzeilen"
_GUIDELINE = "GUIDELINES.md § Python regex"

# Position des flags-Arguments je re-Funktion (0-basiert).
_FLAG_POS = {"compile": 1, "search": 2, "match": 2, "fullmatch": 2, "findall": 2,
             "finditer": 2, "split": 3, "sub": 4, "subn": 4}
_INLINE_M = re.compile(r"^\(\?[aiLsux]*m[aiLsux]*\)")
_UNKNOWN = "\x00"


def _literal(node: ast.AST) -> str | None:
    """Mustertext; nicht auflösbare Teile werden zu einem Platzhalter."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        if left is None and right is None:
            return None
        return (left if left is not None else _UNKNOWN) + (right if right is not None else _UNKNOWN)
    return None


def _has_multiline_flag(node: ast.AST | None) -> bool:
    if node is None:
        return False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr in ("M", "MULTILINE"):
            return True
        if isinstance(sub, ast.Name) and sub.id in ("M", "MULTILINE"):
            return True
    return False


_GROUP_OPEN = re.compile(r"\((?:\?(?::|P<\w+>|<\w+>|[aiLmsux]+:))?")
_WS_QUANT = re.compile(r"\\s[*+]")


def _after_anchor(pattern: str, j: int) -> bool:
    """Folgt nach Position ``j`` (Klammern übersprungen) ``\\s*``/``\\s+``?"""
    while j < len(pattern):
        if pattern[j] == ")":
            j += 1
            continue
        m = _GROUP_OPEN.match(pattern, j)
        if m and m.end() > j:
            j = m.end()
            continue
        break
    return bool(_WS_QUANT.match(pattern, j))


def quadratic_line_start(pattern: str, multiline: bool) -> bool:
    """Beginnt ein Zweig des Musters mit einem Zeilenanfang (``^`` unter
    MULTILINE oder ein ``\\n``) direkt gefolgt von ``\\s*``/``\\s+``?

    Nur am ANFANG eines Zweigs ist jeder Zeilenanfang ein Startpunkt; steht
    davor fester Text (``foo\\n\\s*``), gibt es nur so viele Starts wie ``foo``.
    """
    inline = _INLINE_M.match(pattern)
    i = inline.end() if inline else 0
    leading = True            # nächstes Zeichen steht am Anfang eines Zweigs
    stack: list[bool] = []    # je offene Gruppe: am Zweiganfang geöffnet?
    in_class = False
    while i < len(pattern):
        ch = pattern[i]
        if in_class:
            if ch == "\\":
                i += 2
                continue
            if ch == "]":
                in_class = False
            i += 1
            continue
        if ch == "\\":
            if leading and pattern[i + 1:i + 2] == "n" and _after_anchor(pattern, i + 2):
                return True
            leading = False
            i += 2
            continue
        if ch == "\n":
            if leading and _after_anchor(pattern, i + 1):
                return True
            leading = False
        elif ch == "^":
            if leading and multiline and _after_anchor(pattern, i + 1):
                return True
        elif ch == "(":
            m = _GROUP_OPEN.match(pattern, i)
            stack.append(leading)
            i = m.end() if m else i + 1
            continue
        elif ch == ")":
            stack.pop() if stack else None
            leading = False
        elif ch == "|":
            leading = stack[-1] if stack else True
        elif ch == "[":
            in_class = True
            j = i + 1
            if j < len(pattern) and pattern[j] == "^":
                j += 1
            if j < len(pattern) and pattern[j] == "]":
                j += 1
            i = j
            leading = False
            continue
        else:
            leading = False
        i += 1
    return False


def _re_names(tree: ast.AST) -> tuple[set[str], dict[str, str]]:
    modules: set[str] = set()
    functions: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "re":
                    modules.add(a.asname or "re")
        elif isinstance(node, ast.ImportFrom) and node.module == "re":
            for a in node.names:
                if a.name in _FLAG_POS:
                    functions[a.asname or a.name] = a.name
    return modules, functions


def _re_function(call: ast.Call, modules: set[str], functions: dict[str, str]) -> str | None:
    fn = call.func
    if (isinstance(fn, ast.Attribute) and fn.attr in _FLAG_POS
            and isinstance(fn.value, ast.Name) and fn.value.id in modules):
        return fn.attr
    if isinstance(fn, ast.Name) and fn.id in functions:
        return functions[fn.id]
    return None


def multiline_line_start_calls(text: str) -> list[tuple[ast.Call, bool]]:
    """Alle re-Aufrufe mit auflösbarem Literalmuster und ob sie die
    quadratische Form tragen. Öffentlich, damit der Fix-Weg dieselbe
    Erkennung benutzt statt einer zweiten."""
    tree = ast.parse(text)
    modules, functions = _re_names(tree)
    out: list[tuple[ast.Call, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _re_function(node, modules, functions)
        if name is None:
            continue
        pattern_node = node.args[0] if node.args else next(
            (k.value for k in node.keywords if k.arg == "pattern"), None)
        pattern = _literal(pattern_node) if pattern_node is not None else None
        if pattern is None:
            continue
        pos = _FLAG_POS[name]
        flags = node.args[pos] if len(node.args) > pos else next(
            (k.value for k in node.keywords if k.arg == "flags"), None)
        multiline = _has_multiline_flag(flags) or bool(_INLINE_M.match(pattern))
        out.append((node, quadratic_line_start(pattern, multiline)))
    return out


@register(
    _CHECK_ID, _TITLE, platform="python", severity=Severity.WARNING,
    guideline=_GUIDELINE,
    tags=("redos", "performance", "security"),
    references=("https://docs.python.org/3/library/re.html#re.MULTILINE",),
    rationale=("With re.MULTILINE every line start is a match start. \\s also matches "
               "newlines, so ^\\s* at each line of a blank-line run scans to the run's "
               "end before failing: quadratic time. Measured on this repo: 40 KB of "
               "blank lines took 2.0 s per pattern, 80 KB 8.1 s; [ \\t]* took 0.00 s. "
               "Only literal patterns with a visible multiline flag are judged."),
    self_tests=[
        SelfTestCase(
            name="compile mit re.M",
            files={"a.py": "import re\nP = re.compile(r'^\\s*class_name\\s+X', re.MULTILINE)\n"},
            expect=Status.FAIL, expect_finding_contains="MULTILINE",
        ),
        SelfTestCase(
            name="Inline-(?m) in search",
            files={"a.py": "import re\ndef f(t):\n    return re.search(r'(?m)^\\s*@tool\\b', t)\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="flags als Schlüsselwort und \\s+",
            files={"a.py": "import re\ndef f(t):\n    return re.findall(r'^\\s+x', t, flags=re.M)\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Alias-Import und zusammengesetztes Muster",
            files={"a.py": ("from re import compile as c, escape, M\n"
                            "def f(v):\n    return c(r'^\\s*' + escape(v) + r'\\s*=', M)\n")},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="zweiter Zweig einer Alternation, Gruppe davor",
            files={"a.py": "import re as rx\nP = rx.compile(r'foo|^(?:\\s*)bar', rx.M)\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="(?:^|\\n)\\s* auch ohne MULTILINE",
            files={"a.py": ("import re\nP = re.compile(r'(?:^|\\n)\\s*(?:def\\s+test_\\w+)'"
                            " + '|' + re.escape('x'))\n")},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="\\n mitten im Muster nach festem Text",
            files={"a.py": "import re\nP = re.compile(r'foo\\n\\s*bar')\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="[ \\t]* ist der Fix",
            files={"a.py": "import re\nP = re.compile(r'^[ \\t]*class_name\\s+X', re.MULTILINE)\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="ohne MULTILINE ankert ^ nur am Anfang",
            files={"a.py": ("import re\nP = re.compile(r'^[ \\t]*x', re.M)\n"
                            "def f(line):\n    return re.match(r'^\\s*func\\s+', line)\n")},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="^ in Zeichenklasse und maskiertes ^",
            files={"a.py": ("import re\nA = re.compile(r'x[^\\s*]', re.M)\n"
                            "B = re.compile(r'\\^\\s*', re.M)\nC = re.compile(r'[]^]\\s*', re.M)\n")},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="\\s erst nach Text am Zeilenanfang",
            files={"a.py": "import re\nP = re.compile(r'^foo\\s*=\\s*1', re.M)\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_regex_quadratic_line_start(ctx: Context) -> CheckResult:
    """Literal re patterns with a multiline flag and ^ followed by \\s* or \\s+."""
    findings: list[Finding] = []
    units = 0
    # Auch Regel-/Testdefinitionsdateien: deren Regex läuft wirklich. Muster in
    # Selbsttest-Strings sind keine Aufrufe und zählen deshalb nicht.
    for source in ctx.files_including_rules(".py"):
        try:
            calls = multiline_line_start_calls(source.text)
        except SyntaxError:
            continue
        for node, bad in calls:
            units += 1
            if not bad:
                continue
            findings.append(Finding(
                check_id=_CHECK_ID, severity=Severity.WARNING,
                message=("Zeilenanfang (^ unter MULTILINE oder \\n) + \\s* am Musteranfang: \\s frisst Zeilenumbrüche, jeder "
                         "Zeilenanfang einer Leerzeilenstrecke scannt bis zu deren Ende "
                         "— quadratische Laufzeit (ReDoS) auf fremden Dateien."),
                file=source.rel, line=node.lineno,
                evidence=ast.get_source_segment(source.text, node.args[0])[:120]
                if node.args else "re-Aufruf",
                fix="Nach ^ bzw. \\n nur horizontale Leerzeichen erlauben: [ \\t]* statt \\s* "
                    "(bzw. [ \\t]+ statt \\s+).",
                guideline=_GUIDELINE,
            ))
    if not units:
        return unmeasured(_CHECK_ID, _TITLE,
                          "Kein re-Aufruf mit Literalmuster gefunden.",
                          platform="python")
    return result_for(_CHECK_ID, _TITLE, findings, units, label="Muster", platform="python")
