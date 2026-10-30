"""Bounded advisory for CRC validation while a ZipFile context is writable."""
from __future__ import annotations

import ast

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status,
    register, result_for, unmeasured,
)

CHECK_ID = "python.zip_crc_before_writer_closed"
TITLE = "ZIP-CRC wird noch im Schreibkontext geprüft"
GUIDELINE = "GUIDELINES.md § Python finalized archives"


def _name(node: ast.AST | None) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def _imports(tree: ast.Module) -> tuple[set[str], set[str]]:
    modules, constructors = set(), set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name == "zipfile")
        elif isinstance(node, ast.ImportFrom) and node.module == "zipfile":
            constructors.update(a.asname or a.name for a in node.names if a.name == "ZipFile")
    # Ambiguous/rebound imported symbols cannot identify a standard-library API.
    rebound = {node.id for node in ast.walk(tree)
               if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
    rebound.update(node.arg for node in ast.walk(tree) if isinstance(node, ast.arg))
    rebound.update(node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    return modules - rebound, constructors - rebound


def _mode(node: ast.AST, modules: set[str], constructors: set[str]) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    fn = node.func
    recognized = (isinstance(fn, ast.Name) and fn.id in constructors) or (
        isinstance(fn, ast.Attribute) and fn.attr == "ZipFile"
        and _name(fn.value) in modules)
    if not recognized or any(k.arg is None for k in node.keywords):
        return None
    keywords = [k.value for k in node.keywords if k.arg == "mode"]
    if len(keywords) > 1 or (keywords and len(node.args) > 1):
        return None
    value = node.args[1] if len(node.args) > 1 else keywords[0] if keywords else ast.Constant("r")
    return value.value if isinstance(value, ast.Constant) and value.value in ("r", "w", "a", "x") else None


class _ImmediateCalls(ast.NodeVisitor):
    def __init__(self, owner: str):
        self.owner = owner
        self.calls: list[ast.Call] = []
        self.ambiguous = False

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "testzip" and _name(node.func.value) == self.owner:
            self.calls.append(node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == self.owner and isinstance(node.ctx, (ast.Store, ast.Del)):
            self.ambiguous = True

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name == self.owner:
            self.ambiguous = True
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        if any(_name(item.optional_vars) == self.owner for item in node.items):
            return  # A nested context owns its own binding.
        self.generic_visit(node)

    # These bodies are deferred; lexical placement is not execution evidence.
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        pass


@register(
    CHECK_ID, TITLE, platform="python", severity=Severity.WARNING,
    guideline=GUIDELINE, tags=("packaging", "zip", "artifact"),
    references=("https://docs.python.org/3/library/zipfile.html#zipfile.ZipFile.close",),
    rationale=("A Windows packaging run reported a CRC failure while its append-mode "
               "ZipFile was still open; the same closed archive passed a fresh read. "
               "Validate the finalized file after closing the writer. This advisory "
               "recognizes only imported ZipFile contexts, literal modes and direct "
               "unrebound receivers; it does not prove corruption or execute target code."),
    self_tests=[
        SelfTestCase(name="Geschlossenes Archiv neu lesend prüfen", files={"pack.py":
            "import zipfile\nwith zipfile.ZipFile(p, 'w') as writer:\n writer.writestr('a', b'a')\n"
            "with zipfile.ZipFile(p, 'r') as reader:\n assert reader.testzip() is None\n"}, expect=Status.PASS),
        SelfTestCase(name="Standardmodus ist lesend", files={"pack.py":
            "from zipfile import ZipFile\nwith ZipFile(p) as archive:\n archive.testzip()\n"}, expect=Status.PASS),
        SelfTestCase(name="Innerer Leser verdeckt äußeren Writer", files={"pack.py":
            "import zipfile\nwith zipfile.ZipFile(p, 'w') as archive:\n"
            " with zipfile.ZipFile(q) as archive:\n  archive.testzip()\n"}, expect=Status.PASS),
        SelfTestCase(name="Anhängender Writer noch offen", files={"pack.py":
            "import zipfile\nwith zipfile.ZipFile(p, 'a') as archive:\n archive.testzip()\n"}, expect=Status.FAIL),
        SelfTestCase(name="Neuer Writer noch offen", files={"pack.py":
            "from zipfile import ZipFile as Z\nwith Z(p, 'w') as archive:\n archive.testzip()\n"}, expect=Status.FAIL),
        SelfTestCase(name="Exklusiver Writer mit Keyword", files={"pack.py":
            "import zipfile as z\nwith z.ZipFile(p, mode='x') as archive:\n archive.testzip()\n"}, expect=Status.FAIL),
        SelfTestCase(name="Dynamischer Modus bleibt ungemessen", files={"pack.py":
            "import zipfile\nwith zipfile.ZipFile(p, mode) as archive:\n archive.testzip()\n"}, expect=Status.UNMEASURED),
        SelfTestCase(name="Späterer Callback ist kein direkter Aufruf", files={"pack.py":
            "import zipfile\nwith zipfile.ZipFile(p, 'w') as archive:\n"
            " callback = lambda: archive.testzip()\n"}, expect=Status.UNMEASURED),
        SelfTestCase(name="Unbekannter gleichnamiger Typ bleibt ungemessen", files={"pack.py":
            "class ZipFile: pass\nwith ZipFile(p, 'w') as archive:\n archive.testzip()\n"}, expect=Status.UNMEASURED),
    ],
)
def check_zip_crc(ctx: Context) -> CheckResult:
    findings: list[Finding] = []
    units = 0
    for source in ctx.files(".py"):
        try:
            tree = ast.parse(source.text)
        except SyntaxError:
            continue
        modules, constructors = _imports(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            for index, item in enumerate(node.items):
                owner, mode = _name(item.optional_vars), _mode(item.context_expr, modules, constructors)
                if not owner or mode is None or any(_name(later.optional_vars) == owner for later in node.items[index + 1:]):
                    continue
                visitor = _ImmediateCalls(owner)
                for statement in node.body:
                    visitor.visit(statement)
                if visitor.ambiguous:
                    continue
                units += len(visitor.calls)
                if mode == "r":
                    continue
                for call in visitor.calls:
                    findings.append(Finding(
                        check_id=CHECK_ID, severity=Severity.WARNING,
                        message="ZIP-CRC im noch offenen Schreibkontext; erst Writer schließen, dann Datei neu lesen.",
                        file=source.rel, line=call.lineno,
                        evidence=f"ZipFile mode={mode!r}: {owner}.testzip()",
                        fix="Schreibkontext verlassen und das fertige Archiv separat mit ZipFile(path, 'r') prüfen.",
                        guideline=GUIDELINE,
                    ))
    if not units:
        return unmeasured(CHECK_ID, TITLE,
            "Kein direkter testzip-Aufruf in eindeutig importiertem ZipFile-Kontext mit literalem Modus; dynamische/deferierte Fälle bleiben offen.",
            platform="python")
    return result_for(CHECK_ID, TITLE, findings, units, label="CRC-Aufrufe", platform="python")
