"""Environment gate of the Rust engine (P11-T001): both directions.

A missing or too old toolchain is *not measured* — never green — and in CI
(``--require``) it fails. The decision logic is imported, not rebuilt.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest

from _support import REPO

_spec = importlib.util.spec_from_file_location("engine_gate", REPO / "scripts" / "engine_gate.py")
engine_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine_gate)


class ToolchainState(unittest.TestCase):
    def test_missing_toolchain_is_not_measured(self) -> None:
        code, why = engine_gate.toolchain_state(None, (1, 85))
        self.assertEqual(code, engine_gate.EXIT_UNMEASURED)
        self.assertIn("rustup", why)

    def test_older_than_msrv_is_not_measured(self) -> None:
        code, why = engine_gate.toolchain_state("rustc 1.84.1 (e71f9a9a9 2025-01-27)", (1, 85))
        self.assertEqual(code, engine_gate.EXIT_UNMEASURED)
        self.assertIn("älter", why)

    def test_msrv_and_newer_pass(self) -> None:
        for out in ("rustc 1.85.0 (4d91de4e4 2025-02-17)", "rustc 1.99.0 (b940084d7 2026-09-28)"):
            self.assertEqual(engine_gate.toolchain_state(out, (1, 85))[0], engine_gate.EXIT_OK, out)

    def test_unreadable_version_is_not_measured(self) -> None:
        self.assertEqual(engine_gate.toolchain_state("garbage", (1, 85))[0],
                         engine_gate.EXIT_UNMEASURED)

    def test_msrv_is_read_from_cargo_toml(self) -> None:
        self.assertGreaterEqual(engine_gate.msrv(), (1, 85))

    def test_zero_tests_counted_as_zero(self) -> None:
        self.assertEqual(engine_gate.count_tests("running 0 tests\n"), (0, 0))
        out = ("test result: ok. 2 passed; 0 failed; 0 ignored\n"
               "test result: FAILED. 1 passed; 1 failed; 0 ignored\n")
        self.assertEqual(engine_gate.count_tests(out), (3, 1))


class GateWithoutToolchain(unittest.TestCase):
    """End to end: an empty PATH hides cargo/rustc."""

    def _run(self, *extra: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, PATH="")
        return subprocess.run([sys.executable, str(REPO / "scripts" / "engine_gate.py"), *extra],
                              capture_output=True, text=True, env=env, timeout=60)

    def test_not_measured_without_toolchain(self) -> None:
        proc = self._run()
        self.assertEqual(proc.returncode, engine_gate.EXIT_UNMEASURED, proc.stdout + proc.stderr)
        self.assertIn("NICHT GEMESSEN", proc.stdout)

    def test_require_turns_missing_toolchain_into_failure(self) -> None:
        proc = self._run("--require")
        self.assertEqual(proc.returncode, engine_gate.EXIT_FAILED, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
