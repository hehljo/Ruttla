"""Package structure (P02): entry points, shim parity, rule-module discovery."""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
import unittest

from _support import REPO, SRC, cli, ensure_checks_loaded

import ruttla
from ruttla.engine import official_rule_modules
from ruttla.registry import REGISTRY


class EntryPointTests(unittest.TestCase):
    def test_all_entry_points_report_the_same_version(self) -> None:
        expected = f"ruttla {ruttla.__version__}"
        module = cli("--version").stdout
        shim = subprocess.run([sys.executable, str(REPO / "master_gate.py"), "--version"],
                              capture_output=True, text=True, timeout=60).stdout
        self.assertTrue(module.startswith(expected), module)
        self.assertEqual(module, shim)

    def test_shim_and_module_produce_identical_reports(self) -> None:
        tree = REPO / "tests" / "fixtures" / "packs" / "universal" / "broken"
        args = [str(tree), "--format", "agent", "--max-findings", "1000"]
        module = cli(*args)
        shim = subprocess.run([sys.executable, str(REPO / "master_gate.py"), *args],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(module.returncode, shim.returncode)
        self.assertEqual(module.stdout, shim.stdout)

    def test_legacy_core_alias_is_the_package_module(self) -> None:
        import core
        import master_gate
        self.assertIs(core, importlib.import_module("ruttla.core"))
        self.assertIs(master_gate, importlib.import_module("ruttla.cli"))


class RuleModuleTests(unittest.TestCase):
    def test_discovery_is_sorted_and_skips_helpers(self) -> None:
        modules = official_rule_modules()
        self.assertEqual(modules, sorted(modules))
        self.assertTrue(all(not m.rsplit(".", 1)[-1].startswith("_") for m in modules))
        self.assertGreaterEqual(len(modules), 20)

    def test_every_rule_module_registers_checks_and_ids_match_module_pack(self) -> None:
        ensure_checks_loaded()
        owners: dict[str, list[str]] = {}
        for check in REGISTRY.values():
            owners.setdefault(check.fn.__module__, []).append(check.id)
        for module in official_rule_modules():
            with self.subTest(module=module):
                self.assertTrue(owners.get(module), f"{module} registers nothing")
                pack = module.split(".")[2]
                for check_id in owners[module]:
                    self.assertEqual(REGISTRY[check_id].pack, pack)

    def test_rule_packs_do_not_import_the_legacy_core_alias(self) -> None:
        for path in (SRC / "ruttla" / "checks").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    with self.subTest(path=path.name):
                        self.assertNotEqual(node.module, "core")

    def test_no_module_exceeds_the_monolith_threshold(self) -> None:
        # R-009: 1,000+ line modules were the pre-split problem.
        for path in (SRC / "ruttla").rglob("*.py"):
            lines = path.read_text(encoding="utf-8").count("\n")
            with self.subTest(path=str(path.relative_to(SRC))):
                self.assertLess(lines, 1000)


if __name__ == "__main__":
    unittest.main()
