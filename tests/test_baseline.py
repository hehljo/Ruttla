"""Rule-catalog baseline (P00-T007, R-004, R-007).

Check IDs are public contracts. The frozen list in tests/golden/check_ids.txt
may only grow; removing or renaming an ID needs a deprecation entry in
CHANGELOG.md and an intentional edit of that file. Probe and rule counts may
not silently drop below the 2026-09-24 baseline.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import master_gate  # noqa: E402
from core import REGISTRY  # noqa: E402

BASELINE_CHECKS = 90
BASELINE_PROBES = 206
FROZEN_IDS = REPO / "tests" / "golden" / "check_ids.txt"


class CatalogBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not REGISTRY:
            master_gate.load_checks()

    def test_no_frozen_check_id_disappears(self) -> None:
        frozen = {line.strip() for line in FROZEN_IDS.read_text(encoding="utf-8").splitlines() if line.strip()}
        missing = sorted(frozen - set(REGISTRY))
        self.assertEqual(missing, [], "check IDs removed without deprecation")

    def test_counts_do_not_drop_below_baseline(self) -> None:
        self.assertGreaterEqual(len(REGISTRY), BASELINE_CHECKS)
        probes = sum(len(check.self_tests) for check in REGISTRY.values())
        self.assertGreaterEqual(probes, BASELINE_PROBES)


if __name__ == "__main__":
    unittest.main()
