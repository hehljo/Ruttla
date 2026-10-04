"""Opt-in project invariants and source-bound test evidence.

Explicit requirements avoid guessing a game's intended balance or visuals.
The arithmetic interpreter never imports or executes scanned project code.
Receipts measure declared coverage and freshness, not test authenticity.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from ruttla.contracts import (
    CONTRACT_FILE, ContractError, UnsupportedExpression, evaluate, expression_at,
    load_contracts, local_path, numeric, validate_receipt,
)
from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status, register,
    result_for, strip_comments, unmeasured,
)

GUIDELINE = "CLAUDE.md § Gates — explizite Sollwerte und aktuelle Laufzeitnachweise"


def _expression_files(source: str = "const HEAL: float = 30.0\n", expected=30) -> dict:
    spec = {"id": "healing", "source": "src/item.gd", "target": "HEAL",
            "cases": [{"inputs": {}, "expected": expected}]}
    return {CONTRACT_FILE: json.dumps({"version": 1, "expressions": [spec]}),
            "src/item.gd": source}


def _proof_files(defect: str = "") -> dict:
    source = "extends Node\n"
    proof = {"id": "layout", "receipt": ".test-evidence.json",
             "sources": ["src/ui.gd", "tools/test_ui.py"], "required_cases": ["mobile"]}
    manifest = json.dumps({"version": 1, "proofs": [proof]})
    files = {CONTRACT_FILE: manifest, "src/ui.gd": source, "tools/test_ui.py": "# runner\n"}
    receipt = {"version": 1, "proof_id": "layout", "checks": 1, "failures": 0,
               "cases": {"mobile": True},
               "inputs": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}}
    if defect == "missing":
        return files
    if defect == "source":
        files["src/ui.gd"] += "var changed = true\n"
    if defect == "runner":
        files["tools/test_ui.py"] += "# changed runner\n"
    if defect == "contract":
        files[CONTRACT_FILE] = manifest + "\n"
    if defect == "zero":
        receipt["checks"] = 0
    if defect == "failure":
        receipt["failures"] = 1
    if defect == "case":
        receipt["cases"] = {}
    if defect == "incomplete":
        receipt["inputs"].pop("src/ui.gd")
    files[proof["receipt"]] = json.dumps(receipt)
    return files


def _failure(check_id: str, message: str, evidence: str) -> Finding:
    # Root contracts span multiple files: retain violations in changed-only
    # scans, including changes to requirements and ignored proof artifacts.
    return Finding(check_id, Severity.ERROR, message, evidence=evidence,
                   fix="Vereinbarten Sollwert korrigieren oder den vollständigen Test erneut ausführen; Nachweise nicht von Hand grün setzen.",
                   guideline=GUIDELINE)


def _project_contracts(ctx: Context):
    """Honor nested project contracts when scanning a shared workspace."""
    scan_root = Path(ctx.root)
    paths = {Path(sf.path) for sf in ctx.all_files() if Path(sf.rel).name == CONTRACT_FILE}
    paths.update(scan_root / skipped.rel for skipped in ctx.coverage().skipped
                 if Path(skipped.rel).name == CONTRACT_FILE)
    # A present root contract must be validated even if oversized/invalid and
    # therefore omitted from ordinary source inventory.
    root_manifest = scan_root / CONTRACT_FILE
    if root_manifest.exists():
        paths.add(root_manifest)
    for path in sorted(paths):
        root = path.parent
        label = path.relative_to(scan_root).as_posix()
        try:
            yield root, label, load_contracts(root), None
        except ContractError as exc:
            yield root, label, None, str(exc)


@register(
    "quality.contract_expressions", "Explizite Sollwerte und Rechenfälle",
    severity=Severity.ERROR, guideline=GUIDELINE, safe_by_default=True,
    self_tests=[
        SelfTestCase("gesund: vereinbarte Heilmenge", _expression_files(), Status.PASS),
        SelfTestCase("defekt: Heilmenge weicht ab", _expression_files("const HEAL: float = 25.0\n"), Status.FAIL),
        SelfTestCase("unbekannte dynamische Rechnung bleibt ungemessen", _expression_files("const HEAL = provider.get_amount()\n"), Status.UNMEASURED),
        SelfTestCase("ohne vereinbarten Sollwert", {"src/item.gd": "const HEAL = 25\n"}, Status.UNMEASURED),
        SelfTestCase("defekt: ungültiger Vertrag", {CONTRACT_FILE: '{"version": 999}'}, Status.FAIL),
    ],
)
def check_contract_expressions(ctx: Context) -> CheckResult:
    """`.ruttla-contracts.json`, version 1, optionally declares `expressions`.
    Each entry needs id, source (.gd/.py), target and cases (inputs, expected).
    Optional scope selects a unique function; kind=argument with an argument
    index selects a call argument instead of an assignment. Bounded arithmetic,
    input reads and conditionals are interpreted without eval or target calls.
    Unknown syntax stays UNMEASURED. Contracts in nested projects are included.
    """
    check_id, title = "quality.contract_expressions", "Explizite Sollwerte und Rechenfälle"
    findings, unknown, count = [], [], 0
    specs = []
    for root, label, contracts, error in _project_contracts(ctx):
        if error:
            findings.append(_failure(check_id, error, label))
        else:
            specs.extend((root, spec) for spec in (contracts or {}).get("expressions", []))
    for root, spec in specs:
        location = spec["source"] + " / " + spec["id"]
        try:
            path = local_path(root, spec["source"])
            expression, line = expression_at(strip_comments(path.read_text(encoding="utf-8"), path.suffix), spec)
            for case in spec["cases"]:
                actual, expected = evaluate(expression, case["inputs"]), case["expected"]
                if type(actual) is bool or type(expected) is bool:
                    equal = type(actual) is type(expected) and actual == expected
                else:
                    equal = numeric(actual) and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)
                count += 1
                if not equal:
                    findings.append(_failure(check_id, "Ausdruck verletzt den vereinbarten Prüffall: " + spec["id"],
                                             f"{spec['source']}:{line} — {expression}; erwartet {expected!r}, erhalten {actual!r}"))
        except (OSError, UnicodeError, ContractError):
            findings.append(_failure(check_id, "Vertragliche Quelle fehlt oder ist nicht lesbar", location))
        except UnsupportedExpression as exc:
            unknown.append(location + ": " + str(exc))
    if findings:
        return result_for(check_id, title, findings, max(count, len(specs), len(findings)), "Prüffälle")
    if unknown:
        return CheckResult(check_id, Status.UNMEASURED, title, reason="; ".join(unknown), units_examined=count, unit_label="Prüffälle")
    return result_for(check_id, title, [], count, "Prüffälle")


@register(
    "quality.contract_runtime_evidence", "Vollständige aktuelle Laufzeitnachweise",
    severity=Severity.ERROR, guideline=GUIDELINE, safe_by_default=True,
    self_tests=[
        SelfTestCase("gesund: aktueller vollständiger Nachweis", _proof_files(), Status.PASS),
        *[SelfTestCase("defekt: Nachweis " + defect, _proof_files(defect), Status.FAIL)
          for defect in ("missing", "source", "runner", "contract", "zero", "failure", "case", "incomplete")],
        SelfTestCase("ohne vereinbarte Laufzeitprüfung", {"src/ui.gd": "extends Node\n"}, Status.UNMEASURED),
    ],
)
def check_contract_runtime_evidence(ctx: Context) -> CheckResult:
    """Opt-in `proofs` declare id, receipt, sources and required_cases.
    A project's own test runner calls ruttla.contracts.snapshot_inputs before
    testing and write_receipt after testing. Missing/failed cases, zero tests
    and altered source/runner/contract hashes block. Ruttla does not launch the
    runner. This verifies freshness/completeness of self-reported results;
    it does not independently authenticate tests, platforms or visual quality.
    """
    check_id, title = "quality.contract_runtime_evidence", "Vollständige aktuelle Laufzeitnachweise"
    findings = []
    proofs = []
    for root, label, contracts, error in _project_contracts(ctx):
        if error:
            findings.append(_failure(check_id, error, label))
        else:
            proofs.extend((root, proof) for proof in (contracts or {}).get("proofs", []))
    for root, proof in proofs:
        try:
            validate_receipt(root, proof)
        except ContractError as exc:
            findings.append(_failure(check_id, "Laufzeitnachweis " + proof["id"] + ": " + str(exc), proof["id"] + " / " + proof["receipt"]))
    if not proofs and not findings:
        return unmeasured(check_id, title, "Keine expliziten Laufzeitnachweise vereinbart.")
    return result_for(check_id, title, findings, max(len(proofs), len(findings)), "Laufzeitnachweise")
