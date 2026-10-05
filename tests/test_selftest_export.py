"""Self-test export as oracle for the engine port (P11-T004).

Export → re-import must reproduce every probe outcome, and the format is
frozen: the exact key sets are asserted here, not only in the JSON schema.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from _support import REPO, ensure_checks_loaded

ensure_checks_loaded()

from ruttla.models import Status  # noqa: E402
from ruttla.registry import REGISTRY  # noqa: E402
from ruttla.selftest import (  # noqa: E402
    SELFTEST_EXPORT_SCHEMA, export_self_tests, load_exported_self_tests, probe_count, run_case,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional test dependency
    jsonschema = None

CHECK_KEYS = {"schema", "check_id", "platform", "cases"}
CASE_KEYS = {"name", "files", "expect", "expect_finding_contains"}


class SelfTestExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = cls._tmp.name
        cls.total = export_self_tests(cls.out)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_every_probe_is_exported(self) -> None:
        self.assertGreater(self.total, 0)
        self.assertEqual(self.total, probe_count())
        self.assertEqual(len(os.listdir(self.out)), len(REGISTRY) + 1)

    def test_format_is_frozen(self) -> None:
        for name in sorted(os.listdir(self.out)):
            if name == "index.json":
                continue
            with open(os.path.join(self.out, name), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(set(data), CHECK_KEYS, name)
            self.assertEqual(data["schema"], SELFTEST_EXPORT_SCHEMA)
            for case in data["cases"]:
                self.assertEqual(set(case), CASE_KEYS, name)

    def test_export_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as again:
            export_self_tests(again)
            for name in os.listdir(self.out):
                with open(os.path.join(self.out, name), "rb") as a, \
                        open(os.path.join(again, name), "rb") as b:
                    self.assertEqual(a.read(), b.read(), name)

    def test_matches_json_schema(self) -> None:
        if jsonschema is None:
            self.skipTest("jsonschema not installed")
        with open(REPO / "schemas" / "selftests.schema.json", encoding="utf-8") as fh:
            schema = json.load(fh)
        for name in os.listdir(self.out):
            with open(os.path.join(self.out, name), encoding="utf-8") as fh:
                jsonschema.validate(json.load(fh), schema)

    def test_reimport_reproduces_every_outcome(self) -> None:
        loaded = load_exported_self_tests(self.out)
        self.assertEqual(set(loaded), set(REGISTRY))
        ran = 0
        problems = []
        for cid, cases in loaded.items():
            originals = REGISTRY[cid].self_tests
            self.assertEqual(len(cases), len(originals), cid)
            for case, original in zip(cases, originals):
                self.assertEqual((case.name, case.files, case.expect, case.expect_finding_contains),
                                 (original.name, original.files, original.expect,
                                  original.expect_finding_contains), cid)
                problem = run_case(REGISTRY[cid], case)
                ran += 1
                if problem:
                    problems.append(f"{cid} / {case.name}: {problem}")
        self.assertEqual(ran, probe_count())
        self.assertEqual(problems, [])

    def test_tampered_index_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as bad:
            export_self_tests(bad)
            path = os.path.join(bad, "index.json")
            with open(path, encoding="utf-8") as fh:
                index = json.load(fh)
            index["cases_total"] += 1
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(index, fh)
            with self.assertRaises(ValueError):
                load_exported_self_tests(bad)

    def test_expect_values_round_trip(self) -> None:
        self.assertEqual({s.value for s in Status}, {"pass", "fail", "unmeasured", "error"})


if __name__ == "__main__":
    unittest.main()
