"""Health before sabotage: bounded interpretation and proof freshness."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from _support import cli_json, make_tree
from ruttla.contracts import (
    CONTRACT_FILE, ContractError, UnsupportedExpression, evaluate,
    expression_at, load_contracts, local_path, named_proof, numeric,
    snapshot_inputs, validate_receipt, write_receipt,
    read_json,
)


class ProjectContractsTests(unittest.TestCase):
    def test_healthy_arithmetic_and_isolated_precedence_mutation(self):
        inputs = {"damage": 40, "level": 5, "evolved": True, "player.might": 1.5}
        self.assertEqual(evaluate("damage * (2.8 if evolved else (1 + (level - 1) * .3)) * player.might", inputs), 168)
        self.assertEqual(evaluate("damage * 2.8 if evolved else damage * (1 + (level - 1) * .3) * player.might", inputs), 112)
        inputs["evolved"] = False
        self.assertAlmostEqual(evaluate("damage * (2.8 if evolved else (1 + (level - 1) * .3)) * player.might", inputs), 132)

    def test_no_target_code_is_executed(self):
        for expression in ('__import__("os").system("exit 0")', "object.method()", "(lambda: 7)()", "[x for x in items]", "1 / 0", "2 ** 10000"):
            with self.subTest(expression=expression), self.assertRaises(UnsupportedExpression):
                evaluate(expression, {})
        self.assertFalse(numeric(10 ** 10000))

    def test_expression_selection_and_augmented_assignment(self):
        spec = {"scope": "advance", "target": "pending"}
        code = "var pending = 0\nfunc advance():\n\tpending += 1\nfunc reset():\n\tpending = 0\n"
        expression, line = expression_at(code, spec)
        self.assertEqual(line, 3)
        self.assertEqual(evaluate(expression, {"pending": 2}), 3)
        call = {"scope": "save", "target": "Store.record", "kind": "argument", "argument": 1}
        expression, _ = expression_at("func save():\n\tStore.record(time, kills - recorded, 0)\n", call)
        self.assertEqual(evaluate(expression, {"kills": 15, "recorded": 10}), 5)

    def test_path_and_symlink_escape_rejected(self):
        with make_tree({"src/source.gd": "extends Node\n"}) as tmp, make_tree({"secret.txt": "private"}) as outside:
            root = Path(tmp)
            for path in ("../secret.txt", "/tmp/outside", "src\\file.gd", None):
                with self.assertRaises(ContractError):
                    local_path(root, path)
            (root / "escape").symlink_to(Path(outside))
            with self.assertRaises(ContractError):
                local_path(root, "escape/secret.txt")

    def test_proof_lifecycle_and_sabotage(self):
        proof = {"id": "gameplay", "receipt": ".evidence.json", "sources": ["src/source.gd", "tools/run.py"], "required_cases": ["combat", "layout"]}
        files = {CONTRACT_FILE: json.dumps({"version": 1, "proofs": [proof]}), "src/source.gd": "extends Node\n", "tools/run.py": "# runner\n"}
        with make_tree(files) as tmp:
            root = Path(tmp)
            before = snapshot_inputs(root, named_proof(root, "gameplay"))
            path = write_receipt(root, "gameplay", before, {"combat": True, "layout": True}, 15, 0)
            self.assertEqual(validate_receipt(root, proof), 15)
            healthy = path.read_text()
            for field, value in (("checks", 0), ("checks", True), ("failures", 1), ("cases", {"combat": True}), ("cases", {"combat": True, "layout": 1}), ("inputs", {})):
                receipt = json.loads(healthy)
                receipt[field] = value
                path.write_text(json.dumps(receipt))
                with self.subTest(field=field, value=value), self.assertRaises(ContractError):
                    validate_receipt(root, proof)
            path.write_text(healthy)
            for source in ("src/source.gd", "tools/run.py", CONTRACT_FILE):
                target = root / source
                original = target.read_text()
                target.write_text(original + "\n")
                with self.subTest(source=source), self.assertRaises(ContractError):
                    validate_receipt(root, proof)
                with self.assertRaises(ContractError):
                    write_receipt(root, "gameplay", before, {"combat": True, "layout": True}, 15, 0)
                target.write_text(original)

    def test_invalid_schema_is_failure_not_crash(self):
        spec = {"id": "a", "source": "src/a.gd", "target": "VALUE", "cases": [{"inputs": {}, "expected": 1}]}
        for field, value in (("target", []), ("scope", 42), ("cases", [{"inputs": {"x": None}, "expected": 1}])):
            broken = dict(spec, **{field: value})
            with make_tree({CONTRACT_FILE: json.dumps({"version": 1, "expressions": [broken]})}) as tmp:
                with self.subTest(field=field), self.assertRaises(ContractError):
                    load_contracts(Path(tmp))
                code, report = cli_json(tmp, "--check", "quality.contract_expressions")
                self.assertEqual(code, 1)
                self.assertEqual(report["blocking_findings"], 1)

    def test_unknown_member_and_missing_manifest_are_unmeasured(self):
        with self.assertRaises(UnsupportedExpression):
            evaluate("player.damage", {})
        with make_tree({"src/game.py": "damage = 10\n"}) as tmp:
            code, report = cli_json(tmp, "--check", "quality.contract_expressions")
        self.assertEqual(code, 2)
        self.assertEqual(report["results"][0]["status"], "unmeasured")

    def test_workspace_scan_honors_nested_contracts(self):
        contract = {"version": 1, "expressions": [{"id": "heal", "source": "src/game.gd", "target": "HEAL", "cases": [{"inputs": {}, "expected": 30}]}]}
        files = {"game/" + CONTRACT_FILE: json.dumps(contract), "game/src/game.gd": "const HEAL = 30\n"}
        with make_tree(files) as tmp:
            code, report = cli_json(tmp, "--check", "quality.contract_expressions")
            self.assertEqual(code, 0)
            self.assertEqual(report["results"][0]["units_examined"], 1)
            Path(tmp, "game/src/game.gd").write_text("const HEAL = 25\n")
            code, report = cli_json(tmp, "--check", "quality.contract_expressions")
            self.assertEqual(code, 1)
            self.assertEqual(report["blocking_findings"], 1)

    def test_unsupported_result_does_not_disclose_source_strings(self):
        with self.assertRaises(UnsupportedExpression):
            evaluate("private_value", {"private_value": "do not print this"})

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO probe requires POSIX")
    def test_non_regular_receipts_and_inputs_rejected_without_opening(self):
        with make_tree({CONTRACT_FILE: '{"version": 1}'}) as tmp:
            root = Path(tmp)
            os.mkfifo(root / "pipe.json")
            with self.assertRaises(ContractError):
                read_json(root / "pipe.json")
            with self.assertRaises(ContractError):
                snapshot_inputs(root, {"sources": ["pipe.json"]})


if __name__ == "__main__":
    unittest.main()
