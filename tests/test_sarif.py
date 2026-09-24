"""SARIF 2.1.0 reporter (P04-T001/T002).

Structural checks always run. Full JSON-Schema validation runs when the
official schema is available: set RUTTLA_SARIF_SCHEMA to a local copy of
https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json
(CI downloads it) and install jsonschema.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from _support import REPO, cli, ensure_checks_loaded, make_tree

from ruttla.registry import REGISTRY
from ruttla.reporting.sarif import build_sarif, fingerprint

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

FIXTURES = REPO / "tests" / "fixtures" / "packs"


def sarif_for(tree: Path, *extra: str) -> tuple[int, dict]:
    proc = cli(str(tree), "--format", "sarif", "--max-findings", "1000", *extra)
    return proc.returncode, json.loads(proc.stdout)


class SarifStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.code, cls.doc = sarif_for(FIXTURES / "apple" / "broken")
        cls.sarif_run = cls.doc["runs"][0]

    def test_envelope(self) -> None:
        self.assertEqual(self.doc["version"], "2.1.0")
        self.assertEqual(self.sarif_run["tool"]["driver"]["name"], "Ruttla")
        self.assertEqual(self.sarif_run["invocations"][0]["exitCode"], self.code)

    def test_every_result_has_a_location_and_a_known_rule(self) -> None:
        rules = self.sarif_run["tool"]["driver"]["rules"]
        self.assertTrue(self.sarif_run["results"])
        for result in self.sarif_run["results"]:
            self.assertTrue(result["locations"], result["ruleId"])
            self.assertEqual(rules[result["ruleIndex"]]["id"], result["ruleId"])
            uri = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            self.assertNotIn("\\", uri)
            self.assertFalse(uri.startswith("/"))
            self.assertIn(result["level"], {"error", "warning", "note"})
            self.assertIn("ruttla/v1", result["partialFingerprints"])

    def test_rule_descriptors_carry_metadata(self) -> None:
        for rule in self.sarif_run["tool"]["driver"]["rules"]:
            self.assertTrue(rule["shortDescription"]["text"])
            self.assertIn(rule["defaultConfiguration"]["level"], {"error", "warning", "note"})
            self.assertIn("ruttla --explain", rule["help"]["text"])

    def test_unmeasured_checks_become_notifications(self) -> None:
        notes = self.sarif_run["invocations"][0]["toolExecutionNotifications"]
        self.assertTrue(any(n["message"]["text"].startswith("unmeasured:") for n in notes))

    def test_project_level_finding_gets_an_anchor_location(self) -> None:
        ensure_checks_loaded()
        report = {
            "schema_version": "1.1", "tool_version": "0", "verdict": "failed", "exit_code": 1,
            "checks": {}, "profile": None, "coverage": {"files_skipped": []},
            "results": [{
                "check_id": "web.legal_pages_missing", "status": "fail", "reason": None,
                "findings": [{"check_id": "web.legal_pages_missing", "severity": "error",
                              "message": "fehlt", "file": None, "line": None,
                              "evidence": None, "fix": None, "blocking": True}],
            }],
        }
        rules = {"web.legal_pages_missing": REGISTRY["web.legal_pages_missing"].metadata()}
        doc = build_sarif(report, rules, ["src/app.ts", "README.md"])
        result = doc["runs"][0]["results"][0]
        loc = result["locations"][0]["physicalLocation"]
        self.assertEqual(loc["artifactLocation"]["uri"], "README.md")
        self.assertNotIn("region", loc)
        self.assertTrue(result["properties"]["projectLevel"])

    def test_fingerprint_ignores_line_moves(self) -> None:
        a = {"check_id": "x.y", "file": "a.py", "line": 3, "evidence": "foo  bar"}
        b = {"check_id": "x.y", "file": "a.py", "line": 30, "evidence": "foo bar"}
        c = {"check_id": "x.y", "file": "b.py", "line": 3, "evidence": "foo bar"}
        self.assertEqual(fingerprint(a), fingerprint(b))
        self.assertNotEqual(fingerprint(a), fingerprint(c))

    def test_sarif_file_option_writes_alongside_text(self) -> None:
        with make_tree({"a.ts": 'const t = "ghp_' + "a" * 36 + '";\n'}) as tmp:
            out = Path(tmp, "out.sarif")
            proc = cli(tmp, "--check", "secrets.*", "--sarif", str(out), "--no-color")
            self.assertEqual(proc.returncode, 1)
            doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(doc["runs"][0]["results"][0]["ruleId"], "secrets.hardcoded_credential")
        self.assertTrue(doc["runs"][0]["results"][0]["properties"]["blocking"])


class SarifSchemaTests(unittest.TestCase):
    def test_output_validates_against_official_schema(self) -> None:
        schema_path = os.environ.get("RUTTLA_SARIF_SCHEMA")
        if not schema_path or jsonschema is None:
            self.skipTest("set RUTTLA_SARIF_SCHEMA and install jsonschema")
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        validator = jsonschema.validators.validator_for(schema)(schema)
        for pack in sorted(p.name for p in FIXTURES.iterdir()):
            for kind in ("broken", "healthy"):
                with self.subTest(tree=f"{pack}/{kind}"):
                    _, doc = sarif_for(FIXTURES / pack / kind)
                    errors = [e.message for e in validator.iter_errors(doc)]
                    self.assertEqual(errors[:3], [])


if __name__ == "__main__":
    unittest.main()
