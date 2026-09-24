"""Rule catalog (P01-T005/T006, P04-T004/T005, P05-T007)."""

from __future__ import annotations

import json
import unittest

from _support import REPO, cli, ensure_checks_loaded

from ruttla.catalog import catalog, guideline_family, rules_markdown
from ruttla.registry import LIFECYCLES, REGISTRY

RULES_DOC = REPO / "docs" / "RULES.md"
GUIDELINES_DOC = REPO / "docs" / "GUIDELINES.md"


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_checks_loaded()

    def test_every_rule_has_complete_public_metadata(self) -> None:
        for record in catalog():
            with self.subTest(rule=record["id"]):
                self.assertTrue(record["title"])
                self.assertIn(record["default_severity"], {"error", "warning", "info"})
                self.assertIn(record["lifecycle"], LIFECYCLES)
                self.assertRegex(record["introduced_in"], r"^\d+\.\d+\.\d+$")
                self.assertIsNotNone(record["guideline_public"],
                                     f"guideline without public mapping: {record['guideline']!r}")
                expects = {t["expect"] for t in record["self_tests"]}
                self.assertTrue({"pass", "fail"} <= expects)

    def test_every_mapped_guideline_anchor_exists_in_guidelines_doc(self) -> None:
        text = GUIDELINES_DOC.read_text(encoding="utf-8")
        anchors = {guideline_family(c.guideline)[0] for c in REGISTRY.values()
                   if guideline_family(c.guideline)}
        for anchor in sorted(anchors):
            with self.subTest(anchor=anchor):
                self.assertIn(f'<a id="{anchor}"></a>', text)

    def test_generated_rules_doc_is_up_to_date(self) -> None:
        self.assertEqual(
            RULES_DOC.read_text(encoding="utf-8"), rules_markdown(),
            "docs/RULES.md is stale — run: python scripts/gen_rule_docs.py",
        )

    def test_list_json_matches_registry(self) -> None:
        proc = cli("--list", "--format", "json")
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(sorted(r["id"] for r in data["rules"]), sorted(REGISTRY))

    def test_explain_known_and_unknown(self) -> None:
        proc = cli("--explain", "secrets.hardcoded_credential")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("blocking without a profile: yes", proc.stdout)
        self.assertIn("Probe [fail]", proc.stdout)
        proc = cli("--explain", "no.such.rule", "--format", "agent")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("RUNNER_ERROR\tunknown_check", proc.stdout)

    def test_markdown_format_requires_list(self) -> None:
        proc = cli(".", "--format", "markdown")
        self.assertEqual(proc.returncode, 3)


if __name__ == "__main__":
    unittest.main()
