"""Fix-Klassen und Auftragsdateien (`ruttla triage`)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _support import ensure_checks_loaded

from ruttla import triage
from ruttla.registry import REGISTRY


def report(*results: dict) -> dict:
    return {"root": "/x/Demo", "results": list(results)}


def result(check_id: str, n: int, truncated: int = 0) -> dict:
    findings = [{"file": f"src/f{i}.ts", "line": i + 1, "message": "m", "fix": "tu was",
                 "blocking": i == 0} for i in range(n - truncated)]
    return {"check_id": check_id, "findings": findings, "findings_total": n,
            "findings_truncated": truncated}


class TableTests(unittest.TestCase):
    def test_every_listed_check_and_prefix_exists(self) -> None:
        ensure_checks_loaded()
        table = triage.load_table()
        unknown = [c for c in table["check"] if c not in REGISTRY]
        self.assertEqual(unknown, [], "Karteileichen in fix_classes.toml")
        prefixes = {c.split(".", 1)[0] for c in REGISTRY}
        self.assertEqual([p for p in table["prefix"] if p not in prefixes], [])

    def test_unlisted_check_is_never_mechanical(self) -> None:
        table = triage.load_table()
        self.assertEqual(triage.classify("web.something_new", table), "judgement")
        self.assertEqual(triage.classify("secrets.anything", table), "security")
        self.assertEqual(triage.classify("docs.trailing_whitespace", table), "mechanical")

    def test_unknown_class_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "t.toml")
            path.write_text('schema = "ruttla-fix-classes/1"\ndefault = "flash"\n',
                            encoding="utf-8")
            with self.assertRaises(ValueError):
                triage.load_table(path)


class TaskTests(unittest.TestCase):
    def test_tasks_split_by_class_with_acceptance(self) -> None:
        table = triage.load_table()
        tasks = triage.tasks_from_report(report(
            result("docs.trailing_whitespace", 3), result("secrets.hardcoded_credential", 1),
            result("web.grid_fr_without_minmax", 0)), table)
        self.assertEqual([t["class"] for t in tasks], ["mechanical", "security"])
        text = triage.render_task(tasks[0], "abc123")
        self.assertIn("ruttla guard /x/Demo --base abc123", text)
        self.assertIn("--trusted-ref abc123 --check docs.trailing_whitespace", text)
        self.assertIn("`src/f2.ts:3` m — Fix: tu was", text)
        self.assertIn("Tabu: `.ruttla.toml`", text)

    def test_truncation_is_named(self) -> None:
        tasks = triage.tasks_from_report(report(result("docs.trailing_whitespace", 25, 5)),
                                         triage.load_table())
        self.assertIn("5 weitere nicht gelistet", triage.render_task(tasks[0], "b"))

    def test_cli_writes_index(self) -> None:
        from _support import cli

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "r.json")
            src.write_text(json.dumps(report(result("docs.trailing_whitespace", 2))),
                           encoding="utf-8")
            done = cli("triage", str(src), "--out", str(Path(tmp, "out")), "--base", "b")
            self.assertEqual(done.returncode, 0, done.stderr)
            index = json.loads(Path(tmp, "out", "index.json").read_text(encoding="utf-8"))
            self.assertEqual((index[0]["task"], index[0]["findings"]),
                             ("Demo__mechanical.md", 2))
            src.write_text("{}", encoding="utf-8")
            self.assertEqual(cli("triage", str(src), "--out", tmp).returncode, 3)


if __name__ == "__main__":
    unittest.main()
