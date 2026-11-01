"""Health before sabotage: bounded interpretation and proof freshness."""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from _support import cli, cli_json, make_tree
from ruttla.contracts import (
    CONTRACT_FILE, ContractError, ContractInputError, UnsupportedExpression, evaluate,
    expression_at, load_contracts, local_path, named_proof, numeric,
    resolve_sources, snapshot_inputs, validate_receipt, write_receipt,
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


class DerivedSourcesTests(unittest.TestCase):
    """Real local Git inventories; each freshness defect starts from green."""

    def project(self, **selection):
        proof = {"id": "layout", "receipt": ".evidence.json",
                 "required_cases": ["mobile"], **selection}
        return proof, {CONTRACT_FILE: json.dumps({"version": 1, "proofs": [proof]}),
                       "src/a.gd": "extends Node\n", "src/sub/b.gd": "extends Node\n",
                       "src/c.txt": "not selected\n", "tools/run.py": "# runner\n"}

    def git(self, root, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        proc = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), *args],
                              env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def healthy(self, root, proof):
        before = snapshot_inputs(root, named_proof(root, proof["id"]))
        write_receipt(root, proof["id"], before, {"mobile": True}, 4, 0)
        self.assertEqual(validate_receipt(root, proof), 4)
        return before

    def test_00_healthy_legacy_list_needs_no_git_and_keeps_hashes(self):
        proof, files = self.project(sources=["src/a.gd", "tools/run.py"])
        with make_tree(files) as tmp:
            before = self.healthy(Path(tmp), proof)
            self.assertEqual(set(before), {CONTRACT_FILE, "src/a.gd", "tools/run.py"})

    def test_01_healthy_recursive_and_segment_globs_sorted_union(self):
        proof, files = self.project(source_globs=["src/**/*.gd", "src/[a-z].gd"],
                                    sources=["tools/run.py"], exclude_globs=["src/sub/**"])
        with make_tree(files) as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            before = self.healthy(root, proof)
            self.assertEqual(list(before), sorted(before))
            self.assertEqual(resolve_sources(root, proof), ["src/a.gd", "tools/run.py"])

    def test_new_untracked_source_invalidates_receipt_and_inflight_run(self):
        proof, files = self.project(source_globs=["src/**/*.gd"])
        with make_tree(files) as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            before = self.healthy(root, proof)
            (root / "src/new.gd").write_text("extends Node\n")
            self.assertIn("src/new.gd", snapshot_inputs(root, proof))
            with self.assertRaisesRegex(ContractError, "veraltet"):
                validate_receipt(root, proof)
            with self.assertRaisesRegex(ContractError, "während"):
                write_receipt(root, "layout", before, {"mobile": True}, 4, 0)

    def test_deleted_tracked_source_changes_set_then_new_receipt_is_valid(self):
        proof, files = self.project(source_globs=["src/**/*.gd"])
        with make_tree(files) as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            self.git(root, "add", "src")
            self.healthy(root, proof)
            # Rename a fixture (no project deletion) to simulate a tracked deletion.
            (root / "src/a.gd").rename(root / "removed.txt")
            self.assertNotIn("src/a.gd", snapshot_inputs(root, proof))
            with self.assertRaisesRegex(ContractError, "veraltet"):
                validate_receipt(root, proof)
            self.healthy(root, proof)

    def test_deleted_explicit_input_is_invalid_with_action_and_no_cli_traceback(self):
        proof, files = self.project(sources=["src/a.gd"])
        with make_tree(files) as tmp:
            root = Path(tmp)
            self.healthy(root, proof)
            (root / "src/a.gd").rename(root / "removed.txt")
            with self.assertRaisesRegex(ContractInputError, "src/a.gd.*wiederherstellen"):
                snapshot_inputs(root, proof)
            proc = cli(tmp, "--check", "quality.contract_runtime_evidence", "--format", "json")
            self.assertEqual(proc.returncode, 3)
            report = json.loads(proc.stdout)
            self.assertEqual(report["results"][0]["status"], "error")
            self.assertIn("Ungültige Nachweiseingaben", report["results"][0]["reason"])
            self.assertNotIn("Traceback", proc.stdout + proc.stderr)

    def test_tracked_ignored_files_win_and_untracked_ignored_files_do_not(self):
        proof, files = self.project(source_globs=["src/**"])
        files[".gitignore"] = "src/*.txt\nsrc/ignored/\n"
        with make_tree(files) as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            self.git(root, "add", "-f", "src/c.txt")
            before = self.healthy(root, proof)
            (root / "src/ignored").mkdir()
            (root / "src/ignored/cache.gd").write_text("ignored\n")
            (root / "src/extra.txt").write_text("ignored\n")
            self.assertEqual(snapshot_inputs(root, proof), before)
            self.assertIn("src/c.txt", before)

    def test_explicit_and_globbed_ignored_artifacts_remain_covered(self):
        proof, files = self.project(source_globs=["src/**/*.gd"], sources=["cache/fixed.json"],
                                    include_ignored_globs=["cache/reports/*.json"])
        files.update({".gitignore": "cache/\n", "cache/fixed.json": "{}\n",
                      "cache/reports/a.json": "{}\n", "cache/other.json": "{}\n"})
        with make_tree(files) as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            before = self.healthy(root, proof)
            self.assertIn("cache/fixed.json", before)
            self.assertIn("cache/reports/a.json", before)
            self.assertNotIn("cache/other.json", before)
            (root / "cache/reports/new.json").write_text("{}\n")
            with self.assertRaisesRegex(ContractError, "veraltet"):
                validate_receipt(root, proof)

    def test_artifact_globs_also_cover_tracked_and_nonignored_files(self):
        proof, files = self.project(include_ignored_globs=["src/**/*.gd"])
        with make_tree(files) as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            before = self.healthy(root, proof)
            self.git(root, "add", "src/a.gd")
            self.assertEqual(snapshot_inputs(root, proof), before)
            (root / "src/new.gd").write_text("extends Node\n")
            with self.assertRaisesRegex(ContractError, "veraltet"):
                validate_receipt(root, proof)

    def test_exclusion_cannot_hide_explicit_required_source(self):
        proof, files = self.project(source_globs=["src/**"], sources=["tools/run.py"],
                                    exclude_globs=["tools/**"])
        with make_tree(files) as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            self.assertIn("tools/run.py", self.healthy(root, proof))
            (root / "tools/run.py").rename(root / "removed.txt")
            with self.assertRaises(ContractInputError):
                snapshot_inputs(root, proof)

    def test_subdirectory_contract_stays_inside_its_project(self):
        proof, files = self.project(source_globs=["src/**/*.gd"])
        files = {"nested/" + key: value for key, value in files.items()}
        files["src/outside.gd"] = "extends Node\n"
        with make_tree(files) as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            self.git(root, "add", ".")
            self.assertEqual(resolve_sources(root / "nested", proof), ["src/a.gd", "src/sub/b.gd"])
            self.healthy(root / "nested", proof)
            code, report = cli_json(tmp, "--check", "quality.contract_runtime_evidence")
            self.assertEqual(code, 0, report)

    def test_invalid_patterns_and_unknown_fields_are_rejected(self):
        proof, files = self.project(source_globs=["src/**/*.gd"])
        for field, value in (("source_globs", []), ("source_globs", "src/**"),
                             ("source_globs", ["../**"]), ("source_globs", ["/src/**"]),
                             ("source_globs", ["src\\*.gd"]), ("source_globs", ["src/**x"]),
                             ("exclude_globs", ["../**"]), ("include_ignored_globs", ["../**"]),
                             ("source_globs", ["src/**", "src/**"]), ("typo", ["src/**"])):
            files[CONTRACT_FILE] = json.dumps({"version": 1, "proofs": [{**proof, field: value}]})
            with self.subTest(field=field, value=value), make_tree(files) as tmp:
                with self.assertRaises(ContractError):
                    load_contracts(Path(tmp))

    def test_zero_selected_files_is_invalid_even_with_an_old_receipt(self):
        proof, files = self.project(source_globs=["src/**/*.gd"])
        with make_tree(files) as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            self.healthy(root, proof)
            proof["exclude_globs"] = ["src/**"]
            with self.assertRaisesRegex(ContractInputError, "keine Eingaben"):
                validate_receipt(root, proof)

    def test_receipt_cannot_be_its_own_derived_input(self):
        proof, files = self.project(source_globs=["**"])
        with make_tree(files) as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            # Write a complete receipt with the receipt itself excluded first.
            proof["exclude_globs"] = [".evidence.json"]
            filespec = {"version": 1, "proofs": [proof]}
            (root / CONTRACT_FILE).write_text(json.dumps(filespec))
            self.healthy(root, proof)
            proof.pop("exclude_globs")
            with self.assertRaisesRegex(ContractInputError, "eigenes Quellenmuster"):
                snapshot_inputs(root, proof)

    def test_missing_git_and_nonrepository_are_invalid_not_empty_passes(self):
        proof, files = self.project(source_globs=["src/**"])
        with make_tree(files) as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ContractInputError, "Git-Arbeitsbaum"):
                snapshot_inputs(root, proof)
            with mock.patch("ruttla.contracts.subprocess.run", side_effect=FileNotFoundError):
                with self.assertRaisesRegex(ContractInputError, "Git nicht verfügbar"):
                    snapshot_inputs(root, proof)

    def test_git_environment_cannot_redirect_sources(self):
        proof, files = self.project(source_globs=["src/**/*.gd"])
        with make_tree(files) as tmp, make_tree({"src/foreign.gd": "outside\n"}) as outside:
            root = Path(tmp)
            self.git(root, "init", "-q")
            self.git(outside, "init", "-q")
            with mock.patch.dict(os.environ, {"GIT_DIR": str(Path(outside) / ".git"),
                                              "GIT_WORK_TREE": outside}):
                self.assertEqual(resolve_sources(root, proof), ["src/a.gd", "src/sub/b.gd"])

    def test_matched_symlink_escape_and_nonregular_input_are_invalid(self):
        proof, files = self.project(source_globs=["src/**/*.gd"])
        with make_tree(files) as tmp, make_tree({"outside.gd": "outside\n"}) as outside:
            root = Path(tmp)
            self.git(root, "init", "-q")
            self.healthy(root, proof)
            (root / "src/link.gd").symlink_to(Path(outside) / "outside.gd")
            with self.assertRaisesRegex(ContractInputError, "Symlink"):
                snapshot_inputs(root, proof)
        if hasattr(os, "mkfifo"):
            with make_tree(files) as tmp:
                root = Path(tmp)
                self.git(root, "init", "-q")
                self.healthy(root, proof)
                os.mkfifo(root / "src/pipe.gd")
                # Git does not inventory FIFOs, but explicit inputs must reject them.
                proof["sources"] = ["src/pipe.gd"]
                with self.assertRaises(ContractInputError):
                    snapshot_inputs(root, proof)

    def test_source_change_and_stale_receipt_keep_existing_exit_one(self):
        proof, files = self.project(source_globs=["src/**/*.gd"])
        with make_tree(files) as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            self.healthy(root, proof)
            (root / "src/a.gd").write_text("extends Control\n")
            code, report = cli_json(tmp, "--check", "quality.contract_runtime_evidence")
            self.assertEqual(code, 1)
            self.assertEqual(report["results"][0]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
