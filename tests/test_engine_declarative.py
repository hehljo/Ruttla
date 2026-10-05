"""Declarative rules + engine integration (P10-T008, P11-T005/T006).

Rule files are data; the engine executes them. These tests measure the
contract around that: no two live implementations, load-time rejection,
thread independence, the whitespace bomb and the engine modes of the CLI.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from _support import cli, ensure_checks_loaded, require_engine

ensure_checks_loaded()

from ruttla.declarative import SHADOWED, read_rules, rules_dir  # noqa: E402
from ruttla.registry import REGISTRY  # noqa: E402

RULE = '''format = "ruttla-rule/0"
id = "demo.blank_bomb"
title = "Demo"
platform = "universal"
severity = "warning"
[scope]
extensions = [".py"]
unit_label = "Python-Dateien"
[match]
pattern = '{pattern}'
message = "Treffer"
[[fixtures]]
name = "rot"
expect = "fail"
files = {{ "a.py" = "x\\n  @register(1)\\n" }}
[[fixtures]]
name = "grün"
expect = "pass"
files = {{ "a.py" = "x = 1\\n" }}
'''
# The pattern that made Python's re quadratic on 2026-10-04 (900 s for
# 10 × 40 KB of blank space). The regex crate is linear by construction.
BOMB_PATTERN = r"(?:^|\n)\s*(?:@register\s*\(|SelfTestCase\s*\()"
# Measured 2026-10-05 (aarch64): 10 × 40 KB in 0.11 s (debug build) and
# 0.015 s (release). Python's re on the same pattern: 0.01 s / 0.05 s /
# 0.21 s for 2 / 4 / 8 KB — ×4 per doubling, i.e. quadratic. The bound
# leaves two orders of magnitude for slow CI runners.
BOMB_BOUND_S = 10.0


def _engine(binary: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(binary), *args], capture_output=True, text=True,
                          encoding="utf-8", timeout=300)


class RuleSet(unittest.TestCase):
    def test_no_two_live_implementations(self) -> None:
        self.assertEqual(sorted(SHADOWED), [],
                         "Regel und Python-Check gleicher ID: Python-Check nach dem "
                         "Differenz-Gate löschen (docs/RULE_FORMAT.md, Port)")

    def test_every_rule_file_is_registered_as_engine_check(self) -> None:
        rules = read_rules()
        self.assertGreaterEqual(len(rules), 5)
        for rule in rules:
            check = REGISTRY[rule["id"]]
            self.assertTrue(check.engine, rule["id"])
            self.assertGreaterEqual(len(check.self_tests), 2)

    def test_engine_accepts_the_shipped_rules(self) -> None:
        binary = require_engine(self)
        proc = _engine(binary, "check-rules", "--rules", str(rules_dir()))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(sorted(json.loads(proc.stdout)["rules"]),
                         sorted(r["id"] for r in read_rules()))


class EngineContract(unittest.TestCase):
    def setUp(self) -> None:
        self.binary = require_engine(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.rules = self.tmp / "rules"
        self.rules.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _rule(self, pattern: str) -> None:
        text = RULE.format(pattern=pattern)
        (self.rules / "demo.blank_bomb.toml").write_text(text, encoding="utf-8")

    def test_lookaround_and_backreference_are_rejected_at_load(self) -> None:
        for pattern in (r"(?<!x)@register", r"@register(?=\()", r"(@)\1register"):
            with self.subTest(pattern=pattern):
                self._rule(pattern)
                proc = _engine(self.binary, "check-rules", "--rules", str(self.rules))
                self.assertEqual(proc.returncode, 3, proc.stdout)
                self.assertIn("linearzeitig", proc.stdout)

    def test_whitespace_bomb_stays_under_the_bound(self) -> None:
        self._rule(BOMB_PATTERN)
        root = self.tmp / "bomb"
        root.mkdir()
        for i in range(10):
            (root / f"f{i}.py").write_text(" \n" * 20_000, encoding="utf-8")
        start = time.perf_counter()
        proc = _engine(self.binary, "scan", str(root), "--rules", str(self.rules))
        elapsed = time.perf_counter() - start
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)["results"][0]
        self.assertEqual((result["status"], result["units_examined"]), ("pass", 10))
        self.assertLess(elapsed, BOMB_BOUND_S)

    def test_result_does_not_depend_on_thread_count(self) -> None:
        root = self.tmp / "tree"
        for i in range(40):
            path = root / f"d{i % 7}" / f"f{i}.gd"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"func a():\n    await get_tree().create_timer({i}.5).timeout\n"
                            f"    get_node('../x{i}')\n", encoding="utf-8")
        outputs = {threads: _engine(self.binary, "scan", str(root), "--rules", str(rules_dir()),
                                    "--threads", str(threads)).stdout
                   for threads in (1, 3, 16)}
        self.assertEqual(len(set(outputs.values())), 1)
        results = {r["check_id"]: r for r in json.loads(outputs[1])["results"]}
        self.assertEqual(len(results["godot.fixed_wait_instead_of_state"]["findings"]), 40)
        self.assertEqual(len(results["godot.fragile_node_path"]["findings"]), 40)

    def test_engine_selftest_runs_every_fixture(self) -> None:
        proc = _engine(self.binary, "selftest", "--rules", str(rules_dir()))
        data = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 0, [c for c in data["cases"] if not c["ok"]])
        self.assertEqual(data["total"], sum(len(r["fixtures"]) for r in read_rules()))


class EngineLookup(unittest.TestCase):
    """The engine is never taken from PATH or the scanned directory."""

    def test_binary_on_path_or_in_cwd_is_ignored(self) -> None:
        from ruttla.declarative import find_engine

        with tempfile.TemporaryDirectory() as hostile:
            for name in ("ruttla-engine", "ruttla-engine.exe"):
                fake = Path(hostile) / name
                fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                fake.chmod(0o755)
            old_path, old_cwd = os.environ.get("PATH", ""), os.getcwd()
            old_bin = os.environ.pop("RUTTLA_ENGINE_BIN", None)
            os.environ["PATH"] = hostile + os.pathsep + old_path
            os.chdir(hostile)
            try:
                found = find_engine()
            finally:
                os.chdir(old_cwd)
                os.environ["PATH"] = old_path
                if old_bin is not None:
                    os.environ["RUTTLA_ENGINE_BIN"] = old_bin
            self.assertTrue(found is None or Path(hostile) not in found.parents, found)


class CliEngineModes(unittest.TestCase):
    """Missing engine: auto = not measured, required = runner error."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "ai.ts").write_text(
            "const k = import.meta.env.VITE_OPENAI_API_KEY\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _report(self, *extra: str, env: dict | None = None) -> tuple[int, dict]:
        old = dict(os.environ)
        os.environ.update(env or {})
        try:
            proc = cli(str(self.root), "--check", "web.secret_reaches_browser", "--format", "json",
                       *extra)
        finally:
            os.environ.clear()
            os.environ.update(old)
        return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {})

    def test_off_is_not_measured(self) -> None:
        code, report = self._report("--engine", "off")
        self.assertEqual(code, 2)
        result = report["results"][0]
        self.assertEqual(result["status"], "unmeasured")
        self.assertIn("--engine off", result["reason"])

    def test_required_without_engine_is_a_runner_error(self) -> None:
        code, _ = self._report("--engine", "required",
                               env={"RUTTLA_ENGINE_BIN": str(self.root / "missing-engine")})
        self.assertEqual(code, 3)

    def test_auto_with_engine_finds_the_secret(self) -> None:
        require_engine(self)
        code, report = self._report("--engine", "required")
        self.assertEqual(code, 1, report)
        self.assertEqual(report["results"][0]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
