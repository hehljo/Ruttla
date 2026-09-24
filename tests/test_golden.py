"""Behavioural baseline (P00-T007).

`tests/golden/legacy_projection.json` was produced by running the ORIGINAL
pre-migration commit (71b2df4) on the fixture trees under
`tests/fixtures/packs/`. Each tree bundles the first broken (FAIL) or healthy
(PASS) self-test probe of every check of one pack.

The projection keeps only machine-relevant fields (exit code, verdict,
detected platforms, per-check status and finding identity = check_id,
severity, file, line). Wording may change; these fields may not change
without an intentional, reviewed update of the golden file.

Regenerate only on purpose:
    RUTTLA_UPDATE_GOLDEN=1 python -m unittest tests.test_golden
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "packs"
GOLDEN = REPO / "tests" / "golden" / "legacy_projection.json"


def project(report: dict, exit_code: int) -> dict:
    results = sorted(
        (
            {
                "check_id": r["check_id"],
                "status": r["status"],
                "findings": sorted(
                    [
                        f["check_id"],
                        f["severity"],
                        (f["file"] or "").replace(os.sep, "/"),
                        f["line"] or 0,
                    ]
                    for f in r["findings"]
                ),
            }
            for r in report["results"]
        ),
        key=lambda r: r["check_id"],
    )
    return {
        "exit_code": exit_code,
        "verdict": report["verdict"],
        "platforms_detected": report["platforms_detected"],
        "results": results,
    }


def scan(tree: Path, entry: list[str]) -> dict:
    proc = subprocess.run(
        [*entry, str(tree), "--format", "json", "--max-findings", "100000"],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic path
        raise AssertionError(f"no JSON from {entry} on {tree}: {proc.stderr}") from exc
    return project(report, proc.returncode)


def trees() -> list[tuple[str, Path]]:
    out = []
    for pack in sorted(os.listdir(FIXTURES)):
        for kind in ("broken", "healthy"):
            tree = FIXTURES / pack / kind
            if tree.is_dir():
                out.append((f"{pack}/{kind}", tree))
    return out


class GoldenBaselineTests(unittest.TestCase):
    entry = [sys.executable, str(REPO / "master_gate.py")]

    def test_fixture_projection_matches_frozen_baseline(self) -> None:
        actual = {name: scan(tree, self.entry) for name, tree in trees()}
        if os.environ.get("RUTTLA_UPDATE_GOLDEN") == "1":
            GOLDEN.write_text(
                json.dumps(actual, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            self.skipTest("golden file rewritten")
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(sorted(actual), sorted(expected))
        for name in expected:
            with self.subTest(tree=name):
                self.assertEqual(actual[name], expected[name])

    def test_every_pack_has_broken_and_healthy_tree(self) -> None:
        packs = {name.split("/")[0] for name, _ in trees()}
        for pack in packs:
            self.assertTrue((FIXTURES / pack / "broken").is_dir(), pack)
            self.assertTrue((FIXTURES / pack / "healthy").is_dir(), pack)

    def test_healthy_trees_are_measured_and_not_blocked(self) -> None:
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        for name, data in expected.items():
            if name.endswith("/healthy"):
                with self.subTest(tree=name):
                    self.assertEqual(data["exit_code"], 0)
                    self.assertTrue(any(r["status"] == "pass" for r in data["results"]))


if __name__ == "__main__":
    unittest.main()
