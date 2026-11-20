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
REMOVED_IDS = REPO / "tests" / "golden" / "check_ids_removed.txt"


def _frozen_lines() -> list[str]:
    return FROZEN_IDS.read_text(encoding="utf-8").splitlines()


def _removed_ids() -> set[str]:
    ids: set[str] = set()
    for raw in REMOVED_IDS.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        ids.add(raw.split("\t")[0].strip())
    return ids


class CatalogBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not REGISTRY:
            master_gate.load_checks()

    def test_registry_ids_are_frozen(self) -> None:
        frozen = {line.strip() for line in _frozen_lines() if line.strip()}
        missing = sorted(set(REGISTRY) - frozen)
        if missing:
            self.fail(
                "fehlende Check-IDs in tests/golden/check_ids.txt: "
                + ", ".join(missing)
                + " — neue Check-ID in tests/golden/check_ids.txt eintragen"
            )

    def test_no_frozen_check_id_disappears(self) -> None:
        frozen = {line.strip() for line in _frozen_lines() if line.strip()}
        missing = sorted(frozen - set(REGISTRY) - _removed_ids())
        self.assertEqual(missing, [], "check IDs removed without deprecation entry in check_ids_removed.txt")

    def test_removed_ids_are_retired_and_were_frozen(self) -> None:
        removed = _removed_ids()
        frozen = {line.strip() for line in _frozen_lines() if line.strip()}
        self.assertEqual(sorted(removed & set(REGISTRY)), [], "entfernte IDs stehen noch in der Registry")
        self.assertEqual(sorted(removed - frozen), [], "entfernte IDs fehlen in check_ids.txt")

    def test_frozen_ids_sorted_and_unique(self) -> None:
        lines = _frozen_lines()
        self.assertNotIn("", lines, "leere Zeile in check_ids.txt")
        self.assertEqual(lines, sorted(lines), "check_ids.txt ist nicht sortiert")
        self.assertEqual(len(lines), len(set(lines)), "doppelte Einträge in check_ids.txt")

    def test_counts_do_not_drop_below_baseline(self) -> None:
        self.assertGreaterEqual(len(REGISTRY), BASELINE_CHECKS)
        probes = sum(len(check.self_tests) for check in REGISTRY.values())
        self.assertGreaterEqual(probes, BASELINE_PROBES)


if __name__ == "__main__":
    unittest.main()
