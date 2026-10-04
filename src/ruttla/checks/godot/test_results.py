"""Known Godot false-green test runner shapes, not a control-flow proof.

Godot script assertion errors abort the current script function. A caller
can continue and quit successfully. OS success alone is not a test result.
Reference: https://docs.godotengine.org/en/stable/classes/class_%40gdscript.html#class-gdscript-method-assert
"""
from __future__ import annotations

import ast
import re

from ruttla.core import (
    Context, Finding, SelfTestCase, Severity, Status, register, result_for,
    strip_comments, unmeasured,
)
from ._common import PLATFORM

GUIDELINE = "CODE_QUALITY_GUIDELINES_GAMEDEV.md § Testing — Godot-Exitcode und Skriptfehler getrennt prüfen"

HEALTHY = 'extends Node\nvar failures = 0\nfunc _ready():\n\t_test_logic()\n\tget_tree().quit(1 if failures else 0)\nfunc _test_logic():\n\tif 1 != 2:\n\t\tfailures += 1\n'
BROKEN = 'extends Node\nfunc _ready():\n\t_test_logic()\n\tget_tree().quit(0)\nfunc _test_logic():\n\tassert(1 == 2)\n'


@register(
    "godot.test_helper_assert_then_success", "Testhelfer-Assertion mit anschließendem Erfolgsexit",
    platform=PLATFORM, severity=Severity.WARNING, guideline=GUIDELINE,
    self_tests=[
        SelfTestCase("gesund: gezählte Fehler entscheiden Exit", {"tests/run.gd": HEALTHY}, Status.PASS),
        SelfTestCase("gesund: SceneTree zählt Fehler", {"tests/run.gd": HEALTHY.replace("extends Node", "extends SceneTree").replace("func _ready", "func _init").replace("get_tree().quit", "quit").replace("_test_logic", "test_logic")}, Status.PASS),
        SelfTestCase("defekt: Helferfehler wird als Erfolg beendet", {"tests/run.gd": BROKEN}, Status.FAIL),
        SelfTestCase("defekt: SceneTree-Helferfehler wird als Erfolg beendet", {"tests/run.gd": BROKEN.replace("extends Node", "extends SceneTree").replace("func _ready", "func _init").replace("get_tree().quit", "quit").replace("_test_logic", "test_logic")}, Status.FAIL),
        SelfTestCase("kein Testhelfer", {"src/main.gd": 'extends Node\nfunc _ready():\n\tget_tree().quit(0)\n'}, Status.UNMEASURED),
        SelfTestCase("Assertion im Aufrufer ist nicht gemessen", {"tests/run.gd": 'extends Node\nfunc _ready():\n\tassert(false)\n\tget_tree().quit(0)\n'}, Status.UNMEASURED),
    ],
)
def check_test_helper_assert(ctx: Context):
    check_id, title = "godot.test_helper_assert_then_success", "Testhelfer-Assertion mit anschließendem Erfolgsexit"
    findings, count = [], 0
    for sf in ctx.files_including_rules(".gd"):
        body = strip_comments(sf.text, sf.ext)
        functions = list(re.finditer(r"(?m)^func\s+(\w+)\s*\([^\n]*", body))
        scopes = {m[1]: body[m.end():functions[i + 1].start() if i + 1 < len(functions) else len(body)]
                  for i, m in enumerate(functions)}
        starter = next((name for name in ("_ready", "_init", "_initialize") if name in scopes), None)
        ready = scopes.get(starter, "")
        helpers = [name for name in scopes if name.startswith(("_test_", "test_")) and re.search(r"\b" + re.escape(name) + r"\s*\(", ready)]
        if not helpers:
            continue
        count += 1
        if not re.search(r"(?:get_tree\(\)\.)?\bquit\(0\)", ready):
            continue
        if not any(re.search(r"\bassert\s*\(", scopes[name]) for name in helpers):
            continue
        findings.append(Finding(check_id, Severity.WARNING,
            "Assertion im Testhelfer kann abbrechen, während der Teststarter anschließend quit(0) ausführt.",
            file=sf.rel, evidence="Testhelfer mit assert(...) und Erfolgsexit im Aufrufer",
            fix="Fehler explizit zählen; zusätzlich Engine-Fehler im Prozesslog und eine positive Prüfzahl kontrollieren.", guideline=GUIDELINE))
    return result_for(check_id, title, findings, count, "Teststarter", PLATFORM)


WRAPPER = 'import subprocess\ndef main():\n    result = subprocess.run(["godot", "--headless", "res://tests/run.tscn"], capture_output=True, text=True)\n    return result.returncode\n'


@register(
    "godot.test_wrapper_exit_only", "Godot-Testwrapper akzeptiert ausschließlich den Prozessstatus",
    platform=PLATFORM, severity=Severity.WARNING, guideline=GUIDELINE,
    self_tests=[
        SelfTestCase("gesund: Fehlerlog und Prüfergebnis kontrolliert", {"tools/test.py": WRAPPER.replace("return result.returncode", 'if "SCRIPT ERROR" in result.stdout or "TEST_RESULT" not in result.stdout:\n        return 1\n    return result.returncode')}, Status.PASS),
        SelfTestCase("defekt: nur OS-Exit akzeptiert", {"tools/test.py": WRAPPER}, Status.FAIL),
        SelfTestCase("defekt: gedrucktes Log ist keine Prüfung", {"tools/test.py": WRAPPER.replace("return result.returncode", "print(result.stdout)\n    return result.returncode")}, Status.FAIL),
        SelfTestCase("kein Godot-Testprozess", {"tools/test.py": WRAPPER.replace('"godot"', '"other-engine"')}, Status.UNMEASURED),
    ],
)
def check_test_wrapper_exit_only(ctx: Context):
    check_id, title = "godot.test_wrapper_exit_only", "Godot-Testwrapper akzeptiert ausschließlich den Prozessstatus"
    findings, count, unknown = [], 0, False
    for sf in ctx.files(".py"):
        try:
            tree = ast.parse(sf.text)
        except SyntaxError:
            continue
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for stmt in function.body:
                if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                    continue
                call = stmt.value
                if not isinstance(call, ast.Call) or ast.unparse(call.func) != "subprocess.run" or not call.args or not isinstance(call.args[0], (ast.List, ast.Tuple)):
                    continue
                args = [node.value for node in call.args[0].elts if isinstance(node, ast.Constant) and isinstance(node.value, str)]
                if not args or args[0].rsplit("/", 1)[-1] not in ("godot", "godot4") or not any("test" in s and s.endswith((".tscn", ".gd")) for s in args):
                    continue
                variable = stmt.targets[0].id
                returns = [node for node in ast.walk(function) if isinstance(node, ast.Return) and node.value is not None]
                if not any(ast.unparse(node.value) == variable + ".returncode" for node in returns):
                    continue
                tests = [node.test for node in ast.walk(function) if isinstance(node, (ast.If, ast.Assert))]
                log_guards = any(re.search(r"\b" + re.escape(variable) + r"\.(stdout|stderr)\b", ast.unparse(test)) for test in tests)
                # An output-derived local or delegated validation cannot be
                # proved here. Keep the check conservative in those shapes.
                derived = any(isinstance(node, (ast.Assign, ast.AnnAssign)) and node is not stmt
                              and re.search(r"\b" + re.escape(variable) + r"\.(stdout|stderr)\b", ast.unparse(node))
                              for node in ast.walk(function))
                if log_guards:
                    count += 1
                    continue
                if derived:
                    unknown = True
                    continue
                count += 1
                findings.append(Finding(check_id, Severity.WARNING,
                    "Godot-Testwrapper reicht nur returncode durch; Skriptfehler können bei Exit 0 unbemerkt bleiben.",
                    file=sf.rel, line=stmt.lineno, evidence="subprocess.run(Godot-Test) → return result.returncode",
                    fix="stdout und stderr auf Engine-Fehler sowie vollständige Prüfergebnisse mit positiver Prüfzahl prüfen.", guideline=GUIDELINE))
    if unknown and not findings:
        return unmeasured(check_id, title, "Auswertung lokaler Logvariablen oder delegierter Prüfungen braucht einen eigenen Vertrag.", PLATFORM)
    return result_for(check_id, title, findings, count, "Testwrapper", PLATFORM)
