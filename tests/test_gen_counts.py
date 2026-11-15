"""Zählwerte-Generator (R1-3): gesunde und kaputte Eingaben, beide Richtungen."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import gen_counts  # noqa: E402

COUNTS = {
    "rules": 211, "packs": 8, "checks": 211, "checks_with_probes": 211,
    "probes_ok": 1014, "probes_total": 1014, "tests": 540,
}
TARGET = gen_counts.Target("doc.md", "- {tests} Tests\n- {probes_ok}/{probes_total} Proben\n")
DOC = "# Doku\n\n<!-- ruttla:counts:begin -->\n<!-- ruttla:counts:end -->\n\nEnde\n"


def _run(root: Path, counts: dict, check: bool) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return gen_counts.run(root, counts, (TARGET,), check)


class GenCountsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="gen-counts-test-")
        self.root = Path(self._tmp.name)
        (self.root / "doc.md").write_text(DOC, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_write_then_check_is_green(self) -> None:
        self.assertEqual(_run(self.root, COUNTS, check=False), 0)
        self.assertIn("- 540 Tests\n- 1014/1014 Proben\n", (self.root / "doc.md").read_text(encoding="utf-8"))
        self.assertEqual(_run(self.root, COUNTS, check=True), 0)

    def test_sabotaged_number_turns_check_red(self) -> None:
        _run(self.root, COUNTS, check=False)
        text = (self.root / "doc.md").read_text(encoding="utf-8")
        (self.root / "doc.md").write_text(text.replace("540 Tests", "541 Tests"), encoding="utf-8")
        self.assertEqual(_run(self.root, COUNTS, check=True), 1)

    def test_changed_measurement_turns_check_red(self) -> None:
        _run(self.root, COUNTS, check=False)
        changed = dict(COUNTS, tests=541)
        self.assertEqual(_run(self.root, changed, check=True), 1)

    def test_missing_marker_is_unmeasured_not_green(self) -> None:
        (self.root / "doc.md").write_text("# Doku ohne Marker\n", encoding="utf-8")
        with self.assertRaises(gen_counts.Unmeasured):
            _run(self.root, COUNTS, check=True)

    def test_zero_count_is_rejected(self) -> None:
        with self.assertRaises(gen_counts.Unmeasured):
            gen_counts._positive("Tests", 0)

    def test_measure_failure_maps_to_exit_two(self) -> None:
        original = gen_counts.measure

        def boom(root: Path = REPO) -> dict:
            raise gen_counts.Unmeasured("Test-Attrappe")

        gen_counts.measure = boom
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gen_counts.main(["--check"]), 2)
        finally:
            gen_counts.measure = original


if __name__ == "__main__":
    unittest.main()
