"""Conservative static guard for non-ASCII password comparisons with compare_digest.

Python's hmac/secrets.compare_digest accepts str only when both strings are ASCII.
Password form inputs are Unicode; byte-encoding both operands avoids TypeError.
"""
from __future__ import annotations

import ast
import re

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status,
    register, result_for, unmeasured,
)

_CHECK_ID = "python.compare_digest_unicode_password"
_TITLE = "Unicode-Passwörter können compare_digest(str, str) abstürzen lassen"
_GUIDELINE = "GUIDELINES.md § Python authentication"
_PASSWORD_NAME = re.compile(r"(?:password|passwd|passphrase|confirmation|confirm_password)", re.I)
_ASCII_DERIVED = re.compile(r"(?:hash|hexdigest|digest|fingerprint)$", re.I)


def _password_input(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return bool(_PASSWORD_NAME.search(node.id)) and not _ASCII_DERIVED.search(node.id)
    if isinstance(node, ast.Attribute):
        return bool(_PASSWORD_NAME.search(node.attr)) and not _ASCII_DERIVED.search(node.attr)
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return isinstance(node.slice.value, str) and bool(_PASSWORD_NAME.search(node.slice.value))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Constant)):
        return isinstance(node.args[0].value, str) and bool(_PASSWORD_NAME.search(node.args[0].value))
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and not node.value.isascii()


def _utf8_bytes(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return isinstance(node, ast.Constant) and isinstance(node.value, bytes)
    if node.func.attr != "encode" or node.keywords or len(node.args) > 1:
        return False
    return not node.args or (isinstance(node.args[0], ast.Constant)
                             and isinstance(node.args[0].value, str)
                             and node.args[0].value.lower().replace("-", "") == "utf8")


@register(
    _CHECK_ID, _TITLE, platform="python", severity=Severity.WARNING,
    guideline=_GUIDELINE,
    tags=("auth", "unicode", "runtime-error"),
    references=("https://docs.python.org/3/library/hmac.html#hmac.compare_digest",),
    rationale=("hmac.compare_digest and secrets.compare_digest reject non-ASCII str "
               "operands with TypeError. A password field can contain Unicode even "
               "when tests use only ASCII. This advisory check targets password-"
               "named arguments and explicit non-ASCII literals; names alone do "
               "not prove that Unicode is accepted, so it is not blocking by default."),
    self_tests=[
        SelfTestCase(
            name="Passwort-Strings aus Formular lösen TypeError aus",
            files={"auth.py": (
                "import secrets\n"
                "def setup(password, confirmation):\n"
                "    return secrets.compare_digest(password, confirmation)\n"
            )}, expect=Status.FAIL, expect_finding_contains="UTF-8",
        ),
        SelfTestCase(
            name="Beide Passwörter als UTF-8-Bytes sind sicher",
            files={"auth.py": (
                "import secrets\n"
                "def setup(password, confirmation):\n"
                "    return secrets.compare_digest(password.encode('utf-8'), "
                "confirmation.encode('utf-8'))\n"
            )}, expect=Status.PASS,
        ),
        SelfTestCase(
            name="ASCII-HMAC-Hexdigest bleibt unbeanstandet",
            files={"auth.py": (
                "import hmac\n"
                "def verify(digest, expected):\n"
                "    return hmac.compare_digest(digest, expected)\n"
            )}, expect=Status.PASS,
        ),
        SelfTestCase(
            name="Direktes Nicht-ASCII-Literal wird erkannt",
            files={"auth.py": (
                "from hmac import compare_digest\n"
                "def verify(value):\n"
                "    return compare_digest(value, 'ß')\n"
            )}, expect=Status.FAIL,
        ),
        SelfTestCase(
            name="ASCII-String-Literal ist gültig",
            files={"auth.py": (
                "from secrets import compare_digest as secure_equal\n"
                "def verify(value):\n"
                "    return secure_equal(value, 'ASCII-only')\n"
            )}, expect=Status.PASS,
        ),
        SelfTestCase(
            name="Ein Byte-Operand allein genügt nicht",
            files={"auth.py": (
                "import secrets\n"
                "def verify(password, confirmation):\n"
                "    return secrets.compare_digest(password.encode(), confirmation)\n"
            )}, expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Abgeleitete ASCII-Passwort-Hashes bleiben sauber",
            files={"auth.py": (
                "import secrets\n"
                "def verify(password_hash, expected_hash):\n"
                "    return secrets.compare_digest(password_hash, expected_hash)\n"
            )}, expect=Status.PASS,
        ),
        SelfTestCase(
            name="Passwort direkt aus JSON-Objekt erkannt",
            files={"auth.py": (
                "import secrets\n"
                "def verify(data, expected):\n"
                "    return secrets.compare_digest(data.get('password'), expected)\n"
            )}, expect=Status.FAIL,
        ),
    ],
)
def check_compare_digest_unicode_password(ctx: Context) -> CheckResult:
    """Identify likely Unicode password values passed directly as str."""
    findings: list[Finding] = []
    units = 0
    for source in ctx.files(".py"):
        try:
            tree = ast.parse(source.text)
        except SyntaxError:
            continue
        modules = {"secrets", "hmac"}
        aliases = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.asname for a in node.names
                               if a.name in ("secrets", "hmac") and a.asname)
            elif isinstance(node, ast.ImportFrom) and node.module in ("secrets", "hmac"):
                aliases.update(a.asname or a.name for a in node.names
                               if a.name == "compare_digest")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) != 2:
                continue
            fn = node.func
            named = isinstance(fn, ast.Name) and fn.id in aliases
            qualified = (isinstance(fn, ast.Attribute) and fn.attr == "compare_digest"
                         and isinstance(fn.value, ast.Name) and fn.value.id in modules)
            if not (named or qualified):
                continue
            units += 1
            if not any(_password_input(arg) for arg in node.args):
                continue
            if all(_utf8_bytes(arg) for arg in node.args):
                continue
            findings.append(Finding(
                check_id=_CHECK_ID, severity=Severity.WARNING,
                message=("Passwortvergleich mit möglichen Nicht-ASCII-Zeichen: "
                         "compare_digest(str, str) kann TypeError werfen."),
                file=source.rel, line=node.lineno,
                evidence="compare_digest mit nicht vollständig UTF-8-kodierten Passwortwerten",
                fix="Beide Werte vor compare_digest als UTF-8-Bytes kodieren; Unicode und ASCII testen.",
                guideline=_GUIDELINE,
            ))
    if not units:
        return unmeasured(_CHECK_ID, _TITLE, "Kein compare_digest-Aufruf in Python-Dateien gefunden.",
                          platform="python")
    return result_for(_CHECK_ID, _TITLE, findings, units, label="Vergleiche", platform="python")
