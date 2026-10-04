"""Explicit project contracts: bounded arithmetic, never eval/import target code.

Runtime receipts are self-reported test results bound to declared input hashes.
They establish freshness and completeness, not independent test authenticity.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from pathlib import Path

CONTRACT_FILE = ".ruttla-contracts.json"


class ContractError(ValueError):
    pass


class UnsupportedExpression(ValueError):
    pass


def local_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or any(char in relative for char in ("\\", "\0", "\n", "\r")):
        raise ContractError("Ungültiger relativer Vertragspfad")
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ContractError("Vertragspfad verlässt das Projekt")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ContractError("Vertragspfad oder Symlink verlässt das Projekt")
    return path


def read_json(path: Path) -> dict:
    try:
        if not path.is_file():
            raise ContractError("Nachweise und Verträge benötigen reguläre Dateien")
        if path.stat().st_size > 2_000_000:
            raise ContractError("Vertragsdatei ist zu groß")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError("JSON-Datei fehlt oder ist ungültig: " + path.name) from exc
    if not isinstance(value, dict):
        raise ContractError("JSON-Wurzel muss ein Objekt sein")
    return value


def numeric(value: object) -> bool:
    return type(value) in (int, float) and abs(value) <= 1e15 and math.isfinite(value)


def valid_input(value: object, depth: int = 0) -> bool:
    if depth > 8:
        return False
    if type(value) is bool or numeric(value) or isinstance(value, str):
        return not isinstance(value, str) or len(value) <= 4096
    if isinstance(value, dict):
        return len(value) <= 256 and all(isinstance(k, str) and valid_input(v, depth + 1)
                                          for k, v in value.items())
    if isinstance(value, list):
        return len(value) <= 256 and all(valid_input(v, depth + 1) for v in value)
    return False


def load_contracts(root: Path) -> dict | None:
    path = local_path(root, CONTRACT_FILE)
    if not path.exists():
        return None
    value = read_json(path)
    if type(value.get("version")) is not int or value["version"] != 1:
        raise ContractError("Unbekannte Vertragsversion")
    if set(value) - {"version", "expressions", "proofs"}:
        raise ContractError("Unbekannte Vertragseigenschaft")
    ids = set()
    for group in ("expressions", "proofs"):
        entries = value.get(group, [])
        if not isinstance(entries, list) or len(entries) > 256:
            raise ContractError("Ungültige Vertragsliste: " + group)
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
                raise ContractError("Vertrag benötigt eine eindeutige ID")
            if entry["id"] in ids:
                raise ContractError("Doppelte Vertrags-ID")
            ids.add(entry["id"])
            if group == "expressions":
                if set(entry) - {"id", "source", "scope", "target", "kind", "argument", "cases"}:
                    raise ContractError("Unbekannte Ausdruckseigenschaft")
                source = local_path(root, entry.get("source"))
                if source.suffix not in (".gd", ".py"):
                    raise ContractError("Ausdrucksverträge unterstützen .gd und .py")
                if not isinstance(entry.get("target"), str) or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", entry["target"]):
                    raise ContractError("Ungültiger Ausdrucksbezeichner")
                if "scope" in entry and (not isinstance(entry["scope"], str) or not re.fullmatch(r"[A-Za-z_]\w*", entry["scope"])):
                    raise ContractError("Ungültiger Funktionsbezeichner")
                if entry.get("kind", "assignment") not in ("assignment", "argument"):
                    raise ContractError("Unbekannte Ausdrucksart")
                if entry.get("kind") == "argument" and (type(entry.get("argument")) is not int or not 0 <= entry["argument"] < 32):
                    raise ContractError("Ungültiger Argumentindex")
                cases = entry.get("cases")
                if not isinstance(cases, list) or not 0 < len(cases) <= 256:
                    raise ContractError("Ausdruck benötigt konkrete Prüffälle")
                for case in cases:
                    if not isinstance(case, dict) or set(case) != {"inputs", "expected"} or not isinstance(case["inputs"], dict):
                        raise ContractError("Ungültiger Prüffall")
                    if type(case["expected"]) is not bool and not numeric(case["expected"]):
                        raise ContractError("Erwartung muss eine endliche Zahl oder bool sein")
                    if not valid_input(case["inputs"]):
                        raise ContractError("Prüfeingaben sind ungültig oder zu komplex")
            else:
                if set(entry) != {"id", "receipt", "sources", "required_cases"}:
                    raise ContractError("Nachweis benötigt receipt, sources und required_cases")
                local_path(root, entry["receipt"])
                for field in ("sources", "required_cases"):
                    items = entry[field]
                    if not isinstance(items, list) or not items or len(items) > 512 or any(not isinstance(i, str) or not i for i in items) or len(set(items)) != len(items):
                        raise ContractError("Ungültige Nachweisliste: " + field)
                for relative in entry["sources"]:
                    local_path(root, relative)
                if entry["receipt"] in entry["sources"] or entry["receipt"] == CONTRACT_FILE:
                    raise ContractError("Nachweis darf keine seiner Eingaben überschreiben")
    return value


def snapshot_inputs(root: Path, proof: dict) -> dict[str, str]:
    hashes = {}
    # Also bind the receipt to the requirements, not just the target sources.
    for relative in [CONTRACT_FILE, *proof["sources"]]:
        path = local_path(root, relative)
        try:
            if not path.is_file():
                raise ContractError("Nachweiseingabe ist keine reguläre Datei: " + relative)
            with path.open("rb") as stream:
                hashes[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError as exc:
            raise ContractError("Nachweiseingabe fehlt: " + relative) from exc
    return hashes


def named_proof(root: Path, proof_id: str) -> dict:
    contracts = load_contracts(root)
    for proof in (contracts or {}).get("proofs", []):
        if proof["id"] == proof_id:
            return proof
    raise ContractError("Nachweis-ID ist nicht vereinbart: " + proof_id)


def write_receipt(root: Path, proof_id: str, before: dict, cases: dict[str, bool], checks: int, failures: int) -> Path:
    """Called by the project's test runner; does not launch any target command."""
    proof = named_proof(root, proof_id)
    after = snapshot_inputs(root, proof)
    if before != after:
        raise ContractError("Quellen wurden während des Tests geändert")
    if type(checks) is not int or checks <= 0 or type(failures) is not int or failures < 0:
        raise ContractError("Nachweis benötigt positive Prüfzahl und Fehlerzahl")
    if not isinstance(cases, dict) or any(not isinstance(name, str) or type(result) is not bool for name, result in cases.items()):
        raise ContractError("Prüffallergebnisse müssen bool sein")
    receipt = {"version": 1, "proof_id": proof_id, "inputs": after,
               "checks": checks, "failures": failures, "cases": cases}
    path = local_path(root, proof["receipt"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = local_path(root, proof["receipt"] + ".tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def validate_receipt(root: Path, proof: dict) -> int:
    receipt = read_json(local_path(root, proof["receipt"]))
    if type(receipt.get("version")) is not int or receipt["version"] != 1 or receipt.get("proof_id") != proof["id"]:
        raise ContractError("Nachweis hat falsche Version oder ID")
    if receipt.get("inputs") != snapshot_inputs(root, proof):
        raise ContractError("Nachweis ist veraltet oder deckt die Quellen nicht vollständig ab")
    if type(receipt.get("checks")) is not int or receipt["checks"] <= 0:
        raise ContractError("Nachweis enthält keine positive Prüfzahl")
    if type(receipt.get("failures")) is not int or receipt["failures"] != 0:
        raise ContractError("Nachweis enthält Fehler oder keine gültige Fehlerzahl")
    cases = receipt.get("cases")
    if not isinstance(cases, dict) or any(cases.get(name) is not True for name in proof["required_cases"]):
        raise ContractError("Pflichtprüffälle fehlen oder sind fehlgeschlagen")
    if any(value is not True for value in cases.values()):
        raise ContractError("Nachweis enthält einen fehlgeschlagenen Prüffall")
    return receipt["checks"]


def expression_at(text: str, spec: dict) -> tuple[str, int]:
    lines = text.splitlines()
    start, end = 0, len(lines)
    if spec.get("scope"):
        header = re.compile(r"^(\s*)(?:async\s+)?(?:static\s+)?(?:func|def)\s+" + re.escape(spec["scope"]) + r"\s*\(")
        positions = [(i, m) for i, line in enumerate(lines) if (m := header.match(line))]
        if len(positions) != 1:
            raise UnsupportedExpression("Funktionsbereich fehlt oder ist mehrdeutig")
        index, match = positions[0]
        start = index + 1
        indent = len(match[1].expandtabs(4))
        for i in range(start, len(lines)):
            if lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) == 0:
                end = i
                break
            if lines[i].strip() and len(lines[i][:len(lines[i]) - len(lines[i].lstrip())].expandtabs(4)) <= indent:
                end = i
                break
    target = re.escape(spec["target"])
    pattern = re.compile(r"^\s*(?:(?:const|var)\s+)?" + target + r"\s*(?::\s*[^=]+?)?\s*(\+=|-=|\*=|/=|=)\s*(.+?)\s*$")
    found = []
    for i in range(start, end):
        if spec.get("kind", "assignment") == "assignment":
            match = pattern.match(lines[i])
            if match:
                expression = match[2]
                if match[1] != "=":
                    expression = spec["target"] + " " + match[1][0] + " (" + expression + ")"
                found.append((expression, i + 1))
        elif re.match(r"^\s*" + target + r"\s*\(", lines[i]):
            try:
                node = ast.parse(lines[i].strip(), mode="eval").body
            except SyntaxError as exc:
                raise UnsupportedExpression("Mehrzeiliger oder dynamischer Aufruf") from exc
            argument = spec["argument"]
            if isinstance(node, ast.Call) and len(node.args) > argument and not node.keywords:
                found.append((ast.unparse(node.args[argument]), i + 1))
    if len(found) != 1:
        raise UnsupportedExpression("Ausdruck fehlt oder ist mehrdeutig")
    return found[0]


def evaluate(expression: str, inputs: dict) -> object:
    """Small interpreter for literal arithmetic, conditionals and input reads."""
    if len(expression) > 4096:
        raise UnsupportedExpression("Ausdruck ist zu groß")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UnsupportedExpression("Syntax wird nicht gemessen") from exc
    if sum(1 for _ in ast.walk(tree)) > 128:
        raise UnsupportedExpression("Ausdruck ist zu komplex")

    def number(value):
        if not numeric(value):
            raise UnsupportedExpression("Keine begrenzte endliche Zahl")
        return value

    def run(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in ("true", "false"):
                return node.id == "true"
            if node.id in inputs:
                return inputs[node.id]
        if isinstance(node, ast.Attribute):
            name = ast.unparse(node)
            if name in inputs:
                return inputs[name]
            parent = run(node.value)
            if isinstance(parent, dict) and node.attr in parent:
                return parent[node.attr]
        if isinstance(node, ast.Subscript):
            container, key = run(node.value), run(node.slice)
            if isinstance(container, dict) and isinstance(key, str):
                return container[key]
            if isinstance(container, list) and type(key) is int and 0 <= key < len(container):
                return container[key]
        if isinstance(node, ast.UnaryOp):
            value = run(node.operand)
            if isinstance(node.op, ast.Not) and type(value) is bool:
                return not value
            if isinstance(node.op, ast.USub):
                return -number(value)
            if isinstance(node.op, ast.UAdd):
                return number(value)
        if isinstance(node, ast.BinOp):
            a, b = number(run(node.left)), number(run(node.right))
            if isinstance(node.op, ast.Add): result = a + b
            elif isinstance(node.op, ast.Sub): result = a - b
            elif isinstance(node.op, ast.Mult): result = a * b
            elif isinstance(node.op, ast.Div): result = a / b
            else: raise UnsupportedExpression("Rechenoperator wird nicht gemessen")
            return number(result)
        if isinstance(node, ast.IfExp):
            condition = run(node.test)
            if type(condition) is bool:
                return run(node.body if condition else node.orelse)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords and len(node.args) == 1:
            value = number(run(node.args[0]))
            if node.func.id == "int": return int(value)
            if node.func.id == "float": return float(value)
        raise UnsupportedExpression("Dynamischer Ausdruck wird nicht ausgeführt")

    try:
        result = run(tree.body)
        if type(result) is not bool and not numeric(result):
            raise UnsupportedExpression("Ausdruck liefert keine begrenzte Zahl oder bool")
        return result
    except (KeyError, ArithmeticError, RecursionError) as exc:
        raise UnsupportedExpression("Prüfeingaben reichen für diesen Ausdruck nicht aus") from exc
